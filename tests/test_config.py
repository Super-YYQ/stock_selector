from pathlib import Path

import pytest

from src.config import AppConfig, load_config


def test_load_config_merges_yaml_with_defaults(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "strategy.yml").write_text(
        """
data:
  database: custom/stock.db
report:
  top_observe: 20
features:
  enable_sector_score: false
scoring:
  risk_penalty_max: 18
""",
        encoding="utf-8",
    )
    (config_dir / "stock_pool.yml").write_text(
        """
stock_pool:
  min_price: 4
risk:
  max_pct_chg_5d: 22
""",
        encoding="utf-8",
    )

    config = load_config(config_dir)

    assert isinstance(config, AppConfig)
    assert config.data.database == "custom/stock.db"
    assert config.data.provider == "mixed"
    assert config.report.top_observe == 20
    assert config.report.top_focus == 10
    assert config.features.enable_sector_score is False
    assert config.stock_pool.min_price == 4
    assert config.stock_pool.min_list_days == 120
    assert config.risk.max_pct_chg_5d == 22
    assert config.scoring.risk_penalty_max == 18


def test_load_config_rejects_invalid_threshold(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "strategy.yml").write_text("data:\n  provider: mixed\n", encoding="utf-8")
    (config_dir / "stock_pool.yml").write_text(
        "stock_pool:\n  min_price: -1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="min_price"):
        load_config(config_dir)
