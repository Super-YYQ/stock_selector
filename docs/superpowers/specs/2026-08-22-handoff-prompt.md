你是一个资深 Python/前端工程师，接手一个已有项目的功能实施。项目根目录：E:\我的git项目\Github\stock_selector（Windows，bash shell，.venv 在项目内）。

【你的任务】
严格按这份实施计划文件执行全部步骤，直到完成：
docs/superpowers/specs/2026-08-22-single-screener-config-plan.md

先完整读这份计划文件，再读它引用的 spec：
docs/superpowers/specs/2026-08-22-single-screener-config-design.md

【任务背景（一句话）】
把「单策略筛选」页的配置（启用哪些策略、每策略展示多少条）从「观察名单」配置里拆出来，独立成 single_screener 配置；后端预计算全部 11 个内置策略 × Top 200 命中池使配置即时生效；前端加来源标签（自建/内置/公式）。

【执行要求】
1. 按计划文件的「步骤 A → H」顺序执行，每步对照计划文件里给出的行号和代码片段。
2. 每改完一个文件，用项目自带工具验证：
   - Python：.venv/Scripts/python.exe -m pytest 对应测试 -q -p no:cacheprovider
   - 全量测试：.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider
   - 注意 Windows 上 pytest 临时目录权限问题，设 TMPDIR/TMP/TEMP 为项目内 .pytest_tmp 目录（先 mkdir -p .pytest_tmp）
   - 前端 JS：node --check web/assets/app.js
3. 前端改动必须同步 web/ 和 site/（二者是镜像）：改完 web/assets/app.js 和 web/index.html 后 cp 到 site/ 对应路径，并用 md5 确认一致。
4. 关键约束（计划文件「风险与注意」已列）：
   - 不要动观察名单的评分逻辑（evaluate_enabled_strategies 的 enabled 参数保持 config.strategies.enabled）。
   - config.py 引用 STRATEGY_REGISTRY 可能循环 import，优先复用 config.py 已有的 DEFAULT_ENABLED_STRATEGIES 作默认值。
   - single_screener.enabled 允许为空（不报错，页面显示「暂无启用策略」），与观察名单不同。
   - top_per_strategy 上限 200。
5. 完成后对照计划文件「3. 验收清单」逐项自检，全部打勾才算完成。
6. 最后用 git 提交（不要 push，除非用户要求）：
   git add -A && git commit -m "feat: 单策略筛选独立配置 + 来源标签 + 预计算池即时生效"

【验收硬指标】
- pytest tests/ 全绿（当前 146 个测试 + 你新增的测试）。
- node --check web/assets/app.js 通过。
- web/assets/app.js 与 site/assets/app.js md5 一致；web/index.html 与 site/index.html 一致。
- config/strategy.yml 含独立的 single_screener 小节。
- latest.json（下次 run_daily 后）strategy_screener_results 含全部 11 策略、strategy_screeners 每项含 origin 字段。

开始执行，不要问不必要的澄清问题——计划文件已经足够详细。如果遇到计划文件没覆盖的歧义，按最符合背景目标的方式自行决定并在最终报告里说明。
