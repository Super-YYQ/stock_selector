from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def atomic_output_path(
    target: str | Path,
    *,
    suffix: str = ".tmp",
) -> Iterator[Path]:
    """Yield a same-directory temporary path and atomically replace the target on success."""
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=suffix,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        yield temporary
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(
    target: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    with atomic_output_path(target) as temporary:
        with temporary.open("w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())


def atomic_copy(source: str | Path, target: str | Path) -> None:
    destination = Path(target)
    with atomic_output_path(destination, suffix=destination.suffix or ".tmp") as temporary:
        shutil.copy2(source, temporary)
