"""Lifecycle against real Docker: networks, volumes, containers, and the errors."""

from __future__ import annotations

import time
import uuid

import pytest

from pytest_servex import (
    Container,
    DockerUnavailable,
    ImageNotFound,
    Mount,
    Network,
    NotReady,
    Tmpfs,
    Volume,
    running,
)
from pytest_servex._engine import DockerHost, Engine
from pytest_servex.spec import RunningContainer
from tests.docker_available import needs_docker


def _name(kind: str) -> str:
    return f"servex_test_{kind}_{uuid.uuid4().hex[:8]}"


@needs_docker
def test_network_volume_and_container_flow() -> None:
    net = Network(_name("net"))
    vol = Volume(_name("vol"))
    box = Container(
        image="alpine:3",
        command=("sleep", "300"),
        mounts=(Mount(vol, "/data"), Tmpfs("/scratch")),
        networks=(net,),
        alias="box",
    )
    with running(net) as started_net, running(vol), running(box) as started:
        with Engine() as engine:
            info = engine.call("GET", f"/containers/{started.id}/json")
        assert info["State"]["Running"]
        assert started_net.id in {
            n["NetworkID"] for n in info["NetworkSettings"]["Networks"].values()
        }
        assert "box" in info["NetworkSettings"]["Networks"][net.name]["Aliases"]
    with Engine() as engine:  # all three are gone, in reverse order, with no Conflict
        for path in (
            f"/containers/{started.id}/json",
            f"/networks/{started_net.id}",
            f"/volumes/{vol.name}",
        ):
            with pytest.raises(LookupError):
                engine.call("GET", path)


@needs_docker
def test_pull_never_raises_image_not_found() -> None:
    missing = Container(image="servex-no-such-image:0", pull="never")
    with pytest.raises(ImageNotFound), running(missing):
        pass


@needs_docker
def test_exited_container_fails_fast_with_logs() -> None:
    def never(_: RunningContainer) -> bool:
        return False

    dying = Container(
        image="alpine:3", command=("sh", "-c", "echo boom-from-container; exit 3"), ready=never
    )
    begin = time.monotonic()
    with pytest.raises(NotReady, match="exited with code 3") as caught, running(dying, timeout=30):
        pass
    assert time.monotonic() - begin < 10  # did not wait for the 30 s timeout
    assert "boom-from-container" in caught.value.logs
    assert isinstance(caught.value, TimeoutError)


def test_missing_socket_raises_docker_unavailable() -> None:
    nowhere = DockerHost("unix", "/nonexistent/docker.sock", 0, "127.0.0.1")
    with pytest.raises(DockerUnavailable), Engine(nowhere) as engine:
        engine.call("GET", "/_ping")
