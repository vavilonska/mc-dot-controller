# Minecraft Dot Controller

真实 Minecraft 客户端 + 一个常驻 Python 控制器。当前主线是 `1.1.6-loaded-scan.1`，用于已获准加入的兼容朋友服务器；模型决定下一步，客户端执行每个游戏刻的普通动作。

## 架构

- [`client-mod/`](client-mod/)：NeoForge 1.21.1 客户端内执行连续行走、挖掘、放置和背包槽点击，提供状态、地形、菜单与原生画面
- [`resident-controller/`](resident-controller/)：每个游玩会话由操作者启动一次的常驻进程；认证令牌只在内存中，模型通过共享文件队列提交任务和读取结果
- [`navigation-controller/`](navigation-controller/)：保留已有 A* 与地形解析；常驻控制器直接复用，没有复制一套寻路器或模拟 Minecraft 物理
- [`gameplay-helpers/`](gameplay-helpers/)：显式调用的制作、局部上下台阶路线与本地状态导出源码

服务端不需要安装此桥接模组。使用普通客户端交互、客户端预测和服务端规则；没有协议机器人、传送或世界编辑。

## 已实现的源码

客户端动作接口包含 `follow_path`、`break_block`、`place_block`、`click_slot`，以及状态查询和按 ID 取消。连续输入由客户端每刻执行，不靠外部反复发送 100 ms 按键片段。

原有 look/key/raw-key/mouse/text/command 直接控制保留。直接操作在客户端线程上原子接管输入：取消当前任务、释放它的输入，再执行本次请求；后续直接按键组合仍可持续保持。

常驻进程提供：

- `observe`、直接控制与上述客户端动作
- `walk_to`：用已有局部 A* 生成路径；当前规划器不覆盖任意跳跃、长距离或未知区块
- `craft_planks`：按实际菜单槽把一个观察到的原木转成四块木板，并检查背包变化
- `pillar`：1–8 次普通跳跃与脚下放置，逐步读取结果
- `aim_lock` / `aim_unlock`：外部视角锁定，保持原生画面与直接接管
- `combat_start` / `combat_stop`：原生近战控制源码，尚未实战验收
- `scan_start` / `scan_status` / `scan_cancel`：查询客户端已经加载的方块、群系、聚集区域和地表邻水候选；未知区块仍是未知，不强制加载
- `cancel`、`resume`、`shutdown`；不会自动重连、复活、退出服务器或重放结果不明的 POST

挖掉方块不等于已经拾取掉落物。动作成功表示客户端观察到结果，不是服务端最终确认；直接控制返回只证明已分发输入。挖掘现含保留真实 pick/目标/距离检查的可见面回退。完整契约见[客户端动作](client-mod/docs/client-actions.md)、[已加载世界扫描](client-mod/docs/loaded-world-scans.md)和[常驻控制器指南](resident-controller/README.md)。

## 使用方式

操作者在实际运行 Java 客户端的桌面终端中启动一次常驻进程，明确提供本次验证过的回环 URL 和共享队列目录。令牌通过隐藏提示或操作者明确选择的既有文件提供，不放进模型命令、队列或仓库。

模型侧在 resident-controller/ 中提交请求，不需要令牌或访问桌面的回环端口：

```sh
python3 -m resident_controller --queue /path/to/shared/mailbox submit \
  --json '{"op":"observe","terrain":true,"frame":true}' --wait 10
```

共享目录必须实际由两侧共享；共享源文件不代表共享进程、回环网络或临时目录。启动、任务示例和恢复规则见[指南](resident-controller/README.md)。

## 验证状态

- 当前构建：Minecraft 1.21.1 / NeoForge 21.1.255、Java 21，114 项 Java 测试通过；公开默认版本已与该构建对齐
- 常驻控制器：109 项离线协议/状态机/缓存测试通过
- 制作 helper：23 项离线检查；其余可移植包装检查见对应文档
- 本轮已完成一次小范围实机扫描：4,864 格、41 块煤，结果报告 79 ms、3 个客户端 tick。不是最大规模性能保证，也不代表所有群系/水边模式均已验收
- 实际制作成功的范围：工作台、木镐、石镐、炉子、木棍、石斧、火把。铁工具、铁甲、盾等其他形状仍只有离线检查
- 战斗没有实战验收；单位测试、输入分发和客户端观察不能冒充命中、击杀或服务端确认

公开验证摘要见[当前版本记录](client-mod/docs/loaded-scan-verification.md)。本仓库更新不会操作游戏，也不包含原始现场结果、真实方块位置或玩家身份。

## 保留的旧工作

原来的战斗原型、建筑蓝图、地形查询、受保护单步实验及其文档都保留，历史不覆盖。旧的单人世界、满血和半步限制只属于对应实验接口，不是新的 client-actions 执行策略。

- [`external-controller/`](external-controller/)：旧战斗原型
- [`building-controller/`](building-controller/)：地板/墙体蓝图、材料统计与几何支撑顺序；规划结果本身不等于已经施工
- [`navigation-controller/`](navigation-controller/)：复用的寻路/地形算法及旧探测实验

认证和回环限制保留。仓库只放源码、测试与合成/脱敏夹具，不包含令牌、私人队列、运行报告、截图、存档、安装配置或新编译的模组二进制。来源与许可证见 [NOTICE](NOTICE.md)。
