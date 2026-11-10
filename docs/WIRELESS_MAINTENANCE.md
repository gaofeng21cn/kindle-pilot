# 无线维护

无线维护的用户入口是 KOReader 内的 `KindlePilot.koplugin`。插件只负责显示配对码并启动一个独立的 KindlePilot 配对守护进程；守护进程使用 KOReader 自带的 Dropbear。这样 KOReader 退出或切回原生 Kindle 后，配对服务仍能完成一次配对。

KOReader 的 SSH 插件已经支持公钥登录和 key-only 模式。KindlePilot 复用兼容清单中 KOReader 发布包里的 Dropbear，在 `kindlepilot/runtime/dropbear` 保存校验过的副本；KOReader 自身升级不会覆盖它。配对服务在独立进程中运行，不依赖 KOReader 的 UI 事件循环。

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

这一步只需要 USB。它把 `KindlePilot.koplugin`（含独立配对守护进程）、设备主机密钥和配置放入 `koreader/plugins/` 与 `koreader/KindlePilot/`；客户端私钥不会传到 Kindle。早期版本曾写入 `koreader/settings/KindlePilot/`，新版插件会兼容读取这一路径，因此更新时不会要求重新配对。

维护使用的 Dropbear 从摘要完全匹配清单的发布包中提取，写入 `wireless_maintenance.pairing_dropbear_path`。会话记录绑定该路径；Agent 回读其摘要，再核对固件和设备身份。KOReader 自带的 SSH 文件与登录配置由 KOReader 继续管理。

## 以后每次使用

1. 拔掉 USB，保持 Kindle 和 Mac 在同一局域网。
2. 打开 KOReader，在主菜单选择 **KindlePilot 无线维护 → 配对此电脑并开始维护**。插件会启动独立配对服务；即使之后 KOReader 返回 Kindle 原生桌面，服务仍会继续运行。
3. KOReader 显示一次性 6 位纯数字配对码，把它告诉 Agent，例如：`KOReader 已显示配对码：005219`，保留开头的零。旧版安装记录仍可用原有的 6 位或 12 位十六进制码完成迁移；新版记录只接受纯数字。
4. Agent 优先直连上次已核实的设备地址；地址变化时在局域网内发现 Kindle。通过 HMAC 挑战响应配对，再用 Dropbear 建立临时 SSH。

```sh
python3 scripts/kindle-wireless.py pair \
  --setup work/wireless/koreader-pairing/setup.json \
  --output work/wireless/session-1 \
  --code PAIRING_CODE \
  --interface en0
```

已知上次设备地址时加上 `--host DEVICE_IP`，跳过整网发现；主机连接按所选网卡的实际源地址绑定。命令会完整读取协议行，返回认证失败、服务启动失败等具体原因。SSH 身份检查失败时保留已建立的会话记录，可通过 `connect` 继续核对，不重复提交配对。

配对码不会在网络中明文传输；它只在 Kindle 屏幕和 Agent 对话之间出现。错误尝试最多 3 次，配对窗口默认 120 秒。配对成功后，临时公钥只允许当前 Mac 地址连接，默认 30 分钟自动关闭。

知道设备地址后，Agent 使用固定主机公钥、序列摘要、固件和 Dropbear 摘要回读；用户不需要手动提供 IP。USB/MTP 和无线 SSH 不要同时使用。

菜单中的“查看维护状态”显示服务是否已开启及诊断代码。启动入口仅在独立服务报告就绪后显示配对码。临时 SSH 使用独立工作目录中的授权文件，不修改 KOReader 自带 SSH 插件的授权文件；到期和主动停止共用同一个停止脚本，并以会话标识防止旧计时器关闭新会话。

USB 更新需要先退出 KOReader，等原生系统进入“已连接电脑”后进行；配对码显示后保持 USB 断开。Agent 应先完成本机协议运行测试再要求设备验收。当前守护进程的主机测试覆盖实际 Lua/TCP 握手、插件启动与退出、错误码限制、凭据隔离、到期清理和旧计时器隔离。2026-11-11 已在 Colorsoft 5.20.1.0.2 上完成屏幕配对、固定公钥 SSH、身份回读、无线插件更新、带前导零的纯数字配对，以及 12 秒到期后的端口、密钥和防火墙清理验收。无线更新菜单文件后需要重启一次 KOReader，才会加载新的配对码生成逻辑。

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
- KOReader：负责显示配对码并启动配对守护进程。
- KindlePilot 配对守护进程：独立处理配对协议，不依赖 KOReader UI 进程。
- `SSH.koplugin`/Dropbear：负责 SSH 服务和公钥认证。
- KindlePilot：负责配对协议、临时授权、来源限制、超时清理和 Agent 回读。
- 原生 Kindle 图书馆中的旧 `KindlePilot - Wireless` 入口属于旧版兼容载体；KOReader 插件验收后可以清理。

当前设备路线仍以 `manifests/compatibility.json` 为准：Colorsoft `5.20.1.0.2`。无线通道可用不自动授权合集写入，原生合集能力仍由 `kindle.native.collections.v1` 单独验收。

开发验证除 Python 测试外需要 LuaJIT、LuaSocket 和 libcrypto；CI 安装这些依赖并执行 `tests/test_pairing_daemon.py`。本机可通过 `KINDLE_TEST_LUASOCKET`、`KINDLE_TEST_LUA_PATH`、`KINDLE_TEST_CRYPTO` 指定测试运行库；它们只用于主机测试。
