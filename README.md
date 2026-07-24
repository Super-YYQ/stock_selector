# A 股盘后多因子选股助手

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC)](tests)
[![Deploy report to GitHub Pages](https://github.com/Super-YYQ/stock_selector/actions/workflows/pages.yml/badge.svg)](https://github.com/Super-YYQ/stock_selector/actions/workflows/pages.yml)

免费、本地、可解释的 A 股盘后复盘工具。每天收盘后更新日线数据，评估大盘和板块环境，运行多因子策略，生成 Top 50 观察名单、Top 10 重点关注、Excel 报告和手机网页。

> 本项目只做盘后复盘和观察名单筛选，不构成投资建议，不连接券商，也不执行自动交易。

## 功能

- 免费数据源：默认使用无需账号登录的通达信行情协议，保留 AKShare / Baostock 适配
- 本地数据：日线保存在 SQLite，日常只做增量更新
- 市场判断：指数趋势、上涨比例、涨跌停数量和风险等级
- 板块评分：行业或市场板块涨幅、持续性、量能和强势股数量
- 个股背景：核心概念、细分行业、涨停量价线索和行业近半年阶段表现
- 股票池范围：可排除北交所、科创板、创业板或其他不关注的市场板块
- 多因子排名：板块、股性、量价、RPS、市场修正与风险扣分
- 十一种策略：突破、趋势、回踩、事件、板块共振五类策略
- 单策略筛选：内置策略和安全 YAML 公式统一展示，可逐项查看独立命中股票
- 结果追踪：自动记录入选股票，并回填 1 / 3 / 5 / 10 日收益
- 双报告：格式化 Excel + 响应式网页
- 管理面板：每日简报、单策略筛选、策略开关、任务执行、数据健康和报告下载
- 自动化：Windows 计划任务、Docker Compose、GitHub Pages

## Windows 快速开始

### 1. 安装 Python

安装 [Python 3.12](https://www.python.org/downloads/)，安装时勾选 **Add Python to PATH**。

验证安装：

```powershell
py -3.12 --version
```

### 2. 启动面板

双击仓库根目录的 **`start.bat`**。

脚本会自动完成以下工作：

1. 创建 `.venv` 虚拟环境
2. 安装或更新依赖
3. 启动本地面板
4. 打开 `http://127.0.0.1:8765`

不需要手动激活虚拟环境。

需要停止面板时，双击根目录的 **`stop.bat`**。脚本只会停止经过身份校验的本项目面板进程，不会结束其他 Python 程序。重复双击 `start.bat` 会复用已经运行的面板，不会重复占用端口。

### 3. 首次初始化

打开面板的 **运行状态**，将运行模式选为 **首次初始化 / 补全**，点击 **开始执行**。

默认从 `2023-01-01` 开始保存全市场日线。首次初始化需要下载数百万条记录，耗时取决于网络和电脑性能；任务支持断点续跑，中断后再次执行初始化即可继续。

初始化成功的判断：

- 股票覆盖率达到配置阈值，默认 90%
- 日线记录达到最低数量
- 三个主要指数已写入
- 面板显示数据健康为“正常”

### 4. 每日使用

收盘后有三种方式：

- 打开面板，点击右上角 **执行盘后任务**
- 双击 `daily.bat`
- 安装工作日自动任务，见下文

运行结束后可在面板查看结果，也可打开：

- `reports/YYYY-MM-DD_盘后选股报告.xlsx`
- `site/index.html`

## 一键入口

| 文件 | 用途 |
|---|---|
| `start.bat` | 自动准备环境并启动管理面板 |
| `stop.bat` | 安全停止本地管理面板 |
| `init.bat` | 初始化或补全历史数据 |
| `daily.bat` | 执行一次每日增量更新和选股 |
| `install_scheduler.bat` | 安装工作日 17:30 自动任务 |
| `install_scheduler_publish.bat` | 自动运行，并将网页报告推送到 GitHub |
| `uninstall_scheduler.bat` | 删除自动任务 |

时间可通过 PowerShell 自定义：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduler.ps1 -Time "18:00"
```

## 管理面板

### 市场概览

展示市场评分、风险等级、上涨家数占比、指数涨跌、强势板块和 Top 10。

### 观察名单

在 Top 50 / Top 10 间切换，可按代码、名称、行业、概念和市场板搜索。列表只展示短标签；点击行末详情按钮可查看完整入选理由、得分结构、行业阶段表现、涨停线索、次日条件和风险说明。

### 单策略筛选

统一展示全部内置策略和 `config/custom_strategies.yml` 中的安全公式。每个策略使用相同大小的卡片，可分别查看当日命中总数、独立排名、股票明细和命中原因。

单策略页面只负责独立观察，不改变综合评分；启用状态保存后从下一次任务生效。

### 策略配置

支持四个预设组合，也可以逐项开关策略，并直接配置最低股价、上市天数、最低成交额、ST / 停牌过滤和排除市场板块：

| 组合 | 适用方向 |
|---|---|
| 均衡组合 | 同时观察突破、趋势、回踩、事件和板块信号 |
| 突破优先 | 放量突破、海龟突破、平台收敛突破 |
| 回踩优先 | 趋势回踩、突破后首次回踩、涨停震荡 |
| 稳健趋势 | 低波 RPS、趋势转强和板块领涨 |

相近策略按策略家族去重：同一家族只取最高分，避免多个相似突破信号重复加分。

### 运行状态

显示数据覆盖、最新交易日、日线数量、当前任务输出和最近运行记录。

“定时执行”可直接管理 Windows 计划任务：设置工作日执行时间、启用或停用自动复盘，并选择任务完成后是否自动推送网页报告。默认时间为 17:30；电脑关机期间不会执行，恢复可用后会补跑一次。

> 修改计划任务后如果 Windows 弹出权限提示，请允许当前用户创建计划任务。GitHub Pages 自动推送还要求本机 Git 已完成登录。

“每日增量”会按每只股票本地最后日期继续更新到本次执行日期。中间连续几天没有运行时，会一次补齐期间存在行情的交易日；周末和休市日不会产生空记录。它不会自动扫描最后日期之前已经存在的零散内部缺口，此类异常可使用“首次初始化 / 补全”重新校验。

## 策略列表

| 策略 | 家族 | 核心信号 |
|---|---|---|
| 均线放量突破 | 突破 | 均线多头、放量并突破 |
| 海龟突破 | 突破 | 突破阶段高点 |
| 平台缩量突破 | 突破 | 波动收敛后放量突破 |
| RPS 强势突破 | 趋势 | RPS 居前并保持趋势 |
| 低波 RPS 趋势 | 趋势 | 高相对强度、较低波动 |
| 缩量回踩企稳 | 回踩 | 上升趋势中的缩量回踩 |
| 趋势回踩转强 | 回踩 | 回踩均线后重新转强 |
| 突破后首次回踩 | 回踩 | 突破后的第一次低风险确认 |
| 放量突破缩量承接 | 回踩 | 覆盖高低点抬高、突破回踩、涨停阶梯与上影试盘，按阶段差异化加分 |
| 涨停洗盘回踩 | 事件 | 历史涨停后换手整理 |
| 板块共振领涨 | 板块 | 强板块中的高 RPS 领涨股 |

详细规则见 [策略说明](docs/STRATEGIES.md)。

## Excel 报告

报告包含：

1. 市场环境
2. 强势板块
3. Top50 观察名单
4. Top10 重点关注
5. 个股说明（完整行业、题材、策略与风险说明）
6. 策略表现
7. 自定义策略
8. 风险过滤名单
9. 原始评分明细

Top50 / Top10 使用短标签保持紧凑，完整长文本集中在“个股说明”。表格包含冻结表头与股票列、筛选、条件颜色、数据条、分组页签和统一列宽；原始明细默认隐藏，可在 Excel 中取消隐藏。

## GitHub Pages 手机查看

GitHub Pages 只部署 `site/` 中的静态报告，不上传 SQLite、日志或 Excel。

### 一次性设置

1. 打开仓库 **Settings → Pages**
2. 在 **Build and deployment → Source** 中选择 **GitHub Actions** 并保存
3. 回到 **Actions**，重新运行失败的 Pages 任务，确认部署成功
4. 确认本机 Git 已登录并可执行 `git push`
5. 在面板“运行状态”中勾选“完成后推送网页报告”，设置时间并点击“启用并保存”

这条链路不调用 AI，也不需要保持面板或 Codex 打开。Windows 计划任务会直接执行：

1. 更新数据并生成报告
2. 只提交 `site/` 的变化
3. 推送到 `main`
4. 由 GitHub Actions 部署 Pages

勾选自动推送后，面板中的手动盘后任务也会执行相同的发布流程。计划任务支持电池供电并启用“错过后尽快运行”；由于 Git 推送使用当前用户凭据，执行时需要 Windows 用户处于登录状态且网络可用。

也可以双击 `install_scheduler_publish.bat` 使用默认时间快速安装。

默认访问地址：

[https://super-yyq.github.io/stock_selector/](https://super-yyq.github.io/stock_selector/)

> GitHub Pages 通常是公开页面。静态报告中不要加入账户信息、交易记录或其他隐私内容。

> 首次未启用 Pages 时，Actions 会在 `Configure Pages` 步骤提示 `Get Pages site failed` 或 `Not Found`。这表示仓库尚未选择 GitHub Actions 作为 Pages 来源，按上面的第 1、2 步设置一次即可，不需要修改数据程序或创建访问令牌。

手动发布：

```powershell
.\.venv\Scripts\python.exe scripts\publish_pages.py
```

## Docker 部署

适合 NAS、Linux 服务器或长期运行的电脑：

```bash
docker compose up -d --build
```

打开 `http://127.0.0.1:8765`。数据、配置、报告、日志和站点目录都通过卷保留在宿主机。

服务器公网访问时，应在 Caddy、Nginx 或其他反向代理中配置 HTTPS 和身份验证。默认 Compose 只绑定本机地址。

停止服务：

```bash
docker compose down
```

## Linux / macOS

```bash
chmod +x start.sh daily.sh
./start.sh
```

每日运行：

```bash
./daily.sh
```

## 配置

主要配置位于：

- [`config/strategy.yml`](config/strategy.yml)：数据源、并发、初始化验收、报告、面板、功能开关、总分权重和策略。
- [`config/stock_pool.yml`](config/stock_pool.yml)：股票池范围、市场板排除和风险阈值。
- [`config/custom_strategies.yml`](config/custom_strategies.yml)：自定义公式、启用状态、条件、排序和最大结果数。

常用设置可直接在面板的 **策略配置** 或 **单策略筛选** 页面修改。编辑 YAML 后，配置会在下一次任务中生效。

| 常见目标 | 修改参数 |
|---|---|
| 不观察北交所 / 科创板 | `stock_pool.exclude_boards` |
| 提高流动性要求 | `stock_pool.min_avg_amount_20d` |
| 缩小或扩大名单 | `report.top_observe`、`report.top_focus` |
| 更偏好突破或回踩 | 面板策略组合，或 `strategies.enabled` |
| 调整各因子影响 | `scoring.*_weight` |
| 减少题材网络请求 | `features.context_top_n`、`context_cache_days` |
| 改端口或禁止自动开浏览器 | `panel.port`、`panel.open_browser` |

每一个配置项的默认值、单位、可选值、作用和调参影响见 **[完整配置手册](docs/CONFIGURATION.md)**。策略触发条件见 **[策略说明](docs/STRATEGIES.md)**。

## 数据与磁盘

- 默认保存 `start_date` 至今的全部 A 股日线
- 日常运行只拉取缺失日期，不会重复下载全部历史
- 默认配置通常占用约 0.5 至 1 GB，实际大小随起始日期和股票数量增长
- 数据库路径：`data/stock.db`
- 数据库、日志、Excel 和虚拟环境均已加入 `.gitignore`
- 缩短历史范围可修改 `data.start_date`，但策略至少需要约 120 个交易日

## 命令行

自动脚本之外，也支持直接运行：

```powershell
# 初始化 / 补全
.\.venv\Scripts\python.exe run_daily.py --init

# 每日增量
.\.venv\Scripts\python.exe run_daily.py

# 指定日期重跑
.\.venv\Scripts\python.exe run_daily.py --date 2026-06-22

# 只用本地数据库重算策略和报告，不连接行情源
.\.venv\Scripts\python.exe run_daily.py --date 2026-06-22 --offline

# 启动面板
.\.venv\Scripts\python.exe -m src.panel
```

手动激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

退出虚拟环境：

```powershell
deactivate
```

## 项目结构

```text
config/                 策略、公式、数据源、股票池和风险配置
data/                   SQLite 数据库
src/
  strategies/           策略实现与家族聚合
  custom_formulas.py    安全自定义公式解析与筛选
  panel.py              本地管理面板 API
  run_daily.py          每日任务编排
  database.py           SQLite 与历史追踪
  report.py             Excel 报告
  web_report.py         静态网页报告
web/                    面板与静态站点前端
site/                   GitHub Pages 发布内容
scripts/                启动、定时和发布脚本
tests/                  自动化测试
reports/                本地 Excel 报告
logs/                   每日运行日志
```

架构和扩展入口见 [架构说明](docs/ARCHITECTURE.md)。

## 开发

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

新增策略时：

1. 在 `src/strategies/` 新建策略类
2. 复用 `build_strategy_features` 的共享因子
3. 在 `src/strategies/registry.py` 注册
4. 为信号和家族聚合补充测试
5. 更新 [策略说明](docs/STRATEGIES.md)

新增自定义公式时，优先编辑 `config/custom_strategies.yml`，使用白名单字段和运算符；不要使用 `eval`、任意 Python 表达式或面板上传脚本。完整格式见 [策略说明](docs/STRATEGIES.md#自定义公式策略)。

仓库内的 `AGENTS.md` 记录了模块边界、关键约束和验证命令，方便后续新会话快速接手。

## 常见问题

**面板打不开**

确认 Python 3.12 可用，再次双击 `start.bat`。若端口被占用，修改 `panel.port`。

**首次初始化很久**

全市场历史数据量较大。可以关闭面板后重新执行，已完成的股票会跳过或增量续传。

**报告日期不是今天**

非交易日会使用数据库中的最新交易日，这是正常行为。

**为什么显示“涨停线索”，不是“涨停原因”**

免费涨停池能稳定提供涨停事实、连板和行业，但不总能提供可核验的新闻原因。系统会展示涨停统计与相关核心概念，并明确标为“线索”；不会把概念关联伪装成已确认的涨停原因。

**Pages 在 `Configure Pages` 时报 `Not Found`**

进入仓库 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions** 并保存，再重新运行失败任务。这是仓库首次启用设置，不是程序拉取数据失败。

**Pages 已部署但报告没有更新**

检查定时任务是否成功执行、`site/data/latest.json` 是否发生变化，以及本机是否具备 `git push` 权限。

## 免责声明

本项目输出的是规则筛选结果，仅用于个人学习、盘后复盘和次日人工观察。任何分数、排名、策略命中和历史收益都不代表未来表现。使用者应自行判断市场风险并承担决策责任。
