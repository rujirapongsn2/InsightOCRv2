from types import SimpleNamespace

from app.services import code_sandbox


def test_sandbox_environment_includes_proxy_and_runtime_defaults(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://gateway:8888")
    monkeypatch.setenv("HTTPS_PROXY", "http://gateway:8888")
    monkeypatch.setenv("NO_PROXY", "localhost,backend")

    env = code_sandbox._sandbox_environment()

    assert env["HTTP_PROXY"] == "http://gateway:8888"
    assert env["HTTPS_PROXY"] == "http://gateway:8888"
    assert env["NO_PROXY"] == "localhost,backend"
    assert env["HOME"] == "/tmp"
    assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


def test_sandbox_network_auto_detects_current_non_default_network(monkeypatch):
    monkeypatch.setenv("SANDBOX_DOCKER_NETWORK", "auto")
    monkeypatch.setenv("HOSTNAME", "backend-container")

    current_container = SimpleNamespace(attrs={
        "NetworkSettings": {
            "Networks": {
                "bridge": {},
                "insightocrv2_internal": {},
            }
        }
    })
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda _: current_container))

    assert code_sandbox._sandbox_network_name(client) == "insightocrv2_internal"


def test_sandbox_network_respects_explicit_disable(monkeypatch):
    monkeypatch.setenv("SANDBOX_DOCKER_NETWORK", "none")

    assert code_sandbox._sandbox_network_name(SimpleNamespace()) is None

