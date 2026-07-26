from pathlib import Path

import pytest

from src.atomic_io import atomic_output_path, atomic_write_text


def test_atomic_write_text_replaces_target_without_temp_files(tmp_path: Path) -> None:
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")

    atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob(f".{target.name}.*")) == []


def test_atomic_output_preserves_existing_target_when_generation_fails(tmp_path: Path) -> None:
    target = tmp_path / "report.xlsx"
    target.write_bytes(b"existing")

    with pytest.raises(RuntimeError, match="generation failed"):
        with atomic_output_path(target, suffix=".xlsx") as temporary:
            temporary.write_bytes(b"partial")
            raise RuntimeError("generation failed")

    assert target.read_bytes() == b"existing"
    assert list(tmp_path.glob(f".{target.name}.*")) == []
