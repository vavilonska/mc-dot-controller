# Minecraft Dot Control

Minecraft 客户端控制桥与外部控制器的开发源码。当前快照包含实验性代码，请先阅读验证状态；本仓库不是可直接安装的已验证发行版。

## 目录

- [`client-mod/`](client-mod/)：基于 [Campione01/MineClient-Bridge v1.1.5](https://github.com/Campione01/MineClient-Bridge/tree/60e78940f7e7fa06116cf4fbc58df346ad617531) 的 NeoForge 1.21.1 客户端模组，以及有界只读地形查询扩展
- [`client-mod/docs/terrain-api.md`](client-mod/docs/terrain-api.md)：地形分页、预算、未知区域与碰撞信息的接口契约
- [`external-controller/`](external-controller/)：独立 Python 战斗控制器原型；真实 HTTP 适配器强制只读，战斗行为仅在模拟器中运行
- [`NOTICE.md`](NOTICE.md)：上游来源、修改范围和许可证说明

## 验证状态

上游基础版 1.1.5 已在受控 Linux 图形客户端测试中运行于 Minecraft 1.21.1 / NeoForge 21.1.255：

- 无认证请求被拒绝；已认证的状态、屏幕、按键映射读取成功
- 本地生存世界可读取玩家状态、背包和位置
- 经 HTTP 短按前进、释放按键和 release-all；停止后连续读取未观察到继续移动，持有输入为空
- 兼容的多人服务器连接与状态读取成功；未进行服务器移动、聊天、战斗或建造测试

这些结果属于基础版，不能证明本仓库的实验扩展已通过实机测试。地形扩展的纯 Java 核心已通过 37,371 条断言，4 个新增类已对实际 NeoForge 21.1.255 客户端库单独编译；但完整 Gradle 构建仍受依赖解析阻塞，扩展尚未在游戏中加载验证。MCP framing 测试 8/8 通过；其上游 Windows 路径自测在 Linux 上失败。外部控制器已通过 90 项离线单元测试及 CLI 演示；真实 HTTP 适配器强制只读，即使配置 enabled=true 也不会发送动作。瞄准、攻击和释放流程只在模拟适配器下验证；真实战斗仍需客户端主线程保护机制，尚未实现或实测。自动寻路、建造和完整自主生存不在已完成范围内。

## 构建与测试

客户端模组需要 Java 21，使用仓库内 Gradle wrapper（8.14.3）。首次构建需要从官方依赖源下载 Gradle、Minecraft/NeoForge 构建依赖。

```sh
cd client-mod
./gradlew -Pneo_version=21.1.255 test build
npm --prefix mcp test
```

有界扫描核心的独立测试：

```sh
cd client-mod
JAVA_HOME=/path/to/jdk-21 bash scripts/terrain-core-test.sh
```

控制器离线测试可在 external-controller/ 中运行 python3 -m unittest discover -v。安装、演示与安全限制见 [`external-controller/README.md`](external-controller/README.md)。不要把离线测试通过视为实机安全保证。

## 安全边界

桥接服务默认只接受本机回环连接，每次控制请求都需要私有 bearer token。令牌只应存放于个人运行目录或本机环境，不要提交到 Git。本仓库不包含游戏客户端、模组发行 JAR、存档、会话配置、令牌、服务器地址或个人账号资料。

地形读数可能过期、分页间变化或未知；未知区域不能当作空气或安全地面。任何真实游戏测试都应先保留已验证配置，并在单独的可丢弃本地世界中进行。发布源码不等于批准安装开发版或在服务器上执行动作。
