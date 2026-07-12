import assert from "node:assert/strict";
import test from "node:test";

import {
  planConfigure,
  planRestore,
  type LaunchOptionsBackup,
} from "./model.js";

const W = (value: string): string => `WINEDLLOVERRIDES="${value}"`;

type ConfigureCase = {
  name: string;
  current: string;
  expectedManaged: string;
  backup?: LaunchOptionsBackup;
  expectedSet?: string | null;
  expectedSave?: { original: string; managed: string } | null;
};

const configureCases: ConfigureCase[] = [
  {
    name: "P1 configures empty launch options",
    current: "",
    expectedManaged: `${W("winhttp=n,b")} %command%`,
  },
  {
    name: "P2 prepends an override to existing launch options",
    current: "gamemoderun %command% -flag",
    expectedManaged: `${W("winhttp=n,b")} gamemoderun %command% -flag`,
  },
  {
    name: "P3 normalizes a single-quoted override",
    current: "WINEDLLOVERRIDES='dxgi=n' %command%",
    expectedManaged: `${W("dxgi=n;winhttp=n,b")} %command%`,
  },
  {
    name: "P4 replaces a winhttp.dll entry",
    current: `${W("winhttp.dll=b")} %command%`,
    expectedManaged: `${W("winhttp=n,b")} %command%`,
  },
  {
    name: "P5 preserves variables before the override",
    current: `DXVK_HUD=fps PROTON_LOG=1 ${W("dxgi=n")} %command%`,
    expectedManaged: `DXVK_HUD=fps PROTON_LOG=1 ${W("dxgi=n;winhttp=n,b")} %command%`,
  },
  {
    name: "P6 inserts a missing command token",
    current: W("dxgi=n;d3d11=n"),
    expectedManaged: `${W("dxgi=n;d3d11=n;winhttp=n,b")} %command%`,
  },
  {
    name: "P7 replaces winhttp in place",
    current: `${W("dxgi=n;winhttp.dll=b;dinput8=n")} %command%`,
    expectedManaged: `${W("dxgi=n;winhttp=n,b;dinput8=n")} %command%`,
  },
  {
    name: "P8 inserts command before trailing launch options",
    current: `${W("dxgi=n")} mangohud`,
    expectedManaged: `${W("dxgi=n;winhttp=n,b")} %command% mangohud`,
  },
  {
    name: "P9 normalizes an unquoted override",
    current: "WINEDLLOVERRIDES=dxgi=n,b %command%",
    expectedManaged: `${W("dxgi=n,b;winhttp=n,b")} %command%`,
  },
  {
    name: "P10 normalizes a lowercase variable name",
    current: 'winedlloverrides="dxgi=n" %command%',
    expectedManaged: `${W("dxgi=n;winhttp=n,b")} %command%`,
  },
  {
    name: "P11 fills an empty override and trims whitespace",
    current: `   ${W("")} %command%   `,
    expectedManaged: `${W("winhttp=n,b")} %command%`,
  },
  {
    name: "P12 saves an already managed value when no backup exists",
    current: `${W("winhttp=n,b")} %command%`,
    expectedManaged: `${W("winhttp=n,b")} %command%`,
    expectedSet: null,
  },
  {
    name: "P13 produces no effects for a managed value with a backup",
    current: `${W("winhttp=n,b")} %command%`,
    expectedManaged: `${W("winhttp=n,b")} %command%`,
    backup: { original: "%command%", managed: `${W("winhttp=n,b")} %command%` },
    expectedSet: null,
    expectedSave: null,
  },
  {
    name: "P14 updates launch options without overwriting a backup",
    current: "gamemoderun %command%",
    expectedManaged: `${W("winhttp=n,b")} gamemoderun %command%`,
    backup: { original: "%command%", managed: `${W("winhttp=n,b")} %command%` },
    expectedSave: null,
  },
  {
    name: "P15 replaces only the first matching winhttp entry",
    current: `${W("winhttp=n;winhttp.dll=b")} %command%`,
    expectedManaged: `${W("winhttp=n,b;winhttp.dll=b")} %command%`,
  },
];

for (const configureCase of configureCases) {
  test(configureCase.name, () => {
    const backup = configureCase.backup ?? null;
    const effect = planConfigure({ current: configureCase.current, backup });
    const expectedSave =
      configureCase.expectedSave !== undefined
        ? configureCase.expectedSave
        : {
            original: configureCase.current,
            managed: configureCase.expectedManaged,
          };

    assert.deepEqual(effect, {
      setLaunchOptions:
        configureCase.expectedSet !== undefined
          ? configureCase.expectedSet
          : configureCase.expectedManaged,
      saveBackup: expectedSave,
      clearBackup: false,
    });
  });
}

type RestoreCase = {
  name: string;
  current: string;
  backup: LaunchOptionsBackup;
  expected: string;
};

const restoreCases: RestoreCase[] = [
  {
    name: "R1 restores the original value on the backup fast path",
    current: `${W("winhttp=n,b")} gamemoderun %command%`,
    backup: {
      original: "gamemoderun %command%",
      managed: `${W("winhttp=n,b")} gamemoderun %command%`,
    },
    expected: "gamemoderun %command%",
  },
  {
    name: "R2 preserves drifted flags while removing the override",
    current: `${W("winhttp=n,b")} %command% -newflag`,
    backup: {
      original: "%command%",
      managed: `${W("winhttp=n,b")} %command%`,
    },
    expected: "%command% -newflag",
  },
  {
    name: "R3 removes an override variable containing only winhttp",
    current: `${W("winhttp=n,b")} %command%`,
    backup: null,
    expected: "%command%",
  },
  {
    name: "R4 preserves non-winhttp entries",
    current: `${W("dxgi=n;winhttp=n,b")} %command%`,
    backup: null,
    expected: `${W("dxgi=n")} %command%`,
  },
  {
    name: "R5 normalizes quoting and whitespace",
    current: "WINEDLLOVERRIDES='winhttp.dll=b;dxgi=n'   %command%",
    backup: null,
    expected: `${W("dxgi=n")} %command%`,
  },
  {
    name: "R6 writes back unchanged launch options without an override",
    current: "gamemoderun %command%",
    backup: null,
    expected: "gamemoderun %command%",
  },
  {
    name: "R7 processes only the first override variable",
    current: `${W("dxgi=n")} ${W("winhttp=n,b")} %command%`,
    backup: {
      original: "%command%",
      managed: `${W("winhttp=n,b")} %command%`,
    },
    expected: `${W("dxgi=n")} ${W("winhttp=n,b")} %command%`,
  },
  {
    name: "R8 removes the first managed variable only",
    current: `${W("winhttp=n,b")} ${W("dxgi=n")} %command%`,
    backup: {
      original: "%command%",
      managed: `${W("winhttp=n,b")} %command%`,
    },
    expected: `${W("dxgi=n")} %command%`,
  },
];

for (const restoreCase of restoreCases) {
  test(restoreCase.name, () => {
    assert.deepEqual(
      planRestore({
        current: restoreCase.current,
        backup: restoreCase.backup,
      }),
      {
        setLaunchOptions: restoreCase.expected,
        saveBackup: null,
        clearBackup: true,
      },
    );
  });
}

for (const [name, current] of [
  ["T1 round trips empty launch options", ""],
  ["T2 round trips launch options with flags", "gamemoderun %command% -flag"],
  ["T3 round trips an override without a command token", W("dxgi=n;d3d11=n")],
] as const) {
  test(name, () => {
    const configured = planConfigure({ current, backup: null });
    const managed = configured.setLaunchOptions ?? current;

    assert.equal(configured.saveBackup?.managed, managed);
    assert.equal(
      planRestore({ current: managed, backup: configured.saveBackup })
        .setLaunchOptions,
      current,
    );
  });
}
