"""Start and remove service containers through the Docker Engine API.

No Docker client object outlives a function call. Under pytest-parallex the controller
starts the container and the workers fork from it; a client (and its socket) inherited
by a forked child breaks when several children use it at once. Each function here opens
its own client and closes it before returning.
"""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import docker
from docker.errors import NotFound

from pytest_servex.service import Endpoint, Service

LABEL = "pytest-servex"
LABEL_PID = "pytest-servex.pid"
LABEL_HOST = "pytest-servex.host"


class ServiceStartError(RuntimeError):
    """A service container did not become ready before the timeout."""


@dataclass(frozen=True)
class RunningContainer:
    """A started service container: its Docker id and where it listens."""

    container_id: str
    endpoint: Endpoint


def docker_host_address(docker_host: str | None) -> str:
    """Return the address published container ports are reachable on.

    A ``tcp://`` or ``ssh://`` ``DOCKER_HOST`` means the daemon, and so the published
    ports, are on that remote host. Anything else (unset, ``unix://``, ``npipe://``) means
    the local machine.
    """
    if docker_host:
        parsed = urlparse(docker_host)
        if parsed.scheme in {"tcp", "ssh", "http", "https"} and parsed.hostname:
            return parsed.hostname
    return "127.0.0.1"


def is_stale(labels: dict[str, str], host: str, pid_alive: bool) -> bool:  # noqa: FBT001
    """Return True if a labelled container belongs to a test run that has died.

    Only containers started from this host are judged: a pid from another machine says
    nothing about a process here.
    """
    return labels.get(LABEL_HOST) == host and not pid_alive


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    return True


def remove_stale_containers() -> list[str]:
    """Remove containers left behind by test runs on this host that were killed.

    A normal run removes its own containers at session end. A run killed with SIGKILL
    cannot, so the next run cleans up instead. This replaces the Ryuk sidecar that
    testcontainers starts. Returns the ids of the removed containers.
    """
    host = socket.gethostname()
    removed: list[str] = []
    client = docker.from_env()
    try:
        for container in client.containers.list(all=True, filters={"label": LABEL}):
            labels: dict[str, str] = container.labels
            pid_text = labels.get(LABEL_PID, "")
            alive = pid_text.isdigit() and _pid_alive(int(pid_text))
            if is_stale(labels, host, pid_alive=alive):
                container.remove(force=True)
                removed.append(container.id or "")
    finally:
        client.close()
    return removed


def start(service: Service, timeout: float = 60.0) -> RunningContainer:
    """Start ``service`` in a new container and wait until ``service.ready`` is True.

    The container port is published on a random free port of 127.0.0.1 (or of the
    remote Docker host). The container is removed by Docker when it stops.

    Raises:
        ServiceStartError: The service was not ready within ``timeout`` seconds. The
            container is removed before raising, and the error carries its last logs.
    """
    client = docker.from_env()
    try:
        container = client.containers.run(
            service.image,
            command=list(service.command) or None,
            environment=dict(service.env),
            ports={f"{service.port}/tcp": None},
            tmpfs=dict.fromkeys(service.tmpfs, ""),
            labels={
                LABEL: service.name,
                LABEL_PID: str(os.getpid()),
                LABEL_HOST: socket.gethostname(),
            },
            detach=True,
            auto_remove=True,
        )
        container.reload()
        bindings = container.ports.get(f"{service.port}/tcp") or []
        if not bindings:
            container.remove(force=True)
            raise ServiceStartError(f"{service.name}: Docker published no port for {service.port}")
        endpoint = Endpoint(
            host=docker_host_address(os.environ.get("DOCKER_HOST")),
            port=int(bindings[0]["HostPort"]),
        )
        deadline = time.monotonic() + timeout
        while not service.ready(endpoint):
            if time.monotonic() > deadline:
                logs = container.logs(tail=40).decode(errors="replace")
                container.remove(force=True)
                raise ServiceStartError(
                    f"{service.name} ({service.image}) not ready after {timeout:.0f}s. "
                    f"Last logs:\n{logs}"
                )
            time.sleep(0.1)
        return RunningContainer(container_id=container.id or "", endpoint=endpoint)
    finally:
        client.close()


def stop(running: RunningContainer) -> None:
    """Stop and remove a container started by :func:`start`. A missing container is fine."""
    client = docker.from_env()
    try:
        client.containers.get(running.container_id).remove(force=True)
    except NotFound:
        pass
    finally:
        client.close()
