from pathlib import Path

import scripts.stop_panel as stop_panel


def test_stop_panel_reports_when_pid_file_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(stop_panel, "PID_FILE", tmp_path / "panel.pid")

    assert stop_panel.stop_panel(8765) is False


def test_stop_panel_only_terminates_verified_process(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "panel.pid"
    pid_file.write_text("4321", encoding="ascii")
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(stop_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(
        stop_panel,
        "read_health",
        lambda port: {"app": "stock-selector", "status": "ok", "pid": 4321},
    )
    monkeypatch.setattr(stop_panel, "process_exists", lambda pid: False)
    monkeypatch.setattr(stop_panel.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    assert stop_panel.stop_panel(8765) is True
    assert killed == [(4321, stop_panel.signal.SIGTERM)]
    assert not pid_file.exists()


def test_stop_panel_refuses_unverified_process(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "panel.pid"
    pid_file.write_text("4321", encoding="ascii")
    monkeypatch.setattr(stop_panel, "PID_FILE", pid_file)
    monkeypatch.setattr(
        stop_panel,
        "read_health",
        lambda port: {"app": "another-app", "status": "ok", "pid": 4321},
    )
    monkeypatch.setattr(stop_panel, "process_exists", lambda pid: True)

    assert stop_panel.stop_panel(8765) is False
    assert pid_file.exists()
