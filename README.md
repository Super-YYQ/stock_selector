# 免费版 A 股盘后多因子选股助手

这是一个个人本地运行的 A 股盘后复盘工具。它每天收盘后更新免费数据源，按市场环境、行业热度、历史股性、量价结构、相对强弱、策略命中和风险扣分生成观察名单。

本项目不是投资建议，不做自动交易，不连接券商接口，不使用实时行情。

## 环境要求

- Windows
- Python 3.12 推荐
- 免费数据源：baostock、AKShare

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

当前版本会初始化 SQLite 表结构，并通过 `src/fetch_data.py` 接入 baostock/AKShare 更新股票基础信息、个股日线、指数日线和行业板块数据。AKShare 板块接口失败时会记录日志并降级，不影响主流程。

## 每日盘后运行

```bash
python run_daily.py
```

## 指定日期重跑

```bash
python run_daily.py --date 2026-06-22
```

## 策略筛选

系统现在有一层类似 Sequoia-X 思路的可扩展规则策略筛选层。默认策略在 `config/strategy.yml` 的 `strategies.enabled` 中配置：

- `ma_volume`：均线放量突破
- `turtle_breakout`：海龟突破
- `rps_breakout`：RPS 强势突破
- `pullback_stable`：缩量回踩企稳
- `limit_up_shakeout`：涨停洗盘回踩

策略命中会生成 `strategy_score_raw`、`matched_strategies`、`strategy_reason`，并按 `strategies.strategy_score_weight` 计入总分。新增策略时，把策略类放到 `src/strategies/` 并在 `src/strategies/registry.py` 注册即可。

示例配置：

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

`config/strategy.yml` 控制数据源、报告数量、功能开关、评分权重和策略启用列表。

`config/stock_pool.yml` 控制股票池过滤阈值和风险扣分阈值。

## 数据源

- `baostock`：股票日线、指数日线、基础信息。
- `AKShare`：行业板块和辅助市场数据。

如果 AKShare 行业接口失败，系统会记录日志并继续生成报告，板块分按 0 处理。

## 报告字段

Top50 观察名单包含排名、股票代码、股票名称、总分、所属板块、今日涨跌幅、近 5 日涨跌幅、近 20 日涨跌幅、成交额放大倍数、RPS20、RPS60、板块分、股性分、量价分、策略分、风险扣分、命中策略、策略理由、入选理由和风险提示。

Top10 重点关注名单包含排名、股票代码、股票名称、总分、命中策略、策略理由、重点关注理由、次日观察条件和风险提示。

## 风险说明

观察名单只用于人工复盘。第二天是否操作，需要结合大盘、板块强弱、开盘位置、成交量和个人风险控制判断。
