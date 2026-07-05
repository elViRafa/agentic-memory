"""Cross-platform advisory file locking."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

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
            except (FileNotFoundError, PermissionError):
                # PermissionError: another waiter's handle on this sidecar file is
                # still open (e.g. blocked in a concurrent _lock() retry on Windows).
                # The data file write already completed correctly by this point —
                # leaving the empty .lock sidecar behind is harmless housekeeping
                # debt, not a correctness issue.
                pass


def _lock(handle: BinaryIO) -> None:
    try:
        import msvcrt

        # Lock from the beginning of the file for _WIN_LOCK_NBYTES bytes.
        # Using nbytes=1 (old bug) only locked the first byte, leaving concurrent
        # writes to larger files completely unprotected on Windows.
        # LK_LOCK (not LK_NBLCK) retries for ~10s before raising, so a concurrent
        # writer waits for the lock instead of failing immediately with
        # PermissionError — matching fcntl.flock's default blocking behavior below.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, _WIN_LOCK_NBYTES)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]


def _unlock(handle: BinaryIO) -> None:
    try:
        import msvcrt

        # Must seek to 0 and use the same nbytes that was passed to locking().
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _WIN_LOCK_NBYTES)
        return
    except ImportError:
        pass

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
