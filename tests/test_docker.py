from pathlib import Path


def test_docker_healthcheck_uses_lightweight_endpoint() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")

    assert "127.0.0.1:8765/api/health" in dockerfile
    assert "127.0.0.1:8765/api/status" not in dockerfile
