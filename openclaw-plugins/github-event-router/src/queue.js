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

export async function writeEvent(root, record) {
  const queueDir = path.join(root, queueFor(record.kind));
  const tmpDir = path.join(root, ".tmp");
  await fs.mkdir(queueDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(tmpDir, { recursive: true, mode: 0o700 });
  const name = queueFileName(record);
  const tmp = path.join(tmpDir, `${name}.${process.pid}.tmp`);
  const dest = path.join(queueDir, name);
  const handle = await fs.open(tmp, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(record)}\n`);
    await handle.sync();
  } finally {
    await handle.close();
  }
  try {
    await fs.rename(tmp, dest);
  } catch (err) {
    await fs.rm(tmp, { force: true });
    throw err;
  }
  return dest;
}

/** Keep a bounded sample of bot posts we could not parse, to learn the real shapes. */
export async function recordUnparsed(root, { messageId, text, now = new Date() }) {
  const file = path.join(root, "unparsed.jsonl");
  try {
    const st = await fs.stat(file);
    if (st.size > UNPARSED_MAX_BYTES) return;
  } catch {
    // missing is fine
  }
  await fs.mkdir(root, { recursive: true, mode: 0o700 });
  const line = JSON.stringify({ received_at: now.toISOString(), slack_message_id: messageId ?? null, sample: text.slice(0, 600) });
  await fs.appendFile(file, `${line}\n`, { mode: 0o600 });
}
