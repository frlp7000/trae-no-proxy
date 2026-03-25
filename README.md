# Trae Custom Endpoint Patch

这个项目把 Trae CN 和 Trae 的自定义端点补丁整理成了一个可以直接发布和复用的小工具，核心目标不是做 MITM，而是直接补客户端侧能力，让普通用户也能稳定看到并使用自定义端点相关入口。

它包含两部分：
- 客户端补丁：打开 Trae CN / Trae 里与自定义模型管理相关的前端入口，并把请求策略固定到 local。
- 可选 relay：只在某些网关对 tool 历史消息兼容不好时使用，用来兼容 role=tool 的 content 数组格式。

## 当前支持

- 支持 Trae CN
- 支持 Trae
- 自动搜索常见安装位置和 settings.json
- 也支持用命令行参数或环境变量手动覆盖自动发现结果
- 支持首页状态面板式交互菜单，直接查看客户端状态和 relay 状态
- 首页可直接启动 / 停止 relay，进入客户端页后也能继续管理 relay
- 会记住上次使用的 relay 地址、端口和日志目录，减少重复输入

## 功能概览

- 自动识别常见 Trae CN / Trae 安装目录和 settings.json 位置
- 一条命令同时补 bundle 和 settings
- 每次修改前自动备份
- 支持查看备份、回滚 bundle、回滚 settings、整体验证
- 提供 doctor 命令，快速判断当前客户端是否已经具备可用的自定义端点能力
- 提供首页状态面板式 CLI 菜单，可直接进入客户端管理或一键修补
- 提供独立 relay，方便排查 newapi 或自建网关对 tool message 的兼容性问题
- 自带 unittest、pyproject.toml、GitHub Actions 工作流、协议对照文档和 PowerShell 示例脚本
- GitHub Actions 会在 Windows runner 上自动构建 `trae-patch.exe` 和 zip 包

## 自动发现顺序

默认按下面顺序找路径：
- 显式传入 --app-root / --settings-file
- 环境变量 TRAE_APP_ROOT / TRAE_SETTINGS_FILE
- 常见安装目录，例如 D:/soft/Trae CN、D:/soft/Trae、C:/Program Files/Trae CN、C:/Program Files/Trae
- 用户目录下的常见安装位置和 Roaming 配置目录

## 安装

在仓库根目录执行：

~~~bash
python -m pip install -e .
~~~

安装后可用命令：

~~~bash
trae-patch
python -m trae_custom_endpoint_patch
~~~

如果你不想在本地装 Python，也可以直接下载 GitHub 打好的 Windows 包：
- 如果你打了版本 tag，直接去 `Releases` 下载 `trae-patch-windows-x64.zip`
- 如果只是普通 push 或手动触发，去 `Actions` 里下载产物 `trae-patch-windows-x64`
- 解压后直接运行 `trae-patch.exe`

## 快速开始

最省事的用法是直接打开交互菜单：

~~~bash
trae-patch
~~~

如果你想显式进入菜单，也可以：

~~~bash
trae-patch menu
~~~

菜单首页会显示已发现客户端的状态面板，以及 relay 的当前状态、上游和日志目录。

首页常用操作：
- 直接输入客户端编号进入该客户端管理页
- P：选择一个客户端并一键修补
- R：启动 relay；如果 relay 已在运行，则同一个键会变成停止 relay
- S：查看 relay 详情
- M：手动输入 app_root / settings.json 路径

进入客户端管理页后，可以继续做这些事：
- 一键修补客户端
- 查看当前状态和详细状态
- 查看备份或恢复最近一次备份
- 直接启动 / 停止 relay，或查看 relay 详情

如果你的安装位置比较常规，也可以继续直接用命令：

~~~bash
trae-patch doctor
trae-patch patch-all
trae-patch inspect
~~~

再次确认补丁是否已经生效：

~~~bash
trae-patch doctor
~~~

如果你的安装位置不标准，再显式指定：

~~~bash
trae-patch doctor --app-root D:/soft/Trae --settings-file C:/Users/你的用户名/AppData/Roaming/Trae/User/settings.json
~~~

## 常用命令

查看状态：

~~~bash
trae-patch doctor
trae-patch inspect
~~~

应用补丁：

~~~bash
trae-patch patch-bundle
trae-patch patch-settings
trae-patch patch-all
~~~

如果要手动指定路径：

~~~bash
trae-patch patch-all --app-root D:/soft/Trae CN --settings-file C:/Users/你的用户名/AppData/Roaming/Trae CN/User/settings.json
~~~

查看备份：

~~~bash
trae-patch list-backups
~~~

恢复最近一次备份：

~~~bash
trae-patch restore-bundle
trae-patch restore-settings
trae-patch restore-all
~~~

指定某个备份文件恢复：

~~~bash
trae-patch restore-bundle --app-root D:/soft/Trae CN --backup D:/soft/Trae CN/resources/app/node_modules/@byted-icube/ai-modules-chat/dist/index.js.bak-trae-patch-20260324-103000
~~~

## 环境变量

如果你不想每次都传路径，可以设置 TRAE_APP_ROOT 和 TRAE_SETTINGS_FILE。

设置后可以直接运行：

~~~bash
trae-patch
trae-patch doctor
trae-patch patch-all
~~~

## Relay 什么时候需要

只有在你的网关对 tool message 不兼容时才建议启用 relay。典型现象包括：
- 明明模型本身正常，但 Trae 内部请求总是 502 或 524
- 直连 curl 可以成功，Trae 发起带 tool 历史消息的请求却失败
- role=tool 且 content 为数组时，上游网关不能正确处理

命令行启动 relay：

~~~bash
trae-patch relay --upstream-base https://your.gateway.example/v1
~~~

这个命令现在会把 relay 作为后台进程启动，不会阻塞当前终端。

查看 relay 状态或停止 relay：

~~~bash
trae-patch relay-status
trae-patch relay-stop
~~~

菜单启动 relay 时默认只要求输入 upstream-base。
- 直接回车会复用上次或默认的监听地址、端口和日志目录
- 只有输入 y 才会进入高级设置，手动修改 host / port / log-dir
- relay-status 和 relay-stop 默认也会使用上次记住的 log-dir

对应的 PowerShell 示例脚本：
- examples/check-trae-cn.ps1
- examples/patch-trae-cn.ps1
- examples/run-relay.ps1

## 项目结构

- src/trae_custom_endpoint_patch/patcher.py: 客户端补丁、路径发现、备份、恢复、doctor
- src/trae_custom_endpoint_patch/cli.py: 命令行入口和交互式菜单
- src/trae_custom_endpoint_patch/relay.py: 可选兼容 relay
- docs/protocol-matrix.md: Trae 实际协议痕迹、官方协议、常见网关兼容面的对照
- examples/*.ps1: Windows PowerShell 示例脚本
- scripts/build-exe.ps1: Windows 本地和 GitHub Actions 共用的打包脚本
- tools/trae_newapi_tap.py: 调试网关兼容性时使用的抓包/重放辅助脚本
- tests/test_project.py: 单元测试
- .github/workflows/python.yml: GitHub Actions 测试、artifact 打包和 release 发布工作流

## 发布建议

发到 GitHub 之前建议你再做两件事：
- 选一个你自己的开源许可证并补上 LICENSE 文件
- 把仓库名和项目首页链接填到 pyproject.toml
