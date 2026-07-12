import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import ts from "typescript";

const ROOT = process.cwd();
const SRC = join(ROOT, "src");

function sourceFiles(directory = SRC): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".test.ts")
      ? [path]
      : [];
  });
}

function parse(path: string): ts.SourceFile {
  return ts.createSourceFile(
    path,
    readFileSync(path, "utf-8"),
    ts.ScriptTarget.Latest,
    true,
    path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

function visit(node: ts.Node, callback: (node: ts.Node) => void): void {
  callback(node);
  node.forEachChild((child) => visit(child, callback));
}

test("frontend platform dependencies stay in their adapters", () => {
  const callableFiles = new Set<string>();
  const steamClientFiles = new Set<string>();
  for (const path of sourceFiles()) {
    visit(parse(path), (node) => {
      if (ts.isCallExpression(node) && node.expression.getText() === "callable") {
        callableFiles.add(relative(ROOT, path));
      }
      if (ts.isIdentifier(node) && node.text === "SteamClient") {
        steamClientFiles.add(relative(ROOT, path));
      }
    });
  }
  assert.deepEqual([...callableFiles], ["src/decky/backendClient.ts"]);
  assert.deepEqual([...steamClientFiles], [
    "src/features/launch-options/steamAdapter.ts",
  ]);

  const panel = parse(join(SRC, "features/installer/PluginPanel.tsx"));
  const panelImports = panel.statements
    .filter(ts.isImportDeclaration)
    .map((statement) => (statement.moduleSpecifier as ts.StringLiteral).text);
  assert.equal(panelImports.includes("@decky/api"), false);
});

test("frontend RPC, event, and app-id contracts remain stable", () => {
  const client = parse(join(SRC, "decky/backendClient.ts"));
  const rpcNames: string[] = [];
  visit(client, (node) => {
    if (
      ts.isCallExpression(node) &&
      node.expression.getText() === "callable" &&
      node.arguments.length === 1 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      rpcNames.push(node.arguments[0].text);
    }
  });
  assert.deepEqual(rpcNames.sort(), [
    "check_latest",
    "clear_launch_options_backup",
    "get_launch_options_backup",
    "get_status",
    "install_latest",
    "remember_launch_options",
    "reset_data",
    "uninstall_mod",
  ]);

  const hook = parse(join(SRC, "features/installer/useInstaller.ts"));
  const eventNames: string[] = [];
  visit(hook, (node) => {
    if (
      ts.isCallExpression(node) &&
      ["addEventListener", "removeEventListener"].includes(
        node.expression.getText(),
      ) &&
      node.arguments.length > 0 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      eventNames.push(node.arguments[0].text);
    }
  });
  assert.deepEqual(eventNames, ["install_progress", "install_progress"]);

  const steam = parse(join(SRC, "features/launch-options/steamAdapter.ts"));
  const appIds: number[] = [];
  visit(steam, (node) => {
    if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.name.text === "APP_ID" &&
      node.initializer &&
      ts.isNumericLiteral(node.initializer)
    ) {
      appIds.push(Number(node.initializer.text));
    }
  });
  assert.deepEqual(appIds, [1617400]);
});

test("frontend entrypoint only registers and renders the plugin", () => {
  const index = parse(join(SRC, "index.tsx"));
  const calls: string[] = [];
  visit(index, (node) => {
    if (ts.isCallExpression(node)) {
      calls.push(node.expression.getText());
    }
  });
  assert.deepEqual(calls, ["definePlugin", "console.log"]);
});
