"""
Docker-based Python code execution sandbox.

Security model:
  - Ephemeral containers (auto-removed after execution)
  - Read-only filesystem (except /tmp tmpfs)
  - Memory limit and /tmp size are configurable via SANDBOX_* env vars
  - 60-second default hard timeout
  - Network enabled by default (for pip install, API calls)
    — can be disabled per-execution via allow_network=False
  - Image auto-pulled on first use or at startup
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "insightocr-sandbox:py312")
SANDBOX_AUTO_BUILD = os.getenv("SANDBOX_AUTO_BUILD", "true").lower() not in {"0", "false", "no"}
DEFAULT_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "60"))
DEFAULT_MEMORY_MB = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
DEFAULT_TMPFS_MB = int(os.getenv("SANDBOX_TMPFS_MB", "512"))


class CodeSandboxError(Exception):
    pass


def _default_sandbox_build_context() -> Path:
    return Path(__file__).resolve().parents[2]


def _sandbox_dockerfile() -> Path:
    configured = os.getenv("SANDBOX_DOCKERFILE")
    if configured:
        return Path(configured)
    return _default_sandbox_build_context() / "Dockerfile.sandbox"


def _should_build_sandbox_image() -> bool:
    return SANDBOX_AUTO_BUILD and _sandbox_dockerfile().exists() and not SANDBOX_IMAGE.startswith("python:")


def _build_sandbox_image(client) -> bool:
    dockerfile = _sandbox_dockerfile()
    context_dir = Path(os.getenv("SANDBOX_BUILD_CONTEXT", str(dockerfile.parent)))
    try:
        logger.info("Building sandbox image %s from %s", SANDBOX_IMAGE, dockerfile)
        client.images.build(
            path=str(context_dir),
            dockerfile=str(dockerfile.relative_to(context_dir)) if dockerfile.is_relative_to(context_dir) else str(dockerfile),
            tag=SANDBOX_IMAGE,
            rm=True,
            pull=False,
        )
        logger.info("Sandbox image %s built successfully", SANDBOX_IMAGE)
        return True
    except Exception as e:
        logger.warning("Failed to build sandbox image %s: %s", SANDBOX_IMAGE, e)
        return False


def _sandbox_environment() -> dict[str, str]:
    env = {
        "HOME": "/tmp",
        "PIP_CACHE_DIR": "/tmp/pip-cache",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONUNBUFFERED": "1",
        "MPLCONFIGDIR": "/tmp/matplotlib",
    }
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy",
        "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST",
    ):
        value = os.getenv(key)
        if value:
            env[key] = value
    return env


def _sandbox_network_name(client) -> str | None:
    configured = os.getenv("SANDBOX_DOCKER_NETWORK", "auto").strip()
    if configured.lower() in {"", "none", "disabled", "false"}:
        return None
    if configured.lower() != "auto":
        return configured

    hostname = os.getenv("HOSTNAME")
    if not hostname:
        return None
    try:
        current = client.containers.get(hostname)
        networks = list((current.attrs.get("NetworkSettings", {}).get("Networks") or {}).keys())
    except Exception as e:
        logger.debug("Could not auto-detect sandbox Docker network: %s", e)
        return None

    preferred = [name for name in networks if name not in {"bridge", "host", "none"}]
    return (preferred or networks or [None])[0]


def ensure_sandbox_image() -> bool:
    """Pull the sandbox image if not present. Call at startup.

    Returns True if image is ready, False if pull failed.
    """
    try:
        import docker
        client = docker.from_env(timeout=5)
        try:
            client.images.get(SANDBOX_IMAGE)
            logger.info(f"Sandbox image {SANDBOX_IMAGE} already present")
            return True
        except docker.errors.ImageNotFound:
            if _should_build_sandbox_image() and _build_sandbox_image(client):
                return True
            logger.info(f"Pulling sandbox image {SANDBOX_IMAGE}...")
            client.images.pull(SANDBOX_IMAGE)
            logger.info(f"Sandbox image {SANDBOX_IMAGE} pulled successfully")
            return True
    except ImportError:
        logger.warning("docker package not installed — sandbox unavailable")
        return False
    except Exception as e:
        logger.warning(f"Failed to pull sandbox image: {e}")
        return False


def _indent(code: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + line for line in code.splitlines())


async def execute_python(
    code: str,
    inputs: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    memory_mb: int = DEFAULT_MEMORY_MB,
    allow_network: bool = True,
) -> dict:
    """Execute Python code in an isolated Docker container.

    Args:
        code: Python code to execute. Set 'result' variable to return data.
        inputs: Data accessible as 'inputs' dict in the sandbox.
        timeout: Hard timeout in seconds.
        memory_mb: Memory limit in MB.
        allow_network: Allow outbound network (for pip install, HTTP requests).
                       Disable for untrusted code that shouldn't reach external services.
    """
    if inputs is None:
        inputs = {}

    # Wrap user code with input injection + result capture
    wrapped = f"""
import json, sys, traceback, os, base64, mimetypes, glob, re, shlex
import importlib.metadata as _metadata
import subprocess as _real_sp

# ── Sandbox subprocess shim ──────────────────────────────────────────────
# Redirect any bare `pip install` subprocess call so packages land in /tmp
# even if the caller did not use _pip_install().

def _sandbox_pip_command(args, **kwargs):
    raw = args[0] if isinstance(args, tuple) and len(args) == 1 else args
    was_string = isinstance(raw, str)
    if was_string:
        try:
            cmd = shlex.split(raw)
        except ValueError:
            return raw
    else:
        cmd = list(raw)
    is_pip = (
        len(cmd) >= 3
        and any("pip" in str(c) for c in cmd[:4])
        and "install" in cmd
    )
    if is_pip and "--target" not in cmd and "-t" not in cmd:
        idx = cmd.index("install")
        cmd = cmd[:idx+1] + ["--target", "/tmp"] + cmd[idx+1:]
        if "/tmp" not in sys.path:
            sys.path.insert(0, "/tmp")
    if was_string and kwargs.get("shell"):
        return " ".join(shlex.quote(str(c)) for c in cmd)
    return cmd

class _SubprocessShim:
    @staticmethod
    def check_call(args, **kwargs): return _real_sp.check_call(_sandbox_pip_command(args, **kwargs), **kwargs)
    @staticmethod
    def check_output(args, **kwargs): return _real_sp.check_output(_sandbox_pip_command(args, **kwargs), **kwargs)
    @staticmethod
    def run(args, **kwargs): return _real_sp.run(_sandbox_pip_command(args, **kwargs), **kwargs)
    @staticmethod
    def Popen(args, **kwargs): return _real_sp.Popen(_sandbox_pip_command(args, **kwargs), **kwargs)
    def __getattr__(self, name): return getattr(_real_sp, name)

sys.modules["subprocess"] = _SubprocessShim()
import subprocess  # now points to shim
# ─────────────────────────────────────────────────────────────────────────

inputs = json.loads({json.dumps(json.dumps(inputs, ensure_ascii=False))})
result = None
__error__ = None
__files__ = []

def _package_name(spec: str) -> str:
    spec = spec.strip()
    spec = spec.split("[", 1)[0]
    return re.split(r"[<>=!~]", spec, 1)[0].strip()

def _installed_packages(packages: list[str]) -> tuple[list[str], list[str]]:
    installed = []
    missing = []
    for pkg in packages:
        name = _package_name(pkg)
        if not name:
            continue
        try:
            _metadata.version(name)
            installed.append(pkg)
        except _metadata.PackageNotFoundError:
            missing.append(pkg)
    return installed, missing

def _pip_install(packages: str):
    # Install pip packages to /tmp (only writable path in sandbox).
    requested = packages.split()
    _, missing = _installed_packages(requested)
    if not missing:
        if "/tmp" not in sys.path:
            sys.path.insert(0, "/tmp")
        return
    _real_sp.check_call([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--no-cache-dir", "--target", "/tmp"] + missing)
    if "/tmp" not in sys.path:
        sys.path.insert(0, "/tmp")

def _thai_font_path() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun.ttf",
        "/usr/share/fonts/truetype/tlwg/Sarabun-Regular.ttf",
        "/tmp/Sarabun.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    matches = glob.glob("/usr/share/fonts/**/*Thai*.ttf", recursive=True) + glob.glob("/usr/share/fonts/**/*Sarabun*.ttf", recursive=True)
    return matches[0] if matches else ""

def _save_file(path: str) -> dict:
    # Read a binary file from the sandbox and base64-encode it for output.
    # Call this after generating xlsx, pdf, docx, pptx, or png files.
    # Returns dict with: filename, mime_type, base64, size
    if not os.path.exists(path):
        return {{"error": f"File not found: {{path}}"}}
    with open(path, "rb") as f:
        data = f.read()
    filename = os.path.basename(path)
    extension = os.path.splitext(filename)[1].lower()
    mime_type = {{
        ".csv": "text/csv; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".zip": "application/zip",
    }}.get(extension) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    encoded = base64.b64encode(data).decode("ascii")
    file_info = {{
        "filename": filename,
        "path": path,
        "mime_type": mime_type,
        "base64": encoded,
        "size": len(data),
    }}
    __files__.append(file_info)
    return file_info

def _auto_capture_result_files():
    if __error__ is not None:
        return
    candidates = []
    if isinstance(result, dict):
        for key in ("path", "file_path", "output_path"):
            value = result.get(key)
            if isinstance(value, str):
                candidates.append(value)
        value = result.get("files")
        if isinstance(value, list):
            candidates.extend([item for item in value if isinstance(item, str)])
    elif isinstance(result, str):
        candidates.append(result)

    seen = {{item.get("path") for item in __files__ if isinstance(item, dict)}}
    for path in candidates:
        if not path.startswith("/tmp/") or path in seen or not os.path.isfile(path):
            continue
        saved = _save_file(path)
        if isinstance(saved, dict) and not saved.get("error"):
            saved["auto_captured"] = True
            seen.add(path)

try:
    # ── User Code Start ──
{_indent(code, 4)}
    # ── User Code End ──
except Exception as e:
    __error__ = {{
        "type": type(e).__name__,
        "message": str(e),
        "traceback": traceback.format_exc(),
    }}

_auto_capture_result_files()

__output__ = {{
    "result": result,
    "error": __error__,
    "files": __files__,
}}
print("__SANDBOX_OUTPUT__:" + json.dumps(__output__, ensure_ascii=False, default=str))
"""

    try:
        import docker

        client = docker.from_env(timeout=timeout + 10)

        # Pull image if missing (lazy fallback)
        try:
            client.images.get(SANDBOX_IMAGE)
        except docker.errors.ImageNotFound:
            if not (_should_build_sandbox_image() and _build_sandbox_image(client)):
                logger.info(f"Pulling {SANDBOX_IMAGE} on demand...")
                client.images.pull(SANDBOX_IMAGE)

        run_kwargs = {
            "image": SANDBOX_IMAGE,
            "command": ["python", "-c", wrapped],
            "mem_limit": f"{memory_mb}m",
            "memswap_limit": f"{memory_mb}m",
            "cpu_period": 100000,
            "cpu_quota": 50000,  # 0.5 CPU
            "network_disabled": not allow_network,
            "read_only": True,
            "tmpfs": {"/tmp": f"size={DEFAULT_TMPFS_MB}m,mode=1777,exec"},
            "working_dir": "/tmp",
            "environment": _sandbox_environment(),
            "detach": True,  # detach + wait(timeout) so the timeout is real
        }
        network_name = _sandbox_network_name(client) if allow_network else None
        if network_name:
            run_kwargs["network"] = network_name

        # Run detached and enforce the timeout ourselves: a blocking
        # containers.run() only times out the Docker HTTP client, leaving
        # the container running (and never removed) on timeout.
        container = client.containers.run(**run_kwargs)
        try:
            exit_info = container.wait(timeout=timeout)
            output = container.logs(stdout=True, stderr=True).decode(
                "utf-8", errors="replace"
            )
            if exit_info.get("StatusCode", 0) != 0:
                return {
                    "error": "Container exited with error",
                    "stderr": output[-4000:],
                }
        except Exception:
            try:
                container.kill()
            except Exception:
                pass
            return {"error": f"Sandbox timed out after {timeout}s and was killed"}
        finally:
            try:
                container.remove(force=True)
            except Exception:
                pass

        result_data: dict[str, Any] = {
            "result": None, "error": None, "files": [], "stdout": output,
        }
        for line in output.splitlines():
            if line.startswith("__SANDBOX_OUTPUT__:"):
                try:
                    sandbox_out = json.loads(line[19:])
                    result_data["result"] = sandbox_out.get("result")
                    result_data["error"] = sandbox_out.get("error")
                    result_data["files"] = sandbox_out.get("files", [])
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Sandbox JSON decode failed: %s; raw=%r",
                        e.msg, line[19:][:200],
                    )
                    result_data["error"] = (
                        f"Sandbox returned malformed JSON output: {e.msg}"
                    )
        return result_data

    except ImportError:
        logger.warning("docker package not installed — sandbox unavailable")
        return {"error": "Sandbox unavailable: docker package not installed"}
    except docker.errors.ContainerError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        logger.warning("Sandbox container exited with error: %s", stderr[-4000:])
        return {"error": "Container exited with error", "stderr": stderr}
    except docker.errors.ImageNotFound:
        return {"error": f"Sandbox image {SANDBOX_IMAGE} not found. Please run: docker pull {SANDBOX_IMAGE}"}
    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}")
        return {"error": f"Sandbox failed: {str(e)}"}
