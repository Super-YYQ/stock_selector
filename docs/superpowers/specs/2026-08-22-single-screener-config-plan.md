# 单策略筛选独立配置 — 实施计划

> 日期：2026-08-22
> 状态：待实施（本文件为给执行 AI 的完整施工手册）
> 关联 spec：`docs/superpowers/specs/2026-08-22-single-screener-config-design.md`

## 0. 目标与背景

「单策略筛选」页与「观察名单」共用 `strategies.enabled` + `top_per_strategy`，三者耦合，且策略来源（自建/内置）未区分。本计划：

1. 新增 `single_screener` 配置（独立于观察名单）。
2. 后端预计算**全部 11 个内置策略 × Top 200**命中池，使单策略筛选配置**即时生效**（改完不用重跑每日任务）。
3. 前端卡片加**来源标签**，配置保存改为只影响单策略筛选页。
4. 「保存启用状态」按钮语义改为「保存筛选配置」。

## 1. 现状关键代码位置（已核实，行号基于当前 HEAD）

### 1.1 配置加载 `src/config.py`
- `StrategyConfig`（行 100-108）：观察名单用，含 `enabled` / `top_per_strategy`。
- `AppConfig`（行 131-141）：含 `strategies: StrategyConfig`。
- `load_config`（行 237-）：`strategies=StrategyConfig(**_section(strategy, "strategies"))`。
- `_validate`（行 161-）：校验 `strategies.*`。

### 1.2 策略评估 `src/strategies/registry.py`
- `STRATEGY_CLASSES`（行 22-34）：全部 11 个内置策略类。
- `STRATEGY_REGISTRY`（行 35）：`{key: class}`。
- `evaluate_enabled_strategies`（行 168-）：**只评估传入的 `enabled` 列表**——这是问题根源：单策略筛选拿到的 hits 只含观察名单勾选的策略。
- `strategy_catalog`（行 109-119）：返回 `key/name/family/description/score`，**无 origin 字段**。
- `build_strategy_screener_data`（行 264-322）：
  - 行 271-274：`counts` 来自 `hits.groupby("strategy_key").size()`（只含已评估策略）。
  - 行 286：`result_count = min(matched_count, max_results)`（max_results 来自观察名单的 `top_per_strategy`）。
  - 行 311：`selected.groupby("single_strategy_key").head(max_results)`。

### 1.3 每日任务 `src/run_daily.py`
- 行 913-921：`strategy_evaluation = evaluate_enabled_strategies(..., config.strategies.enabled, ...)` —— 只评估观察名单的策略。
- 行 938-943：`build_strategy_screener_data(strategy_evaluation.hits, ranked, config.strategies.enabled, config.strategies.top_per_strategy)`。

### 1.4 面板 API `src/panel.py`
- `GET/PUT /api/strategies`（行 249-281）：观察名单用，读写 `strategies.enabled`。
- `GET/PUT /api/custom-strategies`（行 284-319）：自定义公式用。

### 1.5 报告输出 `src/web_report.py`
- 行 80-81：`strategy_screeners` / `strategy_screener_results` 写入 latest.json。

### 1.6 前端
- `web/assets/app.js`（与 `site/assets/app.js` 字节相同，需同步）：
  - `singleStrategySource`（行 567-617）：拼接 catalog + results。
  - `renderCustomStrategies`（行 668-761）：渲染卡片（已在卡片标签里处理 matched/result_count 截断显示）。
  - `saveCustomStrategies`（行 763-800）：调 `PUT /api/strategies` + `PUT /api/custom-strategies`。
- `web/index.html` 行 157：`<button id="save-custom-strategies-button">保存启用状态</button>`。

---

## 2. 实施步骤

### 步骤 A：配置层 `src/config.py`

**A1.** 新增 dataclass（紧跟 `StrategyConfig` 之后，约行 108）：

```python
@dataclass(frozen=True)
class SingleScreenerConfig:
    enabled: list[str] = field(default_factory=lambda: list(STRATEGY_REGISTRY_KEYS))
    top_per_strategy: int = 20
```

> 需在 `config.py` 顶部 import `STRATEGY_REGISTRY`（或其 keys）—— 注意避免循环 import。`STRATEGY_REGISTRY` 定义在 `src/strategies/registry.py`，`config.py` 当前未引用它。若循环，则在 `config.py` 内硬编码默认 keys 列表（与 `DEFAULT_ENABLED_STRATEGIES` 同源，可复用）。**推荐：复用 `config.py` 已有的 `DEFAULT_ENABLED_STRATEGIES`**（先 grep 确认它存在且为全部 11 个 key）。

**A2.** `AppConfig`（行 131-141）加字段：

```python
single_screener: SingleScreenerConfig = field(default_factory=SingleScreenerConfig)
```

**A3.** `load_config`（行 243-251）加：

```python
single_screener=SingleScreenerConfig(**_section(strategy, "single_screener")),
```

**A4.** `_validate`（行 161-）加校验：

```python
if not config.single_screener.enabled:
    # 允许为空（单策略筛选不影响评分，空则页面显示「暂无启用策略」），不报错
    pass
if config.single_screener.top_per_strategy < 1:
    raise ValueError("single_screener.top_per_strategy must be >= 1")
if config.single_screener.top_per_strategy > 200:
    raise ValueError("single_screener.top_per_strategy must be <= 200")
unknown = set(config.single_screener.enabled) - set(STRATEGY_REGISTRY)
if unknown:
    raise ValueError("single_screener.enabled 含未知策略: " + ", ".join(sorted(unknown)))
```

### 步骤 B：策略层 `src/strategies/registry.py`

**B1.** `strategy_catalog`（行 109-119）加 `origin` 字段。在 `STRATEGY_CLASSES` 定义后，给每个类打标记。最小侵入方式：在 `strategy_catalog` 返回的 dict 里加：

```python
"origin": "custom" if strategy.key == "volume_breakout_pullback" else "builtin",
```

> 这样无需改每个策略类。`volume_breakout_pullback` 是唯一自建策略（有独立回测脚本 `scripts/backtest_volume_breakout_pullback.py`、文档化形态、详细 DEFAULT_PARAMS）。

**B2.** 修改 `build_strategy_screener_data` 签名与逻辑（行 264-322）。当前它依赖传入的 `hits`（只含观察名单策略）。改为：**评估全部策略**，不依赖观察名单的 enabled。

方案：新增一个独立函数 `build_single_screener_pool`，或在现有函数里解耦。**推荐新增函数**，避免影响观察名单逻辑：

```python
SINGLE_SCREENER_POOL_SIZE = 200

def build_single_screener_pool(
    daily: pd.DataFrame,
    report_date: str,
    factors: pd.DataFrame,
    ranked: pd.DataFrame,
    parameters: dict[str, dict[str, object]],
    max_scoring_hit_rate: float,
    min_selectivity_multiplier: float,
) -> tuple[list[dict[str, object]], pd.DataFrame]:
    """评估全部内置策略，每策略预计算 Top 200 命中池，供单策略筛选页即时截断。"""
    # 评估全部 STRATEGY_REGISTRY keys（不传 enabled 过滤）
    evaluation = evaluate_enabled_strategies(
        daily, report_date, factors,
        list(STRATEGY_REGISTRY),  # 全部策略
        parameters, max_scoring_hit_rate, min_selectivity_multiplier,
    )
    hits = evaluation.hits
    # 复用现有 catalog + 截断逻辑，但 max_results 用 SINGLE_SCREENER_POOL_SIZE
    catalog, results = build_strategy_screener_data(
        hits, ranked, list(STRATEGY_REGISTRY), SINGLE_SCREENER_POOL_SIZE,
    )
    # catalog 每项补 origin（build_strategy_screener_data 内部已从 strategy_catalog 拿到 origin）
    return catalog, results
```

> 注意：`evaluate_enabled_strategies`（行 168）传 `enabled=list(STRATEGY_REGISTRY)` 即评估全部。其内部对未知 key 会跳过（行 189-190），全部 key 都在 registry 里所以都会跑。

**B3.** `build_strategy_screener_data`（行 264）的 catalog append（行 281-290）已通过 `**item` 继承 `strategy_catalog` 的 `origin` 字段（B1 加的）。确认 `result_count` 字段（行 286）保留。`max_results` 字段（行 287 已有）也保留。

### 步骤 C：每日任务 `src/run_daily.py`

**C1.** 行 938-943 现有调用（观察名单用）保持不变。

**C2.** 在其后新增单策略筛选池的预计算（约行 943 后）：

```python
single_screener_catalog, single_screener_results = build_single_screener_pool(
    stock_daily, report_date, factors,
    config.strategies.parameters,
    config.strategies.max_scoring_hit_rate,
    config.strategies.min_selectivity_multiplier,
)
```

**C3.** `build_report_payload`（或等价函数，行 938 附近的 web_report 调用）传入新数据。需 grep `web_report.build_report_payload` 或 `build_payload` 的调用，把 `single_screener_catalog` / `single_screener_results` 加进参数。

### 步骤 D：报告输出 `src/web_report.py`

**D1.** `build_report_payload`（行 ~50-84）加参数 `single_screener_catalog` / `single_screener_results`，写入 latest.json：

```python
"strategy_screeners": _json_value(single_screener_catalog or strategy_screeners or []),
"strategy_screener_results": _records(single_screener_results or strategy_screener_results),
```

> 优先用 `single_screener_catalog`（全部策略 × Top 200），这样单策略筛选页能即时截断。观察名单的 `strategy_screeners` 逻辑可保留为回退。

### 步骤 E：面板 API `src/panel.py`

**E1.** 新增 `GET /api/single-screener`：

```python
@app.get("/api/single-screener")
def single_screener() -> dict[str, Any]:
    config = _config()
    catalog = strategy_catalog()  # 含 origin
    # 补 matched_count/result_count（从 latest.json 读，类似 custom_strategies 的 snapshot 回填）
    payload_path = _latest_payload_path()
    reported: dict[str, dict[str, Any]] = {}
    if payload_path.exists():
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            reported = {str(it.get("key","")): it for it in payload.get("strategy_screeners", []) if it.get("key")}
        except (OSError, json.JSONDecodeError):
            pass
    for item in catalog:
        snap = reported.get(item["key"], {})
        for k in ("matched_count", "result_count", "max_results", "status"):
            if k in snap:
                item[k] = snap[k]
        item["enabled"] = item["key"] in config.single_screener.enabled
    return {
        "catalog": catalog,
        "enabled": config.single_screener.enabled,
        "top_per_strategy": config.single_screener.top_per_strategy,
        "results": payload.get("strategy_screener_results", []) if 'payload' in locals() else [],
    }
```

**E2.** 新增 `PUT /api/single-screener`：

```python
class SingleScreenerUpdate(BaseModel):
    enabled: list[str]
    top_per_strategy: int

@app.put("/api/single-screener")
def update_single_screener(update: SingleScreenerUpdate) -> dict[str, Any]:
    unknown = sorted(set(update.enabled) - set(STRATEGY_REGISTRY))
    if unknown:
        raise HTTPException(status_code=422, detail="未知策略: " + ", ".join(unknown))
    if not 1 <= update.top_per_strategy <= 200:
        raise HTTPException(status_code=422, detail="top_per_strategy 必须在 1-200 之间")
    path = ROOT / "config" / "strategy.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("single_screener", {})
    raw["single_screener"]["enabled"] = list(dict.fromkeys(update.enabled))
    raw["single_screener"]["top_per_strategy"] = update.top_per_strategy
    temporary = path.with_suffix(".yml.tmp")
    temporary.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
    return single_screener()
```

> 注意：`STRATEGY_REGISTRY` 需 import。`BaseModel` 用项目已有的（grep `class.*BaseModel` 或 `from pydantic`）。

### 步骤 F：前端 `web/assets/app.js` + `web/index.html`

**F1. `index.html` 行 157**：按钮文案改：
```html
<button class="secondary-button local-only" id="save-custom-strategies-button"><i data-lucide="save"></i><span>保存筛选配置</span></button>
```

**F2. `app.js` `singleStrategySource`（行 567-617）**：catalog 来源从 `state.strategies` 改为新的 `state.singleScreener`（GET /api/single-screener 的结果）。保留 custom 公式部分不动。

**F3. `app.js` `renderCustomStrategies`（行 708-728）卡片渲染**：加来源标签。在 `<h3>` 前或 `<small>` 旁加：
```js
var originLabel = item.source_type === "formula" ? "公式"
  : (item.origin === "custom" ? "自建" : "内置");
// 在 button 内加 <span class="formula-origin">' + originLabel + '</span>
```

**F4. `app.js` `saveCustomStrategies`（行 763-800）**：改为只调 `PUT /api/single-screener`（不再调 `/api/strategies`）。自定义公式的 `/api/custom-strategies` 保留。

**F5. `app.js` 数据加载**：新增 `loadSingleScreener()` 拉 `GET /api/single-screener`，存 `state.singleScreener`，渲染时按 `state.singleScreener.top_per_strategy` 截断本地池（即时生效）。

**F6. 同步**：`cp web/assets/app.js site/assets/app.js` + `cp web/index.html site/index.html`。用 `node --check web/assets/app.js` 验证语法。

### 步骤 G：测试

**G1. `tests/test_strategies.py`**：
- 新增 `test_build_single_screener_pool_evaluates_all_strategies`：验证返回 catalog 含全部 11 个 key、每个含 `origin` 字段、`volume_breakout_pullback` 的 origin == "custom"。
- 新增 `test_single_screener_pool_respects_pool_size`：命中数 > 200 时 results 每策略 ≤ 200。

**G2. `tests/test_panel.py`**：
- 新增 `test_single_screener_get_returns_config`：默认值正确。
- 新增 `test_single_screener_put_validates`：未知 key → 422；top_per_strategy 越界 → 422。

**G3. `tests/test_web_report.py`**：验证 latest.json 的 `strategy_screeners` 含 `origin` 字段。

**G4. 运行**：
```bash
.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
```
（Windows 上需设 `TMPDIR`/`TMP`/`TEMP` 为项目内可写目录，否则 pytest 临时目录权限报错。）

### 步骤 H：文档与提交

**H1.** `config/strategy.yml` 加默认小节（让配置可见）：
```yaml
single_screener:
  enabled:
    - ma_volume
    - turtle_breakout
    - rps_breakout
    - pullback_stable
    - limit_up_shakeout
    - volatility_squeeze
    - trend_pullback_reversal
    - low_volatility_rps
    - first_pullback
    - volume_breakout_pullback
    - sector_leader
  top_per_strategy: 20
```

**H2.** `README.md` / `docs/STRATEGIES.md`：补一句单策略筛选配置说明（可选）。

**H3.** 提交：
```
git add -A
git commit -m "feat: 单策略筛选独立配置 + 来源标签 + 预计算池即时生效"
```

---

## 3. 验收清单

- [ ] `config/strategy.yml` 有 `single_screener` 小节，与 `strategies` 独立。
- [ ] `run_daily` 生成 latest.json 时，`strategy_screener_results` 含全部 11 策略 × Top 200。
- [ ] `strategy_screeners` 每项含 `origin` 字段。
- [ ] `GET/PUT /api/single-screener` 工作，非法值 422。
- [ ] 前端卡片显示「自建/内置/公式」标签。
- [ ] 改单策略筛选配置后**即时生效**（不重跑任务）。
- [ ] 观察名单的「保存策略」与单策略筛选的「保存筛选配置」互不影响。
- [ ] `node --check web/assets/app.js` 通过；web/ 与 site/ 同步。
- [ ] `pytest tests/` 全绿。

## 4. 风险与注意

- **循环 import**：`config.py` 引用 `STRATEGY_REGISTRY` 可能循环。规避：复用 `config.py` 已有的 `DEFAULT_ENABLED_STRATEGIES` 作默认 enabled。
- **latest.json 体积**：11×200 ≈ 2200 行，增大约 2-3MB。可接受。
- **旧 latest.json 兼容**：前端已对缺失 `origin`/`result_count` 回退（上一轮修复已处理）。
- **不要动观察名单逻辑**：`evaluate_enabled_strategies(..., config.strategies.enabled, ...)`（行 917）保持原样，单策略筛选用新增的 `build_single_screener_pool`。
