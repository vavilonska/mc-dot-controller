# Linux 工具箱交付与验收（2026-10-16）

这里保存已交付 Linux ZIP 的安装/API 文档与 24 项能力矩阵。文中 `source/`、`mod/`、`tools/`、`SHA256SUMS.txt` 等路径均相对该 ZIP 根目录，不能直接当作 Git checkout 的布局；仓库各组件直接位于根目录。

本次 Git 提交保存配套产品源码、测试与公开文档，不包含可运行模组 JAR、游戏、账户、凭据、活动队列/journal、原始运行日志、截图或世界存档。ZIP 已独立交付；本仓库没有创建 Release，也不声称从 checkout 重建会产生同一 JAR。

## 使用与验证边界

- [安装与启动](docs/INSTALL.md)
- [API 示例](docs/API-EXAMPLES.md)
- [24 项能力矩阵](docs/CAPABILITY-MATRIX.md)
- [当前 T46 核心防御验收](docs/T46-ACCEPTANCE.md)
- [历史 T42 工坊验收](docs/T42-ACCEPTANCE.md)
- [已知限制](docs/KNOWN-LIMITS.md)
- [公开版本与测试摘要](evidence/PUBLIC-DELIVERY-SUMMARY.json)

当前同版 T46 在普通路线移动前 stop-only 抢占，同一 owner 反击 3 次，目标僵尸血量 20→0；客户端 `isBlocking` 观察到 14 ticks，玩家血量 20、位移 0。路线保持 `interrupted`，不自动恢复。普通关闭及保存副本已验证。

尚未证明盾牌实际挡伤、健康观测恢复、低血撤离、复杂世界可靠性；T45 拒因诊断仍只有离线验证。T42 的十一任务工坊链绑定旧 JAR，不能移作当前 JAR 的整链验收。保留 T43 unknown、T44 失败和 T45 blocked，未知动作不重试。

## 精确产物

- ZIP：`mdc-linux-toolbox-t46-qualified-candidate-20261016-r2.zip`
- ZIP SHA-256：`d1bd40dd14069914fbf4d050a1e03daf17354f3ad1b9889db76a40b435ff8e00`
- JAR SHA-256：`59523ef1a2e6c9c1a738c13958d60c506ff526033ae21af6023140bd6f0b2694`
- JAR 版本：`1.1.6-toolbox-v1-route-threat-diagnostic-offline-test.1`
- 交付冻结源清单 SHA-256：`fa72779950d6a31088e9a938a1f9e7579721a85eff2a1ab231c7e543f759ed41`，1,034 文件，10,564,728 字节

Git 发布只更新面向读者的说明与公开清单，产品实现、测试、构建文件保持交付源码字节。历史 `gradle.properties` 版本字符串保留；默认 Gradle 重建不自动成为以上已验收 JAR。当前仓库清单与交付冻结清单分别记录，不能互换。
