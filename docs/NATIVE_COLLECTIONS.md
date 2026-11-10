# 原生 Kindle 合集管理

KindlePilot 已在 Colorsoft 5.20.1.0.2 实现原生合集的创建和新增归属，并经设备回读、用户原生界面和打开阅读确认。合集是系统索引中的逻辑分组，月读分类、物理目录各自独立；原推送文件与 `.sdr` 留在原位。

用户可以说：

```text
使用 KindlePilot 优化我原生 Kindle 的合集，优先复用已有分组，不要给每本单册漫画建合集；先形成明确方案，然后落地并核对。
```

## 按使用设计合集

保留已有来源和主题分类，把较少册数的漫画放入综合漫画合集；仅对数量较多、需要频繁寻找的长篇保留独立合集。不要把系列识别结果直接变成等量的合集，也不要仅凭文件扩展名将文字书和单本漫画混放。

本次整理覆盖 319 本本机内容。用户反馈首版 54 个合集太细后，实际收敛为 13 个、359 条关系；原有 7 个合集的 UUID 和全部 171 条原有归属保留。最终统一采用“漫画｜名称”“图书｜名称”，长标题缩短以方便屏幕查找。个人书名、设备 UUID、快照、执行请求与备份均保存在本机忽略目录，公开仓库只提供通用规则和工具。

## 已验证的写入方式

合集写入通过 Kindle 本地 `127.0.0.1:9101/change` 服务进行。`cc.db` 始终只读打开；写前创建备份并运行清单中固定摘要的校验器。一次变更同时更新书籍的 `collections` 和合集的 `members`，保留所有旧归属，再由原生服务重算显示计数。

当前固件的 `collectionCount` 统计的是首页可见合集，不是成员关系表的全部行数。隐藏合集中的书可能计数为 0；这不是损坏证据。读取了合集可见性之后才能判断计数。只有旧 KC 快照时，工具标记“需要可见性信息”，不会要求用户清零已有归属。

`scripts/kindle-collection-additions.py` 提供：

- `export-sql`：准备只读索引查询，读取可见性、书籍归属与真实成员关系。
- `preview`：基于明确的目标 UUID 和书籍 UUID 生成本地新增计划。
- `apply`：使用已核对身份的临时 SSH 会话，按合集备份、提交一次、连续回读。网络失败或结果未知时保留原任务并停止，不重发。

```sh
python3 scripts/kindle-collection-additions.py \
  --route vera-cs-5.20.1.0.2 export-sql --output work/collections/catalog.sql
python3 scripts/kindle-collection-additions.py \
  --route vera-cs-5.20.1.0.2 preview \
  --catalog work/collections/catalog.json --targets work/collections/targets.json \
  --output work/collections/preview.json
python3 scripts/kindle-collection-additions.py \
  --route vera-cs-5.20.1.0.2 apply \
  --session work/wireless/session-1/session.json --host DEVICE_IP \
  --targets work/collections/targets.json --state-dir work/collections/run-1
```

目标文件结构为 `{"collections":[{"uuid":"准确合集UUID","name":"名称","book_uuids":["已索引书籍UUID"]}]}`。已有合集复用原 UUID，新建合集使用新 UUID。整理清单必须展示给用户；用户的整理请求决定允许的变更范围。

## 缩减本轮多余合集

`prepare_retirement` 仅允许清理有本轮创建证据的准确合集：原有合集 UUID 永远不在范围内。先确认每个成员已在方案指定的目的合集，再清空来源归属、更新书籍元数据、删除该合集壳；不删除书籍。后续回读必须证明只有指定来源合集被移除，其他关系和文件路径保持完整。普通新增长期维护不需要删除能力。

## 与 kc-ivy 的关系

[kc-ivy / KC](https://github.com/uiu8/kc-ivy) 仍用于只读导出、纯协议及规划参考。其正式基线为 Windows、Calibre 9.15+、PW5 5.17.1.0.3 和 USB 磁盘；[公开运行范围](https://github.com/uiu8/kc-ivy/blob/v1.0.30/release/KINDLE_ENVIRONMENT.md)没有认证当前 Mac + Colorsoft 组合。

最初的六步测试在快速加入、移出、再次加入后得到 5/6，未通过带成员删除；该完整 KC 路径保持关闭。随后独立验证了实际需要的创建和新增归属路径，不伪造或覆盖 KC 的全量能力记录。具体支持状态分别记录在兼容清单 `native_collections.additions` 与 `wireless_maintenance`。

原装 KC 备份校验器的 SQLite 3.26 不能解析当前数据库生成列。本项目按固定上游源码和 SQLite 3.47.0 重编译，清单固定源码和产物摘要，保留原备份保护。

其他方案中，LibrarianSync 的 rebuild 会移除已有合集；直接覆盖数据库的方案也不符合本项目保留原有关系的路径。本次采用原生服务和明确的新增/撤销清单。

## 验收

区分 USB 可见、型号/固件支持、资产摘要、MTP 回读、设备脚本运行、无线连通、原生合集关系和用户打开阅读。SSH 可用不等于合集编辑可用，主机测试不替代设备验收。

归类后核对目标书覆盖、原有关系保留、未发生未授权变更、元数据两侧一致、可见合集计数和代表性书籍打开；再做延迟回读。样本文件及 `.sdr` 做哈希比较。阅读中系统可能更新阅读进度，所以不能要求所有边车永远字节不变。
