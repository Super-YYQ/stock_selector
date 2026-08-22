# 配置手册

项目使用两个 YAML 文件：

- `config/strategy.yml`：数据、报告、面板、功能、评分和策略。
- `config/stock_pool.yml`：股票池过滤和风险阈值。

面板可直接修改“启用策略、策略组合、最低股价、上市天数、最低成交额、ST/停牌过滤和排除市场板块”。其余参数编辑 YAML 后，在下一次任务中生效。

Windows 本机的工作日定时任务在面板 **运行状态 → 定时执行** 中管理，不写入 YAML。一个固定任务可包含午间盘中快照和盘后正式复盘两个触发器。面板只会调用 `scripts/install_scheduler.ps1` 和 `scripts/uninstall_scheduler.ps1`，任务名称固定为 `A股盘后选股助手`，不接受任意命令或脚本路径。

午间快照默认关闭，启用后建议设为 `12:30`；盘后默认 `17:30`。午间日 K 尚未收盘，结果只作为临时观察，不写入 `selection_history`，也不刷新未来收益。盘后任务会强制重新抓取同一交易日并覆盖午间行情。

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
| `min_latest_stock_coverage` | `0.98` | 当前报告日行情的最低股票覆盖率。低于此值时停止生成报告，避免少量新行情与大量旧行情混排。 |
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
| `min_observe_score` | `45` | 进入观察名单的最低置信分。候选不足时允许少于 Top50，不再强行凑数。 |
| `min_focus_score` | `60` | 进入重点关注名单的最低置信分，必须不低于观察阈值。 |
| `max_per_industry` | `5` | 真实行业分类下单一行业最多进入名单的数量，降低行业拥挤。 |
| `max_per_market_board` | `20` | 单一市场板块最多进入名单的数量。 |

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
| `stock_character_weight` | `20` | 20 | 历史大涨次数、按板块规则识别的涨停次数、振幅和阶段活跃度；不重复计入 RPS。 |
| `volume_price_weight` | `25` | 25 | 放量、突破、均线位置、上影线和量价状态。 |
| `relative_strength_weight` | `15` | 15 | RPS20 与 RPS60 的组合相对强度。 |
| `market_adjust_weight` | `10` | ±10 | 大盘环境与个股量价、策略、RPS 强度的交互修正。强市提高强信号可信度，弱市对同类信号扣分，不再给所有股票增加相同常数。 |
| `strategy_score_weight` | `15` | 15 | 启用策略命中的附加分。 |
| `risk_penalty_max` | `20` | 扣 20 | 单股风险扣分的封顶值。 |
| `factor_percentile_blend` | `0.50` | - | 原始分与当日截面百分位的混合比例；降低固定阈值和极端值对不同市场阶段的漂移影响。 |

计算方式：

```text
总分 = 各因子加权分 + 策略分 + 大盘修正 - 风险扣分
最终结果限制在 0 至 100 分
```

提高某项权重，会让对应风格在排名中更突出。建议一次只调整一类权重，并观察一段时间的入选历史；权重不是收益保证。

## 策略绩效口径

位于 `config/strategy.yml > performance`。正式盘后入选在下一交易日开盘尝试成交，收益扣除双边成本，并同时计算相对基准的超额收益。盘中快照不进入绩效历史。

| 参数 | 默认值 | 作用与调参影响 |
|---|---:|---|
| `benchmark_index_code` | `sh000001` | 超额收益基准；必须已存在对应指数日线。 |
| `entry_cost_bps` | `8` | 买入端综合成本，单位基点；包含佣金和预估滑点。 |
| `exit_cost_bps` | `13` | 卖出端综合成本，单位基点；包含佣金、税费和预估滑点。 |
| `exclude_untradable_entry` | `true` | 排除次日停牌、缺少行情或一字涨停无法买入的样本。 |
| `exclude_price_jump_anomaly` | `true` | 排除持有期跨越疑似除权或异常价格跳变的收益。 |

绩效收益口径为“信号日盘后入选、下一交易日开盘买入、持有到对应交易日收盘”。原始行情仍用于涨跌停与成交判断。当前 TDX 行情未复权，因此异常跳变样本会被隔离；后续接入独立复权因子后，可进一步减少现金分红造成的微小偏差。

## 策略参数

位于 `config/strategy.yml > strategies`。

| 参数 | 默认值 | 作用与可选值 |
|---|---:|---|
| `enabled` | 11 个内置策略 | 实际启用的策略 key。完整 key 和规则见 [策略说明](STRATEGIES.md)。 |
| `profile` | `balanced` | 面板显示的组合：`balanced`、`breakout`、`pullback`、`steady`、`custom`。 |
| `strategy_score_weight` | `15` | 策略原始分换算到总分后的最高权重。 |
| `top_per_strategy` | `20` | 单个策略保留的最高排名候选数，控制单一策略对名单的覆盖范围。 |
| `max_scoring_hit_rate` | `0.20` | 策略命中率高于 20% 时按选择性折减其综合排名加分；独立策略筛选仍保留全部命中。 |
| `min_selectivity_multiplier` | `0.25` | 过宽策略的最低加分倍率，避免完全抹去观察信号。 |
| `parameters` | `{}` | 各内置策略的可选参数映射；未填写时使用策略默认值。 |

### 单策略筛选（single_screener）

位于 `config/strategy.yml > single_screener`，独立于上方 `strategies`（后者只影响观察名单评分）。

| 参数 | 默认值 | 作用与可选值 |
|---|---:|---|
| `enabled` | 11 个内置策略 | 单策略筛选页展示哪些内置策略；允许为空（页面显示「暂无启用策略」）。 |
| `top_per_strategy` | `20` | 每个策略展示的命中条数，范围 1-200（预计算池大小为 200）。 |

修改该小节后展示即时生效：每日任务已预计算全部策略 × Top 200 命中池，前端按配置本地截断，无需重跑任务。

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
| `volume_breakout_pullback` | 放量突破缩量承接 |
| `limit_up_shakeout` | 涨停洗盘回踩 |
| `sector_leader` | 板块共振领涨 |

`volume_breakout_pullback` 可调参数：

| 参数 | 默认值 | 作用 |
|---|---:|---|
| `min_score` | `51` | 观察池最低形态分；提高会减少命中数量。 |
| `ignition_min_age` | `1` | 最近点火日至少间隔的交易日数。 |
| `ignition_max_age` | `12` | 最近点火日最多回看交易日数。 |
| `volume_contraction_max` | `0.90` | 回调期平均量相对点火量上限。 |
| `deep_volume_contraction` | `0.60` | 深度缩量加分阈值。 |
| `trigger_low_hold_ratio` | `0.97` | 点火最低价支撑容忍比例。 |
| `platform_hold_ratio` | `0.96` | 原平台支撑容忍比例。 |
| `trend_near_high_ratio` | `0.80` | 收盘价相对60日高点的最低比例。 |
| `max_distance_ma20` | `22` | 允许的最大20日线乖离，单位百分点。 |

这些参数用于扩大或收紧观察池。单独的“涨停阶梯”只获得较低策略分；是否进入 Top50 仍取决于 RPS、板块、量价总分和风险扣分。

正式盘后运行还会把六个核心原始因子的覆盖率、均值、标准差、分位数和零值率写入 `factor_diagnostic`。它用于发现接口缺列、因子退化为常量和分布漂移，不参与当日加分。

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

另有固定规则：当日成交额超过 20 日均额 3 倍、但涨幅低于 1% 时，视为“爆量滞涨”并扣 4 分。股票池还会隔离缺少报告日行情的股票，以及最近 60 日存在超出对应板块正常涨跌幅范围的疑似除权或异常价格跳变数据。最终扣分不超过 `scoring.risk_penalty_max`。

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
