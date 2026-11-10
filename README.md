# KindlePilot

**让你的 Agent 帮你装好、用好 Kindle。**

KindlePilot 为你的 Agent 提供 Kindle 装机与管理所需的 Skill、工作流和命令行工具。从识别设备、选择越狱路线，到安装 KOReader、月读和检查阅读效果，由 Agent 推进电脑侧操作，你在需要时完成触屏和扫码。

## 一句话开始

1. 用 USB 数据线把 Kindle 接到 Mac，解锁设备；如果正在使用 KOReader，先完全退出。
2. 打开能联网、执行本机命令和访问 USB 设备的 Agent。
3. 把下面这句话发给它：

~~~text
请按 https://github.com/gaofeng21cn/kindle-pilot 的 README 和 Agent 指引，帮我配置已连接的 Kindle：保留原生书库，装好本地阅读、微信读书和番茄小说，需要我触屏或扫码时告诉我，完成后继续。
~~~

无需先手动安装 Skill。Agent 会读取本仓库的 [Agent 指引](skill/kindle-pilot/SKILL.md)，检查电脑环境和设备兼容性，再下载材料并推进安装。完整固件版本需要你从 Kindle 的“设备信息”中提供。

已经安装 `kindle-pilot` Skill 的用户，可以直接说：

~~~text
$kindle-pilot 帮我配置已连接的 Kindle，用来读本地图书、微信读书和番茄小说，并保留原生书库。
~~~

在同一次对话里，按提示完成操作后回复“已连接”“设置好了”或“扫码成功”，Agent 会核对结果并继续。换一段对话时，告诉它上次的本地仓库或状态文件位置，就能接着检查已有进度。

## 能帮你做什么

| 需求 | KindlePilot 的处理方式 |
| --- | --- |
| 第一次装机 | 识别设备和固件，选择已收录的越狱路线，准备材料，引导触屏步骤并继续安装阅读环境 |
| 本地图书和漫画 | 安装 KOReader 与月读，协助整理本地目录并检查代表性内容能否打开 |
| 微信读书、番茄小说 | 按月读支持的书源配置登录，引导手机扫码，分别检查账号书架和章节阅读 |
| 保留原生 Kindle | 保留图书馆和推送入口；旧推送的 KFX 漫画可继续用原生阅读器阅读，减少逐本转换 |
| 日常维护 | 检查安装状态，定位 USB、传输和插件问题，按已有进度继续处理 |

微信读书和番茄小说的可用情况取决于月读对应书源及平台接口，安装后分别以登录和实际打开书籍的结果确认。

## 你和 Agent 如何配合

| 操作 | 谁来完成 |
| --- | --- |
| 环境检查、路线判断、下载校验、文件传输和插件部署 | Agent |
| Kindle 浏览器、字体校准、打开越狱书、搜索框命令和重启确认 | 你按 Agent 的当前提示操作 |
| 手机扫码、账号确认和代表性书籍试读 | 你完成，Agent 记录结果并继续 |

Agent 会在交接时说明是否需要退出阅读器、拔下数据线或重连，以及操作后应看到什么。电脑侧使用 OpenMTP 的命令行工具，按单客户端、单批次传输并回读文件。

## 当前支持

当前电脑侧自动化适配 **macOS、Python 3.10+ 和 OpenMTP**。Agent 会检查这些依赖。

| Kindle | 固件版本 | 越狱路线 |
| --- | --- | --- |
| Colorsoft Signature Edition | `5.20.1.0.2` | Véra |

型号、固件和安装材料以[兼容清单](manifests/compatibility.json)为准。未收录的设备或固件会先给出兼容性结论；新增路线需要核对上游资料和材料。

## 安装后继续使用

在同一对话中，你可以继续说：

~~~text
继续上次的安装，先检查已经完成了哪些步骤。
帮我检查月读里的微信读书和番茄小说是否能打开书。
帮我检查本地漫画目录，先列出整理建议。
~~~

## 给 Agent 和开发者

- [Agent Skill](skill/kindle-pilot/SKILL.md)：如何接受请求、继续任务和交接触屏步骤。
- [操作工作流](docs/WORKFLOW.md)：环境准备、命令行工具、传输和验收。
- [兼容清单](manifests/compatibility.json)：已收录路线、上游地址、文件摘要和再分发策略。
- [架构说明](docs/ARCHITECTURE.md)：状态和工具各自负责的内容。

运行主机侧检查：

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
~~~

这些检查覆盖主机工具；设备安装、应用加载和账号阅读分别在实际使用中验收。

## 来源与许可

KindlePilot 自有代码采用 [MIT 许可证](LICENSE)。阅读环境依赖 KindleModding Véra、KOReader、月读和 `kindle.koplugin` 等上游项目，来源与许可证见[第三方声明](THIRD_PARTY_NOTICES.md)。

仓库保存集成代码、工作流、下载地址和校验摘要。越狱书及插件包按需从上游下载，设备资料和登录信息留在用户本地。
