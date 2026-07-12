# 配置手册

项目使用两个 YAML 文件：

- `config/strategy.yml`：数据、报告、面板、功能、评分和策略。
- `config/stock_pool.yml`：股票池过滤和风险阈值。

面板可直接修改“启用策略、策略组合、最低股价、上市天数、最低成交额、ST/停牌过滤和排除市场板块”。其余参数编辑 YAML 后，在下一次任务中生效。

Windows 本机的工作日定时任务在面板 **运行状态 → 定时执行** 中管理，不写入 YAML。面板会调用 `scripts/install_scheduler.ps1` 和 `scripts/uninstall_scheduler.ps1`，任务名称固定为 `A股盘后选股助手`，不接受任意命令或脚本路径。

> YAML 使用空格缩进，不要使用 Tab。布尔值写 `true` 或 `false`，日期建议加引号。

## 数值约定

| 类型 | 约定 |
|---|---|
| 金额 | 人民币元，例如 `100000000` 表示 1 亿元 |
| 涨跌幅 / 距离 | 百分点，例如 `25` 表示 25% |
| 比例 | 0 到 1，例如 `0.90` 表示 90% |
| 波动率 | 小数，例如 `0.08` 表示 8% |
| 天数 | 交易日或自然日会在参数说明中单独标明 |

## 数据参数

位于 `config/strategy.yml > data`。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `provider` | `tdx` | 行情数据源。推荐 `tdx`，无需账号登录；`akshare` / `eastmoney` 使用 AKShare 接口；`baostock` 使用 Baostock；`mixed` / `auto` 会在 Baostock 被限流或拉黑时转到 TDX。 |
| `database` | `data/stock.db` | SQLite 数据库路径，相对仓库根目录。 |
| `start_date` | `2023-01-01` | 首次初始化的历史起始日期。越早，初始化越慢、数据库越大；建议至少保留 180 至 240 个交易日。 |
| `tdx_parallel_workers` | `4` | TDX 初始化并发数。网络稳定时可小幅提高；过高可能增加断线，不建议超过 8。 |
| `tdx_parallel_chunk_size` | `50` | 每个 TDX 工作批次的股票数。通常无需修改。 |
| `tdx_timeout_seconds` | `3` | 单次 TDX 网络请求超时秒数。网络较慢可改为 5 至 8。 |
| `tdx_query_retries` | `3` | TDX 单次查询最大尝试次数。失败后仍会记录并继续其他股票。 |
| `init_min_stock_coverage` | `0.90` | 初始化验收的最低股票覆盖率。低于此值时初始化判定失败，防止用残缺数据生成结果。 |
| `init_min_daily_rows` | `100000` | 初始化验收的最低日线总记录数。 |
| `init_min_index_count` | `3` | 初始化验收的最低指数数量，默认要求上证、深证和创业板三个指数。 |
| `analysis_lookback_days` | `240` | 每次评分从数据库读取的自然日回看范围，最小 120。提高后计算量增大，但长周期指标更完整。 |
| `baostock_query_retries` | `3` | 仅 Baostock 使用的查询重试次数。遇到黑名单不会反复冲击接口。 |
| `baostock_reconnect_interval` | `200` | 仅 Baostock 使用，每完成多少次查询主动重连。 |
| `baostock_parallel_workers` | `2` | 仅 Baostock 初始化并发数。为降低黑名单风险，不建议提高。 |
| `baostock_parallel_chunk_size` | `20` | 仅 Baostock 使用的任务分块大小。 |

## 报告参数

位于 `config/strategy.yml > report`。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `top_observe` | `50` | 观察名单数量，同时决定 Excel Top50 和网页主名单的最大行数。必须不小于 `top_focus`。 |
| `top_focus` | `10` | 重点关注名单数量。 |
| `output_dir` | `reports` | Excel 输出目录。 |
| `site_dir` | `site` | 静态网页输出目录，也是 GitHub Pages 的部署目录。 |
| `history_days` | `90` | 网页历史 JSON 保留份数，至少为 1；增加会扩大 Git 仓库体积。 |

## 面板参数

位于 `config/strategy.yml > panel`。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `host` | `127.0.0.1` | 面板监听地址。默认仅本机可访问；服务器部署可改为 `0.0.0.0`，但必须配合 HTTPS 和身份验证。 |
| `port` | `8765` | 面板端口，范围 1 至 65535。 |
| `open_browser` | `true` | 启动面板后是否自动打开浏览器。服务器环境建议设为 `false`。 |

## 功能开关

位于 `config/strategy.yml > features`。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `enable_sector_score` | `true` | 是否计算板块热度。关闭后板块分为 0。 |
| `enable_rps` | `true` | 是否计算 RPS20 / RPS60 相对强弱。依赖 RPS 的策略在关闭后难以命中。 |
| `enable_ai_summary` | `false` | AI 总结预留开关，当前版本不调用大模型 API。 |
| `enable_context_enrichment` | `true` | 是否为候选股补充行业、核心概念、涨停线索和行业阶段表现。网络失败只影响说明，不中断评分报告。 |
| `context_top_n` | `50` | 补充题材信息的候选股数量。建议不小于 `report.top_observe`；提高会增加首次请求量。 |
| `context_cache_days` | `7` | 个股行业和概念缓存的自然日有效期。行业阶段表现仍按报告日保存。 |
| `context_workers` | `4` | 题材请求并发数，建议 2 至 6；申万行业历史请求内部最多使用 2 个并发以提高稳定性。 |

## 总分权重

位于 `config/strategy.yml > scoring` 和 `strategies.strategy_score_weight`。

| 参数 | 默认值 | 评分上限 | 含义 |
|---|---:|---:|---|
| `sector_score_weight` | `25` | 25 | 所属板块的涨幅、持续性、量能和强势股表现。 |
| `stock_character_weight` | `20` | 20 | 历史大涨次数、涨停次数、振幅和 RPS 等股性。 |
| `volume_price_weight` | `25` | 25 | 放量、突破、均线位置、上影线和量价状态。 |
| `relative_strength_weight` | `15` | 15 | RPS20 与 RPS60 的组合相对强度。 |
| `market_adjust_weight` | `10` | 10 | 当日大盘环境修正。 |
| `strategy_score_weight` | `15` | 15 | 启用策略命中的附加分。 |
| `risk_penalty_max` | `20` | 扣 20 | 单股风险扣分的封顶值。 |

计算方式：

```text
总分 = 各因子加权分 + 策略分 + 大盘修正 - 风险扣分
最终结果限制在 0 至 100 分
```

提高某项权重，会让对应风格在排名中更突出。建议一次只调整一类权重，并观察一段时间的入选历史；权重不是收益保证。

## 策略参数

位于 `config/strategy.yml > strategies`。

| 参数 | 默认值 | 作用与可选值 |
|---|---:|---|
| `enabled` | 10 个内置策略 | 实际启用的策略 key。完整 key 和规则见 [策略说明](STRATEGIES.md)。 |
| `profile` | `balanced` | 面板显示的组合：`balanced`、`breakout`、`pullback`、`steady`、`custom`。 |
| `strategy_score_weight` | `15` | 策略原始分换算到总分后的最高权重。 |
| `top_per_strategy` | `20` | 单个策略保留的最高排名候选数，控制单一策略对名单的覆盖范围。 |

内置策略 key：

| key | 名称 |
|---|---|
| `ma_volume` | 均线放量突破 |
| `turtle_breakout` | 海龟突破 |
| `volatility_squeeze` | 平台缩量突破 |
| `rps_breakout` | RPS 强势突破 |
| `low_volatility_rps` | 低波 RPS 趋势 |
| `pullback_stable` | 缩量回踩企稳 |
| `trend_pullback_reversal` | 趋势回踩转强 |
| `first_pullback` | 突破后首次回踩 |
| `limit_up_shakeout` | 涨停洗盘回踩 |
| `sector_leader` | 板块共振领涨 |

## 股票池过滤

位于 `config/stock_pool.yml > stock_pool`。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `min_list_days` | `120` | 最少上市交易日。提高可减少次新股，降低则扩大候选范围。 |
| `min_price` | `3` | 报告日最低收盘价，单位元。 |
| `min_avg_amount_20d` | `100000000` | 最近 20 个交易日最低平均成交额，单位元；默认 1 亿元。 |
| `exclude_st` | `true` | 排除名称含 ST 或基础信息标记为 ST/退市风险的股票。 |
| `exclude_suspended` | `true` | 排除报告日停牌或无有效收盘价的股票。 |
| `exclude_boards` | `[北交所]` | 排除市场板块列表。可用值：`沪市主板`、`深市主板`、`创业板`、`科创板`、`北交所`、`其他`。空列表 `[]` 表示不按市场板过滤。 |

示例：同时排除北交所和科创板。

```yaml
stock_pool:
  exclude_boards:
    - 北交所
    - 科创板
```

## 风险阈值

位于 `config/stock_pool.yml > risk`。

| 参数 | 默认值 | 触发后的规则 |
|---|---:|---|
| `max_pct_chg_5d` | `30` | 近 5 日涨幅超过 30% 时扣 5 分。 |
| `max_pct_chg_10d` | `45` | 近 10 日涨幅超过 45% 时扣 5 分。 |
| `max_distance_ma20` | `25` | 收盘价高于 20 日线超过 25% 时扣 5 分。 |
| `long_upper_shadow_ratio` | `0.5` | 上影线占当日振幅比例超过 0.5 时扣 3 分。 |
| `high_turnover_ratio` | `25` | 换手率超过 25% 时扣 3 分；免费源缺少换手率时不触发。 |
| `high_volatility_20d` | `0.08` | 近 20 日收益波动率超过 8% 时扣 3 分。 |

另有固定规则：当日成交额超过 20 日均额 3 倍、但涨幅低于 1% 时，视为“爆量滞涨”并扣 4 分。最终扣分不超过 `scoring.risk_penalty_max`。

## 完整示例

```yaml
# config/stock_pool.yml
stock_pool:
  min_list_days: 180
  min_price: 5
  min_avg_amount_20d: 200000000
  exclude_st: true
  exclude_suspended: true
  exclude_boards:
    - 北交所
    - 科创板

risk:
  max_pct_chg_5d: 25
  max_pct_chg_10d: 40
  max_distance_ma20: 20
  long_upper_shadow_ratio: 0.45
  high_turnover_ratio: 20
  high_volatility_20d: 0.07
```

保存后运行一次每日任务。若 YAML 字段名、类型或取值错误，程序会在日志中给出具体配置错误并停止，原数据库不会被删除。

## 自定义公式配置

位于 `config/custom_strategies.yml`。它与 `strategy.yml > strategies` 的内置加分策略分离：自定义公式只生成独立命中列表，不改变 Top 50 综合排名。

| 参数 | 默认 / 可选值 | 作用 |
|---|---|---|
| `version` | `1` | 配置格式版本。 |
| `strategies[].key` | 小写英文标识 | 公式唯一键。 |
| `strategies[].enabled` | `true` / `false` | 是否执行。面板可修改。 |
| `strategies[].match` | `all` / `any` | 全部条件或任一条件成立。 |
| `strategies[].max_results` | `1` 至 `200` | 单条公式输出上限。 |
| `strategies[].sort_by` | 默认 `total_score` | 命中股票排序字段。 |
| `strategies[].sort_direction` | `asc` / `desc` | 排序方向。 |
| `conditions[].field` | 共享特征字段 | 条件左值。 |
| `conditions[].operator` | `gt`、`gte`、`lt`、`lte`、`eq`、`between` | 比较方式。 |
| `conditions[].value` | 数值 | 固定比较值。 |
| `conditions[].compare_field` | 共享特征字段 | 与另一个字段比较。 |
| `conditions[].multiplier` | 默认 `1` | 比较字段乘数。 |
| `conditions[].offset` | 默认 `0` | 比较字段偏移。 |
| `conditions[].min` / `max` | 数值 | `between` 的闭区间。 |
| `conditions[].label` | 中文短句 | 面板和报告中的可解释条件。 |

安全边界：配置不支持 `eval`、Python 表达式、函数调用、动态导入或上传脚本。新增指标应在 `build_strategy_features` 中实现并补充测试。
