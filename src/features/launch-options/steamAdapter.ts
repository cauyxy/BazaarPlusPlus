const APP_ID = 1617400;

type AppDetails = { strLaunchOptions?: string };
type Registration = { unregister(): void };

export type SteamApps = {
  SetAppLaunchOptions(appId: number, launchOptions: string): void;
  RegisterForAppDetails(
    appId: number,
    callback: (details: AppDetails) => void,
  ): Registration;
};

declare const SteamClient: { Apps: SteamApps };

export interface SteamLaunchOptionsAdapter {
  current(): Promise<string>;
  set(value: string): void;
}

export function createSteamLaunchOptionsAdapter(
  apps: SteamApps = SteamClient.Apps,
  timeoutMs = 3000,
): SteamLaunchOptionsAdapter {
  return {
    current() {
      return new Promise((resolve, reject) => {
        let settled = false;
        let registration: Registration | undefined;
        const timer = globalThis.setTimeout(() => {
          if (!settled) {
            settled = true;
            registration?.unregister();
            reject(new Error("读取 Steam 启动参数超时"));
          }
        }, timeoutMs);

        registration = apps.RegisterForAppDetails(APP_ID, (details) => {
          if (settled) {
            return;
          }
          settled = true;
          globalThis.clearTimeout(timer);
          resolve(details.strLaunchOptions?.trim() ?? "");
          queueMicrotask(() => registration?.unregister());
        });
      });
    },
    set(value) {
      apps.SetAppLaunchOptions(APP_ID, value);
    },
  };
}
