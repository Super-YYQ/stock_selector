# Design QA

## 2026-08-22 浅色设计感强化 + 运行态页统一 + 发布隔离

### 范围
针对反馈「浅色重构像去掉了颜色」「运行态页没优化」「程序与静态页面不独立、开发态过滤实验影响发布」的落地。

### A. 发布隔离（`scripts/publish_pages.py`）
- 移除 `_ensure_report_inputs_clean()` 的源码/配置/模板干净校验（原 `REPORT_INPUT_PATHS` 常量删除），改为 no-op 保留函数签名。
- 发布提交由 `_commit_report` 以 `git commit --only -- <site/data/*>` 创建，仅含报告数据；本地未提交的 `src/`、`config/`（含开发态勾选科创板过滤）、`web/` 模板不再阻断定时发布。
- 保留其余安全网：仅 `site/data/*` 进入提交、快进校验、单父提交校验、分支必须为 `main`、盘中临时快照不发布。
- 测试 `test_publish_refuses_dirty_report_source` → `test_publish_allows_dirty_report_source`：断言 dirty src/config 时发布成功、remote 前进、提交只含报告文件、开发态改动保留在工作区。

### B. UI 更有设计感（`web/assets/app.css`，浅色基底不变）
- tokens：三级 surface（canvas→surface→raised）+ 更深阴影；新增 amber/gold 与 slate-blue 次强调色相、`--tier-*` 分段、品牌渐变 `--grad-brand`/`--grad-amber`、`--console-*` 终端 token、`--pill-*` 徽标 token。
- 色彩与层次：section-label 前加 teal 小色点建立节奏；品牌标与 scheduler 图标改品牌渐变 + 阴影；data-surface 加微阴影；custom hero 加左强调条与卡片化；custom-result-count 大数字用 amber 渐变 text-clip；score-cell 加左侧渐变色条；drawer-score 得分用品牌渐变 text-clip；breakdown 条健康=品牌渐变、风险=coral 分色。
- 数据可视化：mini-track、sector-bar、evidence-temperature 条统一品牌渐变；guardrail 序号改 amber 实心渐变徽标；family-mark.trend/sector 改渐变/slate。
- 运行态（系统页）：`.run-output` 收编为 token 驱动的有意为之深色日志面板（`--console-*`），圆角与字体对齐；health/run/scheduler 三套徽标统一为带圆点的 `--pill-*` pill，run 运行中圆点脉冲；system-note 改 primary-tint 强调条样式。

### C. 同步
- `web/assets/app.css` → `site/assets/app.css`（模板文件随 PR 提交，不走 publish）。
- `web/index.html` / `site/index.html` 缓存版本号 `?v=20260822-1`。
- 未改 `app.js` / `ths_export.js` / Python / API / payload。

### 验证
- `pytest tests/ -p no:cacheprovider`：146 passed。
- `node --check web/assets/app.js`、`node --check web/assets/ths_export.js`：OK。
- CSS 花括号配平 481/481；`var(--token)` 引用全部有定义（74 defined / 57 used / 0 missing）。
- `git diff --check`：通过。

---

## 2026-08-21 浅色重构（历史记录）

## Source and implementation

- Visual source: `C:\Users\闫亚奇\.codex\generated_images\019f93d0-4296-7c93-8df5-5e236ba4b202\call_7S1fe9WeBcKmsopQGxCSGVAC.png`
- Source dimensions: 1440 × 1024 px
- Implementation screenshot: `E:\我的git项目\Github\stock_selector\artifacts\ui-qa\fluid-exchange-desktop.png`
- Implementation dimensions: 1440 × 1024 px
- Mobile screenshot: `E:\我的git项目\Github\stock_selector\artifacts\ui-qa\fluid-exchange-mobile.png`
- Mobile viewport: 390 × 844 px
- Full comparison: `E:\我的git项目\Github\stock_selector\artifacts\ui-qa\comparison-full.png`
- Focused comparison: `E:\我的git项目\Github\stock_selector\artifacts\ui-qa\comparison-focus.png`
- Browser: Google Chrome through the user-approved local Playwright workflow
- State: 单策略筛选 / 放量突破缩量承接 / 440 只命中

## Full-page comparison

The implementation matches the selected Fluid Exchange direction: a floating rounded navigation spine, large asymmetric title and count, a luminous aqua/purple market field, a 13-card strategy orbit with the active card in the center, and a dense dark trading ledger. The app keeps the real Chinese strategy names, result counts, stock data, filters, toggles, and detail drawer instead of reproducing the mock data from the visual source.

## Focused comparison

The strategy orbit and result transition were compared together at the same desktop dimensions. The active card has the intended aqua outline, lifted depth, target icon, and 440 count. All 13 cards are fully visible on the desktop viewport. On mobile, the active strategy is centered with a measured center delta of 0 px, and the document has no horizontal overflow.

## Findings and iteration history

1. First pass: the thirteenth strategy card was partially clipped at 1440 px, and the active mobile card could open outside the visible track.
2. Fix: reduced the desktop card minimum width and track gap while preserving equal card sizes; added active-card centering after render and after entering the single-strategy view.
3. Final visual pass: 13/13 strategy cards are fully visible, the active strategy is centered on mobile, the large count and selected title are correct, and no Lucide placeholders remain unresolved.
4. Interaction pass: switching to another strategy updates the result title; searching for `百合花` filters to one row; the stock detail drawer opens and closes; desktop and mobile navigation return to the single-strategy view correctly.
5. Automated checks: 78 Python tests passed; both JavaScript bundles pass syntax checks; `git diff --check` passed.
6. Environment note: the local Windows scheduler status endpoint returns access denied because this verification process cannot read the system Scheduled Tasks service. The UI catches that optional backend condition, and it does not affect the selected screen, visual rendering, or core interactions.

## Final result

passed
