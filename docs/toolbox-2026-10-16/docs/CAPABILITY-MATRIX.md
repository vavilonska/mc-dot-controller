> 本页根据已交付 ZIP 的使用说明整理。`source/`、`mod/`、`tools/` 和包级校验文件均指该 ZIP 布局；Git 仓库只发布源码与文档。请先读[交付范围](../README.md)。

# MDC 工具箱：能力与证据边界（2026-10-16）

交付定位：已有真实普通单机工作流和当前版本受控防御样例的有界工具箱。不是全场景 Minecraft 自动化验收。

当前 JAR：`59523ef1a2e6c9c1a738c13958d60c506ff526033ae21af6023140bd6f0b2694`；版本 `1.1.6-toolbox-v1-route-threat-diagnostic-offline-test.1`；配套完整 runtime 为 1,034 文件。JAR 与 Python runtime 必须成对。

## 当前版本与历史版本不能合并成一次全通过

- T42 是旧 JAR 的十一 job 工作坊实机通过，属于带人工关闭及保存差异限定的验收。
- T46 是当前 JAR 的 stop-only → 同 owner defend_once 核心实机通过；路线本身保持 interrupted。
- 最新离线编译/变更专项检查和旧版本实机证据可以共同说明工程进展，但不能把旧 T42 重新标成当前 JAR 的实机通过。
- 全 49 catalog 条目没有全场景实机验收；20 项 backend 候选也不等于每种参数/物品/环境均通过。

## 能力矩阵

| ID / 能力 | 已有证据 | 原始适用版本 | 未覆盖 / 限定 | 证据索引 |
|---|---|---|---|---|
| C01 select_hotbar | T07 单次选择槽位 8、已确认 cleanup，普通关闭 34.349 秒，保存后选择槽位一致。 | T07 | 最新 JAR 未重测此独立 public capability；其他槽位/物品组合不外推。 | E017 |
| C02 ensure_hotbar | 属于当前 20 项候选 allowlist；本次有限交付证据整理未建立它的独立实机验收。 | 当前源码/离线；无独立实机 JAR 归属 | 不可由 select_hotbar 或容器移动成功直接推定自动整备各变体均通过。 | E025, E035 |
| C03 container_move | T42 stow-output 在 11-job 工作流内成功；输出木棍从当前观察槽位收纳后继续交付。 | T42 | 新 JAR 未重跑 T42；各类菜单、组件、满包和并发变化尚无全覆盖。 | E054, E072 |
| C04 container_split / container_merge | 当前 allowlist 支持，存在离线有限菜单模拟证据；未在本索引建立独立普通世界通过。 | 当前源码/离线；无独立实机 JAR 归属 | 各数量、组件、溢出、光标竞态及真实容器闭环未普遍验收。 | E025, E073 |
| C05 equip | T30 一次火把/副手盾交换，物品与组件守恒，自动关闭通过。 | T30 | 盔甲目的槽、其他组件/替换规则、重复配装与最新 JAR 未覆盖。 | E074, E075, E076 |
| C06 consume | T31 一瓶水肺药水，返还瓶子并观测 amplifier 0 效果，自动关闭通过。 | T31 | 食物、牛奶、其他药水、打断/堆栈及精确到期衰减不外推。 | E077, E075, E078 |
| C07 interact / close_menu | T29 熔炉开/关成功；T42 两次木桶开/关成功且最终菜单关闭。 | T29, T42 | 其他交互方块/面/距离、非空手与打断路径，以及新 JAR 同流程未覆盖。 | E079, E075, E054 |
| C08 container_withdraw | T32 三 public jobs、四 native mutations 从一个木桶取出一个圆石；T42 工作流取出两块橡木木板。 | T32, T42 | T32 自动 HOLD/人工末窗关闭保留；其他容器/数量/满包及新 JAR 未泛化。 | E080, E081, E054 |
| C09 container_deposit | T42 将四根木棍存入木桶，保存证据显示 slot 0 四根、其余槽为空。 | T42 | 仅该精确旧 JAR 的工作流；不能视为所有容器存储变体或最新 JAR 再验收。 | E054, E082 |
| C10 craft | T24 与 T42 均有两块橡木木板→四根木棍；T42 将产物继续交付。 | T24, T42 | T24 自动 HOLD/人工关闭不改写；其他配方、工作站、批量/原料获取与最新 JAR 未全覆盖。 | E083, E084, E054 |
| C11 smelt | T29 一沙子+一橡木木板燃料得到并收集一玻璃；三 job 链含开/关炉，自动关闭通过。 | T29 | 高炉/烟熏炉、其他燃料/配方、多输出、残留恢复、自动取料与新 JAR 未验收。 | E079, E075, E085 |
| C12 navigate_local | T13 一格基数方向平地移动，native tick 13；健康/库存守恒，普通关闭 51.383 秒、保存终点通过。 | T13 | 障碍、长距、未知/未加载地形、动态危险和全局寻路不外推。 | E086, E087 |
| C13 navigate_step_down | T34 一格基数方向下落，21 tick path_reached，水平误差 0.194367≤0.23；保存终点与普通关闭通过。 | T34 | 原 bbox/roof 比较失败保留；独立 geometry qualification 不证明下段更严格 source centering、连续阶梯或新 JAR。 | E088, E089, E090 |
| C14 navigate_route_local | T42 三个路线 job 共 24 段，合计十一 job 工作坊完成。 | T42 | T42 原自动 HOLD、人工关闭、strict saved aggregate=false 保留；最新 T46 路线在移动前中断，不能当最新 JAR 的完整路线成功。 | E054, E044 |
| C15 mine_local | T15/T16 功能/保存证据保留；T16 目标为空气且库存增一普通橡木木板。 | T15, T16 | T15 超关闭界限，T16 自动 HOLD；不证明掉落因果。最新 JAR、新目标/工具/全自动闭环未验收。 | E091, E092, E093 |
| C16 collect_local | T17 一普通橡木木板独立拾取，public effect known/cleanup confirmed，自动关闭 57.553 秒。 | T17 | 原 success-only harness 失败与原生 cancelled:scoped_collect_target_absent 保留；无独立 after-public observation、掉落因果或最新 JAR 泛化。 | E035, E094, E095 |
| C17 place_local | T23 静止放置一个普通圆石，材料减一、release/cleanup 与保存通过。 | T23 | T22 unknown 不改写；其他块状态、移动放置、多格蓝图与最新 JAR 未验证。 | E096, E097, E035 |
| C18 engage | T21 单目标攻击后精确取消，保存目标/玩家检查独立接受。 | T21 | 原 encoding-comparison harness 失败保留；T46 是 route 的防御反应，不能重标为 public engage 全场景通过。 | E091, E098 |
| C19 defend_once（路线 typed-threat 分支） | T46 同一 owner 在 stop-only 移动前抢占后完成一次防御：3 次攻击派发、目标 20→0、isBlocking 14 ticks；玩家健康 20、位移 0；普通保存退出 82.997 秒，33 文件稳定留存。 | T46 | public route 仍 interrupted，永不自动继续；没有实际挡伤正证、无逐击服务端确认/逐击因果或普遍墙钟保证；非所有防御目标完成。 | E018, E099 |
| C20 defend_once（damage 分支） | 当前源码保留合格已知伤害中断分支，必须确认原 native release、原 owner/上下文及当前明确敌对目标。 | 当前源码/离线；无独立实机 JAR 归属 | T46 是 typed-threat 在移动前抢占，不是 damage branch 实机覆盖；其他任务/敌对种类/伤害来源不外推。 | E027, E031 |
| C21 盾牌实际挡伤 / observation recovery / retreat | T46 有盾牌姿态实机证据；实际挡伤 stat 前后均缺失。recovery episodes=0/completed=0。 | T46 | 真实挡伤、恢复触发/完成/恢复后攻击顺序、低血撤退仍无此次实机通过。T44 失败不能被覆盖。 | E018, E033 |
| C22 route_threat_rejection 诊断 | 最新候选增加受限 HTTP409 原因诊断并保留 definite refusal 语义；不修改 admission predicate。 | 当前源码/离线；无独立实机 JAR 归属 | T46 成功未复现 T45 拒绝；不能宣称历史根因定位或所有间歇拒绝已修好/实机验证。 | E034, E022, E018 |
| C23 bounded container observations | 有源代码与离线快照/平台清单；单次木桶工作流仅证明自身所需的有限观察。 | 当前源码/离线；无独立实机 JAR 归属 | 清单中七项真实 loader/元数据/预算/container fixture gate 不因 T32/T42 自动完成。 | E100, E035 |
| C24 build / build_with_materials、全局导航/船、维度/End、长资源目标 | 目录可列出实现/规划条目，但当前公共执行 allowlist 仅 20 项；可发现不等于可执行。 | 当前源码/离线；无独立实机 JAR 归属 | 蓝图多格施工、全局/未加载导航、船链、维度切换、End 远征及长期无人值守均无本交付普遍通过。 | E025, E035 |

## T42 可复用的组合流程

1. route-out：走到原料桶
2. open-source：打开原料桶
3. withdraw：取出两块橡木木板
4. close-source：关闭菜单
5. route-home：回到合成点
6. craft：两块木板合成四根木棍
7. stow-output：依据新观察收纳产物，满足后续空手交互条件
8. route-delivery：走到交付桶
9. open-delivery：打开交付桶
10. deposit：存入四根木棍
11. close-delivery：关闭菜单

该原始流程共有 40 次 native mutation、24 个完成的路线段。不要把此列表直接当可重复执行的脚本：目标坐标、槽位、session/context 与物品组件必须来自本次观察，且每一步必须获得自己的已知结果与确认清理。

T42 限定：自动 HOLD_NO_REPLAY 与原 summary functional_pass=null 保留。另行接受普通人工关闭；Java/MCP exit 0、九个原 owner/listener 缺席。保存投影中的四份玩家健康/饥饿均为 20，保护物品按槽位一致；原始 inventory 列表排序不同；strict saved aggregate=false。十三个工作坊方块状态一致，但无全世界一致性。仅一次停机保存读取；reader 终端来源为结构化可见工具结果转录。

## T46 当前版本的核心防御

T46 在独立单机副本中，先在普通路线移动前 stop-only 抢占，再由同一 owner 执行显式 defend_once。普通任务不恢复，public route 为 interrupted。三次攻击派发、三次观测生命下降，目标 20→0；保存 damage_dealt 增 200、剑磨损增 3。isBlocking 观测 14 ticks；玩家健康 20、位移 0。普通关闭耗时 82.997 秒，保存副本 33 文件稳定。

这些证据不等于实际挡下攻击：damage_blocked_by_shield 前后均缺失。recovery episodes/completed 均为 0；没有恢复或恢复后攻击次序的实机覆盖。T45 的拒绝未复现，新增拒绝诊断未在拒绝场景中实机验证。无逐击服务端确认、逐击因果归因、普遍墙钟保证。

自动原生数值退出投影仍为 null；独立的本次游戏直接 console 审查补充确认 exit 0，不修改原投影。其他 owner 均 0，十三个精确身份缺席；保存区域自然变化存在，不宣称全世界字节不变。

## 历史未通过结果保留

- T43：unknown：effect 与 cleanup 均未知；不重试、不复标。 原 JAR `64aaa1a35a3f528cfa96cd2bb3a9978e49626d2dd9deeac5d2ecb72664ee7e3e`；证据 E101, E102。
- T44：known interrupted + cleanup confirmed；有 stop proof、防御开始及一次攻击，但完整防御验收失败。 原 JAR `1c53a59bba6ddcb7a40c7a4b435dc2a542eef4f28d1b0b0441ccd4f6b275e159`；证据 E103, E104。
- T45：known HTTP409/no-effect blocked：未到防御；历史 failing row/frame 不在证据中。 原 JAR `cfa9890b26b18051c41ce0ee6277125c132b639df66b85b6e093519931c0b4fb`；证据 E105, E106。

## 原始适用 JAR 对照

- T07: `7018fcc6448c473aebac047749ced6687b941036c9c58c01381d5d99c9ca7075`；绑定证据 E017。
- T13: `81d5b0d470516cf530223411c4d39cbd516ed2711694cd70533a3457a0a3c4c4`；绑定证据 E016。
- T15: `45181baefad1661c4590e97194aba1d1d723f079c1c0e0ccaf4170e44c9b64e0`；绑定证据 E001。
- T16: `45181baefad1661c4590e97194aba1d1d723f079c1c0e0ccaf4170e44c9b64e0`；绑定证据 E002。
- T17: `8048dde926387954edd47028703da0c2b3c8b97a1b441f85de77d670e741b3e7`；绑定证据 E003。
- T21: `8048dde926387954edd47028703da0c2b3c8b97a1b441f85de77d670e741b3e7`；绑定证据 E004。
- T23: `925f179a03dc6ede3b9e6a0aa014f9d9f73c201203e5ce5bbf0e8ebb7b3abc11`；绑定证据 E005。
- T24: `925f179a03dc6ede3b9e6a0aa014f9d9f73c201203e5ce5bbf0e8ebb7b3abc11`；绑定证据 E006。
- T29: `730e08b58aabcfa4297a296c81055c72ade0b093f623b0d6e7db901cd8eca8f4`；绑定证据 E007。
- T30: `730e08b58aabcfa4297a296c81055c72ade0b093f623b0d6e7db901cd8eca8f4`；绑定证据 E008。
- T31: `604032f4dc734dd16431ac9c99d16e2df336a9ecb96f15250d3f8da30de414d5`；绑定证据 E009。
- T32: `604032f4dc734dd16431ac9c99d16e2df336a9ecb96f15250d3f8da30de414d5`；绑定证据 E010。
- T34: `9a85846eb2ad73b2e18ea054b2d58d0034320bd3ac219d5146ccce2a41836bda`；绑定证据 E011。
- T42: `64aaa1a35a3f528cfa96cd2bb3a9978e49626d2dd9deeac5d2ecb72664ee7e3e`；绑定证据 E012。
- T43: `64aaa1a35a3f528cfa96cd2bb3a9978e49626d2dd9deeac5d2ecb72664ee7e3e`；绑定证据 E013。
- T44: `1c53a59bba6ddcb7a40c7a4b435dc2a542eef4f28d1b0b0441ccd4f6b275e159`；绑定证据 E014。
- T45: `cfa9890b26b18051c41ce0ee6277125c132b639df66b85b6e093519931c0b4fb`；绑定证据 E015。
- T46: `59523ef1a2e6c9c1a738c13958d60c506ff526033ae21af6023140bd6f0b2694`；绑定证据 E018。

## 证据索引

115 条证据的公开标签、字节数与 SHA-256 见[摘要索引](../evidence/CAPABILITY-EVIDENCE.json)。原始路径、日志、截图和存档保持私有，不能从本仓库取得；摘要索引不等于公开原始证据，也不代表重复全历史审计或重新实机测试。
