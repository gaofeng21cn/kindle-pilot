# Kindle Agent Companion

Kindle Agent Companion 是一个面向 Agent 的 Kindle 设备管理仓库。它把越狱兼容性判断、Véra / KOReader / Moon 的安装材料、OpenMTP 稳定传输、状态记录和运行验收组织成可回读的工作流。

它的目标不是把越狱过程包装成不可解释的“一键黑盒”，而是让 Agent 能够在每一步回答三件事：当前设备是什么、下一步由谁完成、完成后有什么证据。设备触摸、字体校准、打开 Véra、确认 JAILBROKEN、KPM 搜索命令和微信/番茄扫码登录仍由用户在 Kindle 屏幕上完成；电脑侧的探测、下载校验、MTP 写入、插件安装和安装后回读由工具完成。

## 当前 MVP

- 兼容清单：已收录并核验 Kindle Colorsoft 5.20.1.0.2 的 Véra 路线。
- 设备探测：读取 macOS system_profiler / ioreg，输出产品名和序列号。
- 路线判断：型号、固件版本、精确构建和未知路线分别返回不同状态。
- 资产校验：所有外部文件按 SHA-256 校验；越狱书只记录来源与摘要，不随仓库再分发。
- 状态机：记录 route_supported、资产下载、传输、人工越狱、KPM、KOReader、插件和登录验收步骤。
- MTP：使用 OpenMTP mtp-cli 单批次会话，任何传输错误都会使命令失败，即使底层进程返回 0。
- Agent Skill：见 skill/kindle-agent-companion/SKILL.md。

## 快速检查

~~~sh
PYTHONPATH=src python3 -m kindle_companion --json status
PYTHONPATH=src python3 -m kindle_companion --json resolve-asset \
  fontcal.azw3 --route vera-cs-5.20.1.0.2
PYTHONPATH=src python3 -m kindle_companion verify-asset \
  /path/to/fontcal.azw3 \
  --sha256 0136b8110d490d94b9be50899fc5ce4e4a7f70c02df0ba957c3f35dcdad2d041
~~~

连接 Kindle 后，兼容性探测需要用户提供“设备信息”里看到的固件版本：

~~~sh
PYTHONPATH=src python3 -m kindle_companion --json probe \
  --firmware 5.20.1.0.2
~~~

MTP 辅助命令使用 OpenMTP 的 mtp-cli。默认查找 /Applications/OpenMTP.app/Contents/Resources/bin/mtp-cli，也可以用 KINDLE_MTP_CLI 指定路径：

~~~sh
PYTHONPATH=src python3 scripts/kindle-mtp.py storage
PYTHONPATH=src python3 scripts/kindle-mtp.py ls /documents
~~~

执行删除、上传或安装前，Agent 应先读取当前目录和存储信息，并把具体目标记录到状态证据中。工具不会删除整个 documents，也不会触摸 /koreader、/libkh 或用户的书籍缓存。

## 工作流

~~~text
USB 探测
  → 型号 / 固件路线判断
  → 官方页面下载并 SHA-256 校验
  → 单会话 MTP 传输
  → 用户完成字体校准与 Véra 触发
  → 用户确认 JAILBROKEN / KPM
  → Agent 安装 KOReader / Moon / kindle.koplugin
  → 设备重启后运行验收
  → 用户扫码登录微信读书 / 番茄小说
~~~

兼容性清单是版本化事实源，但越狱上游可能变化。新增型号或固件时，必须同时更新官方来源、精确资产摘要、人工步骤和测试，不能把相邻固件自动当成兼容。

## 资产与许可

仓库不提交越狱书和第三方发布包。manifests/compatibility.json 只保存下载地址、来源、摘要和再分发状态；Agent 在本机下载后校验，私有材料应放在未跟踪目录。

KOReader、Moon、kindle.koplugin 和 KindleModding Véra 分属不同上游项目。它们的许可证、发布权限和运行责任不能由本仓库代替确认，详见 THIRD_PARTY_NOTICES.md。

## 开发

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src scripts
~~~

本项目采用 MIT 许可证。设备安装和登录验收必须在用户自己的 Kindle 和账号上完成；仓库测试只证明主机侧解析、状态机、摘要校验和 MTP 命令合同。
