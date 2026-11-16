"""A minimal Docker Engine API client: ``http.client`` over the Docker socket, stdlib only.

One ``Engine`` holds one keep-alive connection, so the create, start, and inspect requests
of a container start share it. No engine outlives a ``with`` block: under pytest-parallex a
connection inherited by forked workers breaks when they use it at once.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import socket
import struct
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Self
from urllib.parse import urlencode, urlsplit

from pytest_servex.errors import DockerError, DockerUnavailable, docker_error

API = "/v1.41"  # Docker 20.10+, and Podman's Docker-compatible API
DEFAULT_SOCKET = "/var/run/docker.sock"


@dataclass(frozen=True)
class DockerHost:
    """Where the Docker API listens, and where published ports are reachable.

    ``kind`` is ``"unix"`` (``address`` is a socket path) or ``"tcp"`` (``address`` is a
    host name, plain HTTP, no TLS). ``published_host`` is the address tests connect to.
    """

    kind: Literal["unix", "tcp"]
    address: str
    port: int
    published_host: str

    @classmethod
    def from_env(cls, docker_host: str | None, published_host: str | None = None) -> DockerHost:
        """Parse a ``DOCKER_HOST`` value. Unset means the local default socket.

        ``published_host`` (from ``SERVEX_HOST``) overrides where tests connect. Set it when
        the published ports are on another address than the API, for example in GitLab CI
        with a ``docker:dind`` service, where the ports are on the service host ``docker``.
        The host is never guessed from "am I inside a container" checks: they break.

        Raises:
            ValueError: An ``ssh://`` or other unsupported scheme.
        """
        if not docker_host:
            return cls("unix", DEFAULT_SOCKET, 0, published_host or "127.0.0.1")
        parts = urlsplit(docker_host)
        if parts.scheme == "unix":
            return cls("unix", parts.path, 0, published_host or "127.0.0.1")
        if parts.scheme in {"tcp", "http"} and parts.hostname:
            return cls("tcp", parts.hostname, parts.port or 2375, published_host or parts.hostname)
        raise ValueError(f"unsupported DOCKER_HOST {docker_host!r}: use unix:// or tcp://")


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class Engine:
    """One connection to the Docker API. Use it as a context manager."""

    def __init__(self, host: DockerHost | None = None, timeout: float = 120.0) -> None:
        """Open nothing yet; the first request connects."""
        self.host = host or DockerHost.from_env(
            os.environ.get("DOCKER_HOST"), os.environ.get("SERVEX_HOST")
        )
        if self.host.kind == "unix":
            self._conn: http.client.HTTPConnection = _UnixConnection(self.host.address, timeout)
        else:
            self._conn = http.client.HTTPConnection(
                self.host.address, self.host.port, timeout=timeout
            )

    def __enter__(self) -> Self:
        """Return the engine."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the connection."""
        self._conn.close()

    def _send(
        self, method: str, path: str, query: Mapping[str, str] | None, body: object
    ) -> http.client.HTTPResponse:
        url = API + path + (f"?{urlencode(query)}" if query else "")
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        try:
            self._conn.request(method, url, body=payload, headers=headers)
        except (FileNotFoundError, ConnectionRefusedError) as err:
            where = (
                self.host.address
                if self.host.kind == "unix"
                else f"{self.host.address}:{self.host.port}"
            )
            raise DockerUnavailable(f"cannot reach the Docker API at {where}: {err}") from err
        return self._conn.getresponse()

    def call(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: object = None,
    ) -> Any:  # noqa: ANN401  # JSON of many shapes
        """Send one request and return the decoded JSON body (None when empty).

        Raises:
            DockerError: The status is 400 or above.
        """
        response = self._send(method, path, query, body)
        data = response.read()
        if response.status >= 400:  # noqa: PLR2004
            message = data.decode(errors="replace")
            with contextlib.suppress(ValueError):
                message = json.loads(data).get("message", message)
            raise docker_error(response.status, message)
        return json.loads(data) if data else None

    def stream_json(self, method: str, path: str, *, query: Mapping[str, str]) -> Iterator[Any]:
        """Send one request and yield each JSON line of a streamed body, as it arrives.

        Used for image pulls, so progress is never held in memory as a whole.

        Raises:
            DockerError: The status is 400 or above, or a streamed line carries ``error``.
        """
        response = self._send(method, path, query, None)
        if response.status >= 400:  # noqa: PLR2004
            raise docker_error(response.status, response.read().decode(errors="replace"))
        for line in response:
            if line.strip():
                item = json.loads(line)
                if "error" in item:
                    raise DockerError(500, str(item["error"]))
                yield item

    def raw(self, method: str, path: str, *, query: Mapping[str, str]) -> bytes:
        """Send one request and return the raw body. Raises ``DockerError`` on 400 or above."""
        response = self._send(method, path, query, None)
        data = response.read()
        if response.status >= 400:  # noqa: PLR2004
            raise docker_error(response.status, data.decode(errors="replace"))
        return data


def demux_logs(data: bytes) -> str:
    """Return the text of a non-TTY log stream, dropping Docker's 8-byte frame headers.

    Each frame is: stream type (1 byte), 3 zero bytes, payload length (4 bytes, big
    endian), payload. Data that does not start with a valid header is returned as is.
    """
    out: list[bytes] = []
    offset = 0
    while offset + 8 <= len(data):
        kind, length = struct.unpack(">B3xI", data[offset : offset + 8])
        if kind not in {0, 1, 2}:
            return data.decode(errors="replace")
        out.append(data[offset + 8 : offset + 8 + length])
        offset += 8 + length
    return b"".join(out).decode(errors="replace")
