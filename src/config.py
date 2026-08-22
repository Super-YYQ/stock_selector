from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


MARKET_BOARD_OPTIONS = ("沪市主板", "深市主板", "创业板", "科创板", "北交所", "其他")
MARKET_BOARDS = set(MARKET_BOARD_OPTIONS)


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
    "volume_breakout_pullback",
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
    min_latest_stock_coverage: float = 0.98
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
    min_observe_score: float = 45
    min_focus_score: float = 60
    max_per_industry: int = 5
    max_per_market_board: int = 20


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
    enable_context_enrichment: bool = True
    context_top_n: int = 50
    context_cache_days: int = 7
    context_workers: int = 4


@dataclass(frozen=True)
class ScoringConfig:
    sector_score_weight: float = 25
    stock_character_weight: float = 20
    volume_price_weight: float = 25
    relative_strength_weight: float = 15
    market_adjust_weight: float = 10
    risk_penalty_max: float = 20
    factor_percentile_blend: float = 0.50


@dataclass(frozen=True)
class PerformanceConfig:
    benchmark_index_code: str = "sh000001"
    entry_cost_bps: float = 8.0
    exit_cost_bps: float = 13.0
    exclude_untradable_entry: bool = True
    exclude_price_jump_anomaly: bool = True


@dataclass(frozen=True)
class StrategyConfig:
    enabled: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_STRATEGIES))
    profile: str = "balanced"
    strategy_score_weight: float = 15
    top_per_strategy: int = 20
    max_scoring_hit_rate: float = 0.20
    min_selectivity_multiplier: float = 0.25
    parameters: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class SingleScreenerConfig:
    # 单策略筛选页专用，独立于观察名单的 strategies.enabled；
    # 允许为空（页面显示「暂无启用策略」，不影响评分）。
    enabled: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_STRATEGIES))
    top_per_strategy: int = 20


@dataclass(frozen=True)
class StockPoolConfig:
    min_list_days: int = 120
    min_price: float = 3
    min_avg_amount_20d: float = 100000000
    exclude_st: bool = True
    exclude_suspended: bool = True
    exclude_boards: list[str] = field(default_factory=lambda: ["北交所"])


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
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    strategies: StrategyConfig = field(default_factory=StrategyConfig)
    single_screener: SingleScreenerConfig = field(default_factory=SingleScreenerConfig)
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
        raise ValueError("provider must be one of: tdx, akshare, eastmoney, baostock, mixed, auto")
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
    if not 0 < config.data.min_latest_stock_coverage <= 1:
        raise ValueError("min_latest_stock_coverage must be in (0, 1]")
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
    unknown_boards = set(config.stock_pool.exclude_boards) - MARKET_BOARDS
    if unknown_boards:
        raise ValueError(f"stock_pool.exclude_boards contains unknown values: {sorted(unknown_boards)}")
    if config.features.context_top_n < 1:
        raise ValueError("features.context_top_n must be greater than 0")
    if config.features.context_cache_days < 1:
        raise ValueError("features.context_cache_days must be greater than 0")
    if config.features.context_workers < 1:
        raise ValueError("features.context_workers must be greater than 0")
    if config.report.top_observe < config.report.top_focus:
        raise ValueError("top_observe must be greater than or equal to top_focus")
    if config.report.history_days < 1:
        raise ValueError("report.history_days must be greater than 0")
    if not 0 <= config.report.min_observe_score <= config.report.min_focus_score <= 100:
        raise ValueError("report score thresholds must satisfy 0 <= observe <= focus <= 100")
    if config.report.max_per_industry < 1 or config.report.max_per_market_board < 1:
        raise ValueError("report diversification limits must be greater than 0")
    if not 1 <= config.panel.port <= 65535:
        raise ValueError("panel.port must be between 1 and 65535")
    if config.scoring.risk_penalty_max < 0:
        raise ValueError("risk_penalty_max must be non-negative")
    if not 0 <= config.scoring.factor_percentile_blend <= 1:
        raise ValueError("scoring.factor_percentile_blend must be in [0, 1]")
    if not config.performance.benchmark_index_code.strip():
        raise ValueError("performance.benchmark_index_code must not be empty")
    if config.performance.entry_cost_bps < 0 or config.performance.exit_cost_bps < 0:
        raise ValueError("performance costs must be non-negative")
    if config.strategies.strategy_score_weight < 0:
        raise ValueError("strategy_score_weight must be non-negative")
    if config.strategies.profile not in {"balanced", "breakout", "pullback", "steady", "custom"}:
        raise ValueError("strategies.profile must be one of: balanced, breakout, pullback, steady, custom")
    if config.strategies.top_per_strategy < 1:
        raise ValueError("strategies.top_per_strategy must be greater than 0")
    if not 0 < config.strategies.max_scoring_hit_rate <= 1:
        raise ValueError("strategies.max_scoring_hit_rate must be in (0, 1]")
    if not 0 < config.strategies.min_selectivity_multiplier <= 1:
        raise ValueError("strategies.min_selectivity_multiplier must be in (0, 1]")
    if not isinstance(config.strategies.parameters, dict):
        raise ValueError("strategies.parameters must be a mapping")
    if config.single_screener.top_per_strategy < 1:
        raise ValueError("single_screener.top_per_strategy must be greater than 0")
    if config.single_screener.top_per_strategy > 200:
        raise ValueError("single_screener.top_per_strategy must be <= 200")
    unknown_screener = set(config.single_screener.enabled) - set(DEFAULT_ENABLED_STRATEGIES)
    if unknown_screener:
        raise ValueError(
            "single_screener.enabled contains unknown strategies: " + ", ".join(sorted(unknown_screener))
        )


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
        performance=PerformanceConfig(**_section(strategy, "performance")),
        strategies=StrategyConfig(**_section(strategy, "strategies")),
        single_screener=SingleScreenerConfig(**_section(strategy, "single_screener")),
        stock_pool=StockPoolConfig(**_section(stock_pool, "stock_pool")),
        risk=RiskConfig(**_section(stock_pool, "risk")),
    )
    _validate(config)
    return config
