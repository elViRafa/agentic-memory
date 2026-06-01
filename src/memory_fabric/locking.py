"""Cross-platform advisory file locking."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def locked_file(target: Path) -> Iterator[None]:
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        _lock(handle)
        yield
    finally:
        try:
            _unlock(handle)
        finally:
            handle.close()
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _lock(handle) -> None:
    try:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    try:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
