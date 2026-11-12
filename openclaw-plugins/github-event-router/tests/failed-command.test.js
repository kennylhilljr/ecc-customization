// A command request the router cannot publish is saved as its own
// ops-failed-<UUID>.json file in the queue root, written to .tmp and renamed
// into place, so a drain replaying one file can never lose another.

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import { createHandler } from "../index.js";
import * as queue from "../src/queue.js";
import { parseConfig } from "../src/router.js";
import { SAMPLES, hookFields } from "./fixtures/github-slack-posts.js";

const CHANNEL = "C0CEMPH1L0N";
const FAILED_NAME = /^ops-failed-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$/;

function hookArgs(sample, messageId) {
  const { content, body } = hookFields(sample);
  const event = {
    messageId,
    content,
    body,
    channel: "slack",
    sessionKey: `agent:ops:slack:channel:${CHANNEL.toLowerCase()}`,
    senderId: sample.bot_id,
  };
  return [event, { messageId, channelId: "slack", conversationId: `channel:${CHANNEL}`, senderId: sample.bot_id }];
}

async function tempRoot() {
  return fs.mkdtemp(path.join(os.tmpdir(), "ger-failed-"));
}

async function failedFiles(root) {
  return (await fs.readdir(root)).filter((n) => n.startsWith("ops-failed")).sort();
}

function command(messageId = "1730643302.123456") {
  return queue.buildCommand(
    { repo: "o/r", number: 4, target_kind: "issue" },
    { messageId, channelId: CHANNEL, now: new Date("2026-11-04T05:00:00.000Z") },
  );
}

// Wraps node:fs/promises and makes one step of the write fail.
function failingFs(step) {
  const boom = () => Promise.reject(new Error(`injected ${step} failure`));
  return {
    ...fs,
    rename: step === "rename" ? boom : fs.rename,
    open: async (...args) => {
      if (step === "open") return boom();
      const real = await fs.open(...args);
      return {
        writeFile: step === "write" ? boom : (...a) => real.writeFile(...a),
        sync: step === "sync" ? boom : () => real.sync(),
        close: step === "close" ? async () => {
          await real.close();
          return boom();
        } : () => real.close(),
      };
    },
  };
}

test("concurrent failed command requests each become one complete ops-failed-<UUID>.json file", async () => {
  const root = await tempRoot();
  try {
    const errors = [];
    const cfg = parseConfig({ queueRoot: root, botSenderIds: ["B07GITHUBAPP"] }, { openclawConfig: { channels: { slack: { allowFrom: ["U0ADXF02M4K"] } } } });
    const handler = createHandler(cfg, { error: (m) => errors.push(m), info() {}, warn() {} }, {
      command: async () => {
        throw new Error("ops is not a directory");
      },
      now: () => new Date("2026-11-04T05:00:00.000Z"),
    });
    const ids = Array.from({ length: 12 }, (_, i) => `1730643302.${String(i).padStart(6, "0")}`);
    const results = await Promise.all(ids.map((id) => handler(...hookArgs(SAMPLES.mentionComment, id))));
    for (const r of results) assert.deepEqual(r, { handled: true });
    const names = await failedFiles(root);
    assert.equal(names.length, ids.length, `expected one file per request, got ${JSON.stringify(names)}`);
    for (const n of names) assert.match(n, FAILED_NAME);
    const records = [];
    for (const n of names) {
      const file = path.join(root, n);
      assert.equal((await fs.stat(file)).mode & 0o777, 0o600, n);
      const text = await fs.readFile(file, "utf8");
      assert.equal(text.endsWith("\n"), true);
      assert.equal(text.trim().split("\n").length, 1, `${n} holds one request`);
      records.push(JSON.parse(text));
    }
    assert.deepEqual(records.map((r) => r.slack_message_id).sort(), ids);
    for (const r of records) {
      assert.deepEqual(r, {
        kind: "command",
        repo: "kennylhilljr/agent-control-plane-infra",
        number: 6,
        target_kind: "issue",
        received_at: "2026-11-04T05:00:00.000Z",
        slack_message_id: r.slack_message_id,
        slack_channel: CHANNEL,
        source: "github-event-router",
        version: 1,
      });
    }
    assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), []);
    assert.equal(errors.length, ids.length);
    for (const e of errors) {
      const m = /could not write command request \(ops is not a directory\); saved it to (\S+) for the drain to replay/.exec(e);
      assert.ok(m, e);
      assert.match(m[1], FAILED_NAME);
      assert.ok(names.includes(m[1]), m[1]);
    }
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("writeFailedCommand publishes complete content with one rename", async () => {
  assert.equal(typeof queue.writeFailedCommand, "function", "queue.js exports writeFailedCommand");
  const root = await tempRoot();
  try {
    const seen = [];
    const fsImpl = {
      ...fs,
      rename: async (from, to) => {
        seen.push({ to: path.basename(to), dir: path.dirname(from), text: await fs.readFile(from, "utf8") });
        return fs.rename(from, to);
      },
    };
    const rec = command();
    const dest = await queue.writeFailedCommand(root, rec, { fsImpl });
    assert.equal(path.dirname(dest), root);
    assert.match(path.basename(dest), FAILED_NAME);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].dir, path.join(root, ".tmp"));
    assert.equal(seen[0].to, path.basename(dest));
    assert.deepEqual(JSON.parse(seen[0].text), rec);
    assert.equal(await fs.readFile(dest, "utf8"), seen[0].text);
    assert.equal((await fs.stat(dest)).mode & 0o777, 0o600);
    // A second request never touches the first file.
    const second = await queue.writeFailedCommand(root, command("2.2"));
    assert.notEqual(second, dest);
    assert.deepEqual(JSON.parse(await fs.readFile(dest, "utf8")), rec);
    assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), []);
    await assert.rejects(fs.stat(path.join(root, "ops-failed.jsonl")));
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("writeFailedCommand leaves no temp or published file when any step fails", async () => {
  assert.equal(typeof queue.writeFailedCommand, "function", "queue.js exports writeFailedCommand");
  for (const step of ["open", "write", "sync", "close", "rename"]) {
    const root = await tempRoot();
    try {
      await assert.rejects(queue.writeFailedCommand(root, command(), { fsImpl: failingFs(step) }), new RegExp(`injected ${step}`));
      assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), [], step);
      assert.deepEqual(await failedFiles(root), [], step);
    } finally {
      await fs.rm(root, { recursive: true, force: true });
    }
  }
});

test("a failed fallback write is logged, the request is lost and the post is still claimed", async () => {
  const root = await tempRoot();
  try {
    const lost = [];
    const cfg = parseConfig({ queueRoot: root, botSenderIds: ["B07GITHUBAPP"] });
    const handler = createHandler(cfg, { error: (m) => lost.push(m), info() {}, warn() {} }, {
      command: async () => {
        throw new Error("a");
      },
      failed: async () => {
        throw new Error("b");
      },
    });
    assert.deepEqual(await handler(...hookArgs(SAMPLES.mentionComment, "1.1")), { handled: true });
    assert.equal(lost.length, 1);
    assert.match(lost[0], /could not write command request \(a\) or save it as a failed-request file \(b\); it is lost/);
    assert.deepEqual(await failedFiles(root), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
