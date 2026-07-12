import type { BackendClient } from "../../decky/backendClient.js";
import { planConfigure, planRestore, type LaunchEffect } from "./model.js";
import type { SteamLaunchOptionsAdapter } from "./steamAdapter.js";

export interface LaunchOptionsManager {
  configure(): Promise<void>;
  restore(): Promise<void>;
}

async function applyEffect(
  effect: LaunchEffect,
  backend: BackendClient,
  steam: SteamLaunchOptionsAdapter,
): Promise<void> {
  if (effect.saveBackup) {
    await backend.rememberLaunchOptions(
      effect.saveBackup.original,
      effect.saveBackup.managed,
    );
  }
  if (effect.setLaunchOptions !== null) {
    steam.set(effect.setLaunchOptions);
  }
  if (effect.clearBackup) {
    await backend.clearLaunchOptionsBackup();
  }
}

export function createLaunchOptionsManager(
  backend: BackendClient,
  steam: SteamLaunchOptionsAdapter,
): LaunchOptionsManager {
  async function snapshot() {
    const current = await steam.current();
    const backup = await backend.getLaunchOptionsBackup();
    return { current, backup };
  }

  return {
    async configure() {
      await applyEffect(planConfigure(await snapshot()), backend, steam);
    },
    async restore() {
      await applyEffect(planRestore(await snapshot()), backend, steam);
    },
  };
}
