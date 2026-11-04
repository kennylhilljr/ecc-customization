// Queue file writer. One JSON file per event, written to <root>/.tmp and
// renamed into <root>/<queue>/ so a consumer (or launchd QueueDirectories)
// never sees a partial file.

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";

import { queueFor } from "./router.js";

const UNPARSED_MAX_BYTES = 1024 * 1024;

export function compactTimestamp(iso) {
  // 2026-11-03T14:15:02.123Z -> 20261103T141502123Z (sorts like the ISO form)
  return iso.replace(/[-:.]/g, "");
}

function safePart(s) {
  return String(s).replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 80) || "x";
}

export function queueFileName(record, rand = crypto.randomBytes(3).toString("hex")) {
  const [owner, name] = record.repo.split("/");
  return [
    compactTimestamp(record.received_at),
    safePart(record.slack_message_id ?? "nots"),
    `${safePart(owner)}__${safePart(name)}`,
    record.kind,
    String(record.number),
    safePart(record.event),
    rand,
  ].join("-") + ".json";
}

export function buildRecord(parsed, { messageId, channelId, now = new Date() }) {
  return {
    repo: parsed.repo,
    kind: parsed.kind,
    number: parsed.number,
    event: parsed.event,
    received_at: now.toISOString(),
    slack_message_id: messageId ?? null,
    slack_channel: channelId,
    source: "github-event-router",
    version: 1,
  };
}

// The consumers (iwb, prbot) only drain a non-default queue dir whose parent
// holds this file. It lives in the queue root, never inside a queue dir,
// because launchd QueueDirectories fires while a watched dir is non-empty.
export const QUEUE_MARKER = ".github-events-queue";

export async function ensureMarker(root, fsImpl = fs) {
  try {
    await fsImpl.writeFile(path.join(root, QUEUE_MARKER), "github-event-router queue root\n", { flag: "wx", mode: 0o600 });
  } catch (err) {
    if (err?.code !== "EEXIST") throw err;
  }
}

// fsImpl lets tests inject failures; it defaults to node:fs/promises.
export async function writeEvent(root, record, { fsImpl = fs } = {}) {
  return publish(root, queueFor(record.kind), queueFileName(record), record, fsImpl);
}

export const SWEEP_NAME = "sweep.json";
export const SWEEP_QUEUES = ["iwb", "prbot"];

export function buildSweep({ repo, messageId, channelId, now = new Date() }) {
  return {
    kind: "sweep",
    repo: repo ?? null,
    received_at: now.toISOString(),
    slack_message_id: messageId ?? null,
    slack_channel: channelId,
    source: "github-event-router",
    version: 1,
  };
}

/**
 * Ask both consumers for a full pass. One fixed name per queue, replaced
 * atomically, so at most one sweep is pending. If a pending sweep names a
 * different repo, the new one covers all repos (repo null).
 */
export async function writeSweep(root, sweep, { fsImpl = fs } = {}) {
  const written = [];
  for (const queue of SWEEP_QUEUES) {
    let record = sweep;
    try {
      const pending = JSON.parse(await fsImpl.readFile(path.join(root, queue, SWEEP_NAME), "utf8"));
      if (pending?.kind === "sweep" && pending.repo !== sweep.repo) record = { ...sweep, repo: null };
    } catch {
      // none pending, or unreadable: the new sweep replaces it
    }
    written.push(await publish(root, queue, SWEEP_NAME, record, fsImpl));
  }
  return written;
}

async function publish(root, queue, name, record, fsImpl) {
  const queueDir = path.join(root, queue);
  const tmpDir = path.join(root, ".tmp");
  await fsImpl.mkdir(queueDir, { recursive: true, mode: 0o700 });
  await fsImpl.mkdir(tmpDir, { recursive: true, mode: 0o700 });
  await ensureMarker(root, fsImpl);
  const tmp = path.join(tmpDir, `${queue}-${name}.${process.pid}.${crypto.randomBytes(3).toString("hex")}.tmp`);
  const dest = path.join(queueDir, name);
  let handle;
  try {
    handle = await fsImpl.open(tmp, "wx", 0o600);
    await handle.writeFile(`${JSON.stringify(record)}\n`);
    await handle.sync();
    const open = handle;
    handle = undefined;
    await open.close();
    await fsImpl.rename(tmp, dest);
  } catch (err) {
    // Whatever failed (open, write, sync, close or rename), leave no temp file.
    if (handle) await handle.close().catch(() => {});
    await fs.rm(tmp, { force: true }).catch(() => {});
    throw err;
  }
  return dest;
}

/**
 * Keep a bounded sample of bot posts we could not parse, to learn the real
 * shapes. content and body are kept apart because they come from different
 * Slack fields (see analyzePost in router.js).
 */
export async function recordUnparsed(root, { messageId, content, body, now = new Date() }) {
  const clip = (s) => (typeof s === "string" ? s.slice(0, 600) : null);
  const file = path.join(root, "unparsed.jsonl");
  try {
    const st = await fs.stat(file);
    if (st.size > UNPARSED_MAX_BYTES) return;
  } catch {
    // missing is fine
  }
  await fs.mkdir(root, { recursive: true, mode: 0o700 });
  const line = JSON.stringify({
    received_at: now.toISOString(),
    slack_message_id: messageId ?? null,
    content: clip(content),
    body: content === body ? "(same as content)" : clip(body),
  });
  await fs.appendFile(file, `${line}\n`, { mode: 0o600 });
}
