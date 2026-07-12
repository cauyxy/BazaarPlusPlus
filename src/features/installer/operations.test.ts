import assert from "node:assert/strict";
import test from "node:test";

import type { BackendClient, PluginStatus } from "../../decky/backendClient.js";
import type { LaunchOptionsManager } from "../launch-options/manager.js";
import {
  installWithLaunchOptions,
  preserveRepairMode,
  refreshInstallerState,
  subscribeInstallProgress,
  uninstallWithLaunchOptions,
} from "./operations.js";

const installed: PluginStatus = {
  game_found: true,
  game_path: "/game",
  game_running: false,
  installed: true,
  installed_version: "4.4.3",
};
const uninstalled = { ...installed, installed: false, installed_version: null };

function backend(overrides: Partial<BackendClient> = {}): BackendClient {
  return {
    async getStatus() {
      return installed;
    },
    async checkLatest() {
      return { version: "4.4.3", update_available: false };
    },
    async installLatest() {
      return installed;
    },
    async uninstallMod() {
      return uninstalled;
    },
    async resetData() {
      return installed;
    },
    async rememberLaunchOptions() {},
    async getLaunchOptionsBackup() {
      return null;
    },
    async clearLaunchOptionsBackup() {},
    ...overrides,
  };
}

test("backend install failure does not configure launch options", async () => {
  let configured = false;
  const client = backend({
    async installLatest() {
      throw new Error("backend failed");
    },
  });
  const launch: LaunchOptionsManager = {
    async configure() {
      configured = true;
    },
    async restore() {},
  };
  const outcome = await installWithLaunchOptions(client, launch);
  assert.equal(outcome.kind, "failed");
  assert.equal(configured, false);
});

test("successful install with launch failure is partially succeeded", async () => {
  const launch: LaunchOptionsManager = {
    async configure() {
      throw new Error("Steam failed");
    },
    async restore() {},
  };
  const outcome = await installWithLaunchOptions(backend(), launch);
  assert.equal(outcome.kind, "partiallySucceeded");
  assert.equal(outcome.message, "模组已安装，但启动参数配置失败。");
  if (outcome.kind === "partiallySucceeded") {
    assert.equal(outcome.status.installed, true);
    assert.equal(outcome.repair, "configure");
  }
});

test("successful uninstall with restore failure is partially succeeded", async () => {
  const launch: LaunchOptionsManager = {
    async configure() {},
    async restore() {
      throw new Error("Steam failed");
    },
  };
  const outcome = await uninstallWithLaunchOptions(backend(), launch);
  assert.equal(outcome.kind, "partiallySucceeded");
  assert.equal(outcome.message, "模组已卸载，但启动参数恢复失败。");
  if (outcome.kind === "partiallySucceeded") {
    assert.equal(outcome.status.installed, false);
    assert.equal(outcome.repair, "restore");
  }
});

test("full successes are distinguished from partial successes", async () => {
  const launch: LaunchOptionsManager = {
    async configure() {},
    async restore() {},
  };
  assert.equal((await installWithLaunchOptions(backend(), launch)).kind, "succeeded");
  assert.equal((await uninstallWithLaunchOptions(backend(), launch)).kind, "succeeded");
});

test("refresh surfaces status failure and tolerates latest failure", async () => {
  let latestCalled = false;
  await assert.rejects(
    refreshInstallerState(
      backend({
        async getStatus() {
          throw new Error("status failed");
        },
        async checkLatest() {
          latestCalled = true;
          return { version: "unused", update_available: false };
        },
      }),
    ),
    /status failed/,
  );
  assert.equal(latestCalled, false);

  let reported: unknown;
  const state = await refreshInstallerState(
    backend({
      async checkLatest() {
        throw new Error("latest failed");
      },
    }),
    (error) => (reported = error),
  );
  assert.equal(state.status, installed);
  assert.equal(state.latest, null);
  assert.match(String(reported), /latest failed/);
});

test("refresh recovers a pending restore action from persisted backup", async () => {
  const state = await refreshInstallerState(
    backend({
      async getStatus() {
        return uninstalled;
      },
      async getLaunchOptionsBackup() {
        return { original: "%command%", managed: "managed" };
      },
    }),
  );
  assert.equal(state.repairMode, "restore");
  assert.equal(preserveRepairMode(null, state.repairMode), "restore");
  assert.equal(preserveRepairMode("restore", undefined), "restore");
});

test("progress subscription formats events and removes the same listener", () => {
  let callback: ((message: string, percent: number) => void) | undefined;
  const listener = { id: 1 };
  let removed: unknown;
  let text = "";
  const cleanup = subscribeInstallProgress(
    (next) => {
      callback = next;
      return listener;
    },
    (value) => (removed = value),
    (value) => (text = value),
  );
  callback?.("下载官方安装包", 70);
  assert.equal(text, "下载官方安装包 70%");
  cleanup();
  assert.equal(removed, listener);
});
