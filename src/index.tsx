import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api";
import { useCallback, useEffect, useState } from "react";
import { FaStore } from "react-icons/fa";
import {
  planConfigure,
  planRestore,
  type LaunchEffect,
  type LaunchOptionsBackup,
} from "./launchOptions";

const APP_ID = 1617400;

type PluginStatus = {
  game_found: boolean;
  game_path: string | null;
  game_running: boolean;
  installed: boolean;
  installed_version: string | null;
};

type LatestRelease = {
  version: string;
  update_available: boolean;
};

declare const SteamClient: {
  Apps: {
    SetAppLaunchOptions(appId: number, launchOptions: string): void;
    RegisterForAppDetails(
      appId: number,
      callback: (details: { strLaunchOptions?: string }) => void,
    ): { unregister(): void };
  };
};

const getStatus = callable<[], PluginStatus>("get_status");
const checkLatest = callable<[], LatestRelease>("check_latest");
const installLatest = callable<[], PluginStatus>("install_latest");
const uninstallMod = callable<[], PluginStatus>("uninstall_mod");
const resetData = callable<[], PluginStatus>("reset_data");
const rememberLaunchOptions = callable<
  [original: string, managed: string],
  void
>("remember_launch_options");
const getLaunchOptionsBackup =
  callable<[], LaunchOptionsBackup>("get_launch_options_backup");
const clearLaunchOptionsBackup =
  callable<[], void>("clear_launch_options_backup");

function currentLaunchOptions(): Promise<string> {
  return new Promise((resolve, reject) => {
    let settled = false;
    let registration: { unregister(): void } | undefined;
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        registration?.unregister();
        reject(new Error("读取 Steam 启动参数超时"));
      }
    }, 3000);

    registration = SteamClient.Apps.RegisterForAppDetails(APP_ID, (details) => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timer);
      resolve(details.strLaunchOptions?.trim() ?? "");
      queueMicrotask(() => registration?.unregister());
    });
  });
}

async function applyLaunchEffect(effect: LaunchEffect): Promise<void> {
  if (effect.saveBackup) {
    await rememberLaunchOptions(effect.saveBackup.original, effect.saveBackup.managed);
  }
  if (effect.setLaunchOptions !== null) {
    SteamClient.Apps.SetAppLaunchOptions(APP_ID, effect.setLaunchOptions);
  }
  if (effect.clearBackup) {
    await clearLaunchOptionsBackup();
  }
}

async function configureLaunchOptions(): Promise<void> {
  const current = await currentLaunchOptions();
  const backup = await getLaunchOptionsBackup();
  await applyLaunchEffect(planConfigure({ current, backup }));
}

async function restoreLaunchOptions(): Promise<void> {
  const current = await currentLaunchOptions();
  const backup = await getLaunchOptionsBackup();
  await applyLaunchEffect(planRestore({ current, backup }));
}

function StatusCard({
  status,
  latest,
}: {
  status: PluginStatus | null;
  latest: LatestRelease | null;
}) {
  if (!status) {
    return <div style={{ opacity: 0.7 }}>正在检测…</div>;
  }

  const stateText = !status.game_found
    ? "未找到 Steam 版《The Bazaar》"
    : status.installed
      ? `已安装 ${status.installed_version ?? "未知版本"}`
      : "尚未安装";

  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 8,
        background: "rgba(255,255,255,.08)",
        lineHeight: 1.45,
      }}
    >
      <div>{stateText}</div>
      {latest && <div style={{ opacity: 0.7 }}>最新版：{latest.version}</div>}
      {status.game_path && (
        <div style={{ opacity: 0.55, fontSize: 11, wordBreak: "break-all" }}>
          {status.game_path}
        </div>
      )}
      {status.game_running && (
        <div style={{ color: "#ffc46b" }}>请先退出游戏再执行安装操作。</div>
      )}
    </div>
  );
}

function Content() {
  const [status, setStatus] = useState<PluginStatus | null>(null);
  const [latest, setLatest] = useState<LatestRelease | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");

  const refresh = useCallback(async () => {
    const localStatus = await getStatus();
    setStatus(localStatus);
    try {
      const release = await checkLatest();
      setLatest(release);
    } catch (error) {
      console.warn("Unable to check BazaarPlusPlus release", error);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (action: () => Promise<PluginStatus>, done: string) => {
    setBusy(true);
    try {
      const next = await action();
      setStatus(next);
      toaster.toast({ title: "BazaarPlusPlus", body: done });
    } catch (error) {
      toaster.toast({
        title: "BazaarPlusPlus 操作失败",
        body: String(error),
        critical: true,
      });
    } finally {
      setBusy(false);
      setProgress("");
      void refresh();
    }
  };

  useEffect(() => {
    const listener = addEventListener<[message: string, percent: number]>(
      "install_progress",
      (message, percent) => setProgress(`${message} ${percent}%`),
    );
    return () => removeEventListener("install_progress", listener);
  }, []);

  const install = () =>
    run(async () => {
      const next = await installLatest();
      await configureLaunchOptions();
      return next;
    }, "安装完成，Steam 启动参数已配置。");

  const uninstall = () =>
    run(async () => {
      const next = await uninstallMod();
      await restoreLaunchOptions();
      return next;
    }, "模组已卸载，启动参数已恢复。");

  const repairLaunchOptions = async () => {
    try {
      await configureLaunchOptions();
      toaster.toast({
        title: "BazaarPlusPlus",
        body: "Steam 启动参数已修复。",
      });
    } catch (error) {
      toaster.toast({
        title: "启动参数修复失败",
        body: String(error),
        critical: true,
      });
    }
  };

  const updateAvailable = latest?.update_available ?? false;

  return (
    <>
      <PanelSection title="Steam Deck 安装状态">
        <PanelSectionRow>
          <StatusCard status={status} latest={latest} />
        </PanelSectionRow>
        {progress && (
          <PanelSectionRow>
            <div style={{ opacity: 0.75 }}>{progress}</div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="操作">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={
              busy ||
              !status?.game_found ||
              status.game_running ||
              Boolean(status?.installed && !updateAvailable)
            }
            onClick={install}
          >
            {busy
              ? "处理中…"
              : updateAvailable
                ? `更新到 ${latest?.version}`
                : "安装 BazaarPlusPlus"}
          </ButtonItem>
        </PanelSectionRow>
        {status?.installed && (
          <>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={install}
              >
                重新安装 / 修复
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={repairLaunchOptions}
              >
                修复 Steam 启动参数
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={() => run(resetData, "本地对局数据已重置。")}
              >
                重置 BazaarPlusPlus 本地数据
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy || status.game_running}
                onClick={uninstall}
              >
                卸载模组
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={refresh}>
            刷新状态
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="说明">
        <PanelSectionRow>
          <div style={{ fontSize: 12, opacity: 0.7, lineHeight: 1.45 }}>
            首次安装约下载 70 MB。请先启动一次《The Bazaar》并退出，再执行安装。
            模组仍在游戏内运行；本插件只负责 Steam Deck 上的安装、更新和修复。
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "BazaarPlusPlus",
  titleView: <div className={staticClasses.Title}>BazaarPlusPlus</div>,
  content: <Content />,
  icon: <FaStore />,
  onDismount() {
    console.log("BazaarPlusPlus Decky plugin unloaded");
  },
}));
