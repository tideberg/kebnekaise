import {test} from "node:test";
import assert from "node:assert/strict";
import {readAttributes} from "../kebnekaise/matter_read.mjs";

class FakeSocket extends EventTarget {
  static onSend;
  constructor() {
    super();
    queueMicrotask(() => this.dispatchEvent(new Event("open")));
  }
  send(payload) { FakeSocket.onSend(this, JSON.parse(payload)); }
  message(value) { this.dispatchEvent(new MessageEvent("message", {data: JSON.stringify(value)})); }
  close() { this.dispatchEvent(new Event("close")); }
}

const request = () => ({url: "ws://127.0.0.1:5580/ws", timeout_ms: 100,
  reads: [{node_id: 1, attributes: ["1/1026/0", "1/1037/0", "1/1037/8"]}]});
function useFake(t, onSend) {
  const native = globalThis.WebSocket;
  globalThis.WebSocket = FakeSocket;
  FakeSocket.onSend = onSend;
  t.after(() => { globalThis.WebSocket = native; });
}

test("only an explicit read response becomes a timestamped sample", async t => {
  useFake(t, (socket, command) => {
    assert.equal(command.command, "read_attribute");
    assert.deepEqual(command.args, {node_id: 1, attribute_path: request().reads[0].attributes});
    socket.message({event: "attribute_updated", data: [1, "1/1037/0", 9999]});
    socket.message({result: [{node_id: 1, attributes: {"1/1037/0": 9999}}]});
    queueMicrotask(() => socket.message({message_id: command.message_id,
      result: {"1/1026/0": 2392, "1/1037/0": 391, "1/1037/8": 0, "private/unrequested": "discard"}}));
  });
  const before = Math.floor(Date.now()/1000);
  const result = await readAttributes(request());
  assert.deepEqual(result[1].attributes, {"1/1026/0": 2392, "1/1037/0": 391, "1/1037/8": 0});
  assert.ok(result[1].received_at >= before && result[1].received_at <= Math.floor(Date.now()/1000));
});

test("cached state without a matching remote read times out", async t => {
  useFake(t, socket => socket.message({event: "attribute_updated", data: [1, "1/1037/0", 700]}));
  assert.deepEqual(await readAttributes({...request(), timeout_ms: 15}), {1: {error: "timeout"}});
});

test("multiple nodes, partial attributes and out-of-order responses stay separate", async t => {
  let first;
  useFake(t, (socket, command) => {
    if (command.args.node_id === 1) { first = command; return; }
    socket.message({message_id: command.message_id, result: {"1/1037/0": 800, "1/1037/8": 0}});
    socket.message({message_id: first.message_id, error_code: 8, details: "must not be forwarded"});
  });
  const input = request();
  input.reads.push({...input.reads[0], node_id: 2});
  const result = await readAttributes(input);
  assert.deepEqual(result[1], {error: "read_failed"});
  assert.deepEqual(result[2].attributes, {"1/1037/0": 800, "1/1037/8": 0});
});

test("disconnect preserves completed nodes and marks pending reads failed", async t => {
  useFake(t, (socket, command) => {
    if (command.args.node_id === 1) socket.message({message_id: command.message_id, result: {"1/1026/0": 2300}});
    else socket.close();
  });
  const input = request();
  input.reads.push({...input.reads[0], node_id: 2});
  const result = await readAttributes(input);
  assert.equal(result[1].attributes["1/1026/0"], 2300);
  assert.deepEqual(result[2], {error: "connection_closed"});
});

test("remote URLs and unsafe node numbers are refused before connecting", () => {
  assert.throws(() => readAttributes({...request(), url: "ws://192.0.2.1:5580/ws"}));
  const input = request();
  input.reads[0].node_id = Number.MAX_SAFE_INTEGER+1;
  assert.throws(() => readAttributes(input));
});
