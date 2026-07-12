import { addEventListener, removeEventListener, toaster } from "@decky/api";
import { useCallback, useEffect, useState } from "react";

import {
  backendClient,
  type LatestRelease,
  type PluginStatus,
} from "../../decky/backendClient";
import { createLaunchOptionsManager } from "../launch-options/manager";
import { createSteamLaunchOptionsAdapter } from "../launch-options/steamAdapter";
import {
  installWithLaunchOptions,
  preserveRepairMode,
  type OperationOutcome,
  refreshInstallerState,
  subscribeInstallProgress,
  uninstallWithLaunchOptions,
} from "./operations";

const launchOptions = createLaunchOptionsManager(
  backendClient,
  createSteamLaunchOptionsAdapter(),
);

export type InstallerController = {
  status: PluginStatus | null;
  latest: LatestRelease | null;
  busy: boolean;
  progress: string;
  repairMode: "configure" | "restore" | null;
  refresh(): Promise<void>;
  install(): Promise<void>;
  uninstall(): Promise<void>;
  resetData(): Promise<void>;
  repairLaunchOptions(): Promise<void>;
};

export function useInstaller(): InstallerController {
  const [status, setStatus] = useState<PluginStatus | null>(null);
  const [latest, setLatest] = useState<LatestRelease | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [repairMode, setRepairMode] = useState<
    "configure" | "restore" | null
  >(null);

  const refresh = useCallback(async () => {
    try {
      const next = await refreshInstallerState(backendClient, (error) =>
        console.warn("Unable to check BazaarPlusPlus release", error),
      );
      setStatus(next.status);
      setRepairMode((current) => preserveRepairMode(current, next.repairMode));
      if (next.latest !== null) {
        setLatest(next.latest);
      }
    } catch (error) {
      toaster.toast({
        title: "状态刷新失败",
        body: String(error),
        critical: true,
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    return subscribeInstallProgress(
      (callback) =>
        addEventListener<[message: string, percent: number]>(
          "install_progress",
          callback,
        ),
      (listener) => removeEventListener("install_progress", listener),
      setProgress,
    );
  }, []);

  const finish = useCallback(
    async (outcome: OperationOutcome) => {
      if (outcome.kind !== "failed") {
        setStatus(outcome.status);
      }
      if (outcome.kind === "partiallySucceeded") {
        setRepairMode(outcome.repair);
        toaster.toast({
          title: "BazaarPlusPlus 部分完成",
          body: `${outcome.message} ${String(outcome.cause)}`,
          critical: true,
        });
      } else if (outcome.kind === "failed") {
        toaster.toast({
          title: outcome.message,
          body: String(outcome.cause),
          critical: true,
        });
      } else {
        setRepairMode(null);
        toaster.toast({ title: "BazaarPlusPlus", body: outcome.message });
      }
      await refresh();
    },
    [refresh],
  );

  const run = useCallback(
    async (operation: () => Promise<OperationOutcome>) => {
      setBusy(true);
      try {
        await finish(await operation());
      } finally {
        setBusy(false);
        setProgress("");
      }
    },
    [finish],
  );

  const install = useCallback(
    () => run(() => installWithLaunchOptions(backendClient, launchOptions)),
    [run],
  );
  const uninstall = useCallback(
    () => run(() => uninstallWithLaunchOptions(backendClient, launchOptions)),
    [run],
  );

  const resetData = useCallback(async () => {
    setBusy(true);
    try {
      const next = await backendClient.resetData();
      setStatus(next);
      toaster.toast({
        title: "BazaarPlusPlus",
        body: "本地对局数据已重置。",
      });
    } catch (error) {
      toaster.toast({
        title: "数据重置失败",
        body: String(error),
        critical: true,
      });
    } finally {
      setBusy(false);
      await refresh();
    }
  }, [refresh]);

  const repairLaunchOptions = useCallback(async () => {
    try {
      if (repairMode === "restore") {
        await launchOptions.restore();
      } else {
        await launchOptions.configure();
      }
      setRepairMode(null);
      toaster.toast({
        title: "BazaarPlusPlus",
        body:
          repairMode === "restore"
            ? "Steam 启动参数已恢复。"
            : "Steam 启动参数已修复。",
      });
    } catch (error) {
      toaster.toast({
        title: "启动参数修复失败",
        body: String(error),
        critical: true,
      });
    }
  }, [repairMode]);

  return {
    status,
    latest,
    busy,
    progress,
    repairMode,
    refresh,
    install,
    uninstall,
    resetData,
    repairLaunchOptions,
  };
}
