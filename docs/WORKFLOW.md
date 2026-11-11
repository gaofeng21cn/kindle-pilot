# KindlePilot 工作流

已完成装机、现在要整理原生图书馆的设备，直接使用[原生集合工作流](NATIVE_COLLECTIONS.md)，不重复下列越狱步骤。

需要持续执行和多次回读时，使用[无线维护](WIRELESS_MAINTENANCE.md)。首次装机一并准备配对插件与设备身份；以后用户在 KOReader 显示配对码即可连接，无需先插 USB。不要在 USB 模式下反复尝试 SSH。

KindlePilot 的用户入口是一句话：

~~~text
请使用 $kindle-pilot 管理我当前连接的 Kindle：先识别型号、固件和 USB 状态，选择准确兼容路线；如果支持，就下载并校验官方材料，使用单一 MTP 会话传输；保留原生 Kindle 图书馆，同时配置本地图书、微信读书、番茄小说和后续无线维护；在我完成 Kindle 屏幕上的必要步骤后继续，持续推进但不要重复已完成步骤，最后逐项回读验收。
~~~

用户只需要连接数据线，并在 Agent 停下来时完成 Kindle 屏幕或手机上的动作。用户可以用 "已连接"、"继续"、"JAILBROKEN 已出现"、"扫码成功" 等短消息继续同一个状态；Agent 必须先读取状态再决定下一步。

## 分工

Agent 负责：

1. 只读发现 USB 设备，读取产品名和序列号。
2. 读取兼容清单，按完整固件版本选择路线。
3. 下载上游材料并核对 SHA-256。
4. 用一个 OpenMTP 客户端执行明确的传输批次，并回读远端路径、字节数和存储空间。
5. 安装并确认 KOReader 后，在同一次 USB 连接中准备月读、Kindle 书库插件和无线配对组件，回读目标文件。
6. 记录每个步骤的状态、证据和下一步。

用户负责：

1. 按 Agent 给出的官方链接在 Kindle 屏幕上打开页面；如果路线要求设备端下载，就在 Kindle 上完成。
2. 完成 Font Calibration，并观察 `RESTARTING GUI` 与 `JAILBROKEN`。
3. 在搜索框执行 KPM 命令并确认 KOReader 启动。
4. 使用手机完成微信读书、番茄小说等服务的扫码登录。
5. 打开代表性书籍，确认本地书、Kindle 书库和账号书架都能实际阅读。

## 状态顺序

~~~text
USB 可见
  -> 路线支持
  -> 资产下载并通过 SHA-256
  -> MTP 写入并回读
  -> 用户完成字体设置和 Véra 触发
  -> 用户确认 JAILBROKEN / KPM
  -> KOReader 加载
  -> 单批次安装月读 / kindle.koplugin / KindlePilot 无线组件并回读
  -> 用户确认月读加载；数字码无线配对与关闭验收
  -> 微信读书 / 番茄小说登录和书籍行为验收
~~~

USB 可见不等于设备可写；文件存在不等于应用加载；进程退出码为 0 不等于 MTP 传输成功；二维码显示不等于账号登录成功。每一层都要有自己的回读证据。

## 阅读环境与无线一次配置

KOReader 由 KPM 安装并启动确认后，先完全退出 KOReader，再连接 USB。Agent 使用已有装机状态和清单里的材料生成一个批次：

```sh
python3 scripts/kindle-reading-setup.py prepare \
  --state work/kindle-pilot-state.json \
  --asset-dir work/asset-cache \
  --output work/reading-setup/first-install
python3 scripts/kindle-reading-setup.py transfer \
  --plan work/reading-setup/first-install/reading-setup.json
```

`asset-dir` 中准备清单 `reading_environment.plugins` 的两个安装包，以及 `wireless_maintenance.asset` 指定的 KOReader 包。后者只提取已校验的维护 Dropbear，不覆盖 KOReader 运行环境。`prepare` 只在本机生成文件、设备身份和目标清单；`transfer` 重新检查 USB 身份，先只读盘点，再以一个写入批次上传并逐个下载核对 SHA-256，保存 `transfer-receipt.json` 和存储回读。

已有完整的月读和 Kindle 书库插件直接保留复用，不覆盖配置、登录或缓存；残缺目录先停在盘点结果。已有无线身份不会被新建身份覆盖：新流程生成的记录可通过 `prepare --wireless-setup PATH/setup.json` 复用并在传输前核对设备主机密钥。早期使用 `/proc/usid` 原始摘要的记录继续走原无线工作流，补装阅读插件时用 `--without-wireless` 保留它。用户不需要无线时也可用此选项。

状态仍由原 `record-step` 管理：传输回执通过后记录 `install_plugins`、`install_wireless`；用户确认应用加载后记录 `runtime_verify`；实际配对、身份回读和会话清理通过后再记录 `wireless_verify`。后两步与微信读书、番茄小说的账号/试读分别验收。读取旧状态会补充无线步骤，并保留已有完成记录。

传输完成并拔线后，用户启动 KOReader/月读、用六位数字码完成无线验收，并扫码登录阅读账号；Agent 保存 `wireless/setup.json` 路径供以后直接使用。日常进入[无线维护](WIRELESS_MAINTENANCE.md#以后每次使用)，不重复要求 USB 安装。

## 运行约束

- 路线判断以 `manifests/compatibility.json` 为准。精确型号或固件不在清单中时，停止写入。
- MTP 连接只保留一个客户端和一个传输批次。出现 `No raw devices found`、`StoreFull`、`SendObjectInfo` 或顶层 `error:` 时，按失败处理并重新建立单一会话。
- 不删除整个 `documents`、`/koreader`、`/libkh`、未知 `.bin` 或未知用户书籍。
- 删除或清理前，先列出明确目标；完成后读取远端目录和存储空间。
- 不把越狱书、设备转储、Cookie、二维码载荷或插件压缩包提交到仓库。
