# 免费（乞丐）版 A 股盘后多因子选股助手

这是一个个人本地运行的 A 股盘后复盘工具。它每天收盘后更新免费数据源，按市场环境、行业热度、历史股性、量价结构、相对强弱、策略命中和风险扣分生成观察名单。

本项目不是投资建议，不做自动交易，不连接券商接口，不使用实时行情。选出的股票只用于第二天人工观察。

## 应该怎么开始

如果只是想先跑起来，按下面 5 步走。

### 1. 打开 PowerShell，进入项目目录

```powershell
cd \仓库路径\
```

### 2. 确认 Python 版本

推荐使用 Python 3.12.x。

```powershell
python --version
```

如果输出是 `Python 3.12.x`，继续下一步。如果不是，也可以试试下面这个命令：

```powershell
py -3.12 --version
```

如果这两个命令都找不到 Python 3.12，需要先安装 Python 3.12。

### 3. 创建并激活虚拟环境

第一次使用时执行：

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

如果你的电脑上 `python` 不是 3.12，可以用：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\activate
```

激活成功后，命令行前面通常会出现 `(.venv)`。

以后每天再次使用时，只需要进入目录并激活虚拟环境：

```powershell
cd \仓库路径\
.\.venv\Scripts\activate
```

### 4. 安装依赖

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

本项目使用的核心依赖包括 `pandas`、`numpy`、`SQLite`、`openpyxl`、`pytdx`、`baostock` 和 `AKShare`。默认使用通达信公开行情节点（pytdx），免费、免账号，也不会登录 baostock。

### 5. 首次初始化历史数据

第一次运行需要先拉取基础信息和历史行情：

```powershell
python run_daily.py --init
```

这一步会做几件事：

- 创建本地 SQLite 数据库：`data/stock.db`
- 拉取 A 股基础信息
- 拉取个股日线数据
- 拉取主要指数日线数据
- 尝试拉取行业板块数据；不可用时从个股日线聚合沪市主板、深市主板、创业板、科创板和北交所热度
- 生成当日盘后报告

首次初始化需要遍历全市场。当前 Windows 环境实测：从 2023-01-01 回填约 5530 只股票用了约 12 分钟，随后因子计算和 Excel 生成约 2 分钟；网络和电脑性能不同会有差异。中途个别股票或板块接口失败时，程序会写入日志，并尽量继续跑完整体流程。

### 6. 退出虚拟环境

用完后如果想退出当前虚拟环境，执行：

```powershell
deactivate
```

退出后，命令行前面的 `(.venv)` 会消失。下次使用前再执行：

```powershell
.\.venv\Scripts\activate
```


## 数据会占多少硬盘空间

数据主要保存在本地 SQLite 文件：

```text
data/stock.db
```

第一版默认不会拉取 A 股上市以来的所有历史数据，而是从 `config/strategy.yml` 里的 `data.start_date` 开始拉取。当前默认值是：

```yaml
data:
  provider: tdx
  start_date: "2023-01-01"
  tdx_parallel_workers: 4
  tdx_parallel_chunk_size: 50
  tdx_timeout_seconds: 3
  tdx_query_retries: 3
  init_min_stock_coverage: 0.90
  init_min_daily_rows: 100000
  init_min_index_count: 3
  analysis_lookback_days: 240
```

`data.provider` 支持以下值：

- `tdx`：默认值。连接多个通达信公开行情节点，免费、免账号，支持沪深北三市，不会调用 `baostock.login()`。
- `akshare`：使用 AKShare / 东方财富逐只拉取。当前网络下可能出现 `RemoteDisconnected`，不建议用于全市场初始化。
- `baostock`：只使用 baostock。已经出现黑名单时不要选择这个值。
- `mixed`：兼容模式，先尝试 baostock；只有登录被黑名单或限流拦截时才切到 TDX。当前建议直接使用 `tdx`，避免无意义地再次登录 baostock。

TDX 默认使用 4 个线程，每批 50 只股票。某个节点失败时会自动切换到其他节点；如果短时间失败股票过多，熔断器会停止空转并明确报错。`--init` 会记录每只股票的 TDX 完整同步状态，中断后再次执行同一命令可以准确续传。

初始化结束后还会检查数据质量：股票覆盖率至少 90%、日线至少 10 万条、主要指数至少 3 个。没有达到这些条件时命令会失败并提示具体缺口，不会把空数据或少量数据当成初始化成功。

如果已经看到 `黑名单用户，请与管理员联系`，不需要注册账号，也不要继续反复尝试 baostock。确认配置保持 `provider: tdx`，然后运行：

```powershell
python run_daily.py --init
```

从旧版 baostock 数据迁移时，TDX 会按股票逐只用未复权价格完整覆盖配置日期范围，并写入 `stock_sync_status` 断点状态。已有数据不会在开始时整库删除；中断后已完成的股票会被跳过。

默认 TDX 模式不依赖东方财富行业接口；外部行业数据为空时，报告中的强势板块会使用本地市场板块聚合结果，不会再生成空白 sheet。

也就是说，首次执行：

```powershell
python run_daily.py --init
```

会拉取从 2023-01-01 到运行日期之间的 A 股日线、主要指数日线和板块数据。

大致空间估算：

- 当前实测从 2023 年开始的全市场日线约占 600 MB；SQLite 索引、股票数量和运行日期会让体积有所变化。
- 如果把 `start_date` 改到 2010 年甚至更早，数据库可能增长到数 GB。
- `reports/` 里的 Excel 报告通常不大，但长期每天生成也会慢慢累积。
- `logs/` 日志一般很小。

如果你想少占空间，可以把起始日期调近一点，例如只保留最近一年：

```yaml
data:
  start_date: "2025-01-01"
```

但注意：一些因子会用到 60 日历史数据，股票池过滤会用到上市天数和 20 日成交额，所以 `start_date` 不建议太近。比较稳妥的选择是保留至少 6 到 12 个月历史。

日常运行：

```powershell
python run_daily.py
```

会尽量按本地数据库已有日期做增量更新：如果某只股票本地最新日期是 2026-06-20，而你运行到 2026-06-23，它只会请求 2026-06-21 到 2026-06-23 的数据，不会每天重复拉取全部历史。

只有在你明确想清空所有本地数据并从零重建时，才删除数据库后执行 `--init`；普通中断续传不要删除：

```powershell
Remove-Item data\stock.db
python run_daily.py --init
```

删除数据库会清空本地历史行情，下次初始化会重新拉取。

## 每天盘后怎么用

每天收盘后，打开 PowerShell：

```powershell
cd \仓库路径\
.\.venv\Scripts\activate
python run_daily.py
```

运行完成后查看：

```text
reports/YYYY-MM-DD_盘后选股报告.xlsx
logs/run_YYYY-MM-DD.log
```

例如 2026-06-22 的报告会类似：

```text
reports/2026-06-22_盘后选股报告.xlsx
logs/run_2026-06-22.log
```

## 指定日期重跑

如果你想重跑某一天：

```powershell
python run_daily.py --date 2026-06-22
```

也可以使用兼容入口：

```powershell
python main.py --backfill
python main.py --date 2026-06-22
```

## Excel 报告怎么看

报告包含 6 个 sheet：

1. `市场环境`：大盘环境、风险等级、上涨家数占比、涨停跌停数量等。
2. `强势板块`：当日较强行业或板块。
3. `Top50观察名单`：综合评分排名前 50 的观察股。
4. `Top10重点关注`：从 Top50 中进一步筛出的重点观察股。
5. `风险过滤名单`：因为 ST、停牌、成交额过低、上市时间不足等原因被过滤的股票。
6. `原始评分明细`：所有参与评分股票的完整因子和分数。

Top50 重点看这些列：

- `总分`：综合得分，越高代表规则体系越认可。
- `板块分`：所属行业或板块热度。
- `股性分`：历史活跃度、涨停次数、RPS 等。
- `量价分`：放量、突破、均线、相对强弱等。
- `策略分`：是否命中内置策略。
- `命中策略`：例如均线放量突破、海龟突破、RPS强势突破。
- `入选理由`：为什么进入观察名单。
- `风险提示`：追高、偏离均线、长上影、爆量滞涨等风险。

Top10 重点看：

- `重点关注理由`
- `次日观察条件`
- `风险提示`

注意：报告不是买入建议。第二天还要结合大盘、板块、开盘位置、成交量和个人风控人工判断。

## 策略筛选

系统有一层类似 Sequoia-X 思路的可扩展规则策略筛选层。默认策略在 `config/strategy.yml` 的 `strategies.enabled` 中配置：

- `ma_volume`：均线放量突破
- `turtle_breakout`：海龟突破
- `rps_breakout`：RPS强势突破
- `pullback_stable`：缩量回踩企稳
- `limit_up_shakeout`：涨停洗盘回踩

策略命中会生成：

- `strategy_score_raw`
- `matched_strategies`
- `strategy_reason`

并按 `strategies.strategy_score_weight` 计入总分。

示例：

```yaml
strategies:
  enabled:
    - ma_volume
    - turtle_breakout
    - rps_breakout
    - pullback_stable
    - limit_up_shakeout
  strategy_score_weight: 15
```

如果你暂时只想看某一个策略，可以改成：

```yaml
strategies:
  enabled:
    - ma_volume
  strategy_score_weight: 15
```

新增策略时，把策略类放到 `src/strategies/`，并在 `src/strategies/registry.py` 注册即可。

## 常用配置

配置文件主要有两个：

```text
config/strategy.yml
config/stock_pool.yml
```

### 调整报告数量

在 `config/strategy.yml` 中修改：

```yaml
report:
  top_observe: 50
  top_focus: 10
  output_dir: reports
```

### 调整总分权重

在 `config/strategy.yml` 中修改：

```yaml
scoring:
  sector_score_weight: 25
  stock_character_weight: 20
  volume_price_weight: 25
  relative_strength_weight: 15
  market_adjust_weight: 10
  risk_penalty_max: 20
```

### 调整股票池过滤条件

在 `config/stock_pool.yml` 中修改：

```yaml
stock_pool:
  min_list_days: 120
  min_price: 3
  min_avg_amount_20d: 100000000
  exclude_st: true
  exclude_suspended: true
```

含义：

- `min_list_days`：上市至少多少个交易日。
- `min_price`：最低股价。
- `min_avg_amount_20d`：最近 20 日平均成交额下限。
- `exclude_st`：是否剔除 ST。
- `exclude_suspended`：是否剔除停牌。

### 调整风险扣分

在 `config/stock_pool.yml` 中修改：

```yaml
risk:
  max_pct_chg_5d: 30
  max_pct_chg_10d: 45
  max_distance_ma20: 25
  long_upper_shadow_ratio: 0.5
  high_turnover_ratio: 25
  high_volatility_20d: 0.08
```

## 项目目录

```text
stock_selector/
  config/
    strategy.yml
    stock_pool.yml
  data/
    stock.db
  src/
    fetch_data.py
    database.py
    build_pool.py
    market_score.py
    sector_score.py
    stock_character.py
    volume_price_score.py
    risk_filter.py
    scoring.py
    report.py
    run_daily.py
    strategies/
  reports/
  logs/
  run_daily.py
  main.py
  requirements.txt
```

## 新会话或开发者怎么快速熟悉项目

如果你下次新开 Codex 会话，或者让其他开发者接手，建议先让对方阅读根目录的 `AGENTS.md`。

`AGENTS.md` 里整理了：

- 项目定位和明确不做的事情
- 用户常用命令
- 每日选股主流程
- 关键模块职责
- 配置文件含义
- 策略扩展方法
- 常见修改路径
- 测试命令和注意事项

推荐阅读顺序：

1. `AGENTS.md`
2. `README.md`
3. `config/strategy.yml`
4. `config/stock_pool.yml`
5. `src/run_daily.py`
6. 本次任务相关的 `src/*.py` 和 `tests/test_*.py`

如果是新增或优化策略，优先看：

- `src/strategies/registry.py`
- `src/strategies/base.py`
- `tests/test_strategies.py`

## 常见问题

### 1. `python` 不是 3.12 怎么办

先试：

```powershell
py -3.12 --version
```

如果能看到版本号，就用：

```powershell
py -3.12 -m venv .venv
```

如果找不到，需要先安装 Python 3.12。

### 2. 运行脚本时提示无法执行 activate

可以临时允许当前 PowerShell 会话执行脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\activate
```

这个设置只影响当前窗口。

### 3. 安装依赖很慢

可以使用国内镜像：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 4. 行情拉取失败或长时间没有进度

先看日志：

```text
logs/run_YYYY-MM-DD.log
```

先确认 `config/strategy.yml` 中是：

```yaml
data:
  provider: tdx
```

常见原因：

- 当前通达信节点暂时不可用，程序会自动切换到备用节点。
- 网络防火墙阻止了 7709 端口；默认节点列表同时包含 80 端口节点。
- 指定日期早于股票上市日期，此时个别股票可能没有数据。
- 使用了 `provider: baostock`，而当前网络已被 baostock 标记为黑名单。
- 使用了 `provider: akshare`，东方财富主动断开连接。

初始化被中断时直接重新执行即可，不要删除数据库：

```powershell
python run_daily.py --init
```

日志中的 `TDX stock daily progress` 会显示已处理股票数；结束时 `initialization health` 会显示覆盖率、总行数、指数数和最新交易日。

### 5. 没有生成报告

优先检查：

- 是否已执行 `python run_daily.py --init`
- `data/stock.db` 是否存在
- `logs/` 里的日志是否有错误
- 指定日期是否有本地行情数据

### 6. 控制台中文显示乱码

PowerShell 有时会显示乱码，但文件本身通常是 UTF-8。可以先执行：

```powershell
chcp 65001
```

如果只是控制台显示乱码，不一定影响 Excel 报告内容。

## 开发和测试

运行测试：

```powershell
.\.venv\Scripts\activate
pytest
```

或：

```powershell
python -m pytest -v
```

## 风险说明

这个系统只做盘后复盘和观察名单筛选，不是投资建议，也不做自动买卖。

选出的股票只是辅助人工观察，需要结合第二天大盘、板块强弱、开盘位置、成交量和风险控制再决定是否操作。
