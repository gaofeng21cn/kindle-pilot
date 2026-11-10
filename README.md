# KindlePilot

让你的 Agent 帮你装好、用好 Kindle。

KindlePilot 是面向 Agent 的 Kindle 管理工作流。Pilot 表示由 Agent 驾驶整条流程：识别设备、选择路线、安排安装，并在需要时把控制权交回用户确认。它把 USB 识别、精确固件路线、官方材料校验、OpenMTP 稳定传输、KOReader / 月读 / Kindle 书库插件安装，以及安装后的逐项验收放在一条可恢复的流程里。每一步都会说明当前设备、下一位执行者和可以回读的证据。

## 一句话开始

安装 `kindle-pilot` Skill 后，把 Kindle 用数据线连接到电脑，直接对你的 Agent 说：

~~~text
请使用 $kindle-pilot 管理我当前连接的 Kindle：先识别型号、固件和 USB 状态，选择准确兼容路线；如果支持，就下载并校验官方材料，使用单一 MTP 会话传输；保留原生 Kindle 图书馆，同时配置本地图书、微信读书和番茄小说；在我完成 Kindle 屏幕上的必要步骤后继续，持续推进但不要重复已完成步骤，最后逐项回读验收。
~~~

如果 Agent 还没有安装这个 Skill，也可以直接说：

~~~
请读取 https://github.com/gaofeng21cn/kindle-pilot 的 README 和 skill/kindle-pilot/SKILL.md，然后管理我当前连接的 Kindle；需要我操作 Kindle 屏幕时明确告诉我下一步，并在我回复完成后继续推进。
~~~

之后不需要重新描述上下文。下面这些短消息都可以让 Agent 接着上次的状态继续：

~~~text
已连接
我已完成字体设置
Véra 已打开，正在重启
JAILBROKEN 已出现
KPM 可以用了
扫码成功
~~~

## Agent 会完成什么

| 阶段 | Agent 的工作 |
| --- | --- |
| 识别 | 读取 macOS 的 USB / ioreg 信息，确认产品名和设备序列号是否可见 |
| 路线 | 读取 `manifests/compatibility.json`，按型号、完整固件版本和构建号选择精确路线；未知路线会停下，不会猜相邻版本 |
| 材料 | 从声明的上游地址下载材料，逐个核对 SHA-256；越狱书和第三方压缩包只保存在本机忽略目录 |
| 传输 | 生成明确的 MTP 计划，用一个 OpenMTP 客户端完成一批传输，处理带空格的路径，并回读远端文件和可用空间 |
| 安装 | 在越狱和 KOReader 已准备好后，继续安装月读与 Kindle 书库插件，并检查目标路径 |
| 验收 | 分开记录 USB 可见、路线支持、资产校验、MTP 写入回读、应用加载、账号登录和书籍打开结果 |

## 你需要在 Kindle 上完成什么

这些动作需要设备触屏或手机确认，Agent 会在正确的时机停下来并给出具体步骤：

1. 按 Agent 给出的官方链接打开 Véra 页面；如果该路线要求在 Kindle 浏览器下载设备专用书籍，就在 Kindle 上完成这一步。
2. 按官方要求完成 Font Calibration 设置并保存。
3. 打开 Véra 书籍，等待屏幕出现 `RESTARTING GUI`，再确认 `JAILBROKEN`。
4. 在 Kindle 搜索框执行 Agent 给出的 KPM 命令，并确认 KOReader 能启动。
5. 在月读中使用手机完成微信读书、番茄小说等服务的扫码登录。
6. 打开代表性的本地书、Kindle 书库和账号书架，确认实际阅读行为。

Agent 不会把“文件已经复制”“命令退出码为 0”或“二维码已经显示”当成完成；每个节点都要有对应的设备或应用证据。

## 当前适配设备

| 设备 | 固件 | 路线 |
| --- | --- | --- |
| Kindle Colorsoft Signature Edition | `5.20.1.0.2` | KindleModding Véra / Colorsoft 精确路线 |

兼容清单是版本化事实源。固件高于、低于或不同于清单中的精确版本时，KindlePilot 会停在路线判断，不会用相邻固件的越狱材料替代。

## 安装 Skill

将仓库中的 `skill/kindle-pilot` 安装到你的 Agent 的 Skill 目录，或让 Agent 直接读取 GitHub 上的同一路径。安装本机 CLI 后，也可以使用 `kindle-pilot` 命令。Skill 的入口名称是 `$kindle-pilot`，CLI 产品入口是 `kindle-pilot`；Python 内部包名 `kindle_companion` 为现有调用保留。

## 安装后继续管理

你可以继续用自然语言让 Agent 读取状态和推进工作：

~~~text
请使用 $kindle-pilot 继续我上次的 Kindle 流程，只读取现有状态，不要重复传输。
请使用 $kindle-pilot 检查 KOReader、月读和 Kindle 书库插件是否实际加载，并告诉我下一步。
请使用 $kindle-pilot 重新检查当前 Kindle 的 USB、固件路线和安装验收状态，只做只读检查。
~~~

## 主机侧命令

开发或排障时，可以直接调用 CLI：

~~~sh
python3 -m pip install -e .
kindle-pilot --json status

PYTHONPATH=src python3 -m kindle_companion --json status
PYTHONPATH=src python3 -m kindle_companion --json probe --firmware 5.20.1.0.2
PYTHONPATH=src python3 -m kindle_companion --json resolve-asset \
  fontcal.azw3 --route vera-cs-5.20.1.0.2
PYTHONPATH=src python3 -m kindle_companion verify-asset \
  /path/to/fontcal.azw3 \
  --sha256 0136b8110d490d94b9be50899fc5ce4e4a7f70c02df0ba957c3f35dcdad2d041
~~~

MTP 辅助命令使用 OpenMTP 的 `mtp-cli`。默认查找 `/Applications/OpenMTP.app/Contents/Resources/bin/mtp-cli`，也可以用 KINDLE_MTP_CLI 指定路径：

~~~sh
PYTHONPATH=src python3 scripts/kindle-mtp.py storage
PYTHONPATH=src python3 scripts/kindle-mtp.py ls /documents
~~~

执行删除、上传或安装前，Agent 应先读取目录和存储信息，并把具体目标写入状态证据。工具不会删除整个 `documents`、`/koreader`、`/libkh` 或未知用户文件。

## 工作流

~~~text
USB 可见
  -> 型号 / 完整固件路线判断
  -> 上游材料下载与 SHA-256 校验
  -> 单会话 MTP 传输与远端回读
  -> 用户完成字体校准与 Véra 触发
  -> 用户确认 JAILBROKEN / KPM
  -> Agent 安装 KOReader / 月读 / kindle.koplugin
  -> 重启后验证应用加载
  -> 用户完成微信读书 / 番茄小说扫码并打开代表性书籍
~~~

## 资产与许可

仓库不提交越狱书、设备转储、账号 Cookie、二维码载荷或第三方发布包。`manifests/compatibility.json` 只保存上游地址、来源、摘要和再分发状态；Agent 下载后的私有材料应放在未跟踪目录，并在传输前核对 SHA-256。

KOReader、月读、`kindle.koplugin` 和 KindleModding Véra 分属不同上游项目。本仓库只维护集成元数据和主机侧工作流，不代替确认各上游当前的许可证、发布权限和运行责任，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 开发与验证

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
~~~

本项目采用 MIT 许可证。设备安装、账号登录和真实书籍阅读必须在用户自己的 Kindle、手机和账号上完成；仓库测试只证明主机侧解析、状态机、摘要校验和 MTP 命令合同。
