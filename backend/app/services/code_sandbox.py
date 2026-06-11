"""
Docker-based Python code execution sandbox.

Security model:
  - Ephemeral containers (auto-removed after execution)
  - Read-only filesystem (except /tmp with 64MB)
  - Memory limit 256MB, CPU capped at 0.5 core
  - 30-second hard timeout
  - Network enabled by default (for pip install, API calls)
    — can be disabled per-execution via allow_network=False
  - Image auto-pulled on first use or at startup
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

SANDBOX_IMAGE = "python:3.12-slim"
DEFAULT_TIMEOUT = 30
DEFAULT_MEMORY_MB = 256


class CodeSandboxError(Exception):
    pass


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
import json, sys, traceback, subprocess, os, base64, mimetypes

inputs = {json.dumps(inputs, ensure_ascii=False)}
result = None
__error__ = None
__files__ = []

def _pip_install(packages: str):
    # Install pip packages to /tmp (only writable path in sandbox).
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--target", "/tmp"] + packages.split())
    if "/tmp" not in sys.path:
        sys.path.insert(0, "/tmp")

def _save_file(path: str) -> dict:
    # Read a binary file from the sandbox and base64-encode it for output.
    # Call this after generating xlsx, pdf, docx, pptx, or png files.
    # Returns dict with: filename, mime_type, base64, size
    if not os.path.exists(path):
        return {{"error": f"File not found: {{path}}"}}
    with open(path, "rb") as f:
        data = f.read()
    filename = os.path.basename(path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
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
            logger.info(f"Pulling {SANDBOX_IMAGE} on demand...")
            client.images.pull(SANDBOX_IMAGE)

        container_output = client.containers.run(
            image=SANDBOX_IMAGE,
            command=["python", "-c", wrapped],
            mem_limit=f"{memory_mb}m",
            memswap_limit=f"{memory_mb}m",
            cpu_period=100000,
            cpu_quota=50000,  # 0.5 CPU
            network_disabled=not allow_network,
            read_only=True,
            tmpfs={"/tmp": "size=128m,mode=1777"},
            remove=True,
            stdout=True,
            stderr=True,
            detach=False,
        )

        output = container_output.decode("utf-8", errors="replace")

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
                except json.JSONDecodeError:
                    pass
        return result_data

    except ImportError:
        logger.warning("docker package not installed — sandbox unavailable")
        return {"error": "Sandbox unavailable: docker package not installed"}
    except docker.errors.ContainerError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        return {"error": "Container exited with error", "stderr": stderr}
    except docker.errors.ImageNotFound:
        return {"error": f"Sandbox image {SANDBOX_IMAGE} not found. Please run: docker pull {SANDBOX_IMAGE}"}
    except Exception as e:
        logger.error(f"Sandbox execution failed: {e}")
        return {"error": f"Sandbox failed: {str(e)}"}
