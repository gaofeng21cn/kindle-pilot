# KindlePilot 标准能力

KindlePilot 现在以一个 Package 能力目录统一暴露装机、阅读、传输、合集和无线维护。能力目录位于 [`capabilities/kindle-pilot.json`](../capabilities/kindle-pilot.json)，`opl-package.json#/exports/core_module_ids` 与它保持同一顺序；Agent 可以通过下面的只读入口发现能力，而不需要探测设备或读取任务文件：

```sh
PYTHONPATH=src python3 -m kindle_companion --json capabilities
```

## 能力模块

| 模块 | 负责内容 | 关键边界 |
| --- | --- | --- |
| `kindle-pilot.host.v1` | Package 能力发现与兼容入口 | 只读软件目录，不访问设备 |
| `kindle.device.setup.v1` | 型号、固件、兼容路线、越狱材料和屏幕交接 | 路线支持不等于越狱完成 |
| `kindle.mtp.transfer.v1` | 单客户端、单批次 USB/MTP 传输和远端回读 | USB 不能直接执行设备脚本 |
| `kindle.reading.environment.v1` | KOReader 可用后，一次配置月读、Kindle 书库与无线组件 | 保留已有插件配置；文件回读与应用加载分别验收 |
| `kindle.account.reading.v1` | 微信读书、番茄小说的扫码登录和代表性阅读验收 | Agent 不读取 Cookie，也不把二维码显示当成登录成功 |
| `kindle.library.preservation.v1` | 原生图书馆、推送书籍、`.sdr` 和来源文件保护 | 不搬书、不取消订阅、不删除未知文件 |
| `kindle.native.collections.v1` | 盘点、方案、创建、添加、显式重命名和本任务合集收敛 | 数据库只读；写入由 Kindle 原生服务完成 |
| `kindle.wireless.maintenance.v1` | 首次装机集成、6 位数字配对、临时 SSH、动态主机绑定、身份校验和到期清理 | 复用已校验的 KOReader Dropbear；无密码、无转发、不自动授予合集写入权 |

能力目录声明的是可调用接口和权限边界，具体型号与固件状态仍由 [`manifests/compatibility.json`](../manifests/compatibility.json) 决定。当前 Colorsoft `5.20.1.0.2` 的无线维护与原生合集新增路径已完成设备验收；其他型号不能据此推断支持。

合集工作流使用同一套原生集合模块：

- `preview` 生成创建和新增归属计划；
- `rename-preview` 以 UUID 加当前名称做比较并交换，确保只改标题；
- `retire-preview` 只接受本任务创建且成员已有目的归属的合集；
- `apply` 通过已核对身份的无线会话提交请求，并连续回读。

仓库仍保留旧原生 Wireless 入口的封面资产，供迁移期间回退使用；标准无线维护入口是 KOReader 插件，不依赖这张封面。

## 发现与验收

软件安装、设备状态、资产摘要、MTP 回读、应用加载、账号登录和书籍打开各自记录。`capabilities` 命令只证明 Package 能力目录可用；它不改变任何设备状态，也不替代真实设备或账号验收。
