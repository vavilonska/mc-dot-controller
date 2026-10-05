# Minecraft Dot Controller

[mc-dot-controller](https://github.com/vavilonska/mc-dot-controller) 保存 Minecraft 客户端控制桥与外部控制器源码。当前集成版为 `1.1.5-terrain-guard-navigation.1`：已完成编译和离线测试；小范围只读地形实机检查已通过，当前移动/转向扩展和自动战斗/导航仍未通过实机验收。

## 目录

- [`client-mod/`](client-mod/)：基于 [Campione01/MineClient-Bridge v1.1.5](https://github.com/Campione01/MineClient-Bridge/tree/60e78940f7e7fa06116cf4fbc58df346ad617531) 的 NeoForge 1.21.1 客户端模组，新增有界只读地形查询、默认关闭的受保护战斗动作、单次前进采样与导航专用水平转向接口
- [`external-controller/`](external-controller/)：独立 Python 战斗控制器；CLI 仅运行离线模拟，真实 HTTP 动作默认禁用
- [`navigation-controller/`](navigation-controller/)：独立有界地形解析、A* 路径规划与离线导航模拟；新增可选回环 HTTP/单次验收工具源码，尚未连接真实游戏验证
- [`building-controller/`](building-controller/)：离线地板/墙体蓝图、材料统计与几何支撑顺序；所有计划均不可执行
- [`client-mod/docs/terrain-api.md`](client-mod/docs/terrain-api.md)：分页、预算、未知区域与碰撞信息
- [`client-mod/docs/guarded-actions.md`](client-mod/docs/guarded-actions.md)：执行时校验、超时与取消语义、局部试验限制
- [`external-controller/docs/GUARDED_ACCEPTANCE.md`](external-controller/docs/GUARDED_ACCEPTANCE.md)：真实战斗动作启用前的验收要求
- [`client-mod/docs/guarded-movement.md`](client-mod/docs/guarded-movement.md)：单次前进采样、观察凭据、释放和剩余限制
- [`client-mod/docs/guarded-turning.md`](client-mod/docs/guarded-turning.md)：独立默认关闭的水平转向、共享观察凭据及角度边界
- [`navigation-controller/docs/ONE_SAMPLE_ADAPTER.md`](navigation-controller/docs/ONE_SAMPLE_ADAPTER.md)：单次采样/转向适配、动作后回读和静止检查
- [`navigation-controller/docs/OWNER_PROBE.md`](navigation-controller/docs/OWNER_PROBE.md)：默认只读探测、单次本地验收的前置条件与操作者命令
- [`NOTICE.md`](NOTICE.md)：上游来源、修改范围和许可证说明

## 验证状态

2026-10-05 的集成源码已通过：

- Java 21.0.12.1、Gradle 8.14.3、官方 ModDevGradle 2.0.148、NeoForge 21.1.255 下的完整模组编译、测试和打包
- 54 项 JUnit 测试，包含先前 35 项与新增 19 项转向测试，零失败、错误或跳过
- 地形核心 37,371 条断言、地形调度 13 项检查、动作保护 150 项检查及静态地形安全审查
- MCP stdio framing 测试 8/8
- 外部战斗控制器 115 项离线单元测试、Python 编译、默认禁用和模拟演示 CLI
- 导航控制器 244 项离线单元测试、Python 编译；包含先前 163 项、75 项 HTTP/探测工具模拟测试及 6 项启动延迟回归，没有使用真实凭据或游戏连接。两个离线演示均通过：原绕行模拟为 13 次模拟脉冲，新 3 格路径演示为 28 次前进采样与 6 次受限转向，清理检查成功

- 建筑规划器 83 项离线测试（含 18 项独立审查回归）、Python 编译、示例 CLI 输出校验

构建使用官方二进制依赖流程：完整编译本模组并应用访问转换，不重新编译 Minecraft 自身源码。详见[当前转向集成构建记录](client-mod/docs/turning-verification.md)。

运行验证仍有限：

- 基础版 1.1.5 已验证认证状态读取、本地生存世界玩家状态/背包读取、短按前进和释放后的静止状态，以及兼容多人服务器连接和状态读取
- 只读地形接口已通过小范围实机验证：27 格立方体、等价 7 页读取、17 格垂直世界边界；脱敏采集另通过离线解析/规划回归。最大规模扫描、动作新鲜度与导航/战斗不在已验证范围内，见[有限实机记录](client-mod/docs/terrain-live-validation.md)
- 已校验的移动/转向 JAR 已安装到独立测试配置，但该配置尚未启动；保护动作的真实 HTTP、输入与静止行为仍待单独批准的本地验收，自动战斗与导航尚未通过实机验收
- 上游完整 MCP 自测使用 Windows 路径，在 Linux 上该部分失败；这里只验证了跨平台 framing 测试
- 导航已有离线解析、路径规划与平面模拟执行；可选 HTTP 传输仅有模拟测试，仍没有实机寻路验收，建筑只有不可执行的离线蓝图/几何规划，完整自主生存尚未完成

## 构建与离线测试

需要 Java 21。首次构建需要从官方依赖源下载 Gradle 和 Minecraft/NeoForge 构建依赖。

```sh
cd client-mod
JAVA_HOME=/path/to/jdk-21 ./gradlew --no-daemon --max-workers=1 \
  -Dorg.gradle.parallel=false -Pneo_version=21.1.255 -Pbridge.noRecompile=true test build
JAVA_HOME=/path/to/jdk-21 bash scripts/terrain-core-test.sh
JAVA_HOME=/path/to/jdk-21 bash scripts/guarded-action-core-test.sh
python3 scripts/audit-terrain-source.py
node mcp/ndjson-framing-test.mjs
```

控制器使用 Python 3.10+ 标准库，无需安装第三方包：

```sh
cd external-controller
python3 -m unittest discover -v
python3 -m combat_controller
python3 -m combat_controller --demo
```

导航解析、规划与绕行模拟也完全离线：

```sh
cd navigation-controller
python3 -m unittest discover -v
python3 -m navigation_controller
python3 -m navigation_controller.sample_demo
python3 -m navigation_controller.live_probe --help
```

建筑蓝图与规划同样只读本地文件：

```sh
cd building-controller
python3 -m unittest discover -q
python3 -m building_controller --help
python3 -m building_controller plan --blueprint examples/floor-blueprint.json \
  --terrain examples/fake-world.json --terrain-key pages --state-key state
```

以上 cd 路径均相对于仓库根目录。上述控制器命令均不连接游戏。离线测试通过不代表真实游戏安全。

## 战斗动作的限制

Java 战斗动作保护默认关闭。Python 战斗 HTTP 适配器也默认禁止动作；只有操作者明确设置 enabled 与 acceptance_verified，并通过能力检查后，API 才允许调用新的 guarded-action 路由。这些配置是操作者的声明，代码不会自动证明验收已经完成。旧 key/look/mouse/release-all POST 不作为降级路径。

首个允许验收的范围是单独、未开放局域网的本地生存试验世界，仅 NeoForge 和本桥接模组，平坦已知地面、一个允许类型的敌对生物、普通未附魔原版斧。排除其他玩家、宠物、受保护旁观者、多人服务器和任意其他模组。一次请求只尝试普通视角调整或攻击，不证明命中、伤害或击杀；不提供移动或持续按键。

超时不能撤回已经开始的同步动作。任何连接结果不明、过期状态或上下文变化都应停止，不自动重试或回退到旧输入接口。必须先完成文档中的实机验收，再单独批准有限的本地控制器试验；发布源码不代表批准安装或游戏动作。

## 导航当前边界

导航规划只使用当前观测范围内、已加载且已知安全的地面和净空。未知/未加载区域、流体、危险方块及截断信息均不可作为通路；对角移动检查两侧拐角，一格下降仅可规划，暂不执行。A* 的搜索、边界队列、时间和路径长度均有上限。

路线执行器默认关闭，并拒绝真实传输；独立验收工具默认只读。演示没有 Minecraft 物理模型，不能证明真实停止距离、坠落或对角移动安全。脱敏采集缺少完整状态前后对照，且不满足动作新鲜度、附近实体观测范围和居中姿态要求，因此不能用于执行导航。

客户端新移动接口也默认关闭，且与战斗开关分开。一次请求最多提供一次 0.5 强度的普通前进输入采样，并在释放其拥有的输入字段后才确认。100 ms 是请求处理入口到采样的有效期限，不是持键时长、行进时间或制动保证。清除输入不会消除 Minecraft 惯性；游戏线程停滞时，清理和确认可能一直等待。

导航专用水平转向已在源码实现，开关独立且默认关闭；一次至多 30°，不改变俯仰或位置，并按实际 float32 角度验证。转向和前进共享占用、一次性观察凭据与防重放预算，每次转向后必须重新读取状态。

外部适配器现在包含可选数字回环 HTTP 源码和操作者验收 CLI，默认只读，测试全部使用模拟套接字/传输。它不发现端点、不读取已有令牌文件或环境凭据、不保存令牌、不安装模组或选择世界。令牌只由操作者在隐藏终端提示中输入；不要放在命令行、聊天或仓库。

验收 CLI 的单次输入必须先完成并明确批准隔离本地验收前置条件，提供会话指纹及显式接受标志。每个 HTTP 传输实例最多准入一次 POST，即使失败或结果不明也不重试。CLI 只能选一次转向或一次半前进采样；完整路线跟随仍拒绝真实传输，不能靠标志开启。

验收工具增加可选的 --start-delay（默认 0，有限值 0–15 秒）：在隐藏令牌输入之后、任何 HTTP 和新鲜度计时之前暂停，让操作者自行把焦点交回游戏。中断暂停不会发送请求，也不会放宽验收标志或单次动作限制。

每次前进后，适配器等待两个不同游戏刻的近静止回读，再重新读取地形和状态。错误、结果不明或不安全观察会锁定停止。源码和模拟测试不能证明真实 Minecraft 惯性、制动距离、静止门槛或实际 HTTP 行为；本次没有进行真实探测或输入。

旧 duration 模拟器的 pulse_forward(100) 没有映射到该接口，不能沿用其速度/距离假设。真实安装、输入、释放、转向和静止行为仍需单独批准的可丢弃本地世界验收；不能回退到旧 key/look/release 路由。详见[单次采样适配契约](navigation-controller/docs/ONE_SAMPLE_ADAPTER.md)和[导航验收边界](navigation-controller/docs/ACCEPTANCE.md)。

## 建筑当前边界

只实现地板/墙体模板、纯色/棋盘/边框图案、预览与材料数量，目标区域必须显式指定，蓝图最多 512 格。规划会扣除已经正确的方块；冲突、未知地形、危险、实体/玩家重叠或材料不足会阻止整份放置提案。支撑顺序只证明几何相邻依赖，不证明能走到、看见或够到放置面。

所有输出明确标记 executable=false。没有放置原语、执行适配器、真实输入或自动收集/合成/破坏/替换。合成示例仅展示几何规划；脱敏真实采集会因实体覆盖、玩家重叠与空背包产生零提案。未来仍需单块放置保护、实际站位/视线/物品选择校验和单独的实机验收，见[建筑验收边界](building-controller/docs/ACCEPTANCE.md)。

## 数据与许可证

桥接服务保持本机回环和私有 bearer token 认证。令牌只应存放在私有运行配置中，不能提交到 Git。本仓库不包含游戏客户端、编译后的模组、存档、运行会话、令牌、个人账号或服务器地址；已有 Gradle wrapper 仅为构建工具。导航回归中只包含明确脱敏的地形测试夹具：身份标识被替换、水平坐标平移、时间刻重设，没有原始会话信息。

上游 MIT 与 Gradle Apache 许可证保留。独立 Python 战斗、导航与建筑组件尚未指定许可证授权，详见 [NOTICE](NOTICE.md)。
