# 无线维护

无线维护是标准能力 `kindle.wireless.maintenance.v1` 的可选传输层。MTP 用来准备入口和回读文件；用户断开 USB、点击原生入口后，Agent 通过临时 SSH 执行状态检查、备份和已验证的管理操作。无线连接和原生合集写入分别验收，支持状态记录在兼容清单的 `wireless_maintenance` 与 `native_collections.additions`。

用户可以直接说：

```text
使用 KindlePilot 连接我的 Kindle，开启一次临时无线维护，整理合集；先给便于查找的方案，再执行并核对原生界面。
```

Agent 应优先复用现有主题合集。系列识别结果是整理素材，不等于每个系列都应建合集；本机只有一两册的作品通常归入综合漫画合集。用户已有来源分组（例如 WNACG）优先保留。书籍文件和 `.sdr` 不随逻辑归类移动。

## 会话边界

- 每次准备时重新读取 Mac 当前网卡和 IPv4 地址，生成独立 Ed25519 客户端密钥；客户端私钥只保存在本机忽略目录。
- 设备收到该会话的公钥、短期服务器密钥和固定入口。Mac 使用预先固定的服务器公钥与会话别名连接，地址变化不放宽身份校验。
- 设备入口核对序列号摘要、精确固件、Dropbear 与会话文件摘要。Dropbear 来自清单中已校验的 KOReader 包，不修改 KOReader 的 SSH 设置。
- 服务器仅绑定当前 Kindle Wi-Fi 地址，禁用密码及本地/远程端口转发，防火墙仅允许本次 Mac 来源地址。默认 30 分钟，最多 60 分钟；到时停止服务并撤销规则。新会话重新准备授权材料。
- Kindle 端运行目录与本机密钥、日志、快照均不进入 Git。不能输出账号令牌、私钥或 Cookie。

本次 Colorsoft 进入 USB/MTP 模式后无线地址不响应，拔掉 USB 后 SSH 可用。因此操作顺序为：准备及 MTP 回读 → 拔线 → 点击入口 → 无线维护。确切机制尚未证明，不应把一次现象描述为所有 Kindle 的路由规则。

## Agent 操作

首先核对清单、USB 设备身份和现有安装。`--snapshot` 使用当前设备的 KC 只读快照；固件或 KOReader 更新后重新核对清单，不能继承旧组件摘要。

```sh
python3 scripts/kindle-wireless.py prepare \
  --route vera-cs-5.20.1.0.2 \
  --snapshot work/native-collections/latest.json \
  --archive work/asset-cache/koreader-kindlehf-v2026.07.1.zip \
  --interface en0 --output work/wireless/session-1
python3 scripts/kindle-wireless.py transfer \
  --session work/wireless/session-1/session.json
```

`transfer` 以明确目录映射上传 5 个文件，再逐个下载回读并核对 SHA-256。客户端私钥不在传输目录内。用户断开 USB，在原生图书馆打开 `KindlePilot - Wireless Maintenance`（部分固件按文件名显示为 KindlePilot-Wireless）。

入口自带 [Wireless 封面](../assets/wireless-cover.png)，通过 shell 图书支持的 `# Icon` 元数据嵌入。封面摘要也由兼容清单固定；重新准备会话会沿用这张封面，不需要额外安装封面插件。

知道设备地址时执行：

```sh
python3 scripts/kindle-wireless.py connect \
  --session work/wireless/session-1/session.json --host DEVICE_IP
```

地址未知时，可在明确的本机私有子网内查找端口，再用固定服务器公钥和设备摘要验证；不接受未匹配的设备：

```sh
python3 scripts/kindle-wireless.py discover \
  --session work/wireless/session-1/session.json --network LOCAL_SUBNET/24
```

`connect` 同时验证会话主机公钥、设备序列号摘要、固件和 Dropbear；成功只表示维护通道可用。合集新增使用 `scripts/kindle-collection-additions.py`，先生成准确目标，备份、提交一次、回读关系及可见合集计数。结果未知时先核对原提交，不重发。

完成后主动关闭：

```sh
python3 scripts/kindle-wireless.py stop \
  --session work/wireless/session-1/session.json --host DEVICE_IP
```

关闭请求与确认关闭分别记录。随后核对端口不可达，必要时通过 MTP 回读会话 `status` 和停止日志。保留备份与回执；删除过期密钥和临时入口时只处理本会话的准确路径。

## 当前范围

Colorsoft 5.20.1.0.2 已验证固定主机公钥连接、子网内发现，以及独立短会话到期后服务停止、临时授权材料移除和防火墙规则撤销。30 分钟会话实际用于合集整理，原型会话也曾到期关闭。

主机工具优先支持 macOS；网卡通过 `ipconfig` 获取，`en0` 只是默认参数，Agent 应读取实际接口。Linux/Windows 尚未完成无线入口和网卡发现验收。当前设备验证基线为 Colorsoft 5.20.1.0.2，不能扩展到相邻固件或其他型号。
