#!/usr/bin/env node

// Test-only Windows-path model. This does not implement Windows or PowerShell.
import assert from "node:assert/strict";
import { spawn as nativeSpawn } from "node:child_process";
import nativeFs from "node:fs";
import nativePromises from "node:fs/promises";
import * as nodeModule from "node:module";
import nativeOs from "node:os";
import nativePath from "node:path";
import process from "node:process";
import { fileURLToPath as nativeFileURLToPath, pathToFileURL } from "node:url";

const SELF = nativeFileURLToPath(import.meta.url);
const HERE = nativePath.dirname(SELF);
const VOLUME = "T:\\mdc-self-test";
const SERVER = "mineclient-bridge-mcp.mjs";
const TEST = "self-test.mjs";
const ROOT_ENV = "MDC_SYNTHETIC_TEST_ROOT";
const POWERSHELL = `${VOLUME}\\system\\WindowsPowerShell\\v1.0\\powershell.exe`;
const PREFIX = `${VOLUME}\\tmp\\mineclient-bridge-self-test-runs\\`;

function sandbox() {
  const root = process.env[ROOT_ENV];
  assert(root && nativePath.isAbsolute(root) && nativeFs.realpathSync(root) === root &&
    (nativeFs.statSync(root).mode & 0o077) === 0,
    "A canonical private test sandbox is required");
  return root;
}

function local(value) {
  assert(typeof value === "string" && value === value.trim() &&
    !/[\u0000-\u001f\u007f]/.test(value) &&
    (value === VOLUME || value.startsWith(`${VOLUME}\\`)) &&
    !value.slice(2).includes(":") && nativePath.win32.normalize(value) === value,
  "Refusing path outside the canonical synthetic test volume");
  const root = sandbox();
  const parts = value.slice(VOLUME.length).split("\\").filter(Boolean);
  let result = root;
  for (const part of parts) {
    result = nativePath.join(result, part);
    try {
      assert(!nativeFs.lstatSync(result).isSymbolicLink(), "Refusing a synthetic-test symlink");
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  return result;
}

function virtual(value) {
  const relative = nativePath.relative(sandbox(), value);
  assert(relative !== ".." && !relative.startsWith(`..${nativePath.sep}`) &&
    !nativePath.isAbsolute(relative), "Refusing a real path outside the test sandbox");
  return relative ? `${VOLUME}\\${relative.split(nativePath.sep).join("\\")}` : VOLUME;
}

// Only the filesystem operations used by the unchanged fixtures are exposed.
export const fixtureFs = {};
for (const name of ["chmod", "lstat", "mkdir", "open", "readFile", "readdir", "rm", "stat", "unlink", "writeFile"]) {
  fixtureFs[name] = (file, ...args) => nativePromises[name](local(file), ...args);
}
for (const name of ["copyFile", "rename"]) {
  fixtureFs[name] = (from, to, ...args) => nativePromises[name](local(from), local(to), ...args);
}
fixtureFs.realpath = async (file) => virtual(await nativePromises.realpath(local(file)));
export const fixtureFsSync = { closeSync: nativeFs.closeSync };
for (const name of ["appendFileSync", "openSync", "writeFileSync"]) {
  fixtureFsSync[name] = (file, ...args) => nativeFs[name](local(file), ...args);
}
fixtureFsSync.realpathSync = (file) => virtual(nativeFs.realpathSync(local(file)));
fixtureFsSync.realpathSync.native = fixtureFsSync.realpathSync;
export const fixturePath = nativePath.win32;
export const fixtureOs = { ...nativeOs, tmpdir: () => `${VOLUME}\\tmp`, homedir: () => `${VOLUME}\\home` };
export const fixtureFileURLToPath = (url) => virtual(nativeFileURLToPath(url));

function expectedLauncher() {
  return [
    "$ErrorActionPreference='Stop'",
    `$node='${process.execPath.replaceAll("'", "''")}'`,
    "$root=$PSScriptRoot",
    "$test=Join-Path $root 'fixture-bridge.mjs'",
    "try {",
    "  Set-Content -LiteralPath (Join-Path $root 'fixture-launch-started.txt') -Value 'started' -Encoding ascii",
    "  $child=Start-Process -FilePath $node -ArgumentList @($test,'--fixture-bridge',$root) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'fixture-stdout.log') -RedirectStandardError (Join-Path $root 'fixture-stderr.log') -PassThru",
    "  Set-Content -LiteralPath (Join-Path $root 'fixture-child-pid.txt') -Value $child.Id -Encoding ascii",
    "} catch {",
    "  ($_ | Out-String) | Set-Content -LiteralPath (Join-Path $root 'fixture-launch-error.txt') -Encoding utf8",
    "  throw",
    "}", ""
  ].join("\r\n");
}

export function fixtureSpawn(command, args, options) {
  let role;
  let root;
  assert(options && options.env?.[ROOT_ENV] === sandbox(), "Refusing an unowned fixture environment");
  if (command === process.execPath) {
    assert.deepEqual(args, [`${VOLUME}\\mcp\\${SERVER}`], "Refusing an unknown Node entry point");
    assert.deepEqual(options.stdio, ["pipe", "pipe", "pipe"]);
    assert.equal(options.cwd, undefined);
    assert.equal(options.shell, undefined);
    role = "server";
  } else {
    assert.equal(command, POWERSHELL, "Refusing an unknown fixture command");
    root = options.cwd;
    assert(typeof root === "string" && root.startsWith(PREFIX) &&
      /^mineclient-[A-Za-z0-9_-]+$/.test(root.slice(PREFIX.length)), "Refusing an unknown fixture root");
    assert.deepEqual(args, ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
      "Bypass", "-WindowStyle", "Hidden", "-File", `${root}\\launch.ps1`]);
    assert.equal(options.shell, false);
    assert.equal(options.detached, false);
    assert.equal(options.env.MINECLIENT_BRIDGE_RUN_ID, nativePath.win32.basename(root));
    assert.equal(options.env.MINECLIENT_BRIDGE_RUNTIME_ROOT, `${root}\\game`);
    assert.equal(options.env.MINECLIENT_BRIDGE_EVIDENCE_ROOT, `${root}\\game\\captures`);
    assert.equal(options.env.MINECLIENT_BRIDGE_ISOLATED_INPUT, "true");
    assert.equal(nativeFs.readFileSync(local(`${root}\\launch.ps1`), "utf8"), expectedLauncher());
    assert.deepEqual(nativeFs.readFileSync(local(`${root}\\fixture-bridge.mjs`)),
      nativeFs.readFileSync(local(`${VOLUME}\\mcp\\${TEST}`)), "Refusing a modified bridge fixture");
    role = "fixture";
  }
  const childArgs = [SELF, "--child", sandbox(), role, ...(root ? [root] : [])];
  const child = nativeSpawn(process.execPath, childArgs, {
    ...options, cwd: root ? local(root) : sandbox(), shell: false
  });
  if (child.pid) {
    nativeFs.appendFileSync(nativePath.join(sandbox(), "owned-children.jsonl"),
      `${JSON.stringify({ pid: child.pid, argv: [process.execPath, ...childArgs] })}\n`);
    if (root) {
      nativeFs.writeFileSync(local(`${root}\\fixture-launch-started.txt`), "synthetic Node launcher\n");
      nativeFs.writeFileSync(local(`${root}\\fixture-child-pid.txt`), String(child.pid));
    }
  }
  return child;
}

function installFixtureImports() {
  const root = sandbox();
  const support = `${pathToFileURL(SELF).href}?fixture-import`;
  const exports = {
    "node:fs": "fixtureFsSync as default", "node:fs/promises": "fixtureFs as default",
    "node:path": "fixturePath as default", "node:os": "fixtureOs as default",
    "node:url": "fixtureFileURLToPath as fileURLToPath", "node:child_process": "fixtureSpawn as spawn"
  };
  // Scope substitutions to the copied test/server and exact prepared fixture names.
  const loader = `import { fileURLToPath } from 'node:url';
    import path from 'node:path';
    export async function resolve(specifier, context, next) {
      const names = ${JSON.stringify(exports)};
      if (context.parentURL?.startsWith('file:') && names[specifier]) {
        const rel = path.relative(${JSON.stringify(root)}, fileURLToPath(context.parentURL));
        if (rel === 'mcp/${TEST}' || rel === 'mcp/${SERVER}' ||
            /^tmp\\/mineclient-bridge-self-test-runs\\/mineclient-[A-Za-z0-9_-]+\\/fixture-bridge\\.mjs$/.test(rel)) {
          return { shortCircuit: true, url: 'data:text/javascript,' + encodeURIComponent(
            'export { ' + names[specifier] + ' } from ' + ${JSON.stringify(JSON.stringify(support))} + ';') };
        }
      }
      return next(specifier, context);
    }`;
  assert.equal(typeof nodeModule.register, "function", "Linux synthetic tests require Node.js >=20.6");
  nodeModule.register(`data:text/javascript,${encodeURIComponent(loader)}`, import.meta.url);
}

async function checkFixtureGuards() {
  let rejected = 0;
  for (const value of ["/tmp", "T:relative", "T:\\elsewhere", "U:\\mdc-self-test", "\\\\host\\share",
    `${VOLUME}\\..\\escape`, `${VOLUME}\\double\\\\separator`, `${VOLUME}\\file:stream`, `${VOLUME}\\bad\0name`]) {
    assert.throws(() => local(value));
    rejected++;
  }
  const link = nativePath.join(sandbox(), "escape-link");
  await nativePromises.symlink(nativePath.dirname(sandbox()), link);
  assert.throws(() => local(`${VOLUME}\\escape-link\\outside`), /symlink/);
  await nativePromises.unlink(link);
  for (const [command, args] of [["sh", ["-c", "exit 0"]], [process.execPath, ["-e", "process.exit(0)"]],
    [POWERSHELL, ["-Command", "exit 0"]]]) {
    assert.throws(() => fixtureSpawn(command, args, { env: process.env }));
    rejected++;
  }
  assert.equal(await nativePromises.stat(nativePath.join(sandbox(), "owned-children.jsonl")).catch(() => null), null);
  process.stdout.write(`SYNTHETIC_GUARDS_OK rejected=${rejected + 1} no-processes-started=true\n`);
}

async function stopOwnedChildren() {
  const ledger = await nativePromises.readFile(nativePath.join(sandbox(), "owned-children.jsonl"), "utf8").catch(() => "");
  for (const line of ledger.trim().split("\n").filter(Boolean).reverse()) {
    const { pid, argv } = JSON.parse(line);
    const command = await nativePromises.readFile(`/proc/${pid}/cmdline`).catch(() => Buffer.alloc(0));
    if (command.length === 0) continue;
    assert.deepEqual(command.toString().split("\0").filter(Boolean), argv, "Refusing to signal a reused PID");
    try { process.kill(pid, "SIGTERM"); } catch (error) { if (error.code !== "ESRCH") throw error; }
    const deadline = Date.now() + 3000;
    while (await nativePromises.readFile(`/proc/${pid}/cmdline`).then((bytes) => bytes.length > 0, () => false)) {
      assert(Date.now() < deadline, "Owned fixture did not exit; retaining sandbox");
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }
}

async function checkNativeContractAndCleanup() {
  const env = { ...process.env, NODE_ENV: "test", MINECLIENT_BRIDGE_TEST_NAMESPACE: "self-test-native-contract" };
  const child = nativeSpawn(process.execPath, [local(`${VOLUME}\\mcp\\${SERVER}`)], {
    env, cwd: sandbox(), stdio: ["pipe", "pipe", "pipe"]
  });
  if (child.pid) nativeFs.appendFileSync(nativePath.join(sandbox(), "owned-children.jsonl"),
    `${JSON.stringify({ pid: child.pid, argv: [process.execPath, local(`${VOLUME}\\mcp\\${SERVER}`)] })}\n`);
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (bytes) => { stdout += bytes; });
  child.stderr.on("data", (bytes) => { stderr += bytes; });
  const exited = new Promise((resolve, reject) => { child.once("close", resolve); child.once("error", reject); });
  child.stdin.end(`${JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: {
    name: "minecraft_client_register", arguments: { run_id: "mineclient-native-contract",
      token: "synthetic-test-token", base_url: "http://127.0.0.1:1", process_id: process.pid,
      desktop_name: "SyntheticContract", runtime_root: sandbox(), evidence_root: sandbox() }
  } })}\n`);
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; child.kill(); }, 10_000);
  try { assert.equal(await exited, 0); } finally { clearTimeout(timeout); }
  assert.equal(timedOut, false, "Native path-contract probe timed out");
  assert.equal(stderr, "");
  const response = JSON.parse(stdout);
  assert.equal(response.result.isError, true);
  assert.match(response.result.content[0].text, /runtime_root must be a normalized absolute local Windows path/);

  const owned = fixtureSpawn(process.execPath, [`${VOLUME}\\mcp\\${SERVER}`], {
    env, stdio: ["pipe", "pipe", "pipe"], windowsHide: true
  });
  const stopped = new Promise((resolve, reject) => { owned.once("close", resolve); owned.once("error", reject); });
  await new Promise((resolve, reject) => { owned.once("spawn", resolve); owned.once("error", reject); });
  try { throw new Error("synthetic cleanup probe"); } catch (error) {
    assert.equal(error.message, "synthetic cleanup probe");
  } finally { await stopOwnedChildren(); }
  await stopped;
  await nativePromises.unlink(nativePath.join(sandbox(), "owned-children.jsonl"));
  process.stdout.write("NATIVE_WINDOWS_PATH_REJECTION_OK fixture-imports=off; FAILURE_CLEANUP_OK owned-child=exited\n");
}

async function main() {
  if (process.platform === "win32") {
    await import(`./${TEST}`);
    return;
  }
  assert.equal(process.platform, "linux", "Synthetic self-test currently supports Linux only");
  if (process.argv[2] === "--child") {
    assert.equal(process.argv[3], sandbox());
    const role = process.argv[4];
    assert(role === "server" || role === "fixture");
    assert.equal(process.argv.length, role === "server" ? 5 : 6);
    if (role === "fixture") assert(process.argv[5].startsWith(PREFIX) &&
      /^mineclient-[A-Za-z0-9_-]+$/.test(process.argv[5].slice(PREFIX.length)));
    const entry = role === "server" ? local(`${VOLUME}\\mcp\\${SERVER}`) : local(`${process.argv[5]}\\fixture-bridge.mjs`);
    if (role === "fixture") {
      assert.deepEqual(nativeFs.readFileSync(entry), nativeFs.readFileSync(local(`${VOLUME}\\mcp\\${TEST}`)));
      process.argv = [process.execPath, entry, "--fixture-bridge", process.argv[5]];
    }
    installFixtureImports();
    await import(pathToFileURL(entry));
    return;
  }
  const root = await nativePromises.mkdtemp(nativePath.join(nativeFs.realpathSync(nativeOs.tmpdir()), "mdc-node-self-test-"));
  process.env[ROOT_ENV] = root;
  process.env.SystemRoot = `${VOLUME}\\system`;
  process.env.MINECLIENT_BRIDGE_POWERSHELL = POWERSHELL;
  const snapshots = new Map();
  try {
    for (const directory of ["mcp", "tmp", "home", "system/WindowsPowerShell/v1.0"]) {
      await nativePromises.mkdir(nativePath.join(root, directory), { recursive: true });
    }
    for (const name of [SERVER, TEST, "client-action.mjs", "encounter-contract.mjs", "toolbox.mjs", "toolbox-bridge.mjs"]) {
      snapshots.set(name, await nativePromises.readFile(nativePath.join(HERE, name)));
      await nativePromises.writeFile(nativePath.join(root, "mcp", name), snapshots.get(name));
    }
    await nativePromises.writeFile(local(POWERSHELL), "TEST-ONLY PLACEHOLDER; NEVER EXECUTED\n");
    await checkFixtureGuards();
    await checkNativeContractAndCleanup();
    process.stdout.write("SELF_TEST_PLATFORM synthetic-windows-paths/node-fixture-launcher; Windows/PowerShell NOT validated\n");
    installFixtureImports();
    await import(pathToFileURL(nativePath.join(root, "mcp", TEST)));
    for (const [name, bytes] of snapshots) {
      assert.deepEqual(await nativePromises.readFile(nativePath.join(HERE, name)), bytes);
      assert.deepEqual(await nativePromises.readFile(nativePath.join(root, "mcp", name)), bytes);
    }
  } finally {
    await stopOwnedChildren();
    await nativePromises.rm(root, { recursive: true });
  }
}

if (process.argv[1] && pathToFileURL(nativePath.resolve(process.argv[1])).href === import.meta.url) await main();
