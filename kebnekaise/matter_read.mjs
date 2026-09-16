// Bounded read-only client for matter-server 1.4.0 (API schema 13).
// No get_nodes/start_listening snapshots or attribute events become readings.
import {fileURLToPath} from "node:url";

export function readAttributes({url, timeout_ms, reads}) {
  const endpoint = new URL(url);
  if (endpoint.protocol !== "ws:" || endpoint.hostname !== "127.0.0.1" || !endpoint.port ||
      endpoint.pathname !== "/ws" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash ||
      !Number.isInteger(timeout_ms) || timeout_ms < 1 || timeout_ms > 20000 ||
      !Array.isArray(reads) || !reads.length || reads.length > 100 ||
      reads.some(r => !Number.isSafeInteger(r.node_id) || r.node_id < 1 ||
        !Array.isArray(r.attributes) || !r.attributes.length || r.attributes.length > 300 ||
        r.attributes.some(p => typeof p !== "string" || !/^\d+\/(1026\/0|1037\/(0|8))$/.test(p)))) {
    throw new Error("Invalid local read request");
  }
  return new Promise(resolve => {
    const results = {}, pending = new Map();
    let done = false;
    const socket = new WebSocket(url);
    const finish = reason => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      for (const read of pending.values()) results[String(read.node_id)] = {error: reason};
      socket.close();
      resolve(results);
    };
    const timer = setTimeout(() => finish("timeout"), timeout_ms);
    reads.forEach((read, index) => pending.set(`read-${index}`, read));
    socket.addEventListener("open", () => {
      for (const [message_id, read] of pending) {
        socket.send(JSON.stringify({message_id, command: "read_attribute",
          args: {node_id: read.node_id, attribute_path: read.attributes}}));
      }
    });
    socket.addEventListener("message", event => {
      if (done) return;
      try {
        if (typeof event.data !== "string" || event.data.length > 1_000_000) {
          finish("invalid_response"); return;
        }
        const message = JSON.parse(event.data);
        const read = pending.get(message?.message_id);
        if (!read) return; // Greeting, cached initial state, and unsolicited events.
        const attributes = message.result;
        if (message.error_code != null || !attributes || typeof attributes !== "object" || Array.isArray(attributes)) {
          results[String(read.node_id)] = {error: "read_failed"};
        } else {
          results[String(read.node_id)] = {received_at: Math.floor(Date.now()/1000),
            attributes: Object.fromEntries(read.attributes.filter(path => Object.hasOwn(attributes, path))
              .map(path => [path, attributes[path]]))};
        }
        pending.delete(message.message_id);
        if (!pending.size) finish();
      } catch {
        finish("invalid_response");
      }
    });
    socket.addEventListener("error", () => finish("connection_failed"));
    socket.addEventListener("close", () => finish("connection_closed"));
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    let input = "";
    for await (const chunk of process.stdin) {
      input += chunk;
      if (input.length > 100_000) throw new Error("Request too large");
    }
    const result = await readAttributes(JSON.parse(input));
    // Do not wait for a stalled peer's WebSocket close handshake after the batch.
    process.stdout.write(JSON.stringify(result), () => process.exit(0));
  } catch {
    process.exitCode = 1;
  }
}
