"""Start and stop networks, volumes, and containers: ``start``, ``stop``, ``running``.

Starting a container costs three API requests on one connection (create, start,
inspect), plus a streamed pull the first time an image is missing. Every object carries
labels with the run's pid and host, so ``remove_stale`` can delete what a killed run left.
"""

from __future__ import annotations

import contextlib
import os
import socket
import time
from collections.abc import Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, overload

from pytest_servex._engine import Engine, demux_logs
from pytest_servex.errors import DockerError, ImageNotFound, NotFound, NotReady
from pytest_servex.spec import (
    Bind,
    Container,
    Mount,
    Network,
    RunningContainer,
    RunningNetwork,
    RunningVolume,
    Tmpfs,
    Volume,
)

LABEL = "pytest-servex"
LABEL_PID = "pytest-servex.pid"
LABEL_HOST = "pytest-servex.host"

type Spec = Network | Volume | Container
type Running = RunningNetwork | RunningVolume | RunningContainer


def run_labels() -> dict[str, str]:
    """Return the labels that tie an object to this process on this host."""
    return {LABEL: "1", LABEL_PID: str(os.getpid()), LABEL_HOST: socket.gethostname()}


def is_stale(labels: dict[str, str], host: str, *, pid_alive: bool) -> bool:
    """Return True if a labelled object belongs to a run on ``host`` whose pid has died.

    Objects from another host are never stale here: their pid says nothing about this machine.
    """
    return labels.get(LABEL_HOST) == host and not pid_alive


def container_create_body(
    spec: Container, labels: dict[str, str], publish_ip: str
) -> dict[str, Any]:
    """Return the JSON body of ``POST /containers/create`` for ``spec``.

    Only the first network is joined at create time (API 1.41 allows one); ``start``
    connects the others before the container starts.
    """
    host_config: dict[str, Any] = {
        "PortBindings": {f"{p}/tcp": [{"HostIp": publish_ip, "HostPort": ""}] for p in spec.ports},
        "Tmpfs": {m.target: m.options for m in spec.mounts if isinstance(m, Tmpfs)},
        "Mounts": [_mount_body(m) for m in spec.mounts if isinstance(m, Mount | Bind)],
    }
    body: dict[str, Any] = {
        "Image": spec.image,
        "Env": [f"{k}={v}" for k, v in spec.env.items()],
        "Labels": labels,
        "ExposedPorts": {f"{p}/tcp": {} for p in spec.ports},
        "HostConfig": host_config,
    }
    if spec.command:
        body["Cmd"] = list(spec.command)
    if spec.entrypoint:
        body["Entrypoint"] = list(spec.entrypoint)
    if spec.user:
        body["User"] = spec.user
    if spec.working_dir:
        body["WorkingDir"] = spec.working_dir
    if spec.memory is not None:
        host_config["Memory"] = spec.memory
    if spec.shm_size is not None:
        host_config["ShmSize"] = spec.shm_size
    host_config.update(spec.host_config)
    if spec.networks:
        first = spec.networks[0].name
        host_config["NetworkMode"] = first
        body["NetworkingConfig"] = {"EndpointsConfig": {first: _endpoint_config(spec)}}
    return body


def _mount_body(mount: Mount | Bind) -> dict[str, Any]:
    if isinstance(mount, Mount):
        return {"Type": "volume", "Source": mount.volume.name, "Target": mount.target}
    return {
        "Type": "bind",
        "Source": str(Path(mount.source).resolve()),
        "Target": mount.target,
        "ReadOnly": mount.read_only,
    }


def _endpoint_config(spec: Container) -> dict[str, Any]:
    return {"Aliases": [spec.alias]} if spec.alias else {}


def split_image(image: str) -> tuple[str, str]:
    """Split ``repo[:tag]`` into repo and tag (default ``latest``). A registry port is not a tag."""
    repo, sep, tag = image.rpartition(":")
    if not sep or "/" in tag:
        return image, "latest"
    return repo, tag


def _pull(engine: Engine, image: str) -> None:
    repo, tag = split_image(image)
    try:
        for _ in engine.stream_json(
            "POST", "/images/create", query={"fromImage": repo, "tag": tag}
        ):
            pass  # progress lines are read and dropped one by one
    except DockerError as err:
        raise ImageNotFound(err.status, f"pull of {image} failed: {err.message}") from err


def _create_container(engine: Engine, spec: Container) -> str:
    publish_ip = "127.0.0.1" if engine.host.kind == "unix" else ""
    body = container_create_body(spec, run_labels(), publish_ip)
    if spec.pull == "always":
        _pull(engine, spec.image)
    try:
        created = engine.call("POST", "/containers/create", body=body)
    except NotFound as err:
        if spec.pull != "missing":
            raise ImageNotFound(
                err.status, f"{spec.image} is not local and pull={spec.pull!r}"
            ) from err
        _pull(engine, spec.image)
        created = engine.call("POST", "/containers/create", body=body)
    return str(created["Id"])


def _inspect(engine: Engine, container_id: str, spec: Container) -> RunningContainer:
    """Read the container's current published ports from Docker."""
    info = engine.call("GET", f"/containers/{container_id}/json")
    bound: dict[str, list[dict[str, str]]] = info["NetworkSettings"]["Ports"] or {}
    ports = tuple(sorted((p, int(bound[f"{p}/tcp"][0]["HostPort"])) for p in spec.ports))
    return RunningContainer(
        id=container_id, spec=spec, host=engine.host.published_host, ports=ports
    )


def refresh(started: RunningContainer) -> RunningContainer:
    """Return ``started`` with the ports Docker publishes now.

    A restart gives the container new host ports, and ``started`` keeps the old ones. Call
    this after a restart, then use ``endpoint`` on the result.

    Raises:
        NotFound: The container is gone.
        KeyError: The container is stopped, so Docker publishes no ports.
    """
    with Engine() as engine:
        return _inspect(engine, started.id, started.spec)


def _start_container(engine: Engine, spec: Container, timeout: float) -> RunningContainer:
    container_id = _create_container(engine, spec)
    try:
        for network in spec.networks[1:]:
            engine.call(
                "POST",
                f"/networks/{network.name}/connect",
                body={"Container": container_id, "EndpointConfig": _endpoint_config(spec)},
            )
        engine.call("POST", f"/containers/{container_id}/start")
        started = _inspect(engine, container_id, spec)
        _wait_ready(engine, started, timeout)
    except BaseException:
        _remove_container(engine, container_id)
        raise
    return started


POLL = 0.05  # seconds between ready checks
STATE_EVERY = 20  # ask Docker whether the container still runs every 20 polls (1 s)


def _wait_ready(engine: Engine, started: RunningContainer, timeout: float) -> None:
    """Poll ``ready`` until True. Fail fast if the container exits, instead of waiting."""
    deadline = time.monotonic() + timeout
    polls = 0
    while not started.spec.ready(started):
        polls += 1
        reason = ""
        if time.monotonic() > deadline:
            reason = f"no success after {timeout:g}s"
        elif polls % STATE_EVERY == 0:
            state = engine.call("GET", f"/containers/{started.id}/json")["State"]
            if not state["Running"]:
                reason = f"container exited with code {state['ExitCode']}"
        if reason:
            raw = engine.raw(
                "GET",
                f"/containers/{started.id}/logs",
                query={"stdout": "1", "stderr": "1", "tail": "40"},
            )
            raise NotReady(started.spec.image, reason, demux_logs(raw))
        time.sleep(POLL)


def logs(started: RunningContainer, *, tail: int | None = None) -> str:
    """Return the container's stdout and stderr as text, the last ``tail`` lines if given."""
    query = {"stdout": "1", "stderr": "1", "tail": "all" if tail is None else str(tail)}
    with Engine() as engine:
        return demux_logs(engine.raw("GET", f"/containers/{started.id}/logs", query=query))


def _remove_container(engine: Engine, container_id: str) -> None:
    # v=1 also removes anonymous volumes, so nothing is left on disk.
    with contextlib.suppress(NotFound):
        engine.call("DELETE", f"/containers/{container_id}", query={"force": "1", "v": "1"})


@overload
def start(spec: Network, *, timeout: float = ...) -> RunningNetwork: ...
@overload
def start(spec: Volume, *, timeout: float = ...) -> RunningVolume: ...
@overload
def start(spec: Container, *, timeout: float = ...) -> RunningContainer: ...
def start(spec: Spec, *, timeout: float = 60.0) -> Running:
    """Create ``spec`` in Docker and return what was started.

    A container is started and waited on until ``spec.ready`` is True. Its networks and
    volumes must exist already: start them first.

    Raises:
        NotReady: The container was not ready within ``timeout`` seconds. It is removed
            before raising, and the error carries its last 40 log lines.
        ImageNotFound: The image is missing and the pull policy or the pull failed.
        Conflict: A network or volume with that name exists already.
        DockerUnavailable: The Docker API cannot be reached.
    """
    return _start(spec, timeout)


def _start(spec: Spec, timeout: float) -> Running:
    with Engine() as engine:
        match spec:
            case Network():
                body = {"Name": spec.name, "Driver": "bridge", "Labels": run_labels()}
                created = engine.call("POST", "/networks/create", body=body)
                return RunningNetwork(id=str(created["Id"]), spec=spec)
            case Volume():
                engine.call(
                    "POST", "/volumes/create", body={"Name": spec.name, "Labels": run_labels()}
                )
                return RunningVolume(spec=spec)
            case Container():
                return _start_container(engine, spec, timeout)


def stop(running: Running) -> None:
    """Remove what ``start`` created. Something already gone is fine.

    A container is removed with its anonymous volumes. A network or volume still in use
    by a container raises ``Conflict``: stop containers first.
    """
    with Engine() as engine:
        match running:
            case RunningContainer():
                _remove_container(engine, running.id)
            case RunningNetwork():
                _delete(engine, f"/networks/{running.id}")
            case RunningVolume():
                _delete(engine, f"/volumes/{running.spec.name}")


def _delete(engine: Engine, path: str) -> None:
    with contextlib.suppress(NotFound):
        engine.call("DELETE", path)


@overload
def running(spec: Network, *, timeout: float = ...) -> AbstractContextManager[RunningNetwork]: ...
@overload
def running(spec: Volume, *, timeout: float = ...) -> AbstractContextManager[RunningVolume]: ...
@overload
def running(
    spec: Container, *, timeout: float = ...
) -> AbstractContextManager[RunningContainer]: ...
def running(spec: Spec, *, timeout: float = 60.0) -> AbstractContextManager[Running]:
    """Start ``spec`` on enter and stop it on exit, even when the block raises.

    Nest them in dependency order and they stop in reverse::

        with running(net), running(pg) as started:
            started.endpoint(5432)
    """
    return _running(spec, timeout)


@contextmanager
def _running(spec: Spec, timeout: float) -> Generator[Running]:
    started = _start(spec, timeout)
    try:
        yield started
    finally:
        stop(started)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def _stale(labels: dict[str, str] | None, host: str) -> bool:
    labels = labels or {}
    pid = labels.get(LABEL_PID, "")
    return is_stale(labels, host, pid_alive=pid.isdigit() and _pid_alive(int(pid)))


def remove_stale() -> int:
    """Remove the containers, networks, and volumes of killed runs on this host.

    A normal run removes its own objects. A run killed with SIGKILL cannot, so the next
    run does it here. This replaces the Ryuk container testcontainers runs alongside each
    session. Returns how many objects were removed.
    """
    host = socket.gethostname()
    filters = {"filters": f'{{"label": ["{LABEL}"]}}'}
    removed = 0
    with Engine() as engine:
        containers: list[dict[str, Any]] = engine.call(
            "GET", "/containers/json", query={"all": "1", **filters}
        )
        for item in containers:
            if _stale(item.get("Labels"), host):
                _remove_container(engine, item["Id"])
                removed += 1
        networks: list[dict[str, Any]] = engine.call("GET", "/networks", query=filters)
        for item in networks:
            if _stale(item.get("Labels"), host):
                _delete(engine, f"/networks/{item['Id']}")
                removed += 1
        volumes: list[dict[str, Any]] = (
            engine.call("GET", "/volumes", query=filters)["Volumes"] or []
        )
        for item in volumes:
            if _stale(item.get("Labels"), host):
                _delete(engine, f"/volumes/{item['Name']}")
                removed += 1
    return removed
