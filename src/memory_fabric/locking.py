"""Cross-platform advisory file locking."""

from __future__ import annotations

import os
import sys
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
    handle = _acquire_lock(lock_path)
    try:
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


def _acquire_lock(lock_path: Path) -> BinaryIO:
    """Open and lock lock_path, guarding against a TOCTOU race with unlink().

    locked_file() unlinks lock_path only *after* releasing the lock (below), so
    there's a window where a new opener creates a fresh inode at the same path
    while an earlier waiter — already blocked inside _lock(), having opened the
    old inode before the unlink — is still waiting on it. Once that earlier
    waiter's lock is finally granted, it and the new opener hold locks on two
    different inodes that merely happen to share a path: no longer mutually
    exclusive, so both proceed into the critical section at once. Re-checking
    identity after locking, and retrying on mismatch, closes that window: a
    reopen always observes whichever inode is current, so it either contends
    with whoever really holds it or safely finds no lock is currently held.
    """
    while True:
        handle = lock_path.open("a+b")
        _lock(handle)
        try:
            same_file = os.path.samestat(os.fstat(handle.fileno()), os.stat(lock_path))
        except FileNotFoundError:
            same_file = False
        if same_file:
            return handle
        _unlock(handle)
        handle.close()


def _lock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        # Lock from the beginning of the file for _WIN_LOCK_NBYTES bytes.
        # Using nbytes=1 (old bug) only locked the first byte, leaving concurrent
        # writes to larger files completely unprotected on Windows.
        # LK_LOCK (not LK_NBLCK) retries for ~10s before raising, so a concurrent
        # writer waits for the lock instead of failing immediately with
        # PermissionError — matching fcntl.flock's default blocking behavior below.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, _WIN_LOCK_NBYTES)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        # Must seek to 0 and use the same nbytes that was passed to locking().
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _WIN_LOCK_NBYTES)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
