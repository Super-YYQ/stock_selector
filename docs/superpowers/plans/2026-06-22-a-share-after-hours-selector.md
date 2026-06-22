# A Share After Hours Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Python A-share after-hours multi-factor selector that updates free market data, scores market/sector/stock factors, filters risk, and exports an explainable Excel report.

**Architecture:** The project is a standalone Python package under `stock_selector/`. Thin top-level CLI entrypoints call focused modules under `src/`; each scoring module accepts pandas DataFrames and plain config dataclasses so it can be unit-tested without network access. `baostock` and `AKShare` are wrapped behind adapter functions, while tests use small fixtures and temporary SQLite databases.

**Tech Stack:** Python 3.10+, pandas, numpy, SQLite, PyYAML, openpyxl, baostock, AKShare, pytest.

---

## File Structure

- `requirements.txt`: runtime and test dependencies.
- `config/strategy.yml`: data source, report, feature switches, scoring weights.
- `config/stock_pool.yml`: stock pool thresholds and risk thresholds.
- `src/__init__.py`: package marker.
- `src/config.py`: typed configuration loading and defaults.
- `src/database.py`: SQLite schema creation, upserts, and query helpers.
- `src/fetch_data.py`: `baostock` and `AKShare` adapters with normalized DataFrame outputs.
- `src/build_pool.py`: stock pool filtering and filtered reason output.
- `src/indicators.py`: shared rolling-return, moving-average, RPS, and limit-up helpers.
- `src/market_score.py`: market environment score.
- `src/sector_score.py`: industry/sector heat score and stock-to-sector mapping.
- `src/stock_character.py`: stock activity and historical character score.
- `src/volume_price_score.py`: volume-price structure score.
- `src/risk_filter.py`: risk penalty and risk explanation generation.
- `src/scoring.py`: weighted total score, selection reasons, next-day observation conditions.
- `src/report.py`: Excel report writer.
- `src/run_daily.py`: full workflow orchestration and logging.
- `run_daily.py`: top-level CLI shim.
- `main.py`: compatibility CLI shim.
- `README.md`: setup, commands, config, reports, disclaimer.
- `tests/conftest.py`: reusable fixtures.
- `tests/test_config.py`: config loading tests.
- `tests/test_database.py`: SQLite schema and upsert tests.
- `tests/test_fetch_data.py`: adapter normalization tests with fake clients.
- `tests/test_build_pool.py`: stock pool filtering tests.
- `tests/test_indicators.py`: indicator tests.
- `tests/test_market_score.py`: market score tests.
- `tests/test_sector_score.py`: sector score tests.
- `tests/test_stock_character.py`: stock character score tests.
- `tests/test_volume_price_score.py`: volume-price score tests.
- `tests/test_risk_filter.py`: risk penalty tests.
- `tests/test_scoring.py`: total score and reason tests.
- `tests/test_report.py`: Excel sheet and column tests.
- `tests/test_run_daily.py`: orchestration smoke test with fake dependencies.

The current workspace is not a Git repository. Commit steps are written as optional checkpoints: run them only if `git rev-parse --is-inside-work-tree` succeeds inside `stock_selector/`.

---

### Task 1: Project Skeleton, Dependencies, and Configuration

**Files:**
- Create: `stock_selector/requirements.txt`
- Create: `stock_selector/config/strategy.yml`
- Create: `stock_selector/config/stock_pool.yml`
- Create: `stock_selector/src/__init__.py`
- Create: `stock_selector/src/config.py`
- Create: `stock_selector/tests/conftest.py`
- Create: `stock_selector/tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run config tests to verify RED**

Run:

```bash
cd E:\我的git项目\Github\stock_selector
pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'` or `ImportError` because the module is not created.

- [ ] **Step 3: Create dependencies and default YAML files**

Create `requirements.txt`:

```text
pandas>=2.0
numpy>=1.24
PyYAML>=6.0
openpyxl>=3.1
baostock>=0.9
akshare>=1.10
pytest>=8.0
```

Create `config/strategy.yml`:

```yaml
data:
  provider: mixed
  database: data/stock.db
  start_date: "2023-01-01"

report:
  top_observe: 50
  top_focus: 10
  output_dir: reports

features:
  enable_sector_score: true
  enable_rps: true
  enable_ai_summary: false

scoring:
  sector_score_weight: 25
  stock_character_weight: 20
  volume_price_weight: 25
  relative_strength_weight: 15
  market_adjust_weight: 10
  risk_penalty_max: 20
```

Create `config/stock_pool.yml`:

```yaml
stock_pool:
  min_list_days: 120
  min_price: 3
  min_avg_amount_20d: 100000000
  exclude_st: true
  exclude_suspended: true

risk:
  max_pct_chg_5d: 30
  max_pct_chg_10d: 45
  max_distance_ma20: 25
  long_upper_shadow_ratio: 0.5
  high_turnover_ratio: 25
  high_volatility_20d: 0.08
```

Create `src/__init__.py`:

```python
"""A-share after-hours multi-factor selector."""
```

- [ ] **Step 4: Create `src/config.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class DataConfig:
    provider: str = "mixed"
    database: str = "data/stock.db"
    start_date: str = "2023-01-01"


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


def load_config(config_dir: str | Path = "config") -> AppConfig:
    base = Path(config_dir)
    strategy = _read_yaml(base / "strategy.yml")
    stock_pool = _read_yaml(base / "stock_pool.yml")

    config = AppConfig(
        data=DataConfig(**_section(strategy, "data")),
        report=ReportConfig(**_section(strategy, "report")),
        features=FeatureConfig(**_section(strategy, "features")),
        scoring=ScoringConfig(**_section(strategy, "scoring")),
        stock_pool=StockPoolConfig(**_section(stock_pool, "stock_pool")),
        risk=RiskConfig(**_section(stock_pool, "risk")),
    )
    _validate(config)
    return config
```

- [ ] **Step 5: Create shared pytest fixture file**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

- [ ] **Step 6: Run config tests to verify GREEN**

Run:

```bash
cd E:\我的git项目\Github\stock_selector
pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Optional checkpoint**

Run:

```bash
cd E:\我的git项目\Github\stock_selector
git rev-parse --is-inside-work-tree
```

Expected in current workspace: fatal not a git repository. If it returns `true`, run:

```bash
git add requirements.txt config src tests
git commit -m "chore: scaffold selector configuration"
```

---

### Task 2: SQLite Schema and Repository Helpers

**Files:**
- Create: `stock_selector/src/database.py`
- Create: `stock_selector/tests/test_database.py`

- [ ] **Step 1: Write failing database tests**

Create `tests/test_database.py`:

```python
from pathlib import Path

import pandas as pd

from src.database import Database


def test_database_creates_core_tables(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()

    tables = db.list_tables()

    assert {"stock_basic", "stock_daily", "index_daily", "sector_daily", "run_metadata"} <= tables


def test_upsert_stock_daily_replaces_same_code_and_date(tmp_path: Path) -> None:
    db = Database(tmp_path / "stock.db")
    db.initialize()
    first = pd.DataFrame(
        [
            {
                "code": "600000",
                "trade_date": "2026-06-22",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 1000,
                "amount": 105000,
                "turnover_rate": 1.2,
                "pct_chg": 2.0,
                "is_suspended": False,
            }
        ]
    )
    second = first.assign(close=10.8, amount=108000)

    db.upsert_dataframe("stock_daily", first, ["code", "trade_date"])
    db.upsert_dataframe("stock_daily", second, ["code", "trade_date"])
    stored = db.read_table("stock_daily")

    assert len(stored) == 1
    assert stored.loc[0, "close"] == 10.8
    assert stored.loc[0, "amount"] == 108000
```

- [ ] **Step 2: Run database tests to verify RED**

Run:

```bash
pytest tests/test_database.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.database'`.

- [ ] **Step 3: Create `src/database.py`**

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_basic (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exchange TEXT,
    industry TEXT,
    list_date TEXT,
    is_st INTEGER DEFAULT 0,
    is_listed INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_daily (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    turnover_rate REAL,
    pct_chg REAL,
    is_suspended INTEGER DEFAULT 0,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    pct_chg REAL,
    PRIMARY KEY (index_code, trade_date)
);

CREATE TABLE IF NOT EXISTS sector_daily (
    sector_name TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pct_chg REAL,
    pct_chg_5d REAL,
    pct_chg_20d REAL,
    amount REAL,
    amount_ratio REAL,
    limit_up_count INTEGER,
    strong_stock_count INTEGER,
    consecutive_strong_days INTEGER,
    PRIMARY KEY (sector_name, trade_date)
);

CREATE TABLE IF NOT EXISTS run_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def list_tables(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {row["name"] for row in rows}

    def upsert_dataframe(self, table: str, df: pd.DataFrame, key_columns: Iterable[str]) -> int:
        if df.empty:
            return 0
        keys = list(key_columns)
        columns = list(df.columns)
        missing = [column for column in keys if column not in columns]
        if missing:
            raise ValueError(f"missing key columns for {table}: {missing}")
        value_marks = ", ".join(["?"] * len(columns))
        column_sql = ", ".join(columns)
        update_columns = [column for column in columns if column not in keys]
        update_sql = ", ".join([f"{column}=excluded.{column}" for column in update_columns])
        conflict_sql = ", ".join(keys)
        sql = (
            f"INSERT INTO {table} ({column_sql}) VALUES ({value_marks}) "
            f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}"
        )
        records = df.where(pd.notna(df), None).to_records(index=False).tolist()
        with self.connect() as conn:
            conn.executemany(sql, records)
            conn.commit()
        return len(records)

    def read_table(self, table: str) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(f"SELECT * FROM {table}", conn)
```

- [ ] **Step 4: Run database tests to verify GREEN**

Run:

```bash
pytest tests/test_database.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run config and database tests together**

Run:

```bash
pytest tests/test_config.py tests/test_database.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Optional checkpoint**

If inside a Git repository:

```bash
git add src/database.py tests/test_database.py
git commit -m "feat: add sqlite storage layer"
```

---

### Task 3: Data Adapter Normalization

**Files:**
- Create: `stock_selector/src/fetch_data.py`
- Create: `stock_selector/tests/test_fetch_data.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/test_fetch_data.py`:

```python
from collections.abc import Sequence

import pandas as pd

from src.fetch_data import normalize_akshare_sector, normalize_baostock_daily


def test_normalize_baostock_daily_renames_and_converts_numbers() -> None:
    raw = pd.DataFrame(
        [
            {
                "code": "sh.600000",
                "date": "2026-06-22",
                "open": "10.0",
                "high": "11.0",
                "low": "9.9",
                "close": "10.8",
                "volume": "1000",
                "amount": "108000",
                "turn": "1.2",
                "pctChg": "2.86",
            }
        ]
    )

    normalized = normalize_baostock_daily(raw)

    assert normalized.to_dict("records") == [
        {
            "code": "600000",
            "trade_date": "2026-06-22",
            "open": 10.0,
            "high": 11.0,
            "low": 9.9,
            "close": 10.8,
            "volume": 1000.0,
            "amount": 108000.0,
            "turnover_rate": 1.2,
            "pct_chg": 2.86,
            "is_suspended": False,
        }
    ]


def test_normalize_akshare_sector_supports_chinese_columns() -> None:
    raw = pd.DataFrame(
        [
            {"板块名称": "机器人", "涨跌幅": 4.2, "成交额": 18000000000},
            {"板块名称": "AI算力", "涨跌幅": 3.5, "成交额": 15000000000},
        ]
    )

    normalized = normalize_akshare_sector(raw, "2026-06-22")

    assert list(normalized.columns) == [
        "sector_name",
        "trade_date",
        "pct_chg",
        "amount",
    ]
    assert normalized.loc[0, "sector_name"] == "机器人"
    assert normalized.loc[0, "trade_date"] == "2026-06-22"
```

- [ ] **Step 2: Run adapter tests to verify RED**

Run:

```bash
pytest tests/test_fetch_data.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.fetch_data'`.

- [ ] **Step 3: Create `src/fetch_data.py`**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)


BAOSTOCK_DAILY_COLUMNS = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "turn": "turnover_rate",
    "pctChg": "pct_chg",
}


def _strip_exchange(code: str) -> str:
    return code.split(".")[-1]


def normalize_baostock_daily(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"code", *BAOSTOCK_DAILY_COLUMNS.keys()}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"baostock daily missing columns: {sorted(missing)}")
    df = raw[["code", *BAOSTOCK_DAILY_COLUMNS.keys()]].rename(columns=BAOSTOCK_DAILY_COLUMNS)
    df["code"] = df["code"].astype(str).map(_strip_exchange)
    numeric_columns = ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_chg"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["is_suspended"] = df["volume"].fillna(0).le(0)
    return df.dropna(subset=["close"]).reset_index(drop=True)


def normalize_akshare_sector(raw: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    column_map = {
        "板块名称": "sector_name",
        "名称": "sector_name",
        "涨跌幅": "pct_chg",
        "涨跌幅%": "pct_chg",
        "成交额": "amount",
    }
    renamed = raw.rename(columns={key: value for key, value in column_map.items() if key in raw.columns})
    required = {"sector_name", "pct_chg", "amount"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"akshare sector missing columns: {sorted(missing)}")
    df = renamed[["sector_name", "pct_chg", "amount"]].copy()
    df["trade_date"] = trade_date
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["sector_name", "trade_date", "pct_chg", "amount"]].dropna(subset=["sector_name"]).reset_index(drop=True)


@dataclass
class DataFetcher:
    start_date: str

    def fetch_stock_daily(self, code: str, end_date: str | None = None) -> pd.DataFrame:
        import baostock as bs

        bs_code = f"sh.{code}" if code.startswith(("6", "9")) else f"sz.{code}"
        end = end_date or date.today().strftime("%Y-%m-%d")
        login = bs.login()
        if login.error_code != "0":
            raise RuntimeError(f"baostock login failed: {login.error_msg}")
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume,amount,turn,pctChg",
                start_date=self.start_date,
                end_date=end,
                frequency="d",
                adjustflag="1",
            )
            if rs.error_code != "0":
                raise RuntimeError(f"baostock query failed for {code}: {rs.error_msg}")
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            raw = pd.DataFrame(rows, columns=rs.fields)
            return normalize_baostock_daily(raw) if not raw.empty else pd.DataFrame()
        finally:
            bs.logout()

    def fetch_sector_daily(self, trade_date: str) -> pd.DataFrame:
        try:
            import akshare as ak

            raw = ak.stock_board_industry_name_em()
            return normalize_akshare_sector(raw, trade_date)
        except Exception as exc:
            logger.warning("AKShare sector fetch failed: %s", exc)
            return pd.DataFrame(columns=["sector_name", "trade_date", "pct_chg", "amount"])
```

- [ ] **Step 4: Run adapter tests to verify GREEN**

Run:

```bash
pytest tests/test_fetch_data.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/fetch_data.py tests/test_fetch_data.py
git commit -m "feat: normalize free data sources"
```

---

### Task 4: Shared Indicators

**Files:**
- Create: `stock_selector/src/indicators.py`
- Create: `stock_selector/tests/test_indicators.py`

- [ ] **Step 1: Write failing indicator tests**

Create `tests/test_indicators.py`:

```python
import pandas as pd

from src.indicators import add_returns, add_rps, moving_average, pct_change_over


def test_pct_change_over_uses_period_ago_close() -> None:
    series = pd.Series([10, 11, 12, 15], dtype=float)

    result = pct_change_over(series, 3)

    assert round(result.iloc[-1], 2) == 50.0


def test_add_returns_adds_grouped_return_columns() -> None:
    df = pd.DataFrame(
        {
            "code": ["000001", "000001", "000001", "000002", "000002", "000002"],
            "trade_date": ["d1", "d2", "d3", "d1", "d2", "d3"],
            "close": [10, 11, 12, 20, 19, 18],
        }
    )

    result = add_returns(df, periods=(2,))

    assert round(result[result["code"] == "000001"].iloc[-1]["return_2d"], 2) == 20.0
    assert round(result[result["code"] == "000002"].iloc[-1]["return_2d"], 2) == -10.0


def test_add_rps_ranks_latest_date_cross_sectionally() -> None:
    df = pd.DataFrame(
        {
            "code": ["A", "B", "C"],
            "trade_date": ["2026-06-22"] * 3,
            "return_20d": [10, 30, 20],
        }
    )

    result = add_rps(df, "return_20d", "rps20")

    assert result.sort_values("code")["rps20"].tolist() == [33.33333333333333, 100.0, 66.66666666666666]


def test_moving_average_returns_rolling_mean() -> None:
    result = moving_average(pd.Series([1, 2, 3], dtype=float), 2)

    assert result.tolist() == [1.0, 1.5, 2.5]
```

- [ ] **Step 2: Run indicator tests to verify RED**

Run:

```bash
pytest tests/test_indicators.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.indicators'`.

- [ ] **Step 3: Create `src/indicators.py`**

```python
from __future__ import annotations

import pandas as pd


def pct_change_over(close: pd.Series, period: int) -> pd.Series:
    previous = close.shift(period)
    return (close - previous) / previous * 100


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def add_returns(df: pd.DataFrame, periods: Sequence[int] = (5, 10, 20, 60)) -> pd.DataFrame:
    result = df.sort_values(["code", "trade_date"]).copy()
    for period in periods:
        result[f"return_{period}d"] = result.groupby("code")["close"].transform(
            lambda close: pct_change_over(close, period)
        )
    return result


def add_rps(df: pd.DataFrame, return_column: str, output_column: str) -> pd.DataFrame:
    result = df.copy()
    result[output_column] = result.groupby("trade_date")[return_column].rank(pct=True) * 100
    return result


def limit_up_threshold(code: str) -> float:
    if code.startswith(("300", "301", "688")):
        return 19.5
    return 9.5


def is_limit_up(code: str, pct_chg: float) -> bool:
    return pct_chg >= limit_up_threshold(code)
```

- [ ] **Step 4: Run indicator tests to verify GREEN**

Run:

```bash
pytest tests/test_indicators.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/indicators.py tests/test_indicators.py
git commit -m "feat: add scoring indicators"
```

---

### Task 5: Stock Pool Filtering

**Files:**
- Create: `stock_selector/src/build_pool.py`
- Create: `stock_selector/tests/test_build_pool.py`

- [ ] **Step 1: Write failing stock pool tests**

Create `tests/test_build_pool.py`:

```python
import pandas as pd

from src.build_pool import build_stock_pool
from src.config import StockPoolConfig


def test_build_stock_pool_filters_expected_reasons() -> None:
    basic = pd.DataFrame(
        [
            {"code": "000001", "name": "平安银行", "industry": "银行", "list_date": "2000-01-01", "is_st": 0, "is_listed": 1},
            {"code": "000002", "name": "ST测试", "industry": "地产", "list_date": "2000-01-01", "is_st": 1, "is_listed": 1},
            {"code": "000003", "name": "新股", "industry": "电子", "list_date": "2026-06-01", "is_st": 0, "is_listed": 1},
            {"code": "000004", "name": "低价", "industry": "机械", "list_date": "2000-01-01", "is_st": 0, "is_listed": 1},
        ]
    )
    daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-22", "close": 10, "amount": 200000000, "is_suspended": 0, "pct_chg": 2},
            {"code": "000002", "trade_date": "2026-06-22", "close": 8, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000003", "trade_date": "2026-06-22", "close": 20, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
            {"code": "000004", "trade_date": "2026-06-22", "close": 2.5, "amount": 200000000, "is_suspended": 0, "pct_chg": 1},
        ]
    )

    eligible, filtered = build_stock_pool(basic, daily, "2026-06-22", StockPoolConfig(min_avg_amount_20d=100000000))

    assert eligible["code"].tolist() == ["000001"]
    assert set(filtered["code"]) == {"000002", "000003", "000004"}
    assert "ST" in filtered[filtered["code"] == "000002"].iloc[0]["filter_reason"]
    assert "上市不足" in filtered[filtered["code"] == "000003"].iloc[0]["filter_reason"]
    assert "价格低于" in filtered[filtered["code"] == "000004"].iloc[0]["filter_reason"]
```

- [ ] **Step 2: Run stock pool tests to verify RED**

Run:

```bash
pytest tests/test_build_pool.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.build_pool'`.

- [ ] **Step 3: Create `src/build_pool.py`**

```python
from __future__ import annotations

from datetime import date

import pandas as pd

from src.config import StockPoolConfig


def _list_days(list_date: str, report_date: str) -> int:
    return (date.fromisoformat(report_date) - date.fromisoformat(list_date)).days


def _latest_rows(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    latest = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    return latest.groupby("code", as_index=False).tail(1)


def _avg_amount(daily: pd.DataFrame, report_date: str, window: int = 20) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"])
    values = history.groupby("code").tail(window).groupby("code")["amount"].mean().reset_index()
    return values.rename(columns={"amount": "avg_amount_20d"})


def build_stock_pool(
    basic: pd.DataFrame,
    daily: pd.DataFrame,
    report_date: str,
    config: StockPoolConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    latest = _latest_rows(daily, report_date)
    avg_amount = _avg_amount(daily, report_date)
    pool = basic.merge(latest, on="code", how="left").merge(avg_amount, on="code", how="left")
    pool["filter_reason"] = ""

    def add_reason(mask: pd.Series, reason: str) -> None:
        pool.loc[mask, "filter_reason"] = pool.loc[mask, "filter_reason"].apply(
            lambda existing: reason if not existing else f"{existing}; {reason}"
        )

    if config.exclude_st:
        add_reason(pool["is_st"].fillna(0).astype(int).eq(1) | pool["name"].astype(str).str.contains("ST"), "ST 或退市风险")
    if config.exclude_suspended:
        add_reason(pool["is_suspended"].fillna(0).astype(int).eq(1) | pool["close"].isna(), "停牌或无当日行情")
    add_reason(pool["list_date"].apply(lambda value: _list_days(str(value), report_date) < config.min_list_days), f"上市不足 {config.min_list_days} 个自然日")
    add_reason(pool["close"].fillna(0) < config.min_price, f"价格低于 {config.min_price} 元")
    add_reason(pool["avg_amount_20d"].fillna(0) < config.min_avg_amount_20d, f"最近20日平均成交额低于 {int(config.min_avg_amount_20d)}")

    recent = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).groupby("code").tail(5)
    recent_stats = recent.groupby("code").agg(pct_sum=("pct_chg", "sum"), amount_last=("amount", "last"), amount_mean=("amount", "mean")).reset_index()
    pool = pool.merge(recent_stats, on="code", how="left")
    add_reason(pool["pct_sum"].fillna(0).gt(35) & pool["amount_last"].fillna(0).lt(pool["amount_mean"].fillna(0) * 0.7), "连续大涨后高位缩量")

    filtered = pool[pool["filter_reason"] != ""].copy()
    eligible = pool[pool["filter_reason"] == ""].copy()
    return eligible.reset_index(drop=True), filtered.reset_index(drop=True)
```

- [ ] **Step 4: Run stock pool tests to verify GREEN**

Run:

```bash
pytest tests/test_build_pool.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/build_pool.py tests/test_build_pool.py
git commit -m "feat: filter eligible stock pool"
```

---

### Task 6: Market Environment Score

**Files:**
- Create: `stock_selector/src/market_score.py`
- Create: `stock_selector/tests/test_market_score.py`

- [ ] **Step 1: Write failing market score tests**

Create `tests/test_market_score.py`:

```python
import pandas as pd

from src.market_score import calculate_market_score


def test_calculate_market_score_labels_strong_market() -> None:
    index_daily = pd.DataFrame(
        [
            {"index_code": "sh000001", "trade_date": f"2026-06-{day:02d}", "close": 3000 + day, "amount": 1000 + day * 10, "pct_chg": 0.2}
            for day in range(1, 23)
        ]
        + [
            {"index_code": "sz399001", "trade_date": "2026-06-22", "close": 10000, "amount": 1200, "pct_chg": 1.2},
            {"index_code": "sz399006", "trade_date": "2026-06-22", "close": 2200, "amount": 800, "pct_chg": 1.8},
        ]
    )
    stock_daily = pd.DataFrame(
        [
            {"code": f"{i:06d}", "trade_date": "2026-06-22", "pct_chg": 1.0, "amount": 1000}
            for i in range(70)
        ]
        + [
            {"code": f"{i + 70:06d}", "trade_date": "2026-06-22", "pct_chg": -1.0, "amount": 1000}
            for i in range(30)
        ]
    )

    result = calculate_market_score(index_daily, stock_daily, "2026-06-22")

    assert result["market_label"] == "偏强"
    assert result["risk_level"] in {"低", "中"}
    assert result["up_ratio"] == 70.0
    assert result["market_score"] >= 7
```

- [ ] **Step 2: Run market score tests to verify RED**

Run:

```bash
pytest tests/test_market_score.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.market_score'`.

- [ ] **Step 3: Create `src/market_score.py`**

```python
from __future__ import annotations

import pandas as pd

from src.indicators import moving_average


def _latest_index(index_daily: pd.DataFrame, index_code: str, report_date: str) -> pd.DataFrame:
    return index_daily[(index_daily["index_code"] == index_code) & (index_daily["trade_date"] <= report_date)].sort_values("trade_date")


def calculate_market_score(index_daily: pd.DataFrame, stock_daily: pd.DataFrame, report_date: str) -> dict[str, object]:
    latest_stocks = stock_daily[stock_daily["trade_date"] == report_date].copy()
    up_ratio = round((latest_stocks["pct_chg"].gt(0).mean() * 100) if not latest_stocks.empty else 0, 2)
    limit_up_count = int(latest_stocks["pct_chg"].ge(9.5).sum()) if "pct_chg" in latest_stocks else 0
    limit_down_count = int(latest_stocks["pct_chg"].le(-9.5).sum()) if "pct_chg" in latest_stocks else 0

    score = 0.0
    index_changes: dict[str, float] = {}
    above_ma5 = 0
    above_ma20 = 0
    for index_code in ["sh000001", "sz399001", "sz399006"]:
        history = _latest_index(index_daily, index_code, report_date)
        if history.empty:
            continue
        latest = history.iloc[-1]
        pct_chg = float(latest.get("pct_chg", 0) or 0)
        index_changes[index_code] = pct_chg
        score += 1.0 if pct_chg > 0 else 0.0
        ma5 = moving_average(history["close"], 5).iloc[-1]
        ma20 = moving_average(history["close"], 20).iloc[-1]
        above_ma5 += int(float(latest["close"]) >= ma5)
        above_ma20 += int(float(latest["close"]) >= ma20)

    score += min(up_ratio / 20, 3)
    score += min(limit_up_count / 30, 1)
    score -= min(limit_down_count / 20, 1)
    score += above_ma5 * 0.35
    score += above_ma20 * 0.35

    sh_change = index_changes.get("sh000001", 0)
    cyb_change = index_changes.get("sz399006", 0)
    if cyb_change > sh_change:
        score += 0.5

    market_score = round(max(0, min(10, score)), 2)
    if market_score >= 7:
        market_label = "偏强"
    elif market_score >= 4:
        market_label = "震荡"
    else:
        market_label = "偏弱"

    if market_score >= 7 and limit_down_count < 20:
        risk_level = "低"
    elif market_score >= 4:
        risk_level = "中"
    else:
        risk_level = "高"

    return {
        "market_label": market_label,
        "risk_level": risk_level,
        "market_score": market_score,
        "up_ratio": up_ratio,
        "limit_up_count": limit_up_count,
        "limit_down_count": limit_down_count,
        "index_changes": index_changes,
        "above_ma5_count": above_ma5,
        "above_ma20_count": above_ma20,
    }
```

- [ ] **Step 4: Run market score tests to verify GREEN**

Run:

```bash
pytest tests/test_market_score.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/market_score.py tests/test_market_score.py
git commit -m "feat: score market environment"
```

---

### Task 7: Sector Heat Score

**Files:**
- Create: `stock_selector/src/sector_score.py`
- Create: `stock_selector/tests/test_sector_score.py`

- [ ] **Step 1: Write failing sector score tests**

Create `tests/test_sector_score.py`:

```python
import pandas as pd

from src.sector_score import calculate_sector_scores


def test_calculate_sector_scores_ranks_hot_industries() -> None:
    sector_daily = pd.DataFrame(
        [
            {"sector_name": "机器人", "trade_date": "2026-06-22", "pct_chg": 4.2, "amount": 180},
            {"sector_name": "银行", "trade_date": "2026-06-22", "pct_chg": 0.5, "amount": 80},
            {"sector_name": "机器人", "trade_date": "2026-06-21", "pct_chg": 2.0, "amount": 100},
            {"sector_name": "银行", "trade_date": "2026-06-21", "pct_chg": -0.1, "amount": 90},
        ]
    )
    stock_basic = pd.DataFrame(
        [
            {"code": "000001", "industry": "机器人"},
            {"code": "000002", "industry": "银行"},
        ]
    )
    stock_daily = pd.DataFrame(
        [
            {"code": "000001", "trade_date": "2026-06-22", "pct_chg": 10},
            {"code": "000002", "trade_date": "2026-06-22", "pct_chg": 1},
        ]
    )

    stock_scores, strong = calculate_sector_scores(sector_daily, stock_basic, stock_daily, "2026-06-22")

    assert strong.iloc[0]["sector_name"] == "机器人"
    assert stock_scores[stock_scores["code"] == "000001"].iloc[0]["sector_score_raw"] > stock_scores[stock_scores["code"] == "000002"].iloc[0]["sector_score_raw"]
```

- [ ] **Step 2: Run sector score tests to verify RED**

Run:

```bash
pytest tests/test_sector_score.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.sector_score'`.

- [ ] **Step 3: Create `src/sector_score.py`**

```python
from __future__ import annotations

import pandas as pd


def calculate_sector_scores(
    sector_daily: pd.DataFrame,
    stock_basic: pd.DataFrame,
    stock_daily: pd.DataFrame,
    report_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if sector_daily.empty:
        empty_stock = stock_basic[["code", "industry"]].copy()
        empty_stock["sector_score_raw"] = 0.0
        empty_stock["sector_reason"] = "行业数据缺失"
        return empty_stock, pd.DataFrame(columns=["sector_name", "sector_score_raw"])

    history = sector_daily[sector_daily["trade_date"] <= report_date].sort_values(["sector_name", "trade_date"]).copy()
    history["pct_chg_5d"] = history.groupby("sector_name")["pct_chg"].transform(lambda value: value.rolling(5, min_periods=1).sum())
    history["pct_chg_20d"] = history.groupby("sector_name")["pct_chg"].transform(lambda value: value.rolling(20, min_periods=1).sum())
    history["amount_ma5"] = history.groupby("sector_name")["amount"].transform(lambda value: value.rolling(5, min_periods=1).mean())
    latest = history[history["trade_date"] == report_date].copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma5"].replace(0, pd.NA)

    latest_stocks = stock_daily[stock_daily["trade_date"] == report_date].merge(stock_basic[["code", "industry"]], on="code", how="left")
    strong_counts = latest_stocks[latest_stocks["pct_chg"] >= 5].groupby("industry")["code"].count().reset_index(name="strong_stock_count")
    limit_counts = latest_stocks[latest_stocks["pct_chg"] >= 9.5].groupby("industry")["code"].count().reset_index(name="limit_up_count")
    latest = latest.merge(strong_counts, left_on="sector_name", right_on="industry", how="left").drop(columns=["industry"], errors="ignore")
    latest = latest.merge(limit_counts, left_on="sector_name", right_on="industry", how="left").drop(columns=["industry"], errors="ignore")
    latest[["strong_stock_count", "limit_up_count"]] = latest[["strong_stock_count", "limit_up_count"]].fillna(0)

    latest["sector_score_raw"] = (
        latest["pct_chg"].clip(lower=-5, upper=8) * 6
        + latest["pct_chg_5d"].clip(lower=-10, upper=20) * 1.2
        + latest["pct_chg_20d"].clip(lower=-20, upper=40) * 0.4
        + latest["amount_ratio"].fillna(1).clip(lower=0, upper=3) * 10
        + latest["limit_up_count"].clip(upper=10) * 2
        + latest["strong_stock_count"].clip(upper=20)
    ).clip(lower=0, upper=100)
    latest["sector_reason"] = latest.apply(
        lambda row: f"板块涨幅 {row['pct_chg']:.2f}%，成交额放大 {row['amount_ratio']:.2f} 倍，强势股 {int(row['strong_stock_count'])} 家",
        axis=1,
    )

    stock_scores = stock_basic[["code", "industry"]].merge(
        latest[["sector_name", "sector_score_raw", "sector_reason"]],
        left_on="industry",
        right_on="sector_name",
        how="left",
    )
    stock_scores["sector_score_raw"] = stock_scores["sector_score_raw"].fillna(0)
    stock_scores["sector_reason"] = stock_scores["sector_reason"].fillna("行业信息缺失")
    strong = latest.sort_values("sector_score_raw", ascending=False).reset_index(drop=True)
    return stock_scores.drop(columns=["sector_name"], errors="ignore"), strong
```

- [ ] **Step 4: Run sector score tests to verify GREEN**

Run:

```bash
pytest tests/test_sector_score.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/sector_score.py tests/test_sector_score.py
git commit -m "feat: score sector heat"
```

---

### Task 8: Stock Character Score

**Files:**
- Create: `stock_selector/src/stock_character.py`
- Create: `stock_selector/tests/test_stock_character.py`

- [ ] **Step 1: Write failing stock character tests**

Create `tests/test_stock_character.py`:

```python
import pandas as pd

from src.stock_character import calculate_stock_character_scores


def test_stock_character_rewards_active_history_and_rps() -> None:
    rows = []
    for day in range(1, 62):
        rows.append({"code": "A", "trade_date": f"2026-04-{day:02d}", "open": 10, "high": 12, "low": 9, "close": 10 + day * 0.2, "pct_chg": 6 if day % 10 == 0 else 1, "amount": 200 + day})
        rows.append({"code": "B", "trade_date": f"2026-04-{day:02d}", "open": 10, "high": 10.5, "low": 9.8, "close": 10 + day * 0.02, "pct_chg": 0.2, "amount": 100})
    daily = pd.DataFrame(rows)

    result = calculate_stock_character_scores(daily, "2026-04-61")

    score_a = result[result["code"] == "A"].iloc[0]
    score_b = result[result["code"] == "B"].iloc[0]
    assert score_a["stock_character_score_raw"] > score_b["stock_character_score_raw"]
    assert score_a["rps60"] >= score_b["rps60"]
    assert "股性活跃" in score_a["character_reason"]
```

- [ ] **Step 2: Run stock character tests to verify RED**

Run:

```bash
pytest tests/test_stock_character.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.stock_character'`.

- [ ] **Step 3: Create `src/stock_character.py`**

```python
from __future__ import annotations

import pandas as pd

from src.indicators import add_returns, add_rps


def calculate_stock_character_scores(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    history = add_returns(history, periods=(20, 60))
    history = add_rps(history, "return_20d", "rps20")
    history = add_rps(history, "return_60d", "rps60")
    recent60 = history.groupby("code").tail(60).copy()

    recent60["amplitude"] = (recent60["high"] - recent60["low"]) / recent60["close"] * 100
    active = recent60.groupby("code").agg(
        big_up_count=("pct_chg", lambda value: int((value > 5).sum())),
        limit_up_count=("pct_chg", lambda value: int((value >= 9.5).sum())),
        avg_amplitude_20d=("amplitude", lambda value: float(value.tail(20).mean())),
        max_return_60d=("close", lambda value: float((value.max() - value.iloc[0]) / value.iloc[0] * 100) if len(value) else 0),
        amount_mean=("amount", "mean"),
        amount_last=("amount", "last"),
    ).reset_index()

    latest = history.groupby("code", as_index=False).tail(1)[["code", "rps20", "rps60"]]
    result = active.merge(latest, on="code", how="left")
    result[["rps20", "rps60"]] = result[["rps20", "rps60"]].fillna(0)
    result["stock_character_score_raw"] = (
        result["big_up_count"].clip(upper=12) * 4
        + result["limit_up_count"].clip(upper=5) * 5
        + result["avg_amplitude_20d"].clip(upper=12) * 2
        + result["max_return_60d"].clip(lower=0, upper=80) * 0.2
        + result["rps20"] * 0.15
        + result["rps60"] * 0.15
    ).clip(lower=0, upper=100)
    result["character_reason"] = result.apply(
        lambda row: "股性活跃，历史异动频率较高" if row["big_up_count"] >= 4 or row["rps20"] >= 80 else "股性一般，历史活跃度不突出",
        axis=1,
    )
    return result
```

- [ ] **Step 4: Run stock character tests to verify GREEN**

Run:

```bash
pytest tests/test_stock_character.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/stock_character.py tests/test_stock_character.py
git commit -m "feat: score stock character"
```

---

### Task 9: Volume-Price Structure Score

**Files:**
- Create: `stock_selector/src/volume_price_score.py`
- Create: `stock_selector/tests/test_volume_price_score.py`

- [ ] **Step 1: Write failing volume-price tests**

Create `tests/test_volume_price_score.py`:

```python
import pandas as pd

from src.volume_price_score import calculate_volume_price_scores


def test_volume_price_rewards_breakout_with_volume() -> None:
    rows = []
    for day in range(1, 62):
        rows.append({"code": "A", "trade_date": f"2026-05-{day:02d}", "open": 10, "high": 10 + day * 0.1, "low": 9.8, "close": 10 + day * 0.1, "amount": 100})
        rows.append({"code": "B", "trade_date": f"2026-05-{day:02d}", "open": 10, "high": 10.2, "low": 9.8, "close": 10, "amount": 100})
    rows[-2]["amount"] = 300
    rows[-2]["pct_chg"] = 4
    rows[-1]["pct_chg"] = 0
    daily = pd.DataFrame(rows).fillna(1)

    result = calculate_volume_price_scores(daily, "2026-05-61")

    score_a = result[result["code"] == "A"].iloc[0]
    score_b = result[result["code"] == "B"].iloc[0]
    assert score_a["volume_price_score_raw"] > score_b["volume_price_score_raw"]
    assert "突破" in score_a["volume_price_reason"]
```

- [ ] **Step 2: Run volume-price tests to verify RED**

Run:

```bash
pytest tests/test_volume_price_score.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.volume_price_score'`.

- [ ] **Step 3: Create `src/volume_price_score.py`**

```python
from __future__ import annotations

import pandas as pd

from src.indicators import moving_average


def calculate_volume_price_scores(daily: pd.DataFrame, report_date: str) -> pd.DataFrame:
    history = daily[daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).copy()
    history["ma5"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 5))
    history["ma10"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 10))
    history["ma20"] = history.groupby("code")["close"].transform(lambda value: moving_average(value, 20))
    history["amount_ma20"] = history.groupby("code")["amount"].transform(lambda value: moving_average(value, 20))
    history["high_20"] = history.groupby("code")["high"].transform(lambda value: value.rolling(20, min_periods=1).max())
    history["high_60"] = history.groupby("code")["high"].transform(lambda value: value.rolling(60, min_periods=1).max())
    latest = history.groupby("code", as_index=False).tail(1).copy()
    latest["amount_ratio"] = latest["amount"] / latest["amount_ma20"].replace(0, pd.NA)
    latest["break_20d_high"] = latest["close"] >= latest["high_20"] * 0.995
    latest["break_60d_high"] = latest["close"] >= latest["high_60"] * 0.995
    latest["above_ma5"] = latest["close"] >= latest["ma5"]
    latest["above_ma10"] = latest["close"] >= latest["ma10"]
    latest["above_ma20"] = latest["close"] >= latest["ma20"]
    latest["upper_shadow_ratio"] = (latest["high"] - latest[["open", "close"]].max(axis=1)) / (latest["high"] - latest["low"]).replace(0, pd.NA)
    latest["volume_price_score_raw"] = (
        latest["amount_ratio"].fillna(1).clip(upper=3) * 12
        + latest["pct_chg"].fillna(0).clip(lower=-5, upper=8) * 2
        + latest["break_20d_high"].astype(int) * 15
        + latest["break_60d_high"].astype(int) * 15
        + latest["above_ma5"].astype(int) * 8
        + latest["above_ma10"].astype(int) * 6
        + latest["above_ma20"].astype(int) * 6
        - latest["upper_shadow_ratio"].fillna(0).gt(0.5).astype(int) * 10
    ).clip(lower=0, upper=100)
    latest["volume_price_reason"] = latest.apply(
        lambda row: "放量突破，站上关键均线" if row["break_20d_high"] and row["amount_ratio"] >= 1.5 else "量价结构普通",
        axis=1,
    )
    return latest[[
        "code",
        "amount_ratio",
        "break_20d_high",
        "break_60d_high",
        "above_ma5",
        "above_ma10",
        "above_ma20",
        "upper_shadow_ratio",
        "volume_price_score_raw",
        "volume_price_reason",
    ]]
```

- [ ] **Step 4: Run volume-price tests to verify GREEN**

Run:

```bash
pytest tests/test_volume_price_score.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/volume_price_score.py tests/test_volume_price_score.py
git commit -m "feat: score volume price structure"
```

---

### Task 10: Risk Penalty and Warnings

**Files:**
- Create: `stock_selector/src/risk_filter.py`
- Create: `stock_selector/tests/test_risk_filter.py`

- [ ] **Step 1: Write failing risk tests**

Create `tests/test_risk_filter.py`:

```python
import pandas as pd

from src.config import RiskConfig, ScoringConfig
from src.risk_filter import calculate_risk_penalties


def test_risk_penalty_caps_and_explains_multiple_risks() -> None:
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "return_5d": 35,
                "return_10d": 50,
                "distance_ma20": 30,
                "upper_shadow_ratio": 0.7,
                "amount_ratio": 3.5,
                "pct_chg": 0.2,
                "turnover_rate": 30,
                "volatility_20d": 0.1,
            }
        ]
    )

    result = calculate_risk_penalties(factors, RiskConfig(), ScoringConfig(risk_penalty_max=20))

    row = result.iloc[0]
    assert row["risk_penalty"] == 20
    assert "近5日涨幅" in row["risk_warning"]
    assert "距离20日线" in row["risk_warning"]
```

- [ ] **Step 2: Run risk tests to verify RED**

Run:

```bash
pytest tests/test_risk_filter.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.risk_filter'`.

- [ ] **Step 3: Create `src/risk_filter.py`**

```python
from __future__ import annotations

import pandas as pd

from src.config import RiskConfig, ScoringConfig


def calculate_risk_penalties(factors: pd.DataFrame, risk: RiskConfig, scoring: ScoringConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in factors.iterrows():
        penalty = 0.0
        warnings: list[str] = []
        if float(row.get("return_5d", 0) or 0) > risk.max_pct_chg_5d:
            penalty += 5
            warnings.append(f"近5日涨幅 {row.get('return_5d'):.1f}% 过大")
        if float(row.get("return_10d", 0) or 0) > risk.max_pct_chg_10d:
            penalty += 5
            warnings.append(f"近10日涨幅 {row.get('return_10d'):.1f}% 过大")
        if float(row.get("distance_ma20", 0) or 0) > risk.max_distance_ma20:
            penalty += 5
            warnings.append(f"距离20日线 {row.get('distance_ma20'):.1f}% 偏远")
        if float(row.get("upper_shadow_ratio", 0) or 0) > risk.long_upper_shadow_ratio:
            penalty += 3
            warnings.append("今日长上影线明显")
        if float(row.get("amount_ratio", 0) or 0) > 3 and float(row.get("pct_chg", 0) or 0) < 1:
            penalty += 4
            warnings.append("爆量滞涨")
        if float(row.get("turnover_rate", 0) or 0) > risk.high_turnover_ratio:
            penalty += 3
            warnings.append("换手率过高")
        if float(row.get("volatility_20d", 0) or 0) > risk.high_volatility_20d:
            penalty += 3
            warnings.append("近20日波动率偏高")
        rows.append(
            {
                "code": row["code"],
                "risk_penalty": min(scoring.risk_penalty_max, penalty),
                "risk_warning": "，".join(warnings) if warnings else "暂无明显量化风险",
            }
        )
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run risk tests to verify GREEN**

Run:

```bash
pytest tests/test_risk_filter.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/risk_filter.py tests/test_risk_filter.py
git commit -m "feat: calculate risk penalties"
```

---

### Task 11: Weighted Scoring and Selection Text

**Files:**
- Create: `stock_selector/src/scoring.py`
- Create: `stock_selector/tests/test_scoring.py`

- [ ] **Step 1: Write failing scoring tests**

Create `tests/test_scoring.py`:

```python
import pandas as pd

from src.config import ReportConfig, ScoringConfig
from src.scoring import build_ranked_results


def test_build_ranked_results_weights_scores_and_builds_text() -> None:
    factors = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "强势股",
                "industry": "机器人",
                "pct_chg": 4,
                "return_5d": 8,
                "return_20d": 20,
                "amount_ratio": 2,
                "rps20": 90,
                "rps60": 80,
                "sector_score_raw": 90,
                "stock_character_score_raw": 80,
                "volume_price_score_raw": 85,
                "risk_penalty": 5,
                "sector_reason": "板块走强",
                "character_reason": "股性活跃",
                "volume_price_reason": "放量突破",
                "risk_warning": "暂无明显量化风险",
            },
            {
                "code": "000002",
                "name": "普通股",
                "industry": "银行",
                "pct_chg": 0,
                "return_5d": 1,
                "return_20d": 2,
                "amount_ratio": 1,
                "rps20": 30,
                "rps60": 40,
                "sector_score_raw": 30,
                "stock_character_score_raw": 20,
                "volume_price_score_raw": 25,
                "risk_penalty": 0,
                "sector_reason": "板块一般",
                "character_reason": "股性一般",
                "volume_price_reason": "量价普通",
                "risk_warning": "暂无明显量化风险",
            },
        ]
    )
    market = {"market_score": 7.5, "market_label": "偏强"}

    ranked, top50, top10 = build_ranked_results(factors, market, ScoringConfig(), ReportConfig(top_observe=1, top_focus=1))

    assert ranked.iloc[0]["code"] == "000001"
    assert top50["code"].tolist() == ["000001"]
    assert top10["code"].tolist() == ["000001"]
    assert "放量突破" in ranked.iloc[0]["selection_reason"]
    assert "不追高" in ranked.iloc[0]["next_day_condition"]
```

- [ ] **Step 2: Run scoring tests to verify RED**

Run:

```bash
pytest tests/test_scoring.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.scoring'`.

- [ ] **Step 3: Create `src/scoring.py`**

```python
from __future__ import annotations

import pandas as pd

from src.config import ReportConfig, ScoringConfig


def _weighted(raw: pd.Series, weight: float) -> pd.Series:
    return raw.fillna(0).clip(lower=0, upper=100) / 100 * weight


def _reason(row: pd.Series) -> str:
    parts = []
    for column in ["sector_reason", "character_reason", "volume_price_reason"]:
        value = str(row.get(column, "") or "")
        if value:
            parts.append(value)
    if row.get("rps20", 0) >= 80:
        parts.append("RPS20 居前")
    return "；".join(parts)


def _next_day_condition(row: pd.Series, market: dict[str, object]) -> str:
    if market.get("market_label") == "偏弱":
        return "大盘偏弱，降低关注优先级，等待板块和成交量确认"
    if row.get("amount_ratio", 0) >= 1.5 and row.get("rps20", 0) >= 80:
        return "不追高，观察是否回踩 5 日线不破；若板块继续走强再重点观察"
    return "观察是否放量突破前高，弱于板块时降低优先级"


def build_ranked_results(
    factors: pd.DataFrame,
    market: dict[str, object],
    scoring: ScoringConfig,
    report: ReportConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    result = factors.copy()
    result["sector_score"] = _weighted(result["sector_score_raw"], scoring.sector_score_weight)
    result["stock_character_score"] = _weighted(result["stock_character_score_raw"], scoring.stock_character_weight)
    result["volume_price_score"] = _weighted(result["volume_price_score_raw"], scoring.volume_price_weight)
    result["relative_strength_score"] = _weighted((result["rps20"].fillna(0) * 0.6 + result["rps60"].fillna(0) * 0.4), scoring.relative_strength_weight)
    result["market_adjust_score"] = float(market.get("market_score", 5)) / 10 * scoring.market_adjust_weight
    result["total_score"] = (
        result["sector_score"]
        + result["stock_character_score"]
        + result["volume_price_score"]
        + result["relative_strength_score"]
        + result["market_adjust_score"]
        - result["risk_penalty"].fillna(0)
    ).clip(lower=0, upper=100).round(2)
    result["selection_reason"] = result.apply(_reason, axis=1)
    result["next_day_condition"] = result.apply(lambda row: _next_day_condition(row, market), axis=1)
    result = result.sort_values("total_score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", range(1, len(result) + 1))
    return result, result.head(report.top_observe).copy(), result.head(report.top_focus).copy()
```

- [ ] **Step 4: Run scoring tests to verify GREEN**

Run:

```bash
pytest tests/test_scoring.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/scoring.py tests/test_scoring.py
git commit -m "feat: rank stocks with weighted scoring"
```

---

### Task 12: Excel Report Writer

**Files:**
- Create: `stock_selector/src/report.py`
- Create: `stock_selector/tests/test_report.py`

- [ ] **Step 1: Write failing report tests**

Create `tests/test_report.py`:

```python
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from src.report import write_excel_report


def test_write_excel_report_creates_required_sheets(tmp_path: Path) -> None:
    market = {"market_label": "偏强", "risk_level": "中", "market_score": 7.5, "up_ratio": 62, "limit_up_count": 78, "limit_down_count": 12}
    strong_sectors = pd.DataFrame([{"sector_name": "机器人", "sector_score_raw": 90, "sector_reason": "板块涨幅 4.2%"}])
    ranked = pd.DataFrame(
        [
            {
                "rank": 1,
                "code": "000001",
                "name": "强势股",
                "industry": "机器人",
                "total_score": 88,
                "pct_chg": 4,
                "return_5d": 8,
                "return_20d": 20,
                "amount_ratio": 2,
                "rps20": 90,
                "rps60": 80,
                "sector_score": 22,
                "stock_character_score": 16,
                "volume_price_score": 21,
                "risk_penalty": 5,
                "selection_reason": "放量突破",
                "next_day_condition": "不追高",
                "risk_warning": "暂无明显量化风险",
            }
        ]
    )
    filtered = pd.DataFrame([{"code": "000002", "name": "ST测试", "filter_reason": "ST 或退市风险"}])

    path = write_excel_report(tmp_path, "2026-06-22", market, strong_sectors, ranked, ranked, ranked, filtered)

    assert path.exists()
    workbook = load_workbook(path)
    assert workbook.sheetnames == ["市场环境", "强势板块", "Top50观察名单", "Top10重点关注", "风险过滤名单", "原始评分明细"]
    assert workbook["Top50观察名单"]["A1"].value == "排名"
```

- [ ] **Step 2: Run report tests to verify RED**

Run:

```bash
pytest tests/test_report.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.report'`.

- [ ] **Step 3: Create `src/report.py`**

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd


TOP50_COLUMNS = {
    "rank": "排名",
    "code": "股票代码",
    "name": "股票名称",
    "total_score": "总分",
    "industry": "所属板块",
    "pct_chg": "今日涨跌幅",
    "return_5d": "近5日涨跌幅",
    "return_20d": "近20日涨跌幅",
    "amount_ratio": "成交额放大倍数",
    "rps20": "RPS20",
    "rps60": "RPS60",
    "sector_score": "板块分",
    "stock_character_score": "股性分",
    "volume_price_score": "量价分",
    "risk_penalty": "风险扣分",
    "selection_reason": "入选理由",
    "risk_warning": "风险提示",
}

TOP10_COLUMNS = {
    "rank": "排名",
    "code": "股票代码",
    "name": "股票名称",
    "total_score": "总分",
    "selection_reason": "重点关注理由",
    "next_day_condition": "次日观察条件",
    "risk_warning": "风险提示",
}


def _rename_existing(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    existing = [column for column in columns if column in df.columns]
    return df[existing].rename(columns=columns)


def write_excel_report(
    output_dir: str | Path,
    report_date: str,
    market: dict[str, object],
    strong_sectors: pd.DataFrame,
    top50: pd.DataFrame,
    top10: pd.DataFrame,
    ranked: pd.DataFrame,
    filtered: pd.DataFrame,
) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{report_date}_盘后选股报告.xlsx"
    market_df = pd.DataFrame([market])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        market_df.to_excel(writer, sheet_name="市场环境", index=False)
        strong_sectors.to_excel(writer, sheet_name="强势板块", index=False)
        _rename_existing(top50, TOP50_COLUMNS).to_excel(writer, sheet_name="Top50观察名单", index=False)
        _rename_existing(top10, TOP10_COLUMNS).to_excel(writer, sheet_name="Top10重点关注", index=False)
        filtered.to_excel(writer, sheet_name="风险过滤名单", index=False)
        ranked.to_excel(writer, sheet_name="原始评分明细", index=False)
    return path
```

- [ ] **Step 4: Run report tests to verify GREEN**

Run:

```bash
pytest tests/test_report.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Optional checkpoint**

If inside a Git repository:

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: write excel report"
```

---

### Task 13: Workflow Orchestration and CLI

**Files:**
- Create: `stock_selector/src/run_daily.py`
- Create: `stock_selector/run_daily.py`
- Create: `stock_selector/main.py`
- Create: `stock_selector/tests/test_run_daily.py`

- [ ] **Step 1: Write failing orchestration test**

Create `tests/test_run_daily.py`:

```python
from pathlib import Path

from src.run_daily import parse_args, resolve_report_date


def test_parse_args_supports_init_and_date() -> None:
    args = parse_args(["--init", "--date", "2026-06-22"])

    assert args.init is True
    assert args.date == "2026-06-22"


def test_resolve_report_date_uses_requested_date() -> None:
    assert resolve_report_date("2026-06-22", "2026-06-21") == "2026-06-22"
```

- [ ] **Step 2: Run orchestration tests to verify RED**

Run:

```bash
pytest tests/test_run_daily.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.run_daily'`.

- [ ] **Step 3: Create `src/run_daily.py`**

```python
from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from src.build_pool import build_stock_pool
from src.config import load_config
from src.database import Database
from src.market_score import calculate_market_score
from src.report import write_excel_report
from src.scoring import build_ranked_results
from src.sector_score import calculate_sector_scores
from src.stock_character import calculate_stock_character_scores
from src.volume_price_score import calculate_volume_price_scores
from src.risk_filter import calculate_risk_penalties


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A 股盘后多因子选股助手")
    parser.add_argument("--init", action="store_true", help="初始化并回填历史数据")
    parser.add_argument("--date", help="指定报告日期，格式 YYYY-MM-DD")
    return parser.parse_args(argv)


def setup_logging(report_date: str) -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / f"run_{report_date}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def resolve_report_date(requested_date: str | None, latest_trade_date: str | None) -> str:
    if requested_date:
        return requested_date
    return latest_trade_date or date.today().strftime("%Y-%m-%d")


def _empty_if_missing(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df if not df.empty else pd.DataFrame(columns=columns)


def run(argv: list[str] | None = None) -> Path | None:
    args = parse_args(argv)
    preliminary_date = args.date or date.today().strftime("%Y-%m-%d")
    setup_logging(preliminary_date)
    logger = logging.getLogger(__name__)
    config = load_config()
    db = Database(config.data.database)
    db.initialize()

    if args.init:
        logger.info("初始化模式已启动。数据回填将在数据接入任务完成后执行。")

    stock_basic = _empty_if_missing(db.read_table("stock_basic"), ["code", "name", "industry", "list_date", "is_st", "is_listed"])
    stock_daily = _empty_if_missing(db.read_table("stock_daily"), ["code", "trade_date", "open", "high", "low", "close", "amount", "pct_chg", "turnover_rate", "is_suspended"])
    index_daily = _empty_if_missing(db.read_table("index_daily"), ["index_code", "trade_date", "close", "amount", "pct_chg"])
    sector_daily = _empty_if_missing(db.read_table("sector_daily"), ["sector_name", "trade_date", "pct_chg", "amount"])
    latest_trade_date = None if stock_daily.empty else str(stock_daily["trade_date"].max())
    report_date = resolve_report_date(args.date, latest_trade_date)

    if stock_basic.empty or stock_daily.empty:
        logger.warning("本地数据库暂无足够行情数据，请先完成 --init 数据回填。")
        return None

    eligible, filtered = build_stock_pool(stock_basic, stock_daily, report_date, config.stock_pool)
    market = calculate_market_score(index_daily, stock_daily, report_date)
    sector_scores, strong_sectors = calculate_sector_scores(sector_daily, stock_basic, stock_daily, report_date)
    character = calculate_stock_character_scores(stock_daily, report_date)
    volume_price = calculate_volume_price_scores(stock_daily, report_date)

    latest = stock_daily[stock_daily["trade_date"] <= report_date].sort_values(["code", "trade_date"]).groupby("code", as_index=False).tail(1)
    factors = eligible.merge(latest[["code", "pct_chg", "turnover_rate"]], on="code", how="left", suffixes=("", "_latest"))
    factors = factors.merge(sector_scores, on=["code", "industry"], how="left")
    factors = factors.merge(character, on="code", how="left")
    factors = factors.merge(volume_price, on="code", how="left")
    factors["return_5d"] = factors.get("return_5d", 0)
    factors["return_10d"] = factors.get("return_10d", 0)
    factors["return_20d"] = factors.get("return_20d", 0)
    factors["distance_ma20"] = 0
    factors["volatility_20d"] = 0
    risk = calculate_risk_penalties(factors, config.risk, config.scoring)
    factors = factors.merge(risk, on="code", how="left")
    ranked, top50, top10 = build_ranked_results(factors, market, config.scoring, config.report)
    report_path = write_excel_report(config.report.output_dir, report_date, market, strong_sectors, top50, top10, ranked, filtered)

    print(f"今日市场环境：{market['market_label']}")
    print(f"市场风险等级：{market['risk_level']}")
    print(f"上涨家数占比：{market['up_ratio']}%")
    print(f"涨停家数：{market['limit_up_count']}")
    print(f"跌停家数：{market['limit_down_count']}")
    print(f"报告路径：{report_path}")
    return report_path


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Create top-level CLI shims**

Create `run_daily.py`:

```python
from src.run_daily import run


if __name__ == "__main__":
    run()
```

Create `main.py`:

```python
import sys

from src.run_daily import run


if __name__ == "__main__":
    argv = ["--init" if arg == "--backfill" else arg for arg in sys.argv[1:]]
    run(argv)
```

- [ ] **Step 5: Run orchestration tests to verify GREEN**

Run:

```bash
pytest tests/test_run_daily.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run all unit tests**

Run:

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Optional checkpoint**

If inside a Git repository:

```bash
git add src/run_daily.py run_daily.py main.py tests/test_run_daily.py
git commit -m "feat: add daily workflow cli"
```

---

### Task 14: README and Manual Verification

**Files:**
- Create: `stock_selector/README.md`

- [ ] **Step 1: Create README**

Create `README.md`:

```markdown
# 免费版 A 股盘后多因子选股助手

这是一个个人本地运行的 A 股盘后复盘工具。它每天收盘后更新免费数据源，按市场环境、行业热度、历史股性、量价结构、相对强弱和风险扣分生成观察名单。

本项目不是投资建议，不做自动交易，不连接券商接口，不使用实时行情。

## 安装

```bash
cd E:\我的git项目\Github\stock_selector
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## 首次初始化

```bash
python run_daily.py --init
```

兼容入口：

```bash
python main.py --backfill
```

## 每日盘后运行

```bash
python run_daily.py
```

## 指定日期重跑

```bash
python run_daily.py --date 2026-06-22
```

## 输出

报告路径：

```text
reports/YYYY-MM-DD_盘后选股报告.xlsx
```

日志路径：

```text
logs/run_YYYY-MM-DD.log
```

Excel sheet：

1. 市场环境
2. 强势板块
3. Top50观察名单
4. Top10重点关注
5. 风险过滤名单
6. 原始评分明细

## 配置

`config/strategy.yml` 控制数据源、报告数量、功能开关和评分权重。

`config/stock_pool.yml` 控制股票池过滤阈值和风险扣分阈值。

## 数据源

- `baostock`：股票日线、指数日线、基础信息。
- `AKShare`：行业板块和辅助市场数据。

如果 AKShare 行业接口失败，系统会记录日志并继续生成报告，板块分按 0 处理。

## 风险说明

观察名单只用于人工复盘。第二天是否操作，需要结合大盘、板块强弱、开盘位置、成交量和个人风险控制判断。
```

- [ ] **Step 2: Run full unit test suite**

Run:

```bash
cd E:\我的git项目\Github\stock_selector
pytest -v
```

Expected: all tests pass.

- [ ] **Step 3: Run CLI help**

Run:

```bash
python run_daily.py --help
```

Expected: output includes `--init` and `--date`.

- [ ] **Step 4: Run local no-data smoke test**

Run:

```bash
python run_daily.py --date 2026-06-22
```

Expected: exits without traceback, creates `data/stock.db`, creates `logs/run_2026-06-22.log`, and prints a warning that local行情数据不足 if no data has been loaded.

- [ ] **Step 5: Manual network verification**

Run after dependencies are installed and network access is available:

```bash
python run_daily.py --init
python run_daily.py --date 2026-06-22
```

Expected: data updates complete, `reports/2026-06-22_盘后选股报告.xlsx` is created, and workbook contains Top50 and Top10 sheets.

- [ ] **Step 6: Optional checkpoint**

If inside a Git repository:

```bash
git add README.md
git commit -m "docs: document daily selector usage"
```

---

## Self-Review Checklist

- Spec coverage: The plan covers dependencies, config, SQLite, data adapters, stock pool filtering, market score, sector score, stock character, volume-price score, risk penalty, weighted ranking, Excel report, CLI/logging, README, and manual verification.
- Scope control: Real trading, real-time行情, paid data, machine learning, Web frontend, brokerage APIs, and AI summary are excluded from implementation tasks.
- Type consistency: The shared identifiers are `code`, `trade_date`, `industry`, `sector_score_raw`, `stock_character_score_raw`, `volume_price_score_raw`, `risk_penalty`, `rps20`, and `rps60` across modules.
- Test strategy: Unit tests use in-memory DataFrames and temporary SQLite paths; real data-source calls are limited to manual verification.
