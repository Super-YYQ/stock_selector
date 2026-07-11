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
  baostock_query_retries: 4
  baostock_reconnect_interval: 150
  baostock_parallel_workers: 2
  baostock_parallel_chunk_size: 7
  tdx_parallel_workers: 3
  tdx_parallel_chunk_size: 25
  init_min_stock_coverage: 0.8
  init_min_daily_rows: 50000
report:
  top_observe: 20
features:
  enable_sector_score: false
scoring:
  risk_penalty_max: 18
strategies:
  enabled:
    - ma_volume
  strategy_score_weight: 12
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
    assert config.data.provider == "tdx"
    assert config.data.baostock_query_retries == 4
    assert config.data.baostock_reconnect_interval == 150
    assert config.data.baostock_parallel_workers == 2
    assert config.data.baostock_parallel_chunk_size == 7
    assert config.data.tdx_parallel_workers == 3
    assert config.data.tdx_parallel_chunk_size == 25
    assert config.data.init_min_stock_coverage == 0.8
    assert config.data.init_min_daily_rows == 50000
    assert config.report.top_observe == 20
    assert config.report.top_focus == 10
    assert config.features.enable_sector_score is False
    assert config.stock_pool.min_price == 4
    assert config.stock_pool.min_list_days == 120
    assert config.risk.max_pct_chg_5d == 22
    assert config.scoring.risk_penalty_max == 18
    assert config.strategies.enabled == ["ma_volume"]
    assert config.strategies.strategy_score_weight == 12


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


def test_data_config_defaults_use_conservative_parallelism() -> None:
    config = AppConfig()

    assert config.data.baostock_parallel_workers == 2
    assert config.data.tdx_parallel_workers == 4
    assert config.data.tdx_parallel_chunk_size == 50
    assert config.data.provider == "tdx"
