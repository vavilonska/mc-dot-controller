> 本页根据已交付 ZIP 的使用说明整理。`source/`、`mod/`、`tools/` 和包级校验文件均指该 ZIP 布局；Git 仓库只发布源码与文档。请先读[交付范围](../README.md)。

# T42：旧产物的限定工坊组合流程

这份既有实机证据属于 JAR `64aaa1a35a3f528cfa96cd2bb3a9978e49626d2dd9deeac5d2ecb72664ee7e3e` 及其配套 runtime。它没有在本包 59523ef… JAR 上重新跑整条链，不能迁移成当前版本全流程通过。

## 十一项公开任务

1. route-out：到原料桶。
2. open-source：开桶。
3. withdraw：取出两块橡木木板。
4. close-source：关闭菜单。
5. route-home：回到制作点。
6. craft：两木板制作四木棍。
7. stow-output：按新观察整理产物，满足后续空手交互。
8. route-delivery：到交付桶。
9. open-delivery：打开交付桶。
10. deposit：存入四根木棍。
11. close-delivery：关闭菜单。

十一 job 均成功，完整证明覆盖 40 次原生变更、24 个完成的路线段。这是真实普通单人工坊链，但以上清单不是可原样重放的脚本。每步的坐标、槽位、组件、session/context 和任务权限都必须由当前观察与明确目标产生，并核对已知效果与确认清理后再继续。

## 收尾与保存限定

原自动化 `HOLD_NO_REPLAY`、summary 的 functional-pass=null 保留。自动关闭尝试未执行；没有重试结果不明的游戏动作。后续普通人工关闭单独接受：Java、MCP exit 0，九个原 owner/listener 已退出。这不是自动关闭通过。

一次停机读取及独立解码确认：四份玩家表示血量/食物 20、终点在目标半径内；保护物品按槽位一致，但原始 inventory 列表顺序并不相同。交付桶 slot 0 有四根木棍，其余槽为空，十三个检查过的工坊方块状态相同；桶元数据有记录内的变化。

原严格保存 aggregate=false。其他方块实体与实体记录变化，不能称全世界不变或推断背景变化原因。保存审查沿用一次原始停机读取的记录；独立解码不等于对已安装世界进行了第二次独立读取。

这些限制本身就是已接受结果的一部分。新的 T46 防御结论见 [T46 验收](T46-ACCEPTANCE.md)，不会改写 T42 或其他历史失败/unknown。原适用 JAR 与限定结果见[公开交付摘要](../evidence/PUBLIC-DELIVERY-SUMMARY.json)；证据标签与文件 SHA-256 见[摘要索引](../evidence/CAPABILITY-EVIDENCE.json)，原始运行记录不公开。
