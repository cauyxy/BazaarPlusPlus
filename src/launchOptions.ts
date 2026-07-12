const DLL_OVERRIDE = "winhttp=n,b";

export type LaunchOptionsBackup = {
  original: string;
  managed: string;
} | null;

export type LaunchSnapshot = {
  current: string;
  backup: LaunchOptionsBackup;
};

export type LaunchEffect = {
  setLaunchOptions: string | null;
  saveBackup: { original: string; managed: string } | null;
  clearBackup: boolean;
};

function addWinhttpOverride(input: string): string {
  const options = input.trim();
  const variable =
    /\bWINEDLLOVERRIDES=(?:"([^"]*)"|'([^']*)'|([^\s]+))/i;
  const match = variable.exec(options);

  let withOverride = options;
  if (match) {
    const rawValue = match[1] ?? match[2] ?? match[3] ?? "";
    const entries = rawValue.split(";").filter(Boolean);
    const winhttpIndex = entries.findIndex((entry) =>
      /^winhttp(?:\.dll)?=/i.test(entry),
    );
    if (winhttpIndex >= 0) {
      entries[winhttpIndex] = DLL_OVERRIDE;
    } else {
      entries.push(DLL_OVERRIDE);
    }
    withOverride =
      options.slice(0, match.index) +
      `WINEDLLOVERRIDES="${entries.join(";")}"` +
      options.slice(match.index + match[0].length);
  } else {
    withOverride = `WINEDLLOVERRIDES="${DLL_OVERRIDE}" ${options}`.trim();
  }

  if (!/%command%/i.test(withOverride)) {
    const managedVariable = variable.exec(withOverride);
    // 从公开入口不可达。
    if (!managedVariable) {
      return `WINEDLLOVERRIDES="${DLL_OVERRIDE}" %command% ${withOverride}`.trim();
    }
    const commandPosition =
      managedVariable.index + managedVariable[0].length;
    const beforeCommand = withOverride.slice(0, commandPosition).trim();
    const afterCommand = withOverride.slice(commandPosition).trim();
    return `${beforeCommand} %command%${afterCommand ? ` ${afterCommand}` : ""}`;
  }
  return withOverride;
}

function removeWinhttpOverride(input: string): string {
  const variable =
    /\bWINEDLLOVERRIDES=(?:"([^"]*)"|'([^']*)'|([^\s]+))\s*/i;
  const match = variable.exec(input);
  if (!match) {
    return input.trim();
  }

  const rawValue = match[1] ?? match[2] ?? match[3] ?? "";
  const entries = rawValue
    .split(";")
    .filter((entry) => entry && !/^winhttp(?:\.dll)?=/i.test(entry));
  const replacement = entries.length
    ? `WINEDLLOVERRIDES="${entries.join(";")}" `
    : "";
  return (
    input.slice(0, match.index) +
    replacement +
    input.slice(match.index + match[0].length)
  )
    .replace(/\s+/g, " ")
    .trim();
}

export function planConfigure(snapshot: LaunchSnapshot): LaunchEffect {
  const managed = addWinhttpOverride(snapshot.current);
  return {
    setLaunchOptions: managed !== snapshot.current ? managed : null,
    saveBackup:
      snapshot.backup === null
        ? { original: snapshot.current, managed }
        : null,
    clearBackup: false,
  };
}

export function planRestore(snapshot: LaunchSnapshot): LaunchEffect {
  const restored =
    snapshot.backup && snapshot.current === snapshot.backup.managed
      ? snapshot.backup.original
      : removeWinhttpOverride(snapshot.current);
  return {
    setLaunchOptions: restored,
    saveBackup: null,
    clearBackup: true,
  };
}
