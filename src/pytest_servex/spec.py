"""What to start (specs) and what was started (results). All frozen dataclasses.

A spec says what you want: a ``Network``, a ``Volume``, a ``Container``. ``start`` turns a
spec into a result (``RunningNetwork``, ``RunningVolume``, ``RunningContainer``) that holds
only ids and addresses. Change a spec with ``dataclasses.replace``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

type Pull = Literal["missing", "always", "never"]


def _freeze(env: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(sorted(env.items())))


@dataclass(frozen=True)
class Endpoint:
    """A host and port where a started container accepts connections."""

    host: str
    port: int


@dataclass(frozen=True)
class Network:
    """A user-defined bridge network. Containers on it reach each other by alias."""

    name: str


@dataclass(frozen=True)
class Volume:
    """A named Docker volume. Data survives the container, not the end of the run."""

    name: str


@dataclass(frozen=True)
class Mount:
    """Mount ``volume`` at ``target`` inside a container."""

    volume: Volume
    target: str


@dataclass(frozen=True)
class Tmpfs:
    """A tmpfs at ``target`` inside a container: data in memory, nothing written to disk.

    ``options`` are mount options, for example ``"size=256m"``.
    """

    target: str
    options: str = ""


def _never_ready(_: RunningContainer) -> bool:
    return True


@dataclass(frozen=True)
class Container:
    """A container to start.

    Args:
        image: Image reference. Pin a tag; it is pulled only when missing.
        ports: Container ports to publish on random host ports.
        env: Environment variables. Stored sorted and read-only.
        command: Replaces the image's default command when not empty.
        mounts: ``Tmpfs`` and ``Mount`` entries.
        networks: Networks to join. Start them first.
        alias: The DNS name other containers on the same networks use.
        ready: Returns True once the container accepts real work. Called in a loop until
            True or until the start timeout. Return False for "not yet"; do not raise.
            The default treats a started container as ready. Speak the service's own
            protocol (a query, a ``PING``, an HTTP request): Docker's port proxy accepts
            TCP connections before the service listens, so a bare connect proves nothing.
        pull: When to pull the image, with the ``docker run --pull`` values: ``"missing"``
            (default), ``"always"``, ``"never"`` (raise ``ImageNotFound`` if not local).
        entrypoint: Replaces the image's entrypoint when not empty.
        user: ``"uid[:gid]"`` or a user name to run as.
        working_dir: The working directory inside the container.
        memory: Memory limit in bytes.
        shm_size: Size of ``/dev/shm`` in bytes (Postgres parallel queries use it).
        host_config: Extra ``HostConfig`` fields of the Docker API, merged last, for
            anything without its own field (for example ``{"CapAdd": ["NET_ADMIN"]}``).
    """

    image: str
    ports: tuple[int, ...] = ()
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    command: tuple[str, ...] = ()
    mounts: tuple[Tmpfs | Mount, ...] = ()
    networks: tuple[Network, ...] = ()
    alias: str = ""
    ready: Callable[[RunningContainer], bool] = _never_ready
    pull: Pull = "missing"
    entrypoint: tuple[str, ...] = ()
    user: str = ""
    working_dir: str = ""
    memory: int | None = None
    shm_size: int | None = None
    host_config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        """Freeze ``env`` and ``host_config`` so a spec cannot change after it is made."""
        object.__setattr__(self, "env", _freeze(self.env))
        object.__setattr__(self, "host_config", MappingProxyType(dict(self.host_config)))

    def __hash__(self) -> int:
        """Hash by value, with ``env`` as its sorted items."""
        return hash(
            (
                self.image,
                self.ports,
                tuple(self.env.items()),
                self.command,
                self.mounts,
                self.networks,
                self.alias,
                self.ready,
                self.pull,
                self.entrypoint,
                self.user,
                self.working_dir,
                self.memory,
                self.shm_size,
                repr(sorted(self.host_config.items())),  # values may be lists
            )
        )


@dataclass(frozen=True)
class RunningNetwork:
    """A network that ``start`` created."""

    id: str
    spec: Network


@dataclass(frozen=True)
class RunningVolume:
    """A volume that ``start`` created."""

    spec: Volume


@dataclass(frozen=True)
class RunningContainer:
    """A container that ``start`` created and started.

    ``ports`` maps each container port to its published host port, as sorted pairs.
    """

    id: str
    spec: Container
    host: str
    ports: tuple[tuple[int, int], ...]

    def endpoint(self, port: int) -> Endpoint:
        """Return where container ``port`` is reachable from the test process.

        Raises:
            KeyError: ``port`` was not in the spec's ``ports``.
        """
        return Endpoint(host=self.host, port=dict(self.ports)[port])
