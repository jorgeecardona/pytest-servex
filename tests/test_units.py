"""Tests for the pure functions: no Docker, no Postgres."""

import pytest

from pytest_servex import errors, lifecycle, postgres, valkey
from pytest_servex._engine import DockerHost, demux_logs
from pytest_servex.postgres import PostgresDatabase
from pytest_servex.spec import Bind, Container, Mount, Network, Tmpfs, Volume


@pytest.mark.parametrize(
    ("docker_host", "expected"),
    [
        (None, DockerHost("unix", "/var/run/docker.sock", 0, "127.0.0.1")),
        ("", DockerHost("unix", "/var/run/docker.sock", 0, "127.0.0.1")),
        ("unix:///run/podman.sock", DockerHost("unix", "/run/podman.sock", 0, "127.0.0.1")),
        ("tcp://10.0.0.5:2376", DockerHost("tcp", "10.0.0.5", 2376, "10.0.0.5")),
        ("tcp://box", DockerHost("tcp", "box", 2375, "box")),
    ],
)
def test_docker_host_from_env(docker_host: str | None, expected: DockerHost) -> None:
    assert DockerHost.from_env(docker_host) == expected


def test_servex_host_overrides_where_tests_connect() -> None:
    host = DockerHost.from_env("tcp://docker:2375", published_host="10.1.2.3")
    assert (host.address, host.published_host) == ("docker", "10.1.2.3")
    assert DockerHost.from_env(None, published_host="gw").published_host == "gw"


def test_ssh_docker_host_is_refused() -> None:
    with pytest.raises(ValueError, match="unsupported DOCKER_HOST"):
        DockerHost.from_env("ssh://me@box")


def test_stale_only_when_same_host_and_dead() -> None:
    labels = {lifecycle.LABEL_HOST: "here"}
    assert lifecycle.is_stale(labels, "here", pid_alive=False)
    assert not lifecycle.is_stale(labels, "here", pid_alive=True)
    assert not lifecycle.is_stale(labels, "elsewhere", pid_alive=False)


def test_demux_logs_strips_frame_headers() -> None:
    frame = b"\x01\x00\x00\x00\x00\x00\x00\x03abc" + b"\x02\x00\x00\x00\x00\x00\x00\x02de"
    assert demux_logs(frame) == "abcde"
    assert demux_logs(b"plain tty text") == "plain tty text"


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        ("postgres", ("postgres", "latest")),
        ("postgres:17-alpine", ("postgres", "17-alpine")),
        ("registry:5000/team/pg", ("registry:5000/team/pg", "latest")),
        ("registry:5000/team/pg:1.2", ("registry:5000/team/pg", "1.2")),
    ],
)
def test_split_image(image: str, expected: tuple[str, str]) -> None:
    assert lifecycle.split_image(image) == expected


def test_container_create_body() -> None:
    net, other = Network("n1"), Network("n2")
    spec = Container(
        image="img:1",
        ports=(5432,),
        env={"B": "2", "A": "1"},
        command=("run",),
        mounts=(Tmpfs("/data", "size=64m"), Mount(Volume("v"), "/v")),
        networks=(net, other),
        alias="db",
        memory=256,
        host_config={"CapAdd": ["NET_ADMIN"]},
    )
    body = lifecycle.container_create_body(spec, {"l": "1"}, "127.0.0.1")
    assert body["Env"] == ["A=1", "B=2"]
    assert body["Cmd"] == ["run"]
    assert body["ExposedPorts"] == {"5432/tcp": {}}
    host = body["HostConfig"]
    assert host["PortBindings"] == {"5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]}
    assert host["Tmpfs"] == {"/data": "size=64m"}
    assert host["Mounts"] == [{"Type": "volume", "Source": "v", "Target": "/v"}]
    assert host["NetworkMode"] == "n1"
    assert host["Memory"] == 256
    assert host["CapAdd"] == ["NET_ADMIN"]
    assert body["NetworkingConfig"] == {"EndpointsConfig": {"n1": {"Aliases": ["db"]}}}


def test_container_spec_is_frozen_and_hashable() -> None:
    a = Container(image="x", env={"B": "2", "A": "1"})
    b = Container(image="x", env={"A": "1", "B": "2"})
    assert a == b
    assert hash(a) == hash(b)
    assert list(a.env) == ["A", "B"]
    with pytest.raises(TypeError):
        a.env["C"] = "3"  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "kind", "builtin"),
    [
        (404, errors.NotFound, LookupError),
        (409, errors.Conflict, errors.DockerError),
        (500, errors.DockerError, errors.ServexError),
    ],
)
def test_docker_error_maps_status(status: int, kind: type, builtin: type) -> None:
    err = errors.docker_error(status, "boom")
    assert type(err) is kind
    assert isinstance(err, builtin)
    assert err.status == status


def test_not_ready_is_a_timeout_error() -> None:
    assert issubclass(errors.NotReady, TimeoutError)
    assert issubclass(errors.DockerUnavailable, ConnectionError)


def test_with_database_keeps_credentials_and_query() -> None:
    url = "postgresql://u:p@h:5432/postgres?sslmode=disable"
    assert postgres.with_database(url, "db1") == "postgresql://u:p@h:5432/db1?sslmode=disable"


@pytest.mark.parametrize("name", ["Upper", "has-dash", "1starts_digit", 'x"; DROP', "a" * 64])
def test_unsafe_identifier_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="not a safe database name"):
        postgres.check_identifier(name)


@pytest.mark.parametrize(
    ("worker", "expected"),
    [("main", "servex_main"), ("f0", "servex_f0"), ("gw1", "servex_gw1"), ("W-2", "servex_w_2")],
)
def test_worker_database_name(worker: str, expected: str) -> None:
    assert postgres.worker_database_name("servex", worker) == expected


@pytest.mark.parametrize(
    ("image", "data"),
    [
        ("postgres:17-alpine", "/var/lib/postgresql/data"),
        ("postgres:16.4", "/var/lib/postgresql/data"),
        ("postgres:18", "/var/lib/postgresql"),
        ("postgres:18-alpine", "/var/lib/postgresql"),
        ("my.registry/postgres", "/var/lib/postgresql/data"),
    ],
)
def test_postgres_image_moves_tmpfs_for_18(image: str, data: str) -> None:
    service = postgres.postgres_image(image)
    assert service.image == image
    assert service.mounts == (Tmpfs(data),)


def test_sqlalchemy_url() -> None:
    database = PostgresDatabase(name="d", url="postgresql://u:p@h:1/d")
    assert database.sqlalchemy_url() == "postgresql+psycopg://u:p@h:1/d"
    assert database.sqlalchemy_url("asyncpg") == "postgresql+asyncpg://u:p@h:1/d"


def test_resp_encoding() -> None:
    assert valkey.encode("SET", "k", "vé") == b"*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$3\r\nv\xc3\xa9\r\n"


@pytest.mark.parametrize(
    ("worker", "index"), [("main", 0), ("master", 0), ("f0", 0), ("f3", 3), ("gw11", 11)]
)
def test_valkey_worker_index(worker: str, index: int) -> None:
    assert valkey.worker_index(worker) == index


def test_valkey_with_database_keeps_credentials() -> None:
    assert valkey.with_database("redis://:pw@h:6379", 3) == "redis://:pw@h:6379/3"
    assert valkey.with_database("redis://h:1/0", 5) == "redis://h:1/5"


def test_redis_recipe_differs_only_in_image_and_binary() -> None:
    assert valkey.REDIS.command[0] == "redis-server"
    assert valkey.REDIS.command[1:] == valkey.VALKEY.command[1:]
    assert "--databases" in valkey.VALKEY.command


def test_bind_mount_body_is_absolute_and_read_only_by_default() -> None:
    spec = Container(
        image="x", mounts=(Bind("certs", "/auth"), Bind("/srv/w", "/w", read_only=False))
    )
    mounts = lifecycle.container_create_body(spec, {}, "127.0.0.1")["HostConfig"]["Mounts"]
    assert mounts[0]["Type"] == "bind"
    assert mounts[0]["Source"].startswith("/")
    assert mounts[0]["Source"].endswith("/certs")
    assert mounts[0]["ReadOnly"] is True
    assert mounts[1] == {"Type": "bind", "Source": "/srv/w", "Target": "/w", "ReadOnly": False}
