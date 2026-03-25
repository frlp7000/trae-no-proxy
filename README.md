# Trae No Proxy

`Trae No Proxy` 是一个面向 `Trae CN` 和 `Trae` 的本地补丁工具。目标不是做 MITM，也不是劫持官方域名，而是直接补客户端侧入口，让普通用户可以启用和配置自定义端点，并在需要时配合本地 relay 处理部分网关兼容问题。

项目包含两部分：
- 客户端补丁：打开自定义模型管理相关入口，并把请求策略固定到 `local`
- 可选 relay：在少数网关对 `tool` 历史消息兼容不完整时，做本地协议适配

## 功能

- 支持 `Trae CN` 和 `Trae`
- 自动搜索常见安装目录和 `settings.json`
- 支持命令行参数和环境变量覆盖自动发现结果
- 一键补丁 `bundle + settings`
- 修改前自动备份，支持查看和回滚
- 提供 `doctor`、`inspect`、`patch-all` 等常用命令
- 提供交互式菜单，直接在菜单里选择客户端、修补、查看状态、管理 relay
- relay 以后台子进程运行，可随时查看状态或停止
- GitHub Actions 可自动构建 Windows 可执行文件和发布包

## 安装

本地安装：

```bash
python -m pip install -e .
```

安装后可直接运行：

```bash
trae-patch
python -m trae_custom_endpoint_patch
```

如果不想本地装 Python，可以直接下载 Windows 构建产物：
- 发布版本到 `Releases` 下载 `trae-patch-windows-x64.zip`
- 普通 push 或手动触发到 `Actions` 下载 `trae-patch-windows-x64`

## 快速开始

直接进入交互菜单：

```bash
trae-patch
```

或显式打开菜单：

```bash
trae-patch menu
```

如果路径能自动发现，通常只需要两步：

```bash
trae-patch doctor
trae-patch patch-all
```

路径不标准时，可以手动指定：

```bash
trae-patch patch-all --app-root D:/soft/Trae CN --settings-file C:/Users/你的用户名/AppData/Roaming/Trae CN/User/settings.json
```

## 常用命令

查看状态：

```bash
trae-patch doctor
trae-patch inspect
```

应用补丁：

```bash
trae-patch patch-bundle
trae-patch patch-settings
trae-patch patch-all
```

查看或恢复备份：

```bash
trae-patch list-backups
trae-patch restore-bundle
trae-patch restore-settings
trae-patch restore-all
```

## Relay

只有在你的网关对 `tool` 历史消息兼容不好时，才建议启用 relay。常见现象包括：
- 模型本身可用，但 Trae 内请求持续报 `400`、`502`、`524`
- `curl` 直连最小请求成功，Trae 的真实请求失败
- 上游不接受 `role=tool` 或 `content` 数组形式

启动 relay：

```bash
trae-patch relay --upstream-base https://your.gateway.example/v1
```

查看状态或停止 relay：

```bash
trae-patch relay-status
trae-patch relay-stop
```

菜单里也可以直接启动或停止 relay，不需要每次重新输入完整命令。

## 环境变量

如果不想反复传路径，可以设置：
- `TRAE_APP_ROOT`
- `TRAE_SETTINGS_FILE`

设置后可直接运行：

```bash
trae-patch
trae-patch doctor
trae-patch patch-all
```

## 项目结构

- `src/trae_custom_endpoint_patch/patcher.py`: 路径发现、补丁、备份、恢复、校验
- `src/trae_custom_endpoint_patch/cli.py`: CLI 和交互菜单
- `src/trae_custom_endpoint_patch/relay.py`: 本地 relay
- `examples/*.ps1`: Windows PowerShell 示例
- `scripts/build-exe.ps1`: Windows 打包脚本
- `tools/trae_newapi_tap.py`: 调试辅助脚本
- `tests/test_project.py`: 单元测试

## 免责声明

- 本项目是非官方第三方工具，与 `Trae`、`Trae CN`、字节跳动、OpenAI 及其他模型服务商没有任何隶属、授权或背书关系。
- 本项目会修改你本地安装目录中的客户端文件和配置。使用前应自行备份，并确认你知道这些修改会带来的影响。
- 本项目仅适用于你有权控制、测试和修改的设备、客户端实例和网络环境。
- 你需要自行确认使用行为符合相关服务条款、法律法规、公司规范以及上游网关的使用限制。
- 对于因使用本项目导致的账号限制、功能异常、客户端损坏、数据丢失、封禁、服务中断或其他直接和间接损失，项目作者不承担责任。
