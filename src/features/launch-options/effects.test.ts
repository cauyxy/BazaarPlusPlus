import assert from "node:assert/strict";
import test from "node:test";

import type { BackendClient } from "../../decky/backendClient.js";
import type { LaunchOptionsBackup } from "../../decky/backendContracts.js";
import { createLaunchOptionsManager } from "./manager.js";
import type { SteamLaunchOptionsAdapter } from "./steamAdapter.js";

function fixtures(
  current = "%command%",
  backup: LaunchOptionsBackup = null,
) {
  const calls: string[] = [];
  const backend: BackendClient = {
    async getStatus() {
      throw new Error("not used");
    },
    async checkLatest() {
      throw new Error("not used");
    },
    async installLatest() {
      throw new Error("not used");
    },
    async uninstallMod() {
      throw new Error("not used");
    },
    async resetData() {
      throw new Error("not used");
    },
    async rememberLaunchOptions() {
      calls.push("save");
    },
    async getLaunchOptionsBackup() {
      calls.push("backup");
      return backup;
    },
    async clearLaunchOptionsBackup() {
      calls.push("clear");
    },
  };
  const steam: SteamLaunchOptionsAdapter = {
    async current() {
      calls.push("read");
      return current;
    },
    set() {
      calls.push("set");
    },
  };
  return { backend, steam, calls };
}

test("configure applies read, backup, save, then Steam write", async () => {
  const { backend, steam, calls } = fixtures();
  await createLaunchOptionsManager(backend, steam).configure();
  assert.deepEqual(calls, ["read", "backup", "save", "set"]);
});

test("save failure prevents Steam write", async () => {
  const { backend, steam, calls } = fixtures();
  backend.rememberLaunchOptions = async () => {
    calls.push("save");
    throw new Error("save failed");
  };
  await assert.rejects(
    createLaunchOptionsManager(backend, steam).configure(),
    /save failed/,
  );
  assert.deepEqual(calls, ["read", "backup", "save"]);
});

test("Steam restore failure does not clear backup", async () => {
  const { backend, steam, calls } = fixtures("managed", {
    original: "%command%",
    managed: "managed",
  });
  steam.set = () => {
    calls.push("set");
    throw new Error("Steam failed");
  };
  await assert.rejects(createLaunchOptionsManager(backend, steam).restore(), /Steam failed/);
  assert.deepEqual(calls, ["read", "backup", "set"]);
});

test("successful restore clears backup after Steam write", async () => {
  const { backend, steam, calls } = fixtures("managed", {
    original: "%command%",
    managed: "managed",
  });
  await createLaunchOptionsManager(backend, steam).restore();
  assert.deepEqual(calls, ["read", "backup", "set", "clear"]);
});

test("retry after clear failure only clears and preserves original winhttp", async () => {
  const original = 'WINEDLLOVERRIDES="winhttp=b" %command%';
  const managed = 'WINEDLLOVERRIDES="winhttp=n,b" %command%';
  let current = managed;
  let clearCalls = 0;
  const writes: string[] = [];
  const { backend, steam } = fixtures(current, { original, managed });
  steam.current = async () => current;
  steam.set = (value) => {
    writes.push(value);
    current = value;
  };
  backend.clearLaunchOptionsBackup = async () => {
    clearCalls += 1;
    if (clearCalls === 1) {
      throw new Error("clear failed");
    }
  };
  const manager = createLaunchOptionsManager(backend, steam);
  await assert.rejects(manager.restore(), /clear failed/);
  await manager.restore();
  assert.deepEqual(writes, [original]);
  assert.equal(clearCalls, 2);
  assert.equal(current, original);
});

test("already managed configure is a no-op", async () => {
  const managed = 'WINEDLLOVERRIDES="winhttp=n,b" %command%';
  const { backend, steam, calls } = fixtures(managed, {
    original: "%command%",
    managed,
  });
  await createLaunchOptionsManager(backend, steam).configure();
  assert.deepEqual(calls, ["read", "backup"]);
});
