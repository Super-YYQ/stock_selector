# 2026-09-18 Pages 打开慢优化计划

## 背景与测量结论

用户报告线上静态页面打开慢。2026-09-18 用 curl 分段计时（每资源 3 次）+ Playwright 冷加载时间线做了分解测量，结论：

**瓶颈权重排序：**

1. **网络（主因，约 90%）**：本机到 GitHub Pages（Fastly 美国节点）跨境吞吐仅 30–70 KB/s，且 TCP 连接随机卡顿（21 次请求中 2 次连接耗 15s / 22s，GFW 典型特征）。
2. **字节数（次要，约 10%）**：`latest.json` 原始 2.5 MB、gzip 后 319 KB，占初始加载字节的 72%，在慢速管道下花 5–24 秒；静态模式每次先探测 `/api/latest`（必然 404）白等约 1.5 秒。
3. **90 天历史数据（已排除）**：初始加载不拉任何历史文件，`history.json` 索引压缩后仅 316 B；历史 JSON 只在切换日期时按需加载。

一次冷加载时间线（本机）：HTML 1.7s → DCL 12.9s → `latest.json` 完成 37.6s → 数据渲染完成约 38s；拥堵时段会话首绘观测到 73.7s。

关键资源本身不重（HTML 5 KB + CSS 11 KB + app.js 15 KB + lucide 84 KB + ths_export 5 KB ≈ 120 KB）；1.66 MB 的 `fluid-market-field.png` 只被 404 页引用，不在主页关键路径。

## 改动项

### B1. latest.json 紧凑序列化（仓库内，预期压缩后再省 10–15%）

`src/web_report.py` 的 `write_static_report`：`json.dumps(payload, ensure_ascii=False, indent=2)` 改为去掉 `indent=2`。

- 历史文件沿用同一序列化（latest 与当日历史仍要求逐字节一致，见 `publish_pages._validate_report_inputs`）。
- 注意：发布脚本的「已发布历史不可变」校验按内容（行尾归一化）比较，本次改动只影响**新写入**的文件；旧历史文件保持原样，不会被误判改写。
- 验收：单测断言生成文件不含换行缩进；latest 与同日历史仍一致；`publish_pages` 回归全绿。

### B2. 静态模式跳过 /api/latest 探测（省约 1.5s）

`web/assets/app.js` 的 `load()`：静态站点直接走 `data/latest.json`，不再先试 `/api/latest`。判定方式：路径判断（当前页面非面板端口/协议特征）或保留一次带短超时（如 1s）的探测后回退。实现时选择侵入最小的方案：**给 `/api/latest` 请求 1 秒超时**，本地面板存在时秒回，静态站点 1 秒后回退，行为兼容两端。

- 注意 `web/` 是唯一源，`site/` 每次运行重新生成；改动后需跑一次 `run_daily`（或调用 `write_static_report`）+ `publish_pages.py` 才能上线。
- 验收：静态模式首字节请求即为 `data/latest.json`；本地模式不受影响（`/api/health` 等逻辑不动）。

### B3. 404 页去掉 1.66 MB 背景图（不阻塞但明显过重）

`web/404.html` 删除 `<link rel="preload" as="image" href="assets/fluid-market-field.png">` 及相应背景引用，404 页改纯样式。

- 该图不在主页关键路径，此改动只影响 404 命中场景。
- 评估后可进一步：若该图确无其他用途，可从 `web/assets/` 移除，发布体积 -1.66 MB。
- 验收：404 页正常显示纯色/渐变背景；grep 确认无引用残留。

### C. 脚本 defer / 渲染感知（小收益）

`web/index.html`：`lucide.min.js`、`app.js`、`ths_export.js` 加 `defer`。

- 脚本已在 `body` 尾部，defer 的收益是 HTML 解析不等待脚本下载；在慢速管道下能让首屏结构更早出现。
- 验收：页面交互（视图切换、下拉、抽屉）行为不变；脚本执行顺序 `lucide → app → ths_export` 保持（defer 保持文档顺序）。

### A. 镜像到中国可达的 CDN（结构性解决，收益最大）

目标：把 38 秒压到 3 秒量级。方案：**Cloudflare Pages 镜像发布**。

- 动机：Cloudflare 对中国大陆连通性通常显著好于 GitHub 直连（非保证，需实测）；免费额度足够；支持自定义域名。
- 实施草案：
  1. Cloudflare Pages 建项目，来源选「直接上传」或连接 GitHub 仓库的 `gh-pages` 分支（连接仓库方式零新增代码，但需仓库可访问——已是 public，可行）。
  2. 若用「连接 gh-pages 分支」：Pages 每次 gh-pages 更新自动部署，无需改任何发布代码。
  3. 建议先建项目实测国内可达性与吞吐，再决定是否切换主入口；GitHub Pages 保留为兜底。
  4. 域名/入口切换属于用户手动操作（Cloudflare 账号、Dashboard 操作），面板与文档不引入新配置面。
- 前置确认：用户自测手机网络下 `*.pages.dev` 的可达性（不同地区/运营商差异大）。
- 本仓库代码改动：**无**（连接仓库方式）；若未来改为镜像推送，再评估 `publish_pages.py` 增加 `--mirror` 目标。
- 验收：手机实测新入口打开 < 5s（跨境正常时段）；数据与 GitHub Pages 一致（同一 gh-pages 分支部署）。

## 执行顺序与状态

| 项 | 状态 | 实测收益 |
|---|---|---|
| B1 紧凑序列化 | 已完成（5b27977，2026-09-19） | gzip 后省 3.6%（269→259KB），原始体积省 14% |
| B2 跳过 API 探测 | 已完成（5b27977） | 探测 1s 超时掐断（3s 慢 API 下实测 1101ms 回退） |
| B3 404 去背景图 | 已完成（5b27977） | PNG 已删除，发布体积 -1.66MB |
| C 脚本 defer | 已完成（5b27977） | DCL 665ms（原 ~12.9s），首屏结构先出 |
| A Cloudflare 镜像 | 待用户决策与实测 | 38s → 3s 量级 |

B1–C 已随 5b27977 提交推送；随下次每日运行写入紧凑格式数据并发布上线。

B1 涉及序列化格式，需回归 `latest == 同日历史` 的发布校验；B2/C 涉及前端行为，需本地/静态双模式手测（AGENTS.md 前端规则）。

## 测量复现方式

复测时用同一方法对比前后：

```bash
# 分段计时（每资源 3 次）
for i in 1 2 3; do
  curl -s -o /dev/null -H "Accept-Encoding: gzip" \
    -w "ttfb=%{time_starttransfer}s total=%{time_total}s dl=%{size_download}B speed=%{speed_download}B/s\n" \
    "https://super-yyq.github.io/stock_selector/data/latest.json"
done

# 浏览器冷加载时间线（Playwright evaluate performance entries）
# responseStart / domContentLoaded / loadEvent / 数据渲染完成（report-date 填充）
```
