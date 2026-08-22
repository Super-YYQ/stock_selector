# 单策略筛选独立配置设计

日期：2026-08-22
状态：待评审

## 背景与问题

当前「单策略筛选」页与「观察名单」共用同一套配置（`config/strategy.yml` 的 `strategies.enabled` + `top_per_strategy`），导致：

1. **配置耦合**：单策略筛选页没有独立的「启用哪些策略、每个策略展示多少条」配置，改单策略筛选会连带影响观察名单的综合评分。
2. **来源不区分**：11 个内置策略里，`volume_breakout_pullback` 是用户自建（有独立回测脚本、文档化形态、详细参数），其余 10 个是仓库初始从网络收集的通用策略，但 UI 上没有区分。
3. **「保存启用状态」语义模糊**：该按钮实际写的是观察名单用的 `strategies.enabled`，与单策略筛选页的展示逻辑混在一起。

## 目标

- 单策略筛选拥有**独立的、即时生效的**配置（启用哪些策略、每策略展示 N 条），与观察名单配置完全解耦。
- 策略目录卡片标注**来源**（自建 / 内置 / 公式）。
- 「保存启用状态」改为只保存单策略筛选配置，语义清晰。

## 非目标

- 不改变观察名单（Top 50 / Top 10）的生成逻辑和评分权重。
- 不改变自定义公式的求值逻辑（已是独立的 `custom_strategies.yml`）。
- 不做策略的增删改（那是另一套编辑功能）。

## 方案

### 1. 配置拆分（`config/strategy.yml`）

新增独立小节，与现有 `strategies` 并列：

```yaml
strategies:            # 观察名单/综合评分用（保持不变）
  enabled: [...]
  profile: balanced
  top_per_strategy: 20
  ...

single_screener:       # 新增：单策略筛选页专用
  enabled:             # 单策略筛选页启用哪些内置策略（默认全部）
    - ma_volume
    - ...
  top_per_strategy: 20 # 每个策略展示多少条（≤ 预计算上限 200）
```

- `single_screener.enabled` 默认 = 全部 11 个内置策略。
- `single_screener.top_per_strategy` 默认 20，可调，上限 200（预计算池大小）。
- 自定义公式继续用 `custom_strategies.yml` 的 `enabled` + `max_results`，不并入 `single_screener`（保持公式配置的独立性）。

### 2. 后端：预计算大池子（即时生效的关键）

`src/run_daily.py` + `src/strategies/registry.py`：

- `build_strategy_screener_data` 改为**评估全部 11 个内置策略**（不再只算观察名单勾选的 `strategies.enabled`），每个策略预计算 **Top 200** 命中。
- catalog 每项带：
  - `matched_count`：全市场命中总数（不截断）
  - `result_count`：预计算池大小（= min(matched_count, 200)）
  - `origin`：`"custom"`（volume_breakout_pullback）或 `"builtin"`（其余）
- `strategy_screener_results` 存全部预计算行（11 × 200 ≈ 2200 行上限）。

`src/panel.py`：

- 新增 `GET /api/single-screener`：返回 `single_screener` 配置 + 策略 catalog（含 origin）。
- 新增 `PUT /api/single-screener`：写回 `single_screener.enabled` + `top_per_strategy` 到 `strategy.yml`。
- 现有 `GET/PUT /api/strategies`（观察名单用）保持不变，不再被单策略筛选页调用。

### 3. 前端：单策略筛选页

`web/assets/app.js` + `web/index.html`（同步到 `site/`）：

- **来源标签**：策略目录卡片左上角加小标签：
  - `volume_breakout_pullback` → 「自建」
  - 其余内置 → 「内置」
  - 自定义公式 → 「公式」
- **独立配置**：启用勾选 + 每策略 N 的输入，读写新的 `/api/single-screener`，保存后**立即重新渲染**（数据已预计算在本地 `state.payload`，实时截断，无需重跑）。
- **即时生效**：改配置 → PUT 保存 → 前端用本地预计算池按新 `enabled` + `top_per_strategy` 重新过滤渲染。
- **「保存启用状态」→「保存筛选配置」**：只保存单策略筛选配置，不再碰观察名单的 `strategies.enabled`。

### 4. 数据流

```
run_daily（每日任务）
  └─ 评估全部 11 策略 × Top 200 → latest.json
       ├─ strategy_screeners (catalog: matched_count, result_count, origin)
       └─ strategy_screener_results (预计算池)

面板加载
  └─ GET /api/single-screener → single_screener 配置 + catalog
  └─ latest.json → 预计算池

用户改配置 → PUT /api/single-screener → 写 strategy.yml
  └─ 前端用本地池按新配置实时截断渲染（即时生效）
```

## 错误处理

- `single_screener.top_per_strategy` 超出 [1, 200] → PUT 返回 422。
- `single_screener.enabled` 含未知策略 key → 422。
- `single_screener.enabled` 为空 → 允许（页面显示「暂无启用策略」），不强制至少一个（与观察名单不同，因为不影响评分）。
- 旧 `latest.json` 无 `origin`/`result_count` 字段 → 前端回退（origin 默认 builtin，result_count 回退 matched_count）。

## 测试

- `test_strategies.py`：`build_strategy_screener_data` 不再依赖 `enabled` 过滤，全部策略都评估；catalog 含 `origin` 字段。
- `test_panel.py`：`GET/PUT /api/single-screener` 读写 `single_screener` 配置；非法值 422。
- `test_web_report.py`：latest.json 含 `origin` 字段。
- 手动验证：面板改配置后即时生效，来源标签正确显示。

## 迁移

- 现有 `strategy.yml` 无 `single_screener` 小节 → 首次 `GET /api/single-screener` 时返回默认值（全部启用 + 20），首次 PUT 时写入。
- 旧 `latest.json` 兼容（前端回退逻辑已在上轮修复中处理）。
