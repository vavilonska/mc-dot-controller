> 本页根据已交付 ZIP 的使用说明整理。`source/`、`mod/`、`tools/` 和包级校验文件均指该 ZIP 布局；Git 仓库只发布源码与文档。请先读[交付范围](../README.md)。

# 安装与启动：Linux 单机候选

这是有明确验证边界的开发候选。安装不会替你解决旧任务的 unknown，也不授权恢复暂停任务。先读本包根目录 README 和能力矩阵；`source/` 保留构建时的全部原始文件，其中旧 README、版本字符串及历史清单不是本次交付状态。

## 1. 环境与完整性

- Linux/POSIX 同一主机；Python 3.10+，必须有 `fcntl`；Node.js 20.6+；Java 21。
- Minecraft 1.21.1，NeoForge 21.1.x，模组声明范围 `[21.1.197,21.2)`；编译目标 21.1.255。版本范围是声明，不代表每个小版本都做过实机验证。
- Java、Resident、Watchdog、Node 和 Python 必须真实共享相应文件系统、进程和网络环境。原生 Windows 完整工具箱不受支持；没有附带 WSL 桥接方案。
- 不附 Minecraft、NeoForge、解释器、启动器、账户、令牌或存档。工具箱本身不要求额外 pip/npm 包。许可证见 `source/NOTICE.md` 和 `source/client-mod/LICENSE`。

解压到全新目录，不覆盖旧 runtime。先核对外部提供的 ZIP SHA-256，再在包根目录运行：

```sh
sha256sum -c SHA256SUMS.txt
python3 -B tools/check_delivery_health.py --bundle .
```

必须看到 `integrity: PASS` 和 `platform_requirements_met: true`。健康检查只读文件并查询 Node 版本，不连接 Minecraft、不读凭据、不部署，也不证明已安装的 Java/NeoForge 或实机 owner 绑定正确。不要在包内写日志、缓存或工作状态，否则严格的完整文件集校验会失败。

配套模组为 `mod/mineclient-bridge.jar`，SHA-256：

`59523ef1a2e6c9c1a738c13958d60c506ff526033ae21af6023140bd6f0b2694`

JAR 元数据版本为 `1.1.6-toolbox-v1-route-threat-diagnostic-offline-test.1`。`source/` 中 1,034 个文件必须完整保留，尤其不要只拷贝 MCP 脚本或混用旧 Resident。这里的 `offline-test` 是已固定的构建版本名，不是新的验收结论。

## 2. 操作者安装

以下为安装说明，本包的整理工作没有执行这些操作。

1. 保留原世界、旧模组及旧任务证据。仅在先前已知任务正常终止、输入释放已确认、客户端已正常关闭的前提下安装。unknown 或暂停状态交由原 ID 对账和操作者处理，不能清日志、换目录或换 ID 来绕过。
2. 在指定私有单人实例中仅替换 MineClient Bridge 模组；将旧 JAR 备份到 `mods/` 以外，避免重复加载。配套使用本包完整 `source/`，不覆盖旧 runtime。
3. 使用既有已批准的启动器/账户打开独立世界副本，不连接多人。公开工具箱不负责登录、启动或切换世界。
4. 在运行 Java 的实际环境中，按 `source/resident-controller/README.md` 的 owner-start 方法启动唯一 Resident。示例从 `source/resident-controller/` 执行：

   ```sh
   PYTHONDONTWRITEBYTECODE=1 ./owner-start.sh http://127.0.0.1:VERIFIED_PORT /verified/shared/mailbox
   ```

   端口必须来自该次 Java 实际 listener。使用既有批准的隐藏提示或凭据文件机制，不把令牌放进模型参数、队列、聊天、示例或仓库。本安装限制只适用于私有单人，覆盖旧文档中的服务器示例。
5. 启动唯一 Watchdog 写入者。请求式工具箱示例从 `source/defense-watchdog/` 执行：

   ```sh
   python3 -B watchdog.py run --queue /verified/shared/mailbox --control /verified/private/control --execution-policy request_only
   ```

   核对 ready 状态和实际策略，不并行写 Resident 队列，不叠加第二个 Watchdog。既有 durable policy/owner pins 仍有效。
6. 将 `examples/toolbox-config.template.json` 复制到包外私有位置，逐项替换。`python_executable` 使用解析后的真实 Python 可执行文件绝对路径，`python_sha256` 使用该文件当前 SHA-256。control、toolbox journal、runtime journal 三个目录必须互不相等、互不嵌套；它们放在包外。不得新增凭据或扩大权限来完成此步骤。
7. 将 `examples/mcp-client.template.json` 按 MCP 客户端支持的格式配置；Node 路径、`source/client-mod/mcp/mineclient-bridge-mcp.mjs` 路径和私有 config 路径都必须是该主机绝对路径。只重载这一个 MCP 服务。它会启动固定 Python façade，不会替你启动游戏/Resident/Watchdog；不要再手工启动第二个 façade。
8. 初始化 MCP 后查看 `tools/list`、`mdc_catalog`、小范围 `mdc_observe`。核对 `runtime_binding_availability` 的 `available`、`private_singleplayer`、session/context、执行策略，以及所需能力的 `runtime_available`。缺失或拒绝时停止，不走 legacy/raw input 绕路。

## 3. 正常停机与保留证据

仅取消明确的当前任务一次，保留 `cancel_request_id`，确认效果与清理结果。取消不回滚已经发生的效果。先让 façade 按原 owner 有界收尾，输入释放/退出确认后再停 Watchdog、Resident，最后由操作者普通保存关闭游戏。失败的自动收尾仍应记录为失败或 HOLD；后续人工正常关闭单独记录，不能把强杀或日志清空当成功。

任一步请求/释放不明，保持原状态并对账；不自动重启、不重发 mutation。包内旧运行结果、示例和单元测试 fixture 不可用作当前世界的坐标、目标、session、context 或动作授权。
