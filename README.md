# Minecraft Dot Controller

真实 Minecraft 客户端与常驻 Python 执行链。当前主线整合了 toolbox v1、T13 观测式移动、限定采集，以及拾取和战斗候选源码。T21 已独立验证一次单目标攻击后精确取消及保存结果；原测试脚本的编码比较失败仍保留，不代表完整战斗能力验收。新增能力边界见 [采集、拾取与战斗验证说明](docs/MINING-COLLECT-COMBAT.md)。请先阅读 [当前整合与验证边界](SOURCE-CHECKPOINT.md)。本轮用途是私有单人测试；T13 已完成一次公开接口的一格平地移动，保存验证结论见上述文档，尚未完成全部实机验收；下文早期 v6 版本及其测试数字保留为历史记录，不代表当前源码全部通过。模型决定下一步，客户端逐刻执行普通动作。

本次新增 [单方块限定放置候选](capability-runtime/docs/SCOPED-PLACEMENT.md)：只接受原地放置一个普通圆石块，原生边界及跨语言离线检查已通过；T23 已独立验证一次原地圆石放置及保存结果；此前 T22 的未知结果仍保留，不代表多方块或整栋建筑执行能力。

T24 已验证一次制作任务消耗 2 块橡木木板、产出 4 根木棍及保存结果；自动收尾因报告超限保留 HOLD，随后人工正常关闭，不属于全自动流程通过。见 [制作验证与限制](docs/CRAFT-T24.md)。

保留 [方块菜单失败诊断](docs/BLOCK-MENU-DIAGNOSTICS.md)，并整合 [预期射线与消耗完成顺序修复](docs/BOUNDED-RAY-AND-CONSUME-FIXES.md)。T26 原未知结果不变；离线检查与后续限定实测的证据分别记录。

后续 T29 已验证一次开炉、1 份沙子和 1 块橡木木板烧成并取出 1 块玻璃、关菜单的完整限定链；T30 已验证一次火把与副手盾牌交换；T31 已验证喝下 1 瓶水肺药水、返还玻璃瓶并观察到效果。三次均有自动正常收尾与独立保存检查，但只适用于各自绑定的运行产物；源码整合或重新构建不自动继承实机验收。T26/T28 原未知结果及早期 HOLD 均保留。见 [T29–T31 验收与限制](docs/T29-T31-ACCEPTANCE.md)及[能力状态与待验收项](docs/CAPABILITY-STATUS.md)。


## 架构

- [`client-mod/`](client-mod/)：NeoForge 1.21.1 客户端内执行连续行走、挖掘、放置和背包槽点击，提供状态、地形、菜单与原生画面
- [`resident-controller/`](resident-controller/)：每个游玩会话由操作者启动一次的常驻进程；认证令牌只在内存中，模型通过共享文件队列提交任务和读取结果
- [`navigation-controller/`](navigation-controller/)：保留已有 A* 与地形解析；常驻控制器直接复用，没有复制一套寻路器或模拟 Minecraft 物理
- [`gameplay-helpers/`](gameplay-helpers/)：显式调用的制作、局部上下台阶路线与本地状态导出源码
- [`defense-watchdog/`](defense-watchdog/)：保留 v5.1 战斗恢复修正，加入 v6 环境恢复；它是唯一队列写入者，普通任务经 IntentClient 排队
- [`navigation-cursor/`](navigation-cursor/)：保留地面支撑锚点、路径尾段和持久游标；默认执行最长已观察安全片段，保留固定长度模式与 defense_epoch 校验

服务端不需要安装此桥接模组。使用普通客户端交互、客户端预测和服务端规则；没有协议机器人、传送或世界编辑。

## 已实现的源码

客户端动作接口包含 `follow_path`、`break_block`、`place_block`、`click_slot`、`recover_environment`，以及状态查询和按 ID 取消。连续输入由客户端每刻执行，不靠外部反复发送 100 ms 按键片段。

原有 look/key/raw-key/mouse/text/command 直接控制保留。直接操作在客户端线程上原子接管输入：取消当前任务、释放它的输入，再执行本次请求；后续直接按键组合仍可持续保持。

常驻进程提供：

- `observe`、直接控制与上述客户端动作
- `walk_to`：用已有局部 A* 生成路径；当前规划器不覆盖任意跳跃、长距离或未知区块
- `craft_planks`：按实际菜单槽把一个观察到的原木转成四块木板，并检查背包变化
- `pillar`：1–8 次普通跳跃与脚下放置，逐步读取结果
- `aim_lock` / `aim_unlock`：外部视角锁定，保持原生画面与直接接管
- `combat_start` / `combat_stop`：原生近战；射程改为眼部到实际命中点距离，接近通道检查覆盖完整扫过区域。一次旧短脚本剑盾遭遇成功，但后来的 v5 常驻遭遇失败；v5.1 修正与 v6 不能据旧结果宣称实战通过
- `scan_start` / `scan_status` / `scan_cancel`：查询客户端已经加载的方块、群系、聚集区域和地表邻水候选；未知区块仍是未知，不强制加载
- `cancel`、`resume`、`shutdown`；不会自动重连、复活、退出服务器或重放结果不明的 POST

环境恢复在水、岩浆或细雪中由原生动作持续保持普通跳跃，外部只提供已观察的撤离路线；没有路线时不会凭空选择方向。此动作默认 `timeout_ms:0`，直到观察到恢复目标或明确停止，不因模型处理消息而松开输入。死亡、菜单、世界变化与直接接管仍会中断。

制作结果要求两个后续递增游戏刻中背包、合成格和光标均符合预期；放块要求连续五刻观察到目标方块，并观察到材料消耗或创造模式。挖掉方块不等于已经拾取掉落物。这些仍是客户端证据，不是服务端最终确认；直接控制返回只证明已分发输入。挖掘现含保留真实 pick/目标/距离检查的可见面回退。完整契约见[客户端动作](client-mod/docs/client-actions.md)、[已加载世界扫描](client-mod/docs/loaded-world-scans.md)和[常驻控制器指南](resident-controller/README.md)。

## 使用方式

操作者在实际运行 Java 客户端的桌面终端中启动一次常驻进程，明确提供本次验证过的回环 URL 和共享队列目录。令牌通过隐藏提示或操作者明确选择的既有文件提供，不放进模型命令、队列或仓库。

模型侧在 resident-controller/ 中提交请求，不需要令牌或访问桌面的回环端口：

```sh
python3 -m resident_controller --queue /path/to/shared/mailbox submit \
  --json '{"op":"observe","terrain":true,"frame":true}' --wait 10
```

共享目录必须实际由两侧共享；共享源文件不代表共享进程、回环网络或临时目录。启动、任务示例和恢复规则见[指南](resident-controller/README.md)。启用独立 watchdog 后，它应是唯一的 resident 队列写入者；普通任务须走 [IntentClient](defense-watchdog/README.md)，停止并确认输入释放后才恢复直接队列控制。

## 主线与受控并行规划组合

本树另含明确opt-in的受控并行一步：共享快照、只读planner、独立fresh计划和唯一owner，保留原主线环境/稳定结果/菜单合同。客户端能力、Resident、Watchdog和host接口必须配套；旧JAR不得接新受控producer。入口、限制与独立平台门见[联合接口说明](COORDINATION-INTEGRATION.md)。本组合尚未部署或实机验收。

## 历史验证状态（v6 / terrain-refresh.1 截点）

- Python 地形读取增量 `terrain-refresh.1`：保留 v6 全部功能，区分完整性错误与合法陈旧数据；仅后者及明确游标过期/地形限流允许一次全新扫描，失败清空旧缓存。三个 Python 运行时文件变更，不修改 Java/mod。详见[边界与离线验证](resident-controller/docs/TERRAIN_RECOVERY.md)
- 该增量的完整公开 Python 布局：828 项运行，827 项通过，1 项历史源码对照跳过；包含 24 项新增刷新回归。编译与 CLI 检查通过。这是本地离线证据，不代表 GitHub CI 或真实故障恢复已经验收
- 以下 Java 构建与分组 Python 数量保留为 v6 基线记录；本次未重新构建 Java
- 该截点 Java 21 / Minecraft 1.21.1 / NeoForge 21.1.255 完整构建：118 项测试通过
- 最终公开 Python 布局：防御 129 项通过、1 项历史源码对照跳过；寻路 67、制作及便携包装 37、resident 118 项通过
- 本轮仅做源码与离线检查，没有借发布操作游戏；水中持续浮起、细雪/火焰恢复、长片段行走、稳定制作/放块尚待普通游玩中的实机验收
- 旧版本有限实机证据包括一次 4,864 格/41 煤扫描、多段短步导航、七类制作记录，以及一次短脚本剑盾遭遇中 4 次攻击分发后目标死亡、玩家保持 20 血
- 后来的 v5 常驻僵尸遭遇失败：接近受阻、0 次攻击，玩家死亡。v5.1 针对旧终态反复取消作了修正；当前 v6 保留它，但不能据离线测试宣称已解决实战生存问题

[当前源码与构建记录](client-mod/docs/continuity-verification.md)区分最终候选产物和带许可证的公开源码重建。正确版本是 `1.1.6-continuity.1`；早期误写的 `1.1.5-environment-candidate.1` 已废弃，不表示回退到旧功能。原始运行结果、真实坐标和玩家身份不在仓库中。

## 保留的旧工作

原来的战斗原型、建筑蓝图、地形查询、受保护单步实验及其文档都保留，历史不覆盖。旧的单人世界、满血和半步限制只属于对应实验接口，不是新的 client-actions 执行策略。

- [`external-controller/`](external-controller/)：旧战斗原型
- [`building-controller/`](building-controller/)：地板/墙体蓝图、材料统计与几何支撑顺序；规划结果本身不等于已经施工
- [`navigation-controller/`](navigation-controller/)：复用的寻路/地形算法及旧探测实验

认证和回环限制保留。仓库只放源码、测试与合成/脱敏夹具，不包含令牌、私人队列、运行报告、截图、存档、安装配置或新编译的模组二进制。来源与许可证见 [NOTICE](NOTICE.md)。

## Selective P2 integration

The existing three-zombie retreat contract is selectively integrated on the c41 mainline with both encounter gates default-off. See [P2-INTEGRATION.md](P2-INTEGRATION.md) for exact scope, preserved root behavior, harness dependencies and outstanding live acceptance. Rebuilt P2 artifacts are not the previously game-tested c41 JAR.

## Reusable capability runtime (offline development increment)

[`capability-runtime/`](capability-runtime/README.md) adds opt-in guarded primitives, 33 concrete reusable skills, durable execution/scheduling, observed resource/production/build/End workflows and explicit limitations. Current source is an offline-tested development increment; prior live evidence is not transferred to the new JAR. New actions require focused private singleplayer context and never retry unknown outcomes. See its README and delivery evidence for the exact tested scope.
