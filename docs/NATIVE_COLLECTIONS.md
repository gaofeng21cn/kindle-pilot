# 原生 Kindle 集合

KindlePilot 可以读取原生集合和已索引书目，按漫画系列生成整理预览，并准备受控的 KC 适配测试。月读分类、物理目录和原生集合各自独立。

**当前 Colorsoft 5.20.1.0.2 支持只读盘点和预览，自动批量写入尚未通过实机验证。** 支持状态由[兼容清单](../manifests/compatibility.json)中的 `native_collections` 决定。

## 这次实机验证得到了什么

2026-11-10，在 Colorsoft 5.20.1.0.2 上完成了以下验证：

| 环节 | 结果 |
| --- | --- |
| USB 和 MTP | 设备可见，文件上传后逐个下载回读并核对 SHA-256 |
| 只读导出 | 成功读取原生书目、7 个原有集合和 171 条成员关系 |
| 已下载内容 | 319 本；识别为 49 个漫画系列、302 本，其余 17 本保留为独立作品或待确认项 |
| 备份兼容 | 原装 KC 校验器使用 SQLite 3.26，无法解析设备数据库的生成列；用相同源码和 SQLite 3.47.0 重编译后，真实备份校验通过 |
| 六步测试 | 创建、改名、加入、移出、再加入得到当时的确认；删除前成员状态改变，触发 `PRECONDITION_CHANGED`，最终为 5/6 |
| 文件保护 | 样本书和对应 `.sdr` 的前后 SHA-256 一致 |
| 测试恢复 | 用户在原生界面删除了临时集合；样本计数残差通过本地原生服务恢复为 0，连续 5 次回读确认 |
| 最终集合状态 | 原有 7 个集合和 171 条成员关系与测试前完全一致；能力记录仍只有 `verify_state` |

首次失败发生在任何集合修改之前；重编译保留了备份校验，未跳过保护。第二次测试暴露的成员状态变化原因尚未确定，因此没有把短暂的五项确认当成稳定编辑能力，也没有批量创建系列集合。

原生索引里还存在部分“成员表”和“书目集合计数”不一致的历史记录。工具会标记这些项目，阻止直接生成编辑计划。

## 社区方案怎样取舍

| 方案 | 已公开的范围与本项目选择 |
| --- | --- |
| [kc-ivy / KC](https://github.com/uiu8/kc-ivy) | 正式基线为 Windows、Calibre 9.15+、PW5 5.17.1.0.3 和 USB 磁盘；Colorsoft/MTP 属实验范围。本项目复用其设备执行器和纯协议模块，通过主机工具操作，无需安装 Calibre |
| [Kindle Series Manager](https://github.com/mlapaglia/kindle-series-manager) | 提供 KUAL 网页和直接数据库工具；本次没有采用覆盖数据库的路径 |
| [LibrarianSync](https://github.com/barsanuphe/librariansync) | 能从 JSON 生成集合，其中 rebuild 会移除现有集合；不适合本次保留原有集合的目标 |
| [ksync](https://github.com/qingshan/ksync) | 为 OPDS 下载创建原生集合，声明设备基线为 Oasis 10 / 5.16.x，不能直接作为当前 Colorsoft 的支持证据 |

kc-ivy 的明确适配范围见其[运行环境说明](https://github.com/uiu8/kc-ivy/blob/v1.0.30/release/KINDLE_ENVIRONMENT.md)。本次没有找到可直接证明 Mac + Colorsoft 5.20.1.0.2 批量集合写入稳定的上游方案。

## 给 Agent 的操作入口

日常盘点可以直接说：

~~~text
使用 KindlePilot 盘点我当前 Kindle 的原生集合和已下载漫画，按系列生成预览，保留所有原文件、边车和已有集合。
~~~

集合任务不重复越狱。先读取清单，再下载并校验其中声明的 KC 发布包、SQLite 源码和校验器源码。它们均存放在 `work/` 等忽略目录。

电脑负责准备和传输，Kindle 端负责运行脚本。USB/MTP 不能直接执行脚本；用户断开 USB，在原生图书馆点击入口，再重连读取结果。

## 构建与准备

兼容清单记录了所需源码 URL、SHA-256、Zig 版本、目标架构和实测校验器摘要。准备这些文件后执行：

~~~sh
python3 scripts/build-kc-checker.py \
  --route vera-cs-5.20.1.0.2 \
  --sqlite-archive work/native-collections/sqlite-amalgamation-3470000.zip \
  --source work/native-collections/kc_backup_check.c \
  --output work/native-collections/build
~~~

构建脚本同时生成主机和 ARM 校验器，执行 ICU 比较拒绝测试，并核对最终 ARM 摘要。源码、工具版本或产物不匹配时停止传输。

在本机准备设备文件：

~~~sh
python3 scripts/kindle-collections.py \
  --route vera-cs-5.20.1.0.2 \
  --archive work/asset-cache/kc-ivy_1.0.30.zip \
  stage --checker work/native-collections/build/kc-backup-check \
  --output work/native-collections/stage
~~~

通过一个 MTP 批次传输，并下载回读核对每个文件。当前路线只准备 Check 和 Test 入口，不生成批量 Apply 入口。Check 只读取 `cc.db`，不提交原生集合修改。

用户运行 Check 后，读取 `kc-sync/snapshots/latest.json`、`kc-sync/pilot/check.log` 和 KC 运行日志，再生成目录：

~~~sh
python3 scripts/kindle-collections.py \
  --route vera-cs-5.20.1.0.2 \
  --archive work/asset-cache/kc-ivy_1.0.30.zip \
  inspect --snapshot work/native-collections/latest.json \
  --scope /mnt/us/documents/Downloads/Items01 \
  --output work/native-collections/inventory.json
~~~

`plan-series` 只对显式指定的系列生成本地预览，保留已有集合和其他归属；未通过的路线或计数不一致会返回阻断项。盘点结果不构成执行整库变更的授权。

## 实验测试和验收

`probe` 接受一本已索引、位于本机、没有已有集合关系且计数为 0 的书，生成固定六步请求和 MTP 完整性标记。运行前展示准确集合 UUID、书籍和动作。只测试新建的 `KC-PROBE-*` 集合。

KC 执行器通过只读连接导出和备份数据库，由 Kindle 本地 `/change` 服务负责修改。任务绑定设备、保护策略、能力版本和状态摘要。发生冲突或结果未知时，先核对原任务、回执和 pending 文件，不发新任务掩盖旧状态。

`receipt` 比对请求、回执与之后的只读快照，拒绝复用测试前的原始快照，检查最终集合状态和书籍计数。启用正式写入前还必须确认：六步全部通过、测试集合消失、样本计数恢复、样本文件和边车哈希一致、原有集合关系不变。进程退出码或某一时刻的 `confirmed` 不能代替这些验证。

这次测试留下的临时执行和恢复入口已移除；只读检查入口、备份和日志保留。个人快照、书名、UUID、数据库、序列号与认证信息均留在忽略目录，不进入 Git。
