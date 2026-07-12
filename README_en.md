<div align="center">

# BazaarPlusPlus for Steam Deck

Install and manage the [BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus) mod for [*The Bazaar*](https://www.playthebazaar.com) on Steam Deck

[中文](README.md) · [Website](https://bazaarplusplus.com) · [Tutorial](https://bazaarplusplus.com/tutorial) · [BazaarPlusPlus main repo](https://github.com/cauyxy/BazaarPlusPlus) · [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

[![Version](https://img.shields.io/badge/version-0.2.0-6dd9a0?style=flat-square)](package.json)
[![License](https://img.shields.io/badge/license-MIT-e8c87a?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Steam%20Deck-c1875a?style=flat-square)](https://store.steampowered.com/steamdeck)
[![Decky Loader](https://img.shields.io/badge/Decky%20Loader-plugin-3d5afe?style=flat-square)](https://github.com/SteamDeckHomebrew/decky-loader)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square)](https://www.python.org)
[![React](https://img.shields.io/badge/React-19-61dafb?style=flat-square)](https://react.dev)

</div>

---

BazaarPlusPlus for Steam Deck is a [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that installs, updates, repairs, and removes the BazaarPlusPlus mod for *The Bazaar* on Steam Deck. This repository contains only the Steam Deck plugin; see the [BazaarPlusPlus upstream repository](https://github.com/cauyxy/BazaarPlusPlus) for the mod itself, its in-game features, and desktop installers.

The plugin does not bundle the mod or installer source. During installation it reads the release manifest from the official BazaarPlusPlus release host, downloads the latest Windows x86_64 installer, extracts `BepInExSource/BepInEx.zip` from it with 7-Zip, validates the installation payload, writes it into the Steam game directory, and configures the launch option Proton needs.

## Quick start

1. Install and launch *The Bazaar* (Steam version, App ID `1617400`) at least once, then exit the game completely.
2. Install [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) and enable ZIP plugin installation in its developer settings.
3. Download (or [build from source](#build-from-source)) `BazaarPlusPlus-<version>.zip` and install it through Decky.
4. Open BazaarPlusPlus in the Quick Access Menu, select **Install BazaarPlusPlus**, and wait for the download and extraction to finish.
5. Launch the game and confirm that BazaarPlusPlus loads correctly.

The first installation requires network access to the official BazaarPlusPlus release host and GitHub. After installation the plugin adds the launch option Proton requires:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

Existing launch options are preserved where possible. When the mod is removed, the plugin restores the original value if the current options still match the value it managed.

## Features

- **Install / update / reinstall**: reads the official release manifest, compares it against the installed version, and installs the latest release.
- **Game detection**: locates *The Bazaar* in Steam libraries on internal storage and SD cards.
- **Repair launch options**: adds or corrects the launch option required by Proton.
- **Reset local data**: removes the `BazaarPlusPlusV4/` data directory from the game directory.
- **Uninstall**: removes mod files, preserving shared dependencies when other BepInEx plugins exist.
- **Progress reporting**: shows the current installation stage and download progress.

Exit the game before installing, repairing, resetting, or removing the mod. Deleting the Decky plugin does not remove files already written into the game directory; use **Uninstall mod** in the plugin panel first.

## Security

While downloading and writing files, the plugin backend:

- Accepts only HTTPS URLs on the official release host and expected paths
- Rejects cross-host redirects and malformed paths
- Verifies the downloaded 7-Zip tool against a fixed SHA-256 digest
- Limits manifest, download, and extracted payload sizes
- Rejects ZIP path traversal and symbolic links
- Validates required payload files and the payload version
- Writes files through temporary paths with backups and rolls back failed writes

## Build from source

Node.js, pnpm 9+, and Python 3.11+ are required.

```bash
pnpm install --frozen-lockfile
pnpm run bundle
```

`pnpm run bundle` runs TypeScript type checking, the TypeScript / Python unit tests, and the Rollup build. The installable artifact is written to:

```text
.build/package/BazaarPlusPlus-<version>.zip
```

## Repository layout

```text
.
├── main.py                        # Exposes only the Decky Plugin
├── backend/bpp/                   # Backend domain, installer, and Decky adapter
├── src/
│   ├── index.tsx                  # Plugin registration entrypoint
│   ├── decky/                     # Central backend RPC client
│   └── features/                  # Installer and launch-options features
├── tests/backend/                 # Backend module and architecture tests
├── tests/packaging/               # Final zip import smoke test
├── plugin.json                    # Decky plugin metadata
├── package.json                   # Dependencies and build commands
├── pnpm-lock.yaml                 # Reproducible dependency lock
├── rollup.config.js
├── tsconfig.json
└── scripts/build-plugin.sh        # Bundle packaging script
```

## Modding policy

If you plan to build on this project, please follow the official *The Bazaar* Mod Policy:

[The Bazaar Mod Policy](https://www.playthebazaar.com/mod-policy)

## Acknowledgements

- **Upstream mod**: [BazaarPlusPlus](https://github.com/cauyxy/BazaarPlusPlus) (by [cauyxy](https://github.com/cauyxy))
- **Runtime dependencies**: [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader), [BepInEx](https://github.com/BepInEx/BepInEx), [7-Zip](https://www.7-zip.org)
- **Scaffolding**: [Decky Plugin Template](https://github.com/SteamDeckHomebrew/decky-plugin-template)

## License

Released under the [MIT License](LICENSE). Decky Plugin Template-derived portions retain their BSD 3-Clause License notice.
