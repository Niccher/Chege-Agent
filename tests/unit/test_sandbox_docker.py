import sys

import pytest

from backend.app.sandbox.docker import DockerSandbox, DockerSandboxError
from backend.app.security.paths import PathEscapeError


def test_docker_sandbox_maps_cwd_inside_workspace(tmp_path):
    sandbox = DockerSandbox(tmp_path, "demo")

    assert sandbox._workdir(".") == "/workspace"
    assert sandbox._workdir("src/app") == "/workspace/src/app"
    with pytest.raises(PathEscapeError):
        sandbox._workdir("../outside")


@pytest.mark.asyncio
async def test_docker_sandbox_fails_loudly_when_proxy_is_unreachable(tmp_path, monkeypatch):
    class FakeDocker:
        class DockerClient:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("proxy down")

    monkeypatch.setitem(sys.modules, "docker", FakeDocker)
    sandbox = DockerSandbox(tmp_path, "demo", docker_host="tcp://bad-proxy:2375")

    with pytest.raises(DockerSandboxError, match="proxy down"):
        await sandbox._ensure_container()
