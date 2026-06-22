# A 股盘后多因子选股助手设计

## 背景

本项目是一个个人本地运行的 A 股盘后复盘和观察名单筛选工具。它不做自动交易、不接实时行情、不连接券商接口，也不输出投资建议。第一版目标是每天收盘后更新免费数据源、计算市场环境和个股多因子分数、做风险过滤，并生成可解释的 Excel 盘后报告。

项目作为独立目录创建在 `E:\我的git项目\Github\stock_selector`，不改造现有 `Sequoia-X` 项目。`Sequoia-X` 只作为参考，避免把第一版需求耦合到飞书推送和旧策略体系里。

## 第一版目标

第一版优先保证免费、本地、稳定、可解释、可配置、可扩展。验收时需要满足以下行为：

- 可以安装依赖并在 Windows 本地运行。
- 可以初始化或增量更新 A 股日线数据。
- 可以指定日期重跑盘后选股。
- 可以生成 Excel 报告，包含 Top50 观察名单和 Top10 重点关注名单。
- 每只入选股票都有总分、分项分数、入选理由、风险提示和次日观察条件。
- 策略参数通过 YAML 配置调整。
- 数据接口失败、单只股票异常、报告生成失败时有日志说明。

## 范围

第一版包含：

- 免费数据源接入。
- SQLite 本地存储。
- 股票池基础过滤。
- 大盘环境评分。
- 行业板块热度评分。
- 个股历史股性评分。
- 量价结构评分。
- RPS20 和 RPS60 相对强弱。
- 风险扣分和风险说明。
- 100 分制总分排序。
- Excel 报告。
- README、运行示例和配置说明。

第一版不包含：

- 自动交易。
- 实时行情。
- Level-2 数据。
- Wind 或收费数据源。
- 券商下单接口。
- 深度学习或复杂机器学习。
- 复杂 Web 前端。
- 多账户管理。
- 强制接入大模型 API。

## 数据源策略

采用混合免费数据源：

- `baostock`：股票日线、指数日线、股票基础信息、上市状态等相对稳定的数据。
- `AKShare`：行业板块、市场宽度、涨跌停辅助数据等更丰富但可能变化的公开数据。

降级规则：

- 日线和基础信息是主流程必需数据；初始化和每日更新失败时记录错误并终止本次运行。
- 行业板块和市场宽度是增强数据；AKShare 接口失败时记录警告，板块分使用空值或 0 分，主流程继续生成报告。
- 单只股票数据异常只影响该股票，不中断全市场扫描。

## 项目结构

```text
stock_selector/
  config/
    strategy.yml
    stock_pool.yml
  data/
    stock.db
    raw/
    processed/
  logs/
  reports/
  src/
    __init__.py
    config.py
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
  tests/
    test_config.py
    test_database.py
    test_build_pool.py
    test_market_score.py
    test_risk_filter.py
    test_scoring.py
    test_report.py
  main.py
  run_daily.py
  requirements.txt
  README.md
```

顶层 `run_daily.py` 和 `main.py` 是薄入口，实际逻辑在 `src/run_daily.py`。这样用户可以直接运行 `python run_daily.py`，测试也可以直接导入模块。

## 命令行设计

支持以下命令：

```bash
python run_daily.py --init
python run_daily.py --date 2026-06-22
python run_daily.py
python main.py --backfill
python main.py
```

行为定义：

- `--init`：首次初始化数据库表并回填历史日线数据。
- `--date YYYY-MM-DD`：以指定交易日为报告日，使用该日及之前的本地数据计算结果；如果本地缺少该日期数据，先尝试增量更新到该日。
- 无参数：按当前日期执行盘后流程；如果当天不是交易日或无新数据，使用本地最新交易日生成报告并在控制台说明。
- `main.py --backfill`：等价于 `run_daily.py --init`。
- `main.py`：等价于 `run_daily.py`。

## 配置设计

`config/stock_pool.yml` 管股票池和风险阈值：

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

`config/strategy.yml` 管数据源、报告、功能开关和评分权重：

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

配置加载由 `src/config.py` 负责，缺失字段使用默认值，类型错误或非法阈值给出明确异常。

## SQLite 数据模型

第一版使用以下核心表：

- `stock_basic`：股票代码、名称、交易所、行业、上市日期、是否 ST、是否上市。
- `stock_daily`：股票日线，包含开高低收、成交量、成交额、换手率、涨跌幅、是否停牌。
- `index_daily`：上证指数、深证成指、创业板指等指数日线。
- `sector_daily`：行业板块每日行情和成交额。
- `run_metadata`：数据更新时间、最近交易日、运行状态。

关键约束：

- `stock_daily` 使用 `(code, trade_date)` 唯一约束。
- `index_daily` 使用 `(index_code, trade_date)` 唯一约束。
- 写入使用 upsert 或先删后写，保证重跑同一天不会重复。
- 所有日期统一为 `YYYY-MM-DD` 字符串。

## 每日运行流程

`src/run_daily.py` 编排流程：

1. 读取配置并创建日志。
2. 初始化数据库表。
3. 根据命令参数决定回填、增量更新或指定日期重跑。
4. 读取报告日所需的历史窗口数据。
5. 构建可评分股票池。
6. 计算大盘环境分。
7. 计算行业板块热度分。
8. 计算个股股性分。
9. 计算量价结构分。
10. 计算 RPS20、RPS60。
11. 计算风险扣分和风险说明。
12. 合成总分并排序。
13. 生成 Top50、Top10、风险过滤名单和评分明细。
14. 输出 Excel 报告。
15. 在控制台打印市场摘要、强势板块、报告路径。

## 股票池过滤

`src/build_pool.py` 输出两个结果：

- `eligible_pool`：进入评分的股票。
- `filtered_out`：被过滤的股票和原因，用于报告中的风险过滤名单。

过滤规则：

- 剔除 ST 股票。
- 剔除退市风险股票。
- 剔除停牌股票。
- 剔除上市不足配置天数的股票。
- 剔除最近 20 日平均成交额低于阈值的股票。
- 剔除价格低于阈值的股票。
- 剔除最近连续极端大涨但高位缩量明显的股票。

每条过滤原因保留为中文说明，例如“上市不足 120 个交易日”。

## 大盘环境评分

`src/market_score.py` 输出：

- `market_label`：偏强、震荡、偏弱。
- `risk_level`：低、中、高。
- `market_score`：0 到 10 分。
- 上涨家数占比、涨停家数、跌停家数、主要指数涨跌幅和均线状态。

评分因子：

- 上证指数、深证成指、创业板指涨跌幅。
- 全市场上涨家数占比。
- 涨停家数和跌停家数。
- 主要指数是否站上 5 日线和 20 日线。
- 市场成交额是否较 5 日均值放大。
- 创业板或中小盘是否强于主板。

`market_score` 参与个股总分的市场修正，市场偏弱时不直接清空股票池，而是降低总体分数并提高风险提示权重。

## 板块热度评分

`src/sector_score.py` 优先使用 AKShare 行业板块数据。第一版先实现行业板块，概念板块留扩展接口。

评分因子：

- 板块今日涨幅。
- 板块 5 日涨幅。
- 板块 20 日涨幅。
- 板块成交额放大倍数。
- 板块内涨停家数。
- 板块内强势股数量。
- 板块是否连续两天以上走强。

输出强势板块列表和个股所属板块分。个股行业缺失时板块分为 0，并在评分明细中标注“行业信息缺失”。

## 个股股性评分

`src/stock_character.py` 判断股票历史是否活跃，输出 0 到 100 的原始分，再按权重折算。

评分因子：

- 过去 60 个交易日涨幅超过 5% 的次数。
- 过去 60 个交易日涨停次数。
- 过去 20 日平均振幅。
- 过去 60 日最大涨幅。
- 成交额放大时是否容易上涨。
- 所属板块上涨时是否跟涨。
- RPS20 和 RPS60。

目标是解释“历史股性是否活跃、是否容易跟随板块、是否有资金关注痕迹”，不是预测一定上涨。

## 量价结构评分

`src/volume_price_score.py` 输出 0 到 100 的原始分和结构标签。

评分因子：

- 今日成交额与 20 日平均成交额之比。
- 今日涨跌幅。
- 是否突破 20 日新高。
- 是否突破 60 日新高。
- 是否站上 5 日、10 日、20 日均线。
- 近 5 日、10 日涨幅是否强于大盘。
- 是否放量上涨。
- 是否缩量回踩。
- 是否存在长上影线。
- 是否高位爆量滞涨。

偏好形态包括放量突破、回踩企稳、强于大盘、板块共振、历史股性活跃且未极端透支。

## 风险过滤和扣分

`src/risk_filter.py` 不只过滤，还输出风险扣分和风险文本。风险扣分上限由配置控制，默认最高 20 分。

风险因子：

- 近 5 日涨幅过大。
- 近 10 日涨幅过大。
- 距离 20 日均线过远。
- 今日长上影线。
- 今日高开低走。
- 今日爆量滞涨。
- 成交额过低。
- 换手过高。
- 波动率过大。
- 板块过度集中。
- 最近连续涨停后开板。

风险提示示例：“近 5 日涨幅 28%，距离 20 日线偏远，追高风险较高”。

## 总分模型

`src/scoring.py` 使用规则打分，不做机器学习。

总分公式：

```text
总分 = 板块热度分 + 股性分 + 量价结构分 + 相对强弱分 + 大盘环境修正 - 风险扣分
```

默认权重：

- 板块热度：25。
- 股性：20。
- 量价结构：25。
- 相对强弱：15。
- 大盘环境修正：10。
- 风险扣分上限：20。

输出字段：

- 股票代码。
- 股票名称。
- 所属行业。
- 所属概念字段保留，第一版可为空。
- 总分。
- 板块分。
- 股性分。
- 量价分。
- 相对强弱分。
- 风险扣分。
- 入选理由。
- 风险提示。
- 次日观察条件。

入选理由由高贡献因子拼接生成，例如“行业连续走强、放量突破 20 日新高、RPS20 居前、股性活跃”。次日观察条件根据形态和市场状态生成，例如“不追高，观察是否回踩 5 日线不破”。

## 报告输出

`src/report.py` 生成 Excel 文件：

```text
reports/YYYY-MM-DD_盘后选股报告.xlsx
```

至少包含以下 sheet：

1. 市场环境。
2. 强势板块。
3. Top50观察名单。
4. Top10重点关注。
5. 风险过滤名单。
6. 原始评分明细。

Top50 字段：

- 排名。
- 股票代码。
- 股票名称。
- 总分。
- 所属板块。
- 今日涨跌幅。
- 近 5 日涨跌幅。
- 近 20 日涨跌幅。
- 成交额放大倍数。
- RPS20。
- RPS60。
- 板块分。
- 股性分。
- 量价分。
- 风险扣分。
- 入选理由。
- 风险提示。

Top10 字段：

- 排名。
- 股票代码。
- 股票名称。
- 总分。
- 重点关注理由。
- 次日观察条件。
- 风险提示。

HTML 报告不是第一版必须项，保留 `report.py` 扩展接口。

## 日志和异常处理

日志文件路径：

```text
logs/run_YYYY-MM-DD.log
```

日志要求：

- 数据拉取失败记录数据源、接口名、日期和异常信息。
- 单只股票数据异常记录股票代码和原因，继续处理其他股票。
- 报告生成失败输出文件路径和异常信息。
- 接口字段变化时输出缺失字段名称。
- 每日任务开始、数据更新完成、股票池过滤完成、评分完成、报告完成都记录摘要。

## 测试策略

第一版采用 `pytest`，用小型 DataFrame 和临时 SQLite 文件测试核心规则，不依赖真实网络接口。

重点测试：

- YAML 配置加载和默认值合并。
- SQLite 表创建、唯一约束、重跑同日不重复写入。
- 股票池过滤原因。
- 大盘评分标签和风险等级。
- 个股 RPS 排名。
- 风险扣分上限和风险说明。
- 总分排序和 TopN 截取。
- Excel 文件包含规定 sheet 和字段。

真实数据源接口不在单元测试中直接调用，避免网络不稳定导致测试失败。手工验收通过 `python run_daily.py --init` 和 `python run_daily.py --date YYYY-MM-DD` 完成。

## README 内容

README 需要说明：

- 项目用途和免责声明。
- 依赖安装。
- 首次初始化。
- 每日运行。
- 指定日期重跑。
- 配置文件说明。
- 报告字段解释。
- 常见问题，如 AKShare 接口失败、baostock 登录失败、非交易日运行。

## 验收输出示例

运行：

```bash
python run_daily.py --date 2026-06-22
```

控制台输出类似：

```text
今日市场环境：偏强
市场风险等级：中
上涨家数占比：62%
涨停家数：78
跌停家数：12

强势板块：
1. 机器人
2. AI 算力
3. 低空经济

已生成：
Top50 观察名单
Top10 重点关注名单
风险过滤名单

报告路径：
reports/2026-06-22_盘后选股报告.xlsx
```

## 后续扩展

第一版完成后，可以在不破坏主流程的前提下扩展：

- 概念板块评分。
- HTML 报告。
- AI 文本总结。
- 更多股性特征。
- 更多数据源 fallback。
- 定时任务脚本。

这些扩展不进入第一版必须验收范围。
