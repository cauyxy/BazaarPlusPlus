import assert from "node:assert/strict";
import test from "node:test";

import {
  createSteamLaunchOptionsAdapter,
  type SteamApps,
} from "./steamAdapter.js";

test("reads launch options and unregisters", async () => {
  let unregistered = false;
  const apps: SteamApps = {
    SetAppLaunchOptions() {},
    RegisterForAppDetails(appId, callback) {
      assert.equal(appId, 1617400);
      queueMicrotask(() => callback({ strLaunchOptions: "  %command%  " }));
      return { unregister: () => (unregistered = true) };
    },
  };
  assert.equal(await createSteamLaunchOptionsAdapter(apps).current(), "%command%");
  await new Promise<void>((resolve) => queueMicrotask(resolve));
  assert.equal(unregistered, true);
});

test("times out and unregisters the registration", async () => {
  let unregistered = false;
  const apps: SteamApps = {
    SetAppLaunchOptions() {},
    RegisterForAppDetails() {
      return { unregister: () => (unregistered = true) };
    },
  };
  await assert.rejects(
    createSteamLaunchOptionsAdapter(apps, 1).current(),
    /读取 Steam 启动参数超时/,
  );
  assert.equal(unregistered, true);
});

test("writes launch options for the Bazaar app id", () => {
  const writes: unknown[][] = [];
  const apps: SteamApps = {
    SetAppLaunchOptions(...args) {
      writes.push(args);
    },
    RegisterForAppDetails() {
      throw new Error("not used");
    },
  };
  createSteamLaunchOptionsAdapter(apps).set("managed");
  assert.deepEqual(writes, [[1617400, "managed"]]);
});
