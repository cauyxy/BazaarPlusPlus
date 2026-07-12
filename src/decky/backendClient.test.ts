import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeLatestRelease,
  decodeLaunchOptionsBackup,
  decodePluginStatus,
} from "./backendContracts.js";

test("decodes the backend wire contracts", () => {
  assert.deepEqual(
    decodePluginStatus({
      game_found: true,
      game_path: "/game",
      game_running: false,
      installed: true,
      installed_version: "4.4.3.prod",
    }),
    {
      game_found: true,
      game_path: "/game",
      game_running: false,
      installed: true,
      installed_version: "4.4.3.prod",
    },
  );
  assert.deepEqual(decodeLatestRelease({ version: "4.4.3", update_available: true }), {
    version: "4.4.3",
    update_available: true,
  });
  assert.deepEqual(decodeLaunchOptionsBackup(null), null);
  assert.deepEqual(
    decodeLaunchOptionsBackup({ original: "%command%", managed: "managed" }),
    { original: "%command%", managed: "managed" },
  );
});

test("rejects malformed backend payloads", () => {
  for (const value of [null, {}, { game_found: "yes" }]) {
    assert.throws(() => decodePluginStatus(value), /无效的安装状态/);
  }
  for (const value of [null, {}, { version: "4.4.3", update_available: 1 }]) {
    assert.throws(() => decodeLatestRelease(value), /无效的发布信息/);
  }
  for (const value of [{}, { original: "x", managed: 1 }]) {
    assert.throws(() => decodeLaunchOptionsBackup(value), /无效的启动参数备份/);
  }
});
