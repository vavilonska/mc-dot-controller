> 本页根据已交付 ZIP 的使用说明整理。`source/`、`mod/`、`tools/` 和包级校验文件均指该 ZIP 布局；Git 仓库只发布源码与文档。请先读[交付范围](../README.md)。

# MDC 工具箱调用指南（2026-10-16）

## 1. 适用对象与边界

本指南针对 Linux/POSIX 同机的 Minecraft 1.21.1 + NeoForge 21.1.x 工具箱。最新配套为：

- JAR：`59523ef1a2e6c9c1a738c13958d60c506ff526033ae21af6023140bd6f0b2694`
- 版本：`1.1.6-toolbox-v1-route-threat-diagnostic-offline-test.1`
- 完整配套 runtime：1,034 文件；原始 runtime manifest SHA-256：`72f65949219e97945af875dc2a5244df57affc3405b32e574823b7245bf03794`

当前 T46 仅为受控单僵尸路线抢占后防御的核心实机通过。T42 工作坊组合流程是旧 JAR `64aaa1a35a3f528cfa96cd2bb3a9978e49626d2dd9deeac5d2ecb72664ee7e3e` 的历史合格通过，不能自动移植到最新 JAR 的验收栏。详见 [能力矩阵](CAPABILITY-MATRIX.md)。

只用于已经授权的独立普通单机测试副本，保留原世界，不连接多人服务器。不自动恢复暂停任务，不重放未知结果，不通过新目录、清空日志或重启绕过所有权/不确定性。

## 2. 操作者先准备单一控制链

要求 Java 21、Node.js 20+（交付平台自检用 20.6+）、Python 3.10+ 和 POSIX `fcntl`；NeoForge 声明范围 `[21.1.197,21.2)`，本构建编译依赖为 21.1.255。Java 客户端、Resident、Watchdog、Node MCP 和 Python façade 必须实际共享必要的文件、进程和网络命名空间。原生 Windows 工具箱链未受支持，旧 Windows launcher 不能替代 POSIX owner stack。本包不提供通用 launcher、WSL 桥或账号登录能力。

启动顺序由已授权操作者执行：

1. 确认旧 owner 已停止、输入释放已确认、没有未解决的原始 mutation ID。暂停或 unknown 状态是阻断条件。
2. 在现有受信 launcher 中加载独立测试副本和匹配 JAR。只放一个 bridge mod，保存旧 JAR 在 active mods 以外。不要覆盖旧 runtime/journal。
3. 在 Java 所在的实际网络/进程环境启动一个 Resident；使用既有已批准凭据方式，令牌不能进入 AI 参数、聊天、模板或公开 source。
4. 启动唯一 Watchdog queue writer，并确认策略为当前请求所需值。
5. 配置 Node MCP，让它只启动一个固定 Python façade。不要另起第二个 façade 或直接写 Resident 队列。
6. 先读 tools/list、mdc_catalog 和一份小观察；验证单机、session/context、owner、profile、policy 与覆盖信息后才提交动作。

示意命令仅供操作者在确认路径后执行，均未在本次文档整理中运行：

```sh
# 从完整 source/resident-controller/ 中启动；VERIFIED_PORT / 路径必须实际核实。
PYTHONDONTWRITEBYTECODE=1 ./owner-start.sh http://127.0.0.1:VERIFIED_PORT /verified/shared/mailbox

# 从完整 source/defense-watchdog/ 中启动。
python3 -B watchdog.py run --queue /verified/shared/mailbox \
  --control /verified/private/control --execution-policy request_only
```

上述启动会创建/占用包外运行控制状态；不是无副作用自检命令。设置 PYTHONDONTWRITEBYTECODE/-B 是为避免在冻结 source 内写入 Python 缓存；MCP 子进程已自带该设置。不得在存在暂停或不明旧 owner 时照抄运行。

私有 toolbox 配置必须恰有以下六个键，不含 token。所有路径为操作者同一主机上的绝对路径；control、journal、runtime_journal 三目录互不相同，也不能互相嵌套：

```json
{
  "schema_version": 1,
  "python_executable": "/absolute/path/to/python3",
  "python_sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
  "control_directory": "/verified/private/control",
  "journal_directory": "/verified/private/toolbox-journal",
  "runtime_journal_directory": "/verified/private/runtime-journal"
}
```

配置文件须普通非 symlink 文件、最多 64 KiB。Python 可执行文件须解析到实际文件并匹配 SHA-256；不能在不匹配时自动换解释器。Node MCP command 指向核实的 Node，args 指向完整 source 的 `client-mod/mcp/mineclient-bridge-mcp.mjs`，环境变量 `MINECLIENT_TOOLBOX_CONFIG` 指向私有配置。

Node MCP 只启动固定 façade，不启动 Minecraft/Resident/Watchdog。它自设最小环境与 sibling PYTHONPATH；只复制 MCP 单个脚本不可用。

## 3. 公共入口

MCP 公开十二个工具，其中 Playing AI 使用四个：

- `mdc_catalog`：发现能力、读取输入契约与运行时协商信息
- `mdc_observe`：取得当前有界观察；观察/Survey/历史不授予执行权限
- `mdc_plan`：可选规划；规划不执行、不保留资源、不授予动作权限
- `mdc_job`：submit、status、cancel、reconcile

配置 `MINECLIENT_TOOLBOX_CONFIG` 后，legacy launch/register/action/input/close 被 `toolbox_exclusive_operator_binding` 拒绝，即使配置错误也不开放第二个写入者。旧 status/frame/query 使用其独立 legacy session 条件，不应当作 façade session 的替代。

API 版本固定 `mdc.toolbox/1`，capability_version 当前为整数 1。先读 `runtime_binding_availability`：available、private_singleplayer、session_ref、context_ref、execution_policy、supported_policies，以及每项能力的 runtime_available/availability_reason。目录中有名字或 JSON schema 接受某字段，并不等于后端已支持。

当前 20 项候选 allowlist：

`select_hotbar`、`ensure_hotbar`、`equip`、`consume`、`close_menu`、`container_move`、`container_split`、`container_merge`、`container_withdraw`、`container_deposit`、`craft`、`smelt`、`interact`、`navigate_local`、`navigate_step_down`、`navigate_route_local`、`mine_local`、`collect_local`、`place_local`、`engage`。

具体可用性还取决于已协商 native profile、action 和安全条件。`navigate_step_down`、`navigate_route_local`、`place_local` 要求实际 request_only 策略。不能通过请求来改变已运行 Watchdog 策略：noncombat→noncombat、guarded→standard、request_only→request_only。

## 4. 最小调用样例

随附 [toolbox-call-examples.json](../examples/toolbox-call-examples.json) 为当前 source 的九个原样调用模板，不是顺序执行脚本。本次交付检查了九个模板的 schema/domain 参数形状并核对复制字节，没有把任何模板提交给实际游戏。模板中的坐标/UUID 为合成占位，必须按本次 fresh observation 和明确目标替换。

以下示例通过普通 MCP tools/call 包装；结果是 MCP text content 中的 toolbox JSON。

### A. 查询一个小目录页

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mdc_catalog","arguments":{"api_version":"mdc.toolbox/1","detail":"contracts","capability_ids":["select_hotbar","navigate_route_local"]}}}
```

### B. 使用实际返回的 session 做小观察

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"mdc_observe","arguments":{"api_version":"mdc.toolbox/1","session_ref":"REPLACE_WITH_CATALOG_SESSION_REF","profile":"inventory"}}}
```

非 memory 观察请省略 selectors 或保持空对象；bounds 省略或仅使用当前公共 API 与 backend 均支持的 radius。不要传 max_cells、max_entities、max_results 或 acquisition_profile 并假设已实现；未实现项会拒绝。内部 Python 允许的某些字段并不在公共 schema 中，不能绕过 schema 使用。MCP 每条消息上限 1 MiB，内部较大的 JSON 上限不能替代它。

### C. 明确意图后提交一次简单动作

先从实际观察确认 slot 0 确实有物品且此次确实要选择它；为一个真正的新意图分配一次不可变 request_id。session 与 expected_context 必须使用实际返回值。

```json
{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"mdc_job","arguments":{
    "api_version":"mdc.toolbox/1","operation":"submit",
    "request_id":"REPLACE_NEW_APPROVED_INTENT_ID",
    "session_ref":"REPLACE_WITH_CATALOG_SESSION_REF",
    "expected_context_ref":"REPLACE_WITH_CURRENT_CONTEXT_REF",
    "capability":"select_hotbar","capability_version":1,
    "arguments":{"slot":0},
    "policy":{"version":1,"execution_mode":"request_only","reactions":"stop"},
    "budgets":{"deadline_seconds":15,"max_actions":2,"max_observations":16,
      "cleanup_reserve_actions":1,"reflex_reserve_actions":0},
    "wait_ms":0
  }}
}
```

这允许一个普通 mutation 和一个预留 cleanup。复杂配方/路线须按真实所需预留原始预算；子动作不会重置预算和期限。

### D. 查询原 ID；不要因丢回复再 submit

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"mdc_job","arguments":{"api_version":"mdc.toolbox/1","operation":"status","session_ref":"REPLACE_WITH_CATALOG_SESSION_REF","request_id":"REPLACE_ORIGINAL_REQUEST_ID","wait_ms":1000}}}
```

status 必须在 job_id 和 request_id 中恰选一个。accepted/running/stopping 尚未结束。查看 state 之外，还必须看 effect_certainty 与 cleanup_certainty。状态语义已知但 cleanup 未知仍不能继续其他 mutation。任务占用/存在不确定性期间，mdc_observe 可能拒绝；用 status 跟踪原任务。

### E. 取消已知当前任务

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"mdc_job","arguments":{"api_version":"mdc.toolbox/1","operation":"cancel","session_ref":"REPLACE_WITH_CATALOG_SESSION_REF","job_id":"REPLACE_WITH_ORIGINAL_JOB_ID","cancel_request_id":"REPLACE_ONE_IMMUTABLE_CANCEL_ID","wait_ms":1000}}}
```

取消不回滚已发生效果，也不使未知动作变成未执行。保留同一个 cancel_request_id；检查原始结果与 release。

### F. 仅核对未知原任务证据

```json
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"mdc_job","arguments":{"api_version":"mdc.toolbox/1","operation":"reconcile","session_ref":"REPLACE_WITH_CATALOG_SESSION_REF","job_id":"REPLACE_WITH_ORIGINAL_JOB_ID"}}}
```

reconcile 只读取原始证据，不自动 resume、release、replay。当前实现可能继续返回 unknown，这不是替换 ID 再做一次的依据。超时、断流、坏 JSON、无回复都不证明动作没发生。已知拒绝也要先读取具体原因，再判断是否存在另一个有独立依据的新动作。

## 5. 移动、容器和组合工作流

- navigate_local 仍是一格基数方向平地；navigate_step_down 是一格基数方向下降。
- navigate_route_local 是已加载局部、有限段数的 flat/up-one/down-one 基数路线，含物理居中与有限绕行；不是全局/未加载寻路。
- place_local 仅静止单个普通圆石。build/build_with_materials 不在当前 public runtime allowlist。
- 合成/quick-move 后重新观察物品实际槽位，不能硬编码旧实验的产物槽位。
- block-menu 交互前核对空手等条件。若合成填充当前选中槽位，可在明确意图下通过 public container_move 转到新观察的空储物槽，再核对组件/数量守恒和双手。不能丢物或用 raw input 绕过 admission。
- T42 的取料→合成→入桶流程是可参考的任务分解，不是跨版本验收，也不授权重跑其原 IDs。

## 6. 当前 defend_once 的两条触发分支

默认 reactions=stop。显式 defend_once 仅适用于 navigate_local、navigate_step_down、navigate_route_local、mine_local、collect_local，且需要 negotiated combat profile；route 仍为 request_only。noncombat 不可 opt in。avoid 与旧 defend 虽存在于通用 schema 枚举中，当前后端不广告/执行。

防御策略例子：

```json
{"version":1,"execution_mode":"request_only","reactions":"defend_once","defense":{"target_uuid":"44444444-4444-4444-8444-444444444444","timeout_ms":2000,"min_health":14}}
```

这个 UUID 纯属示意，必须替换为用户选定且本次新观察支持的敌对 UUID。不是自动找最近怪，也不支持自动换目标。T46 实机用 timeout_ms=5000；该 2000ms 模板没有由 T46 单独验收。

分支一，damage：原 native follow_path/break_block 以已知 failed/cancelled 的 capability_damage_observed 结束，原输入释放确认，原 owner/job/lease 与世界/玩家/action 上下文保持，fresh integrated-server target facts 确认该明确敌对目标正在针对该玩家。当前再次检查距离 ≤6 格及支持的 zombie/skeleton 家族类型。不能据此声称它就是此前伤害的来源。

分支二，typed threat：仅 route 协商 movement-local-segment-spatial-threat-v1 后，可消费精确绑定原 action 的 capability_threat_observed typed stop proof；当前支持选择的精确 vanilla zombie，必须当前正在针对玩家且距离 ≤3 格。若 stop proof 表明 preempted_before_motion，允许在普通移动发生前防御。单纯 admission HTTP409 拒绝不授予防御权限。

两条分支共同要求：

- 原始预算至少留一个 reflex action、一个 cleanup action，转换时还剩 ≥15 observations
- 同一 owner、原总期限/预算、原 immutable action proof；不能增新 owner/reset deadline
- 一次 bounded combat_entity，approach=false、shield=true；50–5000 ms，min_health 14–20
- 一次 native action 内可以有多 tick 攻击或安全撤退；不是“一次挥剑”保证
- environmental hazard、成功普通动作、unknown、取消、超期、错误 proof 不触发防御
- 普通任务始终 interrupted，不因防御成功变 succeeded，也不自动续走

T46 只证明第二分支中的一个受控核心样例。它未实证伤害分支、实际盾牌挡伤、健康观察恢复、低血撤退或 T45 拒绝诊断。

## 7. 关闭与自检边界

结束或精确取消当前已知任务并确认 cleanup 后，先正常关闭 façade，再停 Watchdog、Resident，最后按既有授权普通保存/退出流程收尾。EOF/SIGTERM 请求有界 exact-owner stop；没有确认的关闭继续保留 unknown。不能把 kill、清 journal、自动 restart 作为成功证明；toolbox-bound server 不能用 legacy minecraft_client_close 绕过链。

在本交付包的新解压目录根部执行：

```sh
sha256sum -c SHA256SUMS.txt
python3 -B tools/check_delivery_health.py --bundle .
```

该交付自检检查完整路径集、字节与 SHA-256、清单中的文件模式，以及解释器平台条件；10 个 shell/gradlew 文件在包装时规范为 0755，其余为 0644。它不启动 Minecraft、不核实实际 Java/NeoForge instance 或 live binding。不要把 integrity PASS 写成“已安装可玩”。

下面是从 source/ 根目录运行的源码自检；第一项在交付中已做过，Node 全套可按需另行运行，此次交付没有重复：

```sh
python3 -B test-tools/check_toolbox_call_examples.py
cd client-mod/mcp
npm run test:toolbox
```

其中 owner-chain native endpoint 是合成的；不是普通世界测试。每次新打包/重编译仍需独立 source/JAR 绑定，不能沿用旧成果的实机声明。

## 8. 本稿的源码依据

API contract 来自当前 runtime 的 toolbox-bridge.mjs、contracts.py、runtime_adapter.py、defend_once.py、terminal_defense.py 和 schema。具体 SHA-256 见 [证据索引](../evidence/CAPABILITY-EVIDENCE.json) 的 api_source_evidence。

旧 docs/DEFEND-ONCE.md 与部分 QUICKSTART 段落仍为 damage-only/待实机历史文字。本稿依据当前生产分支与 SPATIAL-DEFENSE、DEFENSE-STOP-PROOF、DEFENSE-CONTINUITY、ROUTE-THREAT-REFUSAL-DIAGNOSTIC 四份增量契约更正，但不改动冻结 runtime。本包已在交付层更新本指南、能力矩阵与清单，冻结 source 原文保持不变。
