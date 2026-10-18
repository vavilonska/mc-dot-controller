/** Actual production ToolboxBridge, synthetic replies and fake child streams only. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {EventEmitter} from 'node:events';
import {PassThrough, Writable} from 'node:stream';
import {fileURLToPath, pathToFileURL} from 'node:url';
import childProcess from 'node:child_process';
import net from 'node:net';
import dgram from 'node:dgram';
import {syncBuiltinESMExports} from 'node:module';

// Applied before importing production code, including named builtin exports.
const forbidden = () => { throw new Error('offline_wire_test_external_action_forbidden'); };
for (const name of ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork']) {
  childProcess[name] = forbidden;
}
net.connect = net.createConnection = net.createServer = forbidden;
net.Socket.prototype.connect = net.Server.prototype.listen = forbidden;
dgram.createSocket = forbidden;
syncBuiltinESMExports();
const output = path.resolve(process.env.MDC_MOVEMENT_WIRE_E2E_OUTPUT);
const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const {ToolboxBridge} = await import(pathToFileURL(path.join(source, 'client-mod/mcp/toolbox-bridge.mjs')));
const MIB = 1024 * 1024;
const cases = JSON.parse(fs.readFileSync(path.join(output, 'node-cases.json'), 'utf8'));
assert.equal(cases.schema, 'mdc.full-reply-node-input/1');
const rows = [];
const sha = raw => createHash('sha256').update(raw).digest('hex');

function fixture() {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.writes = [];
  child.stdin = new Writable({write(chunk, _encoding, callback) {
    child.writes.push(Buffer.from(chunk)); callback();
  }});
  const bridge = new ToolboxBridge(child, {requestTimeoutMs: 1500});
  return {child, bridge};
}

async function settle(f) {
  // The child is purely an EventEmitter; no process handle or kill operation exists.
  f.child.emit('exit', 0, null);
  f.child.stdout.end(); f.child.stderr.end();
  f.child.emit('close', 0, null);  // Real ChildProcess closes only after stdio drains.
  const result = await f.bridge.close({waitMs: 10});
  assert.equal(result.exit_code, 0);
  assert.equal(f.bridge.pending.size, 0);
  f.child.stdout.destroy(); f.child.stderr.destroy(); f.child.stdin.destroy();
}

function emitChunks(child, raw, fragmented) {
  if (!fragmented) { child.stdout.write(raw); return; }
  // Prime-sized widths split both framing and multibyte UTF-8 boundaries.
  const widths = [1, 7, 4093, 2, 8191, 13];
  let at = 0, index = 0;
  while (at < raw.length) {
    const end = Math.min(raw.length, at + widths[index++ % widths.length]);
    child.stdout.write(raw.subarray(at, end)); at = end;
  }
}

function retained(relative, limit) {
  assert.equal(typeof relative, 'string');
  const filename = path.resolve(output, relative);
  assert.ok(filename.startsWith(output + path.sep));
  const stat = fs.lstatSync(filename);
  assert.ok(stat.isFile() && !stat.isSymbolicLink() && stat.size <= limit);
  return fs.readFileSync(filename);
}

async function fullReply(row, fragmented) {
  const reply = retained(row.reply, MIB);
  assert.equal(reply.length, row.reply_bytes);
  assert.equal(sha(reply), row.reply_sha256);
  const request = JSON.parse(retained(row.request, 65536));
  const envelope = JSON.parse(reply);
  const f = fixture();
  try {
    const pending = f.bridge.call(request.tool, request.arguments);
    assert.equal(f.child.writes.length, 1);
    assert.deepEqual(JSON.parse(f.child.writes[0]), request);
    emitChunks(f.child, reply, fragmented);
    const result = await pending;
    if (Object.hasOwn(envelope, 'result')) {
      assert.deepEqual(result, envelope.result, 'complete Python reply differs at actual Node boundary');
    } else {
      assert.equal(envelope.error.code, 'response_too_large');
      assert.equal(result.state, 'unknown');
      assert.equal(result.effect_certainty, 'unknown');
      assert.equal(result.error.reason, 'service_error_response');
    }
    assert.equal(f.bridge.protocolFailure, false);
    assert.equal(f.bridge.buffer.length, 0);
    assert.equal(f.bridge.pending.size, 0);
    // Late duplicate output must not trigger a new request or alter any new identity.
    f.child.stdout.write(reply);
    assert.equal(f.bridge.pending.size, 0);
    assert.equal(f.child.writes.length, 1);
    rows.push({case: row.label, fragmented, complete_reply_bytes: reply.length,
               reply_sha256: sha(reply), request_writes: f.child.writes.length});
  } finally { await settle(f); }
}

function exactNodeFrame(bytes) {
  const frame = {id: 'tb_1', result: {synthetic_boundary_only: true, padding: ''}};
  const needed = bytes - Buffer.byteLength(JSON.stringify(frame));
  assert.ok(needed >= 0);
  frame.result.padding = '界'.repeat(Math.floor(needed / 3)) + 'x'.repeat(needed % 3);
  const raw = Buffer.from(JSON.stringify(frame));
  assert.equal(raw.length, bytes);
  return raw;
}

async function nodeFrameBoundary(bytes, newline, fragmented) {
  const body = exactNodeFrame(bytes);
  const raw = newline ? Buffer.concat([body, Buffer.from('\n')]) : body;
  const f = fixture();
  try {
    const pending = f.bridge.call('mdc_observe', {});
    emitChunks(f.child, raw, fragmented);
    const result = await pending;
    if (bytes === MIB) {
      assert.deepEqual(result, JSON.parse(body).result);
      assert.equal(f.bridge.protocolFailure, false);
      assert.equal(f.child.stdin.writableEnded, false);
    } else {
      assert.equal(f.bridge.protocolFailure, true);
      assert.equal(f.child.stdin.writableEnded, true);
      assert.equal(result.state, 'unknown');
      assert.equal(result.error.reason, 'malformed_service_response');
      assert.equal(result.continuation, 'reconcile_original_id_required');
      const refused = await f.bridge.call('mdc_observe', {});
      assert.equal(refused.error.reason, 'toolbox_service_unavailable');
    }
    assert.equal(f.child.writes.length, 1, 'protocol failure caused replay');
    rows.push({case: 'node-frame-boundary', pre_newline_bytes: bytes,
               full_bytes: raw.length, newline, fragmented, accepted: bytes === MIB,
               request_writes: f.child.writes.length});
  } finally { await settle(f); }
}

async function nodeRequestBoundary(bytes) {
  const f = fixture();
  try {
    const args = {synthetic_boundary_only: true, padding: ''};
    const base = Buffer.byteLength(JSON.stringify({id: 'tb_1', tool: 'mdc_observe', arguments: args}) + '\n');
    args.padding = 'x'.repeat(bytes - base);
    const pending = f.bridge.call('mdc_observe', args);
    if (bytes === MIB) {
      assert.equal(f.child.writes.length, 1);
      assert.equal(f.child.writes[0].length, MIB);
      f.child.stdout.write(Buffer.from('{"id":"tb_1","result":{"boundary_ack":true}}\n'));
      assert.deepEqual(await pending, {boundary_ack: true});
    } else {
      assert.equal(f.child.writes.length, 0);
      assert.equal((await pending).error.reason, 'toolbox_request_too_large');
      assert.equal(f.bridge.pending.size, 0);
    }
    rows.push({case: 'node-request-boundary', full_request_bytes: bytes,
               accepted: bytes === MIB, request_writes: f.child.writes.length});
  } finally { await settle(f); }
}

let failure = null;
try {
  for (const row of cases.cases) {
    await fullReply(row, false);
    await fullReply(row, true);
  }
  for (const fragmented of [false, true]) {
    await nodeFrameBoundary(MIB, true, fragmented);
    await nodeFrameBoundary(MIB + 1, true, fragmented);
    await nodeFrameBoundary(MIB + 1, false, fragmented);
  }
  await nodeRequestBoundary(MIB);
  await nodeRequestBoundary(MIB + 1);
} catch (error) {
  failure = {name: error.name, message: String(error.message).slice(0, 1500)};
} finally {
  const report = {schema: 'mdc.full-reply-node-report/1', success: failure === null,
    scope: 'real ToolboxBridge.onData and call; fake child streams; no process spawned',
    python_limit_includes_newline: true, node_reply_limit_excludes_newline: true,
    source_reply_limit_bytes: MIB, cases: rows, failure};
  fs.writeFileSync(path.join(output, 'node-report.json'), JSON.stringify(report), {flag: 'wx', mode: 0o600});
}
console.log(JSON.stringify({success: failure === null, cases: rows.length, failure}));
if (failure) process.exitCode = 1;
