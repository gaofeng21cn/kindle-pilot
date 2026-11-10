# KindlePilot 视觉资产

`wireless-cover.png` 是 Wireless 入口的 600×800 PNG 封面，由内置 imagegen 生成，再缩小并优化文件大小。原始生成稿保留在本机；最终提示词见 [wireless-cover.prompt.txt](wireless-cover.prompt.txt)。

`kindlepilot.koplugin/` 是 KOReader 内的 KindlePilot 配对插件源码。它复用 KOReader 的 Dropbear/SSH 环境；封面属于旧原生 Wireless 入口的兼容资产。

`prepare_session` 核对兼容清单摘要，并将其写入启动脚本的 `# Icon: data:image/png;base64,...` 元数据。无需在设备上另放一份图片。

![Wireless 封面](wireless-cover.png)
