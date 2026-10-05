# Minecraft Dot Controller

[mc-dot-controller](https://github.com/vavilonska/mc-dot-controller) 保存 Minecraft 客户端控制桥与外部控制器源码。当前集成版为 `1.1.5-terrain-guard-movement.1`：已完成编译和离线测试；小范围只读地形实机检查已通过，当前移动扩展和自动战斗/导航仍未通过实机验收。

## 目录

- [`client-mod/`](client-mod/)：基于 [Campione01/MineClient-Bridge v1.1.5](https://github.com/Campione01/MineClient-Bridge/tree/60e78940f7e7fa06116cf4fbc58df346ad617531) 的 NeoForge 1.21.1 客户端模组，新增有界只读地形查询、默认关闭的受保护战斗动作与单次前进采样接口
- [`external-controller/`](external-controller/)：独立 Python 战斗控制器；CLI 仅运行离线模拟，真实 HTTP 动作默认禁用
- [`navigation-controller/`](navigation-controller/)：独立有界地形解析、A* 路径规划与离线导航模拟；没有真实移动传输实现
- [`client-mod/docs/terrain-api.md`](client-mod/docs/terrain-api.md)：分页、预算、未知区域与碰撞信息
- [`client-mod/docs/guarded-actions.md`](client-mod/docs/guarded-actions.md)：执行时校验、超时与取消语义、局部试验限制
- [`external-controller/docs/GUARDED_ACCEPTANCE.md`](external-controller/docs/GUARDED_ACCEPTANCE.md)：真实战斗动作启用前的验收要求
- [`client-mod/docs/guarded-movement.md`](client-mod/docs/guarded-movement.md)：单次前进采样、观察凭据、释放和剩余限制
- [`NOTICE.md`](NOTICE.md)：上游来源、修改范围和许可证说明

## 验证状态

2026-10-05 的集成源码已通过：

- Java 21.0.12.1、Gradle 8.14.3、官方 ModDevGradle 2.0.148、NeoForge 21.1.255 下的完整模组编译、测试和打包
- 35 项 JUnit 测试，包含 21 项新增移动测试，零失败、错误或跳过
- 地形核心 37,371 条断言、地形调度 13 项检查、动作保护 150 项检查及静态地形安全审查
- MCP stdio framing 测试 8/8
- 外部战斗控制器 115 项离线单元测试、Python 编译、默认禁用和模拟演示 CLI
- 导航控制器 104 项离线单元测试、Python 编译；包含 11 项脱敏真实地形采集回归。离线障碍绕行模拟以 13 次不超过 100 ms 的模拟脉冲到达并释放输入

构建使用官方二进制依赖流程：完整编译本模组并应用访问转换，不重新编译 Minecraft 自身源码。详见[当前移动扩展构建记录](client-mod/docs/movement-verification.md)。

运行验证仍有限：

- 基础版 1.1.5 已验证认证状态读取、本地生存世界玩家状态/背包读取、短按前进和释放后的静止状态，以及兼容多人服务器连接和状态读取
- 只读地形接口已通过小范围实机验证：27 格立方体、等价 7 页读取、17 格垂直世界边界；脱敏采集另通过离线解析/规划回归。最大规模扫描、动作新鲜度与导航/战斗不在已验证范围内，见[有限实机记录](client-mod/docs/terrain-live-validation.md)
- 当前移动扩展没有安装或执行真实输入；自动战斗与导航仍未通过实机验收
- 上游完整 MCP 自测使用 Windows 路径，在 Linux 上该部分失败；这里只验证了跨平台 framing 测试
- 导航已有离线解析、路径规划与平面模拟执行；没有真实移动传输或实机寻路验收，建造和完整自主生存尚未完成

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
```

以上 cd 路径均相对于仓库根目录。上述控制器命令均不连接游戏。离线测试通过不代表真实游戏安全。

## 真实动作的限制

Java 战斗动作保护默认关闭。Python 战斗 HTTP 适配器也默认禁止动作；只有操作者明确设置 enabled 与 acceptance_verified，并通过能力检查后，API 才允许调用新的 guarded-action 路由。这些配置是操作者的声明，代码不会自动证明验收已经完成。旧 key/look/mouse/release-all POST 不作为降级路径。

首个允许验收的范围是单独、未开放局域网的本地生存试验世界，仅 NeoForge 和本桥接模组，平坦已知地面、一个允许类型的敌对生物、普通未附魔原版斧。排除其他玩家、宠物、受保护旁观者、多人服务器和任意其他模组。一次请求只尝试普通视角调整或攻击，不证明命中、伤害或击杀；不提供移动或持续按键。

超时不能撤回已经开始的同步动作。任何连接结果不明、过期状态或上下文变化都应停止，不自动重试或回退到旧输入接口。必须先完成文档中的实机验收，再单独批准有限的本地控制器试验；发布源码不代表批准安装或游戏动作。

## 导航当前边界

导航规划只使用当前观测范围内、已加载且已知安全的地面和净空。未知/未加载区域、流体、危险方块及截断信息均不可作为通路；对角移动检查两侧拐角，一格下降仅可规划，暂不执行。A* 的搜索、边界队列、时间和路径长度均有上限。

执行器默认关闭，只接受显式的模拟适配器。演示没有 Minecraft 物理模型，不能证明真实停止距离、坠落或对角移动安全。脱敏采集缺少完整状态前后对照，且不满足动作新鲜度、附近实体观测范围和居中姿态要求，因此不能用于执行导航。

客户端新移动接口也默认关闭，且与战斗开关分开。一次请求最多提供一次 0.5 强度的普通前进输入采样，并在释放其拥有的输入字段后才确认。100 ms 是请求处理入口到采样的有效期限，不是持键时长、行进时间或制动保证。清除输入不会消除 Minecraft 惯性；游戏线程停滞时，清理和确认可能一直等待。

导航专用转向和真实外部移动适配器尚未实现。模拟器的 pulse_forward(100) 不能直接映射为该单次采样接口，也不能沿用模拟器的速度/距离假设。下一步需要受保护的玩家朝向对齐、单次采样语义适配与静止/位移回读，再进行单独批准的可丢弃本地世界验收。不能回退到旧 key/look/release 路由。详见[移动接口契约](client-mod/docs/guarded-movement.md)和[导航验收边界](navigation-controller/docs/ACCEPTANCE.md)。

## 数据与许可证

桥接服务保持本机回环和私有 bearer token 认证。令牌只应存放在私有运行配置中，不能提交到 Git。本仓库不包含游戏客户端、编译后的模组、存档、运行会话、令牌、个人账号或服务器地址；已有 Gradle wrapper 仅为构建工具。导航回归中只包含明确脱敏的地形测试夹具：身份标识被替换、水平坐标平移、时间刻重设，没有原始会话信息。

上游 MIT 与 Gradle Apache 许可证保留。独立 Python 战斗与导航控制器尚未指定许可证授权，详见 [NOTICE](NOTICE.md)。
