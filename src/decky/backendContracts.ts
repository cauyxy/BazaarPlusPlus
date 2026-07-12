export type PluginStatus = {
  game_found: boolean;
  game_path: string | null;
  game_running: boolean;
  installed: boolean;
  installed_version: string | null;
};

export type LatestRelease = {
  version: string;
  update_available: boolean;
};

export type LaunchOptionsBackup = {
  original: string;
  managed: string;
} | null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

export function decodePluginStatus(value: unknown): PluginStatus {
  if (
    !isRecord(value) ||
    typeof value.game_found !== "boolean" ||
    !isNullableString(value.game_path) ||
    typeof value.game_running !== "boolean" ||
    typeof value.installed !== "boolean" ||
    !isNullableString(value.installed_version)
  ) {
    throw new Error("后端返回了无效的安装状态");
  }
  return {
    game_found: value.game_found,
    game_path: value.game_path,
    game_running: value.game_running,
    installed: value.installed,
    installed_version: value.installed_version,
  };
}

export function decodeLatestRelease(value: unknown): LatestRelease {
  if (
    !isRecord(value) ||
    typeof value.version !== "string" ||
    typeof value.update_available !== "boolean"
  ) {
    throw new Error("后端返回了无效的发布信息");
  }
  return {
    version: value.version,
    update_available: value.update_available,
  };
}

export function decodeLaunchOptionsBackup(value: unknown): LaunchOptionsBackup {
  if (value === null) {
    return null;
  }
  if (
    !isRecord(value) ||
    typeof value.original !== "string" ||
    typeof value.managed !== "string"
  ) {
    throw new Error("后端返回了无效的启动参数备份");
  }
  return { original: value.original, managed: value.managed };
}
