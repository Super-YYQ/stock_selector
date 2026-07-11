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
    "volatility_squeeze",
    "trend_pullback_reversal",
    "low_volatility_rps",
    "first_pullback",
    "sector_leader",
]


@dataclass(frozen=True)
class DataConfig:
    provider: str = "tdx"
    database: str = "data/stock.db"
    start_date: str = "2023-01-01"
    tdx_parallel_workers: int = 4
    tdx_parallel_chunk_size: int = 50
    tdx_timeout_seconds: float = 3.0
    tdx_query_retries: int = 3
    init_min_stock_coverage: float = 0.90
    init_min_daily_rows: int = 100000
    init_min_index_count: int = 3
    analysis_lookback_days: int = 240
    baostock_query_retries: int = 3
    baostock_reconnect_interval: int = 200
    baostock_parallel_workers: int = 2
    baostock_parallel_chunk_size: int = 20


@dataclass(frozen=True)
class ReportConfig:
    top_observe: int = 50
    top_focus: int = 10
    output_dir: str = "reports"
    site_dir: str = "site"
    history_days: int = 90


@dataclass(frozen=True)
class PanelConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True


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
    profile: str = "balanced"
    strategy_score_weight: float = 15
    top_per_strategy: int = 20


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
    panel: PanelConfig = field(default_factory=PanelConfig)
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
    if config.data.provider.strip().lower() not in {"tdx", "akshare", "eastmoney", "baostock", "mixed", "auto"}:
        raise ValueError("provider must be one of: tdx, akshare, baostock, mixed, auto")
    if config.data.tdx_parallel_workers < 1:
        raise ValueError("tdx_parallel_workers must be greater than 0")
    if config.data.tdx_parallel_chunk_size < 1:
        raise ValueError("tdx_parallel_chunk_size must be greater than 0")
    if config.data.tdx_timeout_seconds <= 0:
        raise ValueError("tdx_timeout_seconds must be greater than 0")
    if config.data.tdx_query_retries < 1:
        raise ValueError("tdx_query_retries must be greater than 0")
    if not 0 < config.data.init_min_stock_coverage <= 1:
        raise ValueError("init_min_stock_coverage must be in (0, 1]")
    if config.data.init_min_daily_rows < 1:
        raise ValueError("init_min_daily_rows must be greater than 0")
    if config.data.init_min_index_count < 1:
        raise ValueError("init_min_index_count must be greater than 0")
    if config.data.analysis_lookback_days < 120:
        raise ValueError("analysis_lookback_days must be at least 120")
    if config.data.baostock_query_retries < 1:
        raise ValueError("baostock_query_retries must be greater than 0")
    if config.data.baostock_reconnect_interval < 1:
        raise ValueError("baostock_reconnect_interval must be greater than 0")
    if config.data.baostock_parallel_workers < 1:
        raise ValueError("baostock_parallel_workers must be greater than 0")
    if config.data.baostock_parallel_chunk_size < 1:
        raise ValueError("baostock_parallel_chunk_size must be greater than 0")
    if config.stock_pool.min_price <= 0:
        raise ValueError("min_price must be greater than 0")
    if config.stock_pool.min_list_days < 1:
        raise ValueError("min_list_days must be greater than 0")
    if config.stock_pool.min_avg_amount_20d < 0:
        raise ValueError("min_avg_amount_20d must be non-negative")
    if config.report.top_observe < config.report.top_focus:
        raise ValueError("top_observe must be greater than or equal to top_focus")
    if config.report.history_days < 1:
        raise ValueError("report.history_days must be greater than 0")
    if not 1 <= config.panel.port <= 65535:
        raise ValueError("panel.port must be between 1 and 65535")
    if config.scoring.risk_penalty_max < 0:
        raise ValueError("risk_penalty_max must be non-negative")
    if config.strategies.strategy_score_weight < 0:
        raise ValueError("strategy_score_weight must be non-negative")
    if config.strategies.profile not in {"balanced", "breakout", "pullback", "steady", "custom"}:
        raise ValueError("strategies.profile must be one of: balanced, breakout, pullback, steady, custom")
    if config.strategies.top_per_strategy < 1:
        raise ValueError("strategies.top_per_strategy must be greater than 0")


def load_config(config_dir: str | Path = "config") -> AppConfig:
    base = Path(config_dir)
    strategy = _read_yaml(base / "strategy.yml")
    stock_pool = _read_yaml(base / "stock_pool.yml")

    config = AppConfig(
        data=DataConfig(**_section(strategy, "data")),
        report=ReportConfig(**_section(strategy, "report")),
        panel=PanelConfig(**_section(strategy, "panel")),
        features=FeatureConfig(**_section(strategy, "features")),
        scoring=ScoringConfig(**_section(strategy, "scoring")),
        strategies=StrategyConfig(**_section(strategy, "strategies")),
        stock_pool=StockPoolConfig(**_section(stock_pool, "stock_pool")),
        risk=RiskConfig(**_section(stock_pool, "risk")),
    )
    _validate(config)
    return config
