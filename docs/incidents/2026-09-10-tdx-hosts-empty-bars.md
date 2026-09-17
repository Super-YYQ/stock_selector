# 2026-09-10 TDX 行情节点集体失效：每日任务连续 6 天无报告

## 现象

- 最后一次成功：`2026-09-09 16:45`（`run_2026-09-09.log`）。
- `2026-09-10 12:30` 起，每次计划任务都在 16 分钟后失败，`site/data/latest.json` 与 Excel 报告停留在 09-09。
- 日志中 5,530 只股票与 3 个指数全部失败，错误一律是：

  ```
  TDX get_security_bars failed: beijing-unicom-80: calling function error | beijing-unicom: calling function error | ...
  ```

- 严格校验随后拦下报告：`当日股票覆盖率 0.0% 低于要求 98.0%`。这一步是正确的，放宽校验只会用旧数据伪装成新报告。

## 排查过程

1. **对比日志**：09-01～09-09 日志约 28 KB，09-10～09-15 每份约 3 MB，失败从 09-10 12:30 那次开始，没有任何过渡期，说明是外部环境突变而非代码回归（这段时间 `src/tdx_fetcher.py` 无改动）。
2. **读 pytdx 源码**：`calling function error` 是 `pytdx/base_socket_client.py` 里 `update_last_ack_time` 装饰器对一切失败的统一包装，真实原因放在 `exc.original_exception`；仓库用 `str(exc)` 记日志，把原因丢了。
3. **最小诊断矩阵**（每个节点 × TCP 连接 × 协议握手 × `get_security_count` × 指数日线 × 个股日线 × 实时行情）：
   - 6 个内置节点 TCP 全通；4 个握手成功，`get_security_count` 正常返回 24284；
   - `get_index_bars` / `get_security_bars` 在解析阶段抛 `struct.error: unpack requires a buffer of 4 bytes`；
   - `get_security_quotes([600000])` 返回 0 条。
4. **抓原始字节**：失败节点对任何 K 线请求（换股票、换 `category`、换 `start`/`count`）都返回固定的 2 字节应答 `20 03`；正常的"无数据"应答是 `00 00`，正常有数据的应答是 `05 00` + 5 根 bar。这是服务端对本客户端请求格式的**拒绝应答**，不是数据为空。
5. **扩大扫描**：对 pytdx 内置的 103 个节点和 mootdx 的 38 个官方"双线"云节点逐个探测：
   - 所有能连上的通达信官方主站（上证云 / 上海电信 / 北京联通 / 杭州 / 广发 / 中信 / 国信 / 双线云节点）一律返回 `20 03`；
   - 只有国泰君安自建集群 `117.34.114.14/16/17/18/20/27` 返回完整日线（含当天）。
6. **排除"被拉黑"**：仓库从未访问过的广发/中信/国信/官方云节点，在第一次请求时就返回 `20 03`，因此与本机 IP 的历史行为无关；同期社区报告（`electkismet/eltdx#18`、`jiangtaovan/tdxrs#12`）也显示官方主站在 9 月初开始调整协议。
7. **验证替代节点负载能力**：国泰君安节点 800 根分页 0.05 s、三大指数、北交所 `92xxxx` 代码、实时行情全部正常。

## 根本原因

1. **外部**：2026-09-10 起，通达信官方运营的公共行情主站不再为 pytdx 1.72 使用的 K 线请求格式返回数据，只回一个 2 字节占位应答；pytdx 自 2019 年后没有新版本。
2. **仓库**：`DEFAULT_TDX_HOSTS` 硬编码的 6 个节点全部属于上述集群；连接逻辑只判断"能否连上"，不判断"能否出数据"；节点列表不可配置；错误信息丢掉了 `original_exception`。四个因素叠加，导致所有入口（面板、`daily.bat`、计划任务）每天重复同样的 16 分钟失败。

## 修复（本次提交）

- `src/tdx_fetcher.py`
  - 默认节点改为国泰君安集群；
  - 每次建连后先请求 1 根上证指数日线做健康探测，探测失败的节点按连接失败处理并切换下一节点；
  - 错误信息附带 pytdx 隐藏的原始异常，例如 `calling function error (error: unpack requires a buffer of 4 bytes)`；
  - 新增 `parse_tdx_hosts`，节点列表透传到并行 worker。
- `src/config.py`、`src/run_daily.py`、`docs/CONFIGURATION.md`：新增 `data.tdx_hosts`（`ip:port` 列表，留空使用内置节点），带格式校验。
- 回归测试：连得上但不出 K 线的节点必须被跳过；错误信息必须保留原始异常；节点解析、透传与配置校验。

验证：全仓 `pytest` 173 passed；真实运行 `run_daily.py --snapshot auto`，4 分钟补齐 09-10～09-17 六个交易日 33,092 条日线，校验 5,526/5,530（99.9%）、指数 3/3，生成 `2026-09-17` 报告。

## 后续优化点

按收益排序，均未在本次实施：

1. **快速失败**：所有节点都坏时，目前仍会逐批次尝试连接后才被熔断（约 5 分钟）。可以在并行抓取前先用一次探测判定"供应商整体不可用"，几十秒内退出并给出明确原因。
2. **节点冷却记忆**：把节点探测结果（连续失败次数、最后成功时间）写入本地状态，下次任务优先使用最近成功的节点，避免重复踩坏节点。
3. **多集群冗余**：当前默认列表只有国泰君安一个集群。若该集群也升级协议，pytdx 路线将彻底失效，届时需要把 `data.provider` 切到 `akshare` / `baostock`，或接入支持新协议的客户端；`tdx_hosts` 配置项为此预留。
4. **启动脚本退出状态**：`daily.bat` 无论成败都打印 `Daily task finished`，计划任务通过 `cmd.exe /c` 包装后 `LastTaskResult` 不能反映真实结果；应透传 Python 退出码并在失败时打印失败摘要。
5. **发布流程约束**：`scripts/publish_pages.py` 发现本地存在未推送的非发布提交时会停止自动发布。任何代码修复都必须及时推送到远端，否则下一次计划任务只会更新数据、不会发布。

## 参考

- pytdx 错误包装：`.venv/Lib/site-packages/pytdx/base_socket_client.py`（`update_last_ack_time`）
- 社区同期报告：https://github.com/electkismet/eltdx/issues/18 、https://github.com/jiangtaovan/tdxrs/issues/12
