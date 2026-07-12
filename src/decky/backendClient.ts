import { callable } from "@decky/api";

import {
  decodeLatestRelease,
  decodeLaunchOptionsBackup,
  decodePluginStatus,
  type LatestRelease,
  type LaunchOptionsBackup,
  type PluginStatus,
} from "./backendContracts.js";

export type { LatestRelease, LaunchOptionsBackup, PluginStatus };

export interface BackendClient {
  getStatus(): Promise<PluginStatus>;
  checkLatest(): Promise<LatestRelease>;
  installLatest(): Promise<PluginStatus>;
  uninstallMod(): Promise<PluginStatus>;
  resetData(): Promise<PluginStatus>;
  rememberLaunchOptions(original: string, managed: string): Promise<void>;
  getLaunchOptionsBackup(): Promise<LaunchOptionsBackup>;
  clearLaunchOptionsBackup(): Promise<void>;
}

const getStatusRpc = callable<[], unknown>("get_status");
const checkLatestRpc = callable<[], unknown>("check_latest");
const installLatestRpc = callable<[], unknown>("install_latest");
const uninstallModRpc = callable<[], unknown>("uninstall_mod");
const resetDataRpc = callable<[], unknown>("reset_data");
const rememberLaunchOptionsRpc = callable<
  [original: string, managed: string],
  void
>("remember_launch_options");
const getLaunchOptionsBackupRpc = callable<[], unknown>(
  "get_launch_options_backup",
);
const clearLaunchOptionsBackupRpc = callable<[], void>(
  "clear_launch_options_backup",
);

export const backendClient: BackendClient = {
  async getStatus() {
    return decodePluginStatus(await getStatusRpc());
  },
  async checkLatest() {
    return decodeLatestRelease(await checkLatestRpc());
  },
  async installLatest() {
    return decodePluginStatus(await installLatestRpc());
  },
  async uninstallMod() {
    return decodePluginStatus(await uninstallModRpc());
  },
  async resetData() {
    return decodePluginStatus(await resetDataRpc());
  },
  rememberLaunchOptions: rememberLaunchOptionsRpc,
  async getLaunchOptionsBackup() {
    return decodeLaunchOptionsBackup(await getLaunchOptionsBackupRpc());
  },
  clearLaunchOptionsBackup: clearLaunchOptionsBackupRpc,
};
