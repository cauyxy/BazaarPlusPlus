<div align="center">

# BazaarPlusPlus for Steam Deck

在 Steam Deck 上安装与管理 [《The Bazaar》](https://www.playthebazaar.com) 的 [BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus) 模组

[English](README_en.md) · [官网](https://bazaarplusplus.com) · [使用教程](https://bazaarplusplus.com/tutorial) · [BazaarPlusPlus 主仓库](https://github.com/cauyxy/BazaarPlusPlus) · [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

[![Version](https://img.shields.io/badge/version-0.2.0-6dd9a0?style=flat-square)](package.json)
[![License](https://img.shields.io/badge/license-MIT-e8c87a?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Steam%20Deck-c1875a?style=flat-square)](https://store.steampowered.com/steamdeck)
[![Decky Loader](https://img.shields.io/badge/Decky%20Loader-plugin-3d5afe?style=flat-square)](https://github.com/SteamDeckHomebrew/decky-loader)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)](https://www.python.org)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square)](https://react.dev)

</div>

---

BazaarPlusPlus for Steam Deck 是一个 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 插件，负责在 Steam Deck 上安装、更新、修复和卸载《The Bazaar》的 BazaarPlusPlus 模组。本仓库仅包含 Steam Deck 插件；模组本体、游戏内功能和桌面端安装器的相关信息见 [BazaarPlusPlus 主仓库](https://github.com/cauyxy/BazaarPlusPlus)。

本插件不内置模组或安装器源码：安装时它从 BazaarPlusPlus 官方发布源读取发布清单，下载最新版 Windows x86_64 安装器，用 7-Zip 从中提取 `BepInExSource/BepInEx.zip`，校验安装内容后写入 Steam 游戏目录，并为 Proton 配置所需的启动参数。

## 快速开始

1. 安装并至少启动一次《The Bazaar》（Steam 版，App ID `1617400`），然后完全退出游戏。
2. 安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)，并在其开发者设置中启用从 ZIP 安装插件。
3. 下载（或[从源码构建](#从源码构建)）`BazaarPlusPlus-<version>.zip`，通过 Decky 安装。
4. 在快捷菜单中打开 BazaarPlusPlus，选择「安装 BazaarPlusPlus」，等待下载与解包完成。
5. 启动游戏，确认 BazaarPlusPlus 已正常加载。

首次安装需要能访问 BazaarPlusPlus 官方发布源和 GitHub。安装完成后，插件会为游戏加入 Proton 所需的启动参数：

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

插件会尽量保留已有启动参数。卸载模组时，如果启动参数仍与插件记录的一致，插件会恢复安装前的原始值。

## 功能概览

- **安装 / 更新 / 重装**：读取官方发布清单，比较本地已装版本并安装最新版。
- **游戏目录检测**：自动在内置存储和 SD 卡中的 Steam 库里定位《The Bazaar》。
- **修复启动参数**：补充或修正 Proton 所需的启动参数。
- **重置本地数据**：删除游戏目录下的 `BazaarPlusPlusV4/` 数据目录。
- **卸载模组**：移除模组文件；检测到其他 BepInEx 插件时保留共享依赖。
- **进度反馈**：安装过程中显示当前阶段和下载进度。

安装、修复、重置和卸载前必须先退出游戏。直接删除 Decky 插件不会删除已写入游戏目录的模组文件；请先在插件面板中执行「卸载模组」。

## 安全措施

插件后端在下载与写入过程中会：

- 只接受官方发布主机上的 HTTPS URL 和预期路径
- 拒绝跨主机重定向和异常路径
- 按固定 SHA-256 摘要校验下载的 7-Zip 工具
- 限制发布清单、下载文件和解压内容的大小
- 拒绝 ZIP 路径穿越和符号链接
- 校验安装内容中的必需文件和版本号
- 使用临时文件和备份写入游戏目录，失败时回滚

## 从源码构建

需要 Node.js、pnpm 9+ 和 Python 3.11+。

```bash
pnpm install --frozen-lockfile
pnpm run bundle
```

`pnpm run bundle` 会依次执行 TypeScript 类型检查、TypeScript / Python 单元测试和 Rollup 构建，成品位于：

```text
.build/package/BazaarPlusPlus-<version>.zip
```

## 仓库结构

```text
.
├── main.py                        # 仅暴露 Decky Plugin
├── backend/bpp/                   # 后端领域、安装与 Decky adapter
├── src/
│   ├── index.tsx                  # 插件注册入口
│   ├── decky/                     # 集中式后端 RPC client
│   └── features/                  # installer 与 launch-options 功能
├── tests/backend/                 # 后端模块与架构测试
├── tests/packaging/               # 最终 zip import smoke test
├── plugin.json                    # Decky 插件元数据
├── package.json                   # 依赖与构建命令
├── pnpm-lock.yaml                 # 可复现依赖锁定
├── rollup.config.js
├── tsconfig.json
└── scripts/build-plugin.sh        # bundle 打包脚本
```

## 二次开发须知

如果你计划基于本项目进行二次开发，请遵守《The Bazaar》官方 Mod Policy：

[The Bazaar Mod Policy](https://www.playthebazaar.com/mod-policy)

## 致谢

- **模组本体**：[BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus)（作者：[cauyxy](https://github.com/cauyxy)）
- **运行依赖**：[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)、[BepInEx](https://github.com/BepInEx/BepInEx)、[7-Zip](https://www.7-zip.org)
- **脚手架**：[Decky Plugin Template](https://github.com/SteamDeckHomebrew/decky-plugin-template)

## 许可证

本项目采用 [MIT License](LICENSE)。Decky Plugin Template 相关部分保留其 BSD 3-Clause License 声明。
