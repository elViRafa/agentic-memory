"""Cross-platform advisory file locking."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# A safe upper-bound for the number of bytes to lock on Windows.
# msvcrt.locking requires a byte count; we use a large fixed value
# so that the full range of any reasonably-sized lock file is covered.
_WIN_LOCK_NBYTES = 1 << 22  # 4 MiB — larger than any lock file we create


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

        # Lock from the beginning of the file for _WIN_LOCK_NBYTES bytes.
        # Using nbytes=1 (old bug) only locked the first byte, leaving concurrent
        # writes to larger files completely unprotected on Windows.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _WIN_LOCK_NBYTES)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle) -> None:
    try:
        import msvcrt

        # Must seek to 0 and use the same nbytes that was passed to locking().
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _WIN_LOCK_NBYTES)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
