from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_ENABLED_STRATEGIES = [
    "ma_volume",
    "turtle_breakout",
    "rps_breakout",
    "pullback_stable",
    "limit_up_shakeout",
]


@dataclass(frozen=True)
class DataConfig:
    provider: str = "mixed"
    database: str = "data/stock.db"
    start_date: str = "2023-01-01"
    baostock_query_retries: int = 3
    baostock_reconnect_interval: int = 200


@dataclass(frozen=True)
class ReportConfig:
    top_observe: int = 50
    top_focus: int = 10
    output_dir: str = "reports"


@dataclass(frozen=True)
class FeatureConfig:
    enable_sector_score: bool = True
    enable_rps: bool = True
    enable_ai_summary: bool = False


@dataclass(frozen=True)
class ScoringConfig:
    sector_score_weight: float = 25
    stock_character_weight: float = 20
    volume_price_weight: float = 25
    relative_strength_weight: float = 15
    market_adjust_weight: float = 10
    risk_penalty_max: float = 20


@dataclass(frozen=True)
class StrategyConfig:
    enabled: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_STRATEGIES))
    strategy_score_weight: float = 15


@dataclass(frozen=True)
class StockPoolConfig:
    min_list_days: int = 120
    min_price: float = 3
    min_avg_amount_20d: float = 100000000
    exclude_st: bool = True
    exclude_suspended: bool = True


@dataclass(frozen=True)
class RiskConfig:
    max_pct_chg_5d: float = 30
    max_pct_chg_10d: float = 45
    max_distance_ma20: float = 25
    long_upper_shadow_ratio: float = 0.5
    high_turnover_ratio: float = 25
    high_volatility_20d: float = 0.08


@dataclass(frozen=True)
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    strategies: StrategyConfig = field(default_factory=StrategyConfig)
    stock_pool: StockPoolConfig = field(default_factory=StockPoolConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def _validate(config: AppConfig) -> None:
    if config.data.baostock_query_retries < 1:
        raise ValueError("baostock_query_retries must be greater than 0")
    if config.data.baostock_reconnect_interval < 1:
        raise ValueError("baostock_reconnect_interval must be greater than 0")
    if config.stock_pool.min_price <= 0:
        raise ValueError("min_price must be greater than 0")
    if config.stock_pool.min_list_days < 1:
        raise ValueError("min_list_days must be greater than 0")
    if config.stock_pool.min_avg_amount_20d < 0:
        raise ValueError("min_avg_amount_20d must be non-negative")
    if config.report.top_observe < config.report.top_focus:
        raise ValueError("top_observe must be greater than or equal to top_focus")
    if config.scoring.risk_penalty_max < 0:
        raise ValueError("risk_penalty_max must be non-negative")
    if config.strategies.strategy_score_weight < 0:
        raise ValueError("strategy_score_weight must be non-negative")


def load_config(config_dir: str | Path = "config") -> AppConfig:
    base = Path(config_dir)
    strategy = _read_yaml(base / "strategy.yml")
    stock_pool = _read_yaml(base / "stock_pool.yml")

    config = AppConfig(
        data=DataConfig(**_section(strategy, "data")),
        report=ReportConfig(**_section(strategy, "report")),
        features=FeatureConfig(**_section(strategy, "features")),
        scoring=ScoringConfig(**_section(strategy, "scoring")),
        strategies=StrategyConfig(**_section(strategy, "strategies")),
        stock_pool=StockPoolConfig(**_section(stock_pool, "stock_pool")),
        risk=RiskConfig(**_section(stock_pool, "risk")),
    )
    _validate(config)
    return config
