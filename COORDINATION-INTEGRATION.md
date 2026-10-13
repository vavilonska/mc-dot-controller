# 主线与受控并行一步

本树在主线功能上整合受控并行规划与唯一输入owner。普通启动路径保持原行为；新路径仅在既有Watchdog显式接入`coordination_factory`时启用。`ControlledStepRuntime`接受限定Grant和2–3个只读PlannerWorker，同一快照产生Advice，独立新扫描后生成新计划，最多执行一个动作。普通Coordinator仍默认FakeExecutor。

## 版本配套

Resident、Watchdog、mdcoord和客户端JAR必须来自同一已验证源码集合。旧客户端会忽略陌生`coordination_step`字段，不能因此推定支持安全模式。新producer同时要求Resident协议、native `coordination_step_protocol:1`、当前state的同源采样证据和原始身份；缺任何一项均不得发动作。

`coordination_step`是`follow_path`的严格可选模式，不新增action种类或MCP工具。原九种native动作及八个MCP工具保留，MCP有限请求schema不会转写或接受此私有owner元数据。`recover_environment`的timeout 0仍沿用主线合同。

## 同源样本与有限执行

仅单人且未向LAN公开的环境；一个相邻居中同高基点、50–1000ms、无跳跃/冲刺/蹲下/换槽。支撑仅stone/cobblestone/dirt/grass_block且满足完整物理判据，脚头air；独立扫描必须具备精确45格，8格AABB内自身以外所有已加载实体均拒绝。native接收和每callback检查位置、实体、地形、伤害、上下文和控制权。

`source_tick`与state的game_time共享读取；`source_nano`为原JVM有符号长整数字符串，不与Python时钟比较，不从读取时刻重造。入场期限仍为5ticks和800ms。已有动作总deadline、managed cleanup和release证据保持；未知不重试。

state Sample headers和Python metadata只是诊断。完成观测的三个unknown标记必须缺省或明确False；该capture的typed policy必须双false，另一次clear session不能使坏capture有效。新的明确clear请求可重新发布，历史action不作为永久全局锁。

## 主线控制权保护

新的capture/plan/dispatch尊重当前release、handoff、环境、ranged、菜单恢复、STOP和其他owner。已持有动作遇冲突时只保留原ID只读核对/最多一次精确取消，不启动另一个自动控制路径。取消attempt在POST前记下并由Resident异常路径共享；后续未知不能再次cancel。

精确status/cancel采用纯身份检查，失败不能调用普通任务接管或清掉后到owner。当前原ID回执继续使用主线release reason优先判据；no-effect只说明这个proposal没有动作，不是全局释放证明。普通显式direct、ground-anchor/adaptive、environment、terrain page-tick反转硬拒绝、稳定采放/制作及菜单恢复保持原合同。

## Host与恢复

实际模型host还依赖单独固定的`persistent-host-r2`接口，负责原run/role/native-task/claim截止身份；mdcoord本身不会启动或假装调用对话中的原生agent。已有历史case launcher绑定一次性授权和已消耗案例，不能作为新案例默认入口或清标记重用。新实例由明确授权的操作者在同版源码/JAR和新验证上下文下建立；本源码导入不启动游戏、host或队列。

源码附带的host/owner测试使用显式合成native I/O和模型回答，不能当作实机或真实模型运行。真实Windows/PowerShell和7个NeoForge生命周期门仍独立验收。保留的历史单树实机结果不能外推本联合版本。

## 验证入口

- Python：逐组件unittest；新增组件`multiagent-coordination/tests`保留原source测试并加当前policy、receipt及竞态反例。
- Java：既有默认离线Gradle test/build；不要把默认跳过的真实loader门计作通过。
- fresh Java→Python：`client-mod/build/validation/coordination-step-wire.json`与`grass-support-wire.json`来自当前JUnit产物；后者通过`MDC_GRASS_SUPPORT_WIRE`交Python测试。
- fresh Java→Node：`client-mod/validation/mcp-native-contract/run.sh`接受项目、既有Gson、JDK21和本次真实build JAR四个参数，只编译原emitter，不用Guard替身。
- Node：直接执行mcp/package.json所列本地测试文件。Linux平台fixture保留Windows身份约束，但不等于Windows真实平台通过。

本组只移state同源诊断和协调POST原metadata留证；一般POST/boat时序包装、P2三僵尸、gate-off探针和预热等其它候选增量不在此次迁入范围。
