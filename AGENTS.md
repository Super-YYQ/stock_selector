# AGENTS.md

本文件给未来进入仓库的开发者或 AI 助手快速建立上下文。开始修改代码前，先读本文件，再按需阅读 `README.md`、`config/strategy.yml`、`config/stock_pool.yml` 和相关测试。

## 项目定位

这是一个免费、本地运行、盘后使用的 A 股多因子选股助手。

目标是每天收盘后自动复盘市场，筛选观察名单，生成 Excel 报告，辅助用户第二天人工观察。

明确不做：

- 自动交易
- 券商下单
- 实时行情
- Level-2 数据
- Wind 等付费数据源
- 深度学习预测
- 复杂 Web 前端

任何新功能都应优先保持：免费、本地、稳定、可解释、可配置、可扩展。

## 用户常用命令

安装依赖：

```powershell
cd E:\我的git项目\Github\stock_selector
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

首次初始化历史数据：

```powershell
python run_daily.py --init
```

每日盘后运行：

```powershell
python run_daily.py
```

指定日期重跑：

```powershell
python run_daily.py --date 2026-06-22
```

兼容入口：

```powershell
python main.py --backfill
python main.py --date 2026-06-22
```

运行测试：

```powershell
python -m pytest -v
```

## 当前架构

核心入口：

- `run_daily.py`：根目录轻入口，调用 `src.run_daily.run()`。
- `main.py`：兼容入口，把 `--backfill` 转成 `--init`。
- `src/run_daily.py`：每日流程编排。

每日流程大致是：

1. 读取配置：`src/config.py`
2. 初始化 SQLite 表：`src/database.py`
3. 拉取或更新免费数据：`src/fetch_data.py`
4. 构建可评分股票池：`src/build_pool.py`
5. 计算大盘环境：`src/market_score.py`
6. 计算行业或板块热度：`src/sector_score.py`
7. 计算历史股性：`src/stock_character.py`
8. 计算量价结构：`src/volume_price_score.py`
9. 运行策略筛选：`src/strategies/registry.py`
10. 计算风险扣分：`src/risk_filter.py`
11. 汇总总分和排序：`src/scoring.py`
12. 生成 Excel 报告：`src/report.py`

## 关键目录

```text
config/                  策略、权重、过滤条件配置
src/                     业务代码
tests/                   单元测试
docs/superpowers/specs/  设计文档
docs/superpowers/plans/  实施计划
data/                    本地 SQLite 和数据文件，通常不提交
reports/                 生成的 Excel 报告，通常不提交
logs/                    运行日志，通常不提交
```

`.gitignore` 已忽略 `.venv/`、缓存、`data/*.db`、`logs/`、`reports/`、`.worktrees/` 等本地运行产物。

## 配置地图

`config/strategy.yml`：

- `data`：数据源、本地数据库路径、回填起始日期。
- `report`：TopN 数量和报告目录。
- `features`：功能开关。
- `scoring`：板块、股性、量价、RPS、大盘修正、风险扣分权重。
- `strategies`：启用哪些策略，以及策略分权重。

`config/stock_pool.yml`：

- `stock_pool`：股票池过滤条件，例如最低价格、上市天数、20 日平均成交额、是否剔除 ST 和停牌。
- `risk`：风险扣分阈值，例如 5 日涨幅、10 日涨幅、偏离 20 日线、换手率、波动率。

新增参数时，优先放入配置文件，并在 `src/config.py` 中建 dataclass 字段和校验。

## 策略筛选层

策略目录：`src/strategies/`

当前策略：

- `ma_volume`：均线放量突破
- `turtle_breakout`：海龟突破
- `rps_breakout`：RPS强势突破
- `pullback_stable`：缩量回踩企稳
- `limit_up_shakeout`：涨停洗盘回踩

新增策略建议步骤：

1. 在 `src/strategies/` 新增一个策略文件。
2. 继承 `src.strategies.base.Strategy`。
3. 实现 `key`、`name`、`score` 和 `evaluate()`。
4. 在 `src/strategies/registry.py` 的 `STRATEGY_REGISTRY` 注册。
5. 在 `config/strategy.yml` 的 `strategies.enabled` 中启用。
6. 增加或更新 `tests/test_strategies.py`。
7. 跑 `python -m pytest -v`。

策略输出应包含：

- `code`
- `strategy`
- `strategy_score_raw`
- `strategy_reason`

聚合后由 `run_enabled_strategies()` 生成：

- `strategy_score_raw`
- `matched_strategies`
- `strategy_reason`

## 测试约定

当前测试主要是单元测试，避免真实网络请求。

常见测试对应关系：

- 配置：`tests/test_config.py`
- 数据库：`tests/test_database.py`
- 数据清洗：`tests/test_fetch_data.py`
- 股票池过滤：`tests/test_build_pool.py`
- 市场环境：`tests/test_market_score.py`
- 板块评分：`tests/test_sector_score.py`
- 股性评分：`tests/test_stock_character.py`
- 量价评分：`tests/test_volume_price_score.py`
- 风险扣分：`tests/test_risk_filter.py`
- 总分排序：`tests/test_scoring.py`
- 报告生成：`tests/test_report.py`
- 每日入口：`tests/test_run_daily.py`
- 策略筛选：`tests/test_strategies.py`

改业务逻辑时，优先补或改对应测试。提交前至少跑：

```powershell
python -m pytest -v
```

## 常见修改路径

### 增加一个新策略

修改：

- `src/strategies/<new_strategy>.py`
- `src/strategies/registry.py`
- `config/strategy.yml`
- `tests/test_strategies.py`
- 必要时更新 `README.md`

### 调整总分权重

修改：

- `config/strategy.yml`
- 必要时 `src/config.py`
- 必要时 `tests/test_config.py` 和 `tests/test_scoring.py`

### 调整股票池过滤

修改：

- `config/stock_pool.yml`
- `src/build_pool.py`
- `tests/test_build_pool.py`

### 调整风险扣分

修改：

- `config/stock_pool.yml`
- `src/risk_filter.py`
- `tests/test_risk_filter.py`

### 调整 Excel 报告字段

修改：

- `src/report.py`
- `tests/test_report.py`
- `README.md` 的报告说明

### 处理数据源字段变化

修改：

- `src/fetch_data.py` 中的 normalize 函数
- `tests/test_fetch_data.py`

注意给出明确错误信息，例如缺少哪些字段。

## 编码和 Windows 注意事项

- 源码和文档使用 UTF-8。
- PowerShell 有时会把中文显示成乱码，可以先执行 `chcp 65001`，或用 Python 按 UTF-8 读取文件确认。
- Windows 下路径包含中文，命令里尽量使用引号。
- 不要提交 `.venv/`、`data/stock.db`、`logs/`、`reports/`、`.pytest_cache/`。

## 开发原则

- 先保持第一版稳定跑通，再逐步扩展策略。
- 规则要可解释，报告里尽量体现入选理由和风险提示。
- 不把阈值硬编码在业务逻辑里，能配置就放配置。
- 单只股票数据异常不应中断整体任务。
- 免费接口不稳定时，要记录日志并尽量降级继续。
- 新增策略不要让总分不可解释；命中策略、策略理由和风险提示要能对应到报告。
- 不引入自动交易、实时行情、券商接口、复杂前端或重模型。

## 新会话建议阅读顺序

1. `AGENTS.md`：先建立项目地图。
2. `README.md`：确认用户使用方式和配置说明。
3. `config/strategy.yml`、`config/stock_pool.yml`：理解当前参数。
4. `src/run_daily.py`：理解主流程。
5. 与任务相关的 `src/*.py` 和 `tests/test_*.py`。
6. 如果是策略相关任务，重点读 `src/strategies/registry.py` 和 `tests/test_strategies.py`。
## 数据更新策略

- `python run_daily.py --init`：按 `config/strategy.yml` 中的 `data.start_date` 初始化历史数据。
- `python run_daily.py`：读取本地 SQLite 已有的最新交易日，按股票和指数做增量更新。
- 本地数据主要在 `data/stock.db`，默认不提交。
- 修改数据拉取范围时，优先调整 `config/strategy.yml` 的 `data.start_date`，并同步更新 README。

## Data Fetching and Blacklist Notes

- The default provider is `tdx`. It uses `src/tdx_fetcher.py`, public TDX quote nodes, four worker threads, host failover, and a high-failure circuit breaker. It does not create a baostock session.
- Treat `provider: baostock` as an explicit opt-in. Never add an automatic baostock retry loop after a blacklist response. `mixed` exists only for compatibility and falls back from a blocked baostock login to TDX.
- TDX stock prices are stored unadjusted. `stock_sync_status` tracks the `tdx_unadjusted_v1` basis per symbol so an interrupted migration cannot silently mix baostock-adjusted and TDX-unadjusted rows.
- On `--init`, symbols without a complete TDX sync marker are fetched from `data.start_date`; completed symbols resume incrementally. Do not delete `data/stock.db` to resume.
- `validate_initialization()` is the success gate. Coverage, daily-row, and index thresholds are configured under `data.init_min_*`.
- Update logic must query latest dates in SQLite. Report calculations intentionally load only `data.analysis_lookback_days`, not the entire historical table.
- AKShare remains useful for the compact stock code/name list. Its EastMoney historical endpoint is not the default because it can close connections during large backfills.
- Sequoia-X still uses baostock. Its login/reconnect approach is reference context, not the current default architecture here.
