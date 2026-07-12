import type {
  BackendClient,
  LatestRelease,
  PluginStatus,
} from "../../decky/backendClient.js";
import type { LaunchOptionsManager } from "../launch-options/manager.js";

export type OperationOutcome =
  | { kind: "succeeded"; message: string; status: PluginStatus }
  | {
      kind: "partiallySucceeded";
      message: string;
      status: PluginStatus;
      repair: "configure" | "restore";
      cause: unknown;
    }
  | { kind: "failed"; message: string; cause: unknown };

export async function refreshInstallerState(
  backend: BackendClient,
  onLatestError: (error: unknown) => void = () => undefined,
): Promise<{
  status: PluginStatus;
  latest: LatestRelease | null;
  repairMode: "restore" | undefined;
}> {
  const status = await backend.getStatus();
  const repairMode =
    !status.installed && (await backend.getLaunchOptionsBackup()) !== null
      ? "restore"
      : undefined;
  try {
    return { status, latest: await backend.checkLatest(), repairMode };
  } catch (error) {
    onLatestError(error);
    return { status, latest: null, repairMode };
  }
}

export function subscribeInstallProgress<T>(
  add: (callback: (message: string, percent: number) => void) => T,
  remove: (listener: T) => void,
  update: (text: string) => void,
): () => void {
  const listener = add((message, percent) => update(`${message} ${percent}%`));
  return () => remove(listener);
}

export function preserveRepairMode(
  current: "configure" | "restore" | null,
  discovered: "restore" | undefined,
): "configure" | "restore" | null {
  return discovered ?? current;
}

export async function installWithLaunchOptions(
  backend: BackendClient,
  launchOptions: LaunchOptionsManager,
): Promise<OperationOutcome> {
  let status: PluginStatus;
  try {
    status = await backend.installLatest();
  } catch (cause) {
    return { kind: "failed", message: "模组安装失败", cause };
  }
  try {
    await launchOptions.configure();
    return {
      kind: "succeeded",
      message: "安装完成，Steam 启动参数已配置。",
      status,
    };
  } catch (cause) {
    return {
      kind: "partiallySucceeded",
      message: "模组已安装，但启动参数配置失败。",
      status,
      repair: "configure",
      cause,
    };
  }
}

export async function uninstallWithLaunchOptions(
  backend: BackendClient,
  launchOptions: LaunchOptionsManager,
): Promise<OperationOutcome> {
  let status: PluginStatus;
  try {
    status = await backend.uninstallMod();
  } catch (cause) {
    return { kind: "failed", message: "模组卸载失败", cause };
  }
  try {
    await launchOptions.restore();
    return {
      kind: "succeeded",
      message: "模组已卸载，启动参数已恢复。",
      status,
    };
  } catch (cause) {
    return {
      kind: "partiallySucceeded",
      message: "模组已卸载，但启动参数恢复失败。",
      status,
      repair: "restore",
      cause,
    };
  }
}
