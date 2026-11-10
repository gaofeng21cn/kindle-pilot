# 无线维护

无线维护的用户入口是 KOReader 内的 `KindlePilot.koplugin`。KOReader 自带 `SSH.koplugin` 和 Dropbear；KindlePilot 只负责一次性屏幕配对、临时公钥、来源限制和到期清理，不再创建一个独立的原生 Wireless 书籍入口。

KOReader 的 SSH 插件已经支持公钥登录和 key-only 模式。KindlePilot 插件复用同一个 KOReader 运行环境和 Dropbear，不复制 SSH 服务。

## 一次性安装

第一次迁移到配对模式时，电脑侧准备插件和设备主机身份：

```sh
python3 scripts/kindle-wireless.py prepare-plugin \
  --route vera-cs-5.20.1.0.2 \
  --snapshot work/native-collections/latest.json \
  --archive work/asset-cache/koreader-kindlehf-v2026.07.1.zip \
  --output work/wireless/koreader-pairing
python3 scripts/kindle-wireless.py transfer-plugin \
  --setup work/wireless/koreader-pairing/setup.json
```

这一步只需要 USB。它把 `KindlePilot.koplugin`、设备主机密钥和配置放入 `koreader/plugins/` 与 `koreader/settings/KindlePilot/`；客户端私钥不会传到 Kindle。

## 以后每次使用

1. 拔掉 USB，保持 Kindle 和 Mac 在同一局域网。
2. 打开 KOReader，在主菜单选择 **KindlePilot wireless maintenance → Pair this computer and start maintenance**。
3. KOReader 显示一次性 12 位配对码，把它告诉 Agent：`KOReader 已显示配对码：XXXXXXXXXXXX`。
4. Agent 在局域网内发现 Kindle，用 HMAC 挑战响应配对，再用 KOReader 的 Dropbear 建立临时 SSH。

```sh
python3 scripts/kindle-wireless.py pair \
  --setup work/wireless/koreader-pairing/setup.json \
  --output work/wireless/session-1 \
  --code PAIRING_CODE \
  --interface en0
```

配对码不会在网络中明文传输；它只在 Kindle 屏幕和 Agent 对话之间出现。错误尝试最多 3 次，配对窗口默认 120 秒。配对成功后，临时公钥只允许当前 Mac 地址连接，默认 30 分钟自动关闭。

知道设备地址后，Agent 使用固定主机公钥、序列摘要、固件和 Dropbear 摘要回读；用户不需要手动提供 IP。USB/MTP 和无线 SSH 不要同时使用。

## 会话关闭

完成工作后可以由 Agent 主动关闭：

```sh
python3 scripts/kindle-wireless.py stop \
  --session work/wireless/session-1/session.json \
  --host DEVICE_IP
```

到期或主动关闭会删除临时 `authorized_keys`、终止 Dropbear 并撤销防火墙规则；设备主机身份和 KOReader 插件保留，下一次只需重新打开 KOReader 配对菜单。

## 能力边界

- USB：只负责首次安装/更新插件和主机身份。
- KOReader：负责显示配对码和承载插件。
- `SSH.koplugin`/Dropbear：负责 SSH 服务和公钥认证。
- KindlePilot：负责配对协议、临时授权、来源限制、超时清理和 Agent 回读。
- 原生 Kindle 图书馆中的旧 `KindlePilot - Wireless` 入口属于旧版兼容载体；KOReader 插件验收后可以清理。

当前设备路线仍以 `manifests/compatibility.json` 为准：Colorsoft `5.20.1.0.2`。无线通道可用不自动授权合集写入，原生合集能力仍由 `kindle.native.collections.v1` 单独验收。
