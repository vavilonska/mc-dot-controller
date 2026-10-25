# MDC — 2026-10-25 源码保存（C8 + reactive defense r1.4）

本次保存的是实际单机运行的完整源码组合，而非仅最后一个补丁：Recovery C8 基线、普通模式单调时钟/准入边界，以及原生烈焰人护送/传送门交接、世界备份、末影人棚下交战、尸壳兼容、反应式防御和 r1.4 输入释放/暂停闭环。另保留相应 Python 控制器和可复用 sidecar。

**源码身份：**部署 JAR SHA-256 为 `29141caad50641cdcfc9826a138ff30b2cfd7c555e24ce726fd03abbe366b68e`，大小 1,617,670 bytes。JAR 内原有 C8 mod metadata 未改版；`r1.4` 是组合补丁身份，不把旧 metadata 当作最新版本证明。

## 本次验证

- 已核对真实安装 JAR、冻结源码和全部增量包来源；269 个生产 Java 源文件完整编译，输出 632 个 class，**632 个全部与安装 JAR 逐字节一致**，无缺项/多项。8 个非 class 资源与 C8 一致。
- 单独 r1.4 冻结构建还原出相同完整 JAR 哈希；1,117 项策略/dispatcher/registry/请求准备器断言或场景、34 项源码 hook 检查通过。
- 这些是离线编译、源码与字节一致性、模拟上下文/实际生产谓词测试。**不是完整 Gradle/NeoForge loader 测试，也不等于新实机验收。**最初仅用 r1.4 局部编译 classpath 编译全树时出现 22 个既有 access-transformer 可见性错误；应用原项目全部、未改变的 AT 规则后全量编译通过。临时可见性 overlay 未进入模组。
- Python/Node 分组件结果、原失败与排除项见 [VALIDATION.json](VALIDATION.json)。不存在“全仓测试全绿”声明。

## 相比上次 GitHub 保存新增的范围

上次 main 是 `39799603de3372ec30a917a09382684d3593566c`（Recovery 2.5）。本次保留其全部远端文件/历史文档，不用较旧本地 README 覆盖已公开的限定结论。

- Recovery 2.7–C8 的显式新生命/空闲暂停确认、普通原木几何与 NeoForge 属性兼容、限定目标与 typed portal、伤害诊断、短输入、交互 v1/v2/v3、导航 v4/v5、维护 v5、生存 v6/4096 历史容量源码及测试。
- 普通模式 schema-2 单调观察时钟与准入/HTTP 分发边界。
- 原生护送、棚下末影人、尸壳、固定写者集备份、反应式接管、幽灵/复活上下文、直接输入释放与精确暂停意图修复。旧 UNKNOWN 不重写、不自动重试，中断任务不自动恢复。
- [current-sidecars](../../gameplay-helpers/current-sidecars/) 保存 r9 会话工具、普通/房间往返和收尾拾取、旅行/用水监督、历史地形记忆。它们不是全新统一的一键产品接口；一些历史脚本仍有固定单机身份和本地运行目录，见该目录说明。

本次游戏过程是 AI 逐步决策与 MDC 普通操作的组合；不据此声称“自主屠龙模块”通过通用验收。仓库不包含该次战役路线/坐标计划、世界、私有账本、原始日志、访问令牌、第三方游戏依赖或模组 JAR。源代码中的原有上下文安全约束没有为了公开方便而放宽。

## 构建与检查

- Java 21；Minecraft 1.21.1 / NeoForge 21.1.255 固定开发依赖。常规 Gradle 入口仍在 `client-mod/`；本次未重新执行完整联网 Gradle/loader 构建。
- [完整映射源码核验器](../../client-mod/validation/current-native/)接受操作者已有、哈希固定的外部依赖，不下载或分发 Minecraft/NeoForge 二进制，也不启动游戏。
- [r1.4 精确增量还原](../../client-mod/validation/reactive-r1_4/)包含原冻结构建器与 pin；须由操作者提供其所列前序包/依赖，不能把纯源码仓库误当成独立离线二进制发行包。
- `python3 capability-runtime/run_checks.py` 保留历史聚合入口；它不覆盖所有新增 controller/sidecar。新增 sidecar 需逐目录独立运行测试，避免不同版本的同名 Python 模块相互污染。

## 公开整理与验证限制

未修改产品生产源码来迎合测试。两个 r9 测试文件作了可审阅的测试专用修正：可附加属性的假 Session，及既有 5 秒 HTTP response wait / 0.5 秒 scheduling quantum 的分别断言；旧测试 2 failures + 1 error 被记录，修正后 90/90 通过。继承 native 测试选择最新尸壳版本的 BlazeEscortChecks；Enderman 源码 hook 比较仅消除空白差异，生产条件不变。

私有 TEST 世界 block dump、战役计划及 legacy94/101/338 历史账本不发布；相应历史测试保留源码并说明缺失输入，冷世界几何测试显式跳过。少量 fixture provenance 的绝对私有路径替换为排除说明；房间 sidecar 的 CORE-PIN 只保留必要文件哈希，去掉无关私有 Library ID。其余已复制生产实现保持原字节。

历史根目录 `PUBLICATION-MANIFEST.json`、`SOURCE_SHA256SUMS.txt` 及早期文档继续描述各自截点。**本次完整公开树使用 [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json)**；原生来源在 [NATIVE-SOURCE-PROVENANCE.json](NATIVE-SOURCE-PROVENANCE.json)，编译/还原 receipt 在本目录。旧成功/失败/UNKNOWN 的版本限定不被本次源码保存覆盖。
