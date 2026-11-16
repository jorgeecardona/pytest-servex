"""Model check of the start, stop, crash, and cleanup flows with musil.

Two test runs, A and B, on one host. Each starts a network, a volume, and a container in
that order (``with running(net), running(vol), running(ctr)``), stops them in reverse, and
may crash at any point. A run's first step is ``remove_stale``, which uses the library's
own ``is_stale`` to pick what to delete. musil explores every interleaving.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from musil import Action, Model, check

from pytest_servex.lifecycle import LABEL_HOST, is_stale

HOST = "host"
START = ("net", "vol", "ctr")  # dependency order
STOP = ("ctr", "vol", "net")  # reverse order
CLEANUP = ("ctr", "net", "vol")  # remove_stale's order: containers first
NEEDS_CTR_GONE = {"net", "vol"}  # Docker refuses to delete these while a container uses them


@dataclass(frozen=True)
class Run:
    """One pytest run: alive or killed, how far it got, and what it has in Docker."""

    alive: bool = True
    cleaned: bool = False  # ran remove_stale
    step: int = 0  # 0-2: next START index; 3-5: next STOP index + 3; 6: finished
    objects: frozenset[str] = frozenset()

    @property
    def finished(self) -> bool:
        return self.step == len(START) + len(STOP)


@dataclass(frozen=True)
class World:
    """Both runs, plus flags for the failures the invariants forbid."""

    runs: tuple[Run, Run] = (Run(), Run())
    conflict: bool = False  # a delete Docker would refuse with 409
    removed_live: bool = False  # cleanup deleted an object of a live run


def _set(world: World, i: int, run: Run) -> World:
    runs = list(world.runs)
    runs[i] = run
    return replace(world, runs=(runs[0], runs[1]))


def _delete(objects: frozenset[str], order: tuple[str, ...]) -> tuple[frozenset[str], bool]:
    """Delete ``objects`` in ``order``; report whether any delete hit a 409."""
    left, conflict = set(objects), False
    for name in order:
        if name in left:
            conflict |= name in NEEDS_CTR_GONE and "ctr" in left
            left.discard(name)
    return frozenset(left), conflict


def _actions(i: int, cleanup_order: tuple[str, ...]) -> list[Action[World]]:
    other = 1 - i

    def me(w: World) -> Run:
        return w.runs[i]

    def cleanup(w: World) -> World:
        o = w.runs[other]
        stale = is_stale({LABEL_HOST: HOST}, HOST, pid_alive=o.alive)
        w = _set(w, i, replace(me(w), cleaned=True))
        if not stale or not o.objects:
            return w
        left, conflict = _delete(o.objects, cleanup_order)
        w = replace(w, conflict=w.conflict or conflict, removed_live=w.removed_live or o.alive)
        return _set(w, other, replace(o, objects=left))

    def advance(w: World) -> World:
        r = me(w)
        if r.step < len(START):
            return _set(w, i, replace(r, step=r.step + 1, objects=r.objects | {START[r.step]}))
        left, conflict = _delete(r.objects, (STOP[r.step - len(START)],))
        w = replace(w, conflict=w.conflict or conflict)
        return _set(w, i, replace(r, step=r.step + 1, objects=left))

    def ready_fails(w: World) -> World:
        # start() removes the container, then the with-stack unwinds: vol, then net.
        r = me(w)
        return _set(w, i, replace(r, step=len(START) + 1, objects=r.objects - {"ctr"}))

    def crash(w: World) -> World:
        return _set(w, i, replace(me(w), alive=False))

    name = "AB"[i]
    return [
        Action(f"{name}.remove_stale", lambda w: me(w).alive and not me(w).cleaned, cleanup),
        Action(
            f"{name}.next",
            lambda w: me(w).alive and me(w).cleaned and not me(w).finished,
            advance,
        ),
        Action(
            f"{name}.ready_fails",
            lambda w: me(w).alive and me(w).step == len(START) and "ctr" in me(w).objects,
            ready_fails,
        ),
        Action(f"{name}.crash", lambda w: me(w).alive and not me(w).finished, crash),
    ]


INVARIANTS: dict[str, Callable[[World], bool]] = {
    "no-409-on-stop-or-cleanup": lambda w: not w.conflict,
    "cleanup-never-touches-a-live-run": lambda w: not w.removed_live,
    "container-only-with-its-network-and-volume": lambda w: all(
        "ctr" not in r.objects or {"net", "vol"} <= r.objects for r in w.runs if r.alive
    ),
    "a-finished-run-leaves-nothing": lambda w: all(not r.objects for r in w.runs if r.finished),
}


def _done(w: World) -> bool:
    return all(r.finished or not r.alive for r in w.runs)


def build_model(cleanup_order: tuple[str, ...] = CLEANUP) -> Model[World]:
    """Return the two-run model with ``remove_stale`` deleting in ``cleanup_order``."""
    return Model(
        init=World(),
        actions=[*_actions(0, cleanup_order), *_actions(1, cleanup_order)],
        invariants=INVARIANTS,
        terminal=_done,
    )


def test_lifecycle_flows_hold_in_every_interleaving() -> None:
    result = check(build_model())
    assert result.ok, result


def test_wrong_cleanup_order_is_caught() -> None:
    """The model has teeth: deleting the network before the container is reported."""
    result = check(build_model(cleanup_order=("net", "ctr", "vol")))
    assert not result.ok
    assert "no-409" in str(result)
