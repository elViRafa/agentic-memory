"""Standalone entry points invoked as separate OS processes by
test_cross_process.py. Not a test module (no `test_` prefix) — pytest will
not collect this file; it only runs when launched via `subprocess.Popen`.
"""

from __future__ import annotations

import sys


def _write_loop() -> None:
    from memory_fabric.storage import write_memory_store

    cwd, store_path, label, count = sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
    for i in range(count):
        write_memory_store(
            cwd, store_path, f"Marker-{label}-{i}: distinct content for this write", mode="append"
        )


def _hang_while_locked() -> None:
    import time
    from pathlib import Path

    from memory_fabric.locking import locked_file

    target = Path(sys.argv[2])
    with locked_file(target):
        target.write_text("PARTIAL-CONTENT-FROM-HANGING-WRITER", encoding="utf-8")
        print("LOCK_ACQUIRED", flush=True)
        time.sleep(60)  # would hold the lock "forever" if the test didn't kill us


if __name__ == "__main__":
    _mode = sys.argv[1]
    if _mode == "write_loop":
        _write_loop()
    elif _mode == "hang_while_locked":
        _hang_while_locked()
    else:
        raise SystemExit(f"unknown mode: {_mode}")
