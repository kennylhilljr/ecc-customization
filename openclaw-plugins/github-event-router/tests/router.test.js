import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import plugin, { createHandler } from "../index.js";
import { buildRecord, queueFileName, writeEvent } from "../src/queue.js";
import { ConfigError, decide, isBotSender, isFeedChannel, mentionsOpenclaw, parseConfig } from "../src/router.js";
import { SAMPLES, flattenLikeOpenClaw } from "./fixtures/github-slack-posts.js";

const CHANNEL = "C0CEMPH1L0N";
const cfg = parseConfig({ queueRoot: "/q" });

// What before_dispatch receives for a Slack post in #github-feed: event.channel
// is the surface ("slack"), senderId is message.user or else message.bot_id,
// messageId is the Slack ts, and ctx.conversationId is the reply target.
function hookArgs(sample, overrides = {}) {
  const text = flattenLikeOpenClaw(sample);
  const event = {
    messageId: "1730643302.123456",
    content: text,
    body: text,
    channel: "slack",
    sessionKey: `agent:ops:slack:channel:${CHANNEL.toLowerCase()}`,
    senderId: sample.bot_id,
    isGroup: true,
    timestamp: 1730643302123,
    ...overrides.event,
  };
  const ctx = {
    messageId: event.messageId,
    channelId: "slack",
    conversationId: `channel:${CHANNEL}`,
    sessionKey: event.sessionKey,
    senderId: event.senderId,
    ...overrides.ctx,
  };
  return [event, ctx];
}

async function tempRoot() {
  return fs.mkdtemp(path.join(os.tmpdir(), "ger-"));
}

async function listQueue(root, q) {
  try {
    return (await fs.readdir(path.join(root, q))).sort();
  } catch {
    return [];
  }
}

test("config defaults and validation", () => {
  const c = parseConfig({}, { home: "/Users/x" });
  assert.equal(c.channelId, CHANNEL);
  assert.equal(c.queueRoot, "/Users/x/.local/state/github-events");
  assert.deepEqual(c.botSenderIds, []);
  assert.throws(() => parseConfig({ queueRoot: "rel/path" }), ConfigError);
  assert.throws(() => parseConfig({ queueRoot: "/a/../b" }), ConfigError);
  assert.throws(() => parseConfig({ channelId: "general" }), ConfigError);
  assert.throws(() => parseConfig({ botSenderIds: ["kenny"] }), ConfigError);
});

test("feed channel match accepts the conversation id forms OpenClaw uses", () => {
  for (const conversationId of [CHANNEL, `channel:${CHANNEL}`, `team:T0ABC123:channel:${CHANNEL}`]) {
    assert.ok(isFeedChannel({ channel: "slack" }, { conversationId }, CHANNEL), conversationId);
  }
  assert.ok(isFeedChannel({ channel: "slack", sessionKey: `agent:ops:slack:channel:${CHANNEL.toLowerCase()}:thread:1.2` }, {}, CHANNEL));
  assert.ok(!isFeedChannel({ channel: "slack" }, { conversationId: "channel:C0CERFQ8UJV" }, CHANNEL));
  assert.ok(!isFeedChannel({ channel: "slack" }, { conversationId: `channel:${CHANNEL}X` }, CHANNEL));
  assert.ok(!isFeedChannel({ channel: "discord" }, { conversationId: `channel:${CHANNEL}` }, CHANNEL));
});

test("bot sender: B ids by default, explicit list when configured", () => {
  assert.ok(isBotSender({ senderId: "B07GITHUBAPP" }, {}, []));
  assert.ok(!isBotSender({ senderId: "U0ADXF02M4K" }, {}, []));
  assert.ok(!isBotSender({}, {}, []));
  assert.ok(isBotSender({ senderId: "U0GITHUBAPP" }, {}, ["U0GITHUBAPP"]));
  assert.ok(!isBotSender({ senderId: "B07OTHERBOT" }, {}, ["U0GITHUBAPP"]));
});

test("@openclaw is matched case-insensitively and as a whole word", () => {
  for (const t of ["@openclaw do it", "hey @OpenClaw.", "@OPENCLAW", "x\n@OpenClaw: ping"]) assert.ok(mentionsOpenclaw(t), t);
  for (const t of ["openclaw", "@openclawbot", "@open_claw", "email me@openclaw_x"]) assert.ok(!mentionsOpenclaw(t), t);
});

test("claim decision", () => {
  const claim = decide(...hookArgs(SAMPLES.prOpened), cfg);
  assert.equal(claim.action, "claim");
  assert.deepEqual(claim.parsed, SAMPLES.prOpened.expect);

  assert.deepEqual(decide(...hookArgs(SAMPLES.mentionComment), cfg), { action: "pass", reason: "mention" });

  const unparsed = decide(...hookArgs(SAMPLES.subscribeAck), cfg);
  assert.deepEqual(unparsed, { action: "claim", parsed: null });

  // Kenny typing in the channel: untouched.
  assert.deepEqual(decide(...hookArgs({ ...SAMPLES.prOpened, bot_id: undefined }, { event: { senderId: "U0ADXF02M4K" } }), cfg), { action: "ignore" });
  // Same bot post in another channel: untouched.
  assert.deepEqual(
    decide(...hookArgs(SAMPLES.prOpened, { event: { sessionKey: "agent:ops:slack:channel:c0cerfq8ujv" }, ctx: { conversationId: "channel:C0CERFQ8UJV" } }), cfg),
    { action: "ignore" },
  );
});

test("handler writes one queue file per event and claims without text", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null, { now: () => new Date("2026-11-03T14:15:02.123Z") });
    assert.deepEqual(await handler(...hookArgs(SAMPLES.issueComment)), { handled: true });
    assert.deepEqual(await handler(...hookArgs(SAMPLES.prPush)), { handled: true });

    const iwb = await listQueue(root, "iwb");
    const prbot = await listQueue(root, "prbot");
    assert.equal(iwb.length, 1);
    assert.equal(prbot.length, 1);
    const parts = iwb[0].split("-");
    assert.equal(parts[0], "20261103T141502123Z");
    assert.equal(parts[1], "1730643302_123456");
    assert.ok(iwb[0].includes("-kennylhilljr__agent-control-plane-infra-issue-6-comment-"), iwb[0]);
    assert.match(parts.at(-1), /^[0-9a-f]{6}\.json$/);
    const rec = JSON.parse(await fs.readFile(path.join(root, "iwb", iwb[0]), "utf8"));
    assert.deepEqual(rec, {
      repo: "kennylhilljr/agent-control-plane-infra",
      kind: "issue",
      number: 6,
      event: "comment",
      received_at: "2026-11-03T14:15:02.123Z",
      slack_message_id: "1730643302.123456",
      slack_channel: CHANNEL,
      source: "github-event-router",
      version: 1,
    });
    const pr = JSON.parse(await fs.readFile(path.join(root, "prbot", prbot[0]), "utf8"));
    assert.equal(pr.kind, "pull_request");
    assert.equal(pr.event, "synchronize");
    // Nothing left behind in the temp dir.
    assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("handler leaves @openclaw posts and human messages to the agent", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null);
    assert.equal(await handler(...hookArgs(SAMPLES.mentionComment)), undefined);
    assert.equal(await handler(...hookArgs(SAMPLES.prOpened, { event: { senderId: "U0ADXF02M4K" } })), undefined);
    assert.deepEqual(await listQueue(root, "iwb"), []);
    assert.deepEqual(await listQueue(root, "prbot"), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("unparsable bot posts are claimed and sampled, not queued", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null);
    assert.deepEqual(await handler(...hookArgs(SAMPLES.pushToBranch)), { handled: true });
    assert.deepEqual(await listQueue(root, "iwb"), []);
    assert.deepEqual(await listQueue(root, "prbot"), []);
    const lines = (await fs.readFile(path.join(root, "unparsed.jsonl"), "utf8")).trim().split("\n");
    assert.equal(lines.length, 1);
    assert.equal(JSON.parse(lines[0]).slack_message_id, "1730643302.123456");
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a failed queue write still claims and logs", async () => {
  const warnings = [];
  const handler = createHandler(cfg, { warn: (m) => warnings.push(m), info() {} }, {
    write: async () => {
      throw new Error("disk full");
    },
  });
  assert.deepEqual(await handler(...hookArgs(SAMPLES.prOpened)), { handled: true });
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /disk full/);
});

test("queue file names sort by time and stay unique", () => {
  const parsed = { repo: "o/r", kind: "issue", number: 1, event: "opened" };
  const a = queueFileName(buildRecord(parsed, { messageId: "1.1", channelId: CHANNEL, now: new Date("2026-11-03T09:00:00.000Z") }), "aaaaaa");
  const b = queueFileName(buildRecord(parsed, { messageId: "1.2", channelId: CHANNEL, now: new Date("2026-11-03T10:00:00.000Z") }), "000000");
  assert.ok(a < b);
  const same = buildRecord(parsed, { messageId: "1.1", channelId: CHANNEL, now: new Date("2026-11-03T09:00:00.000Z") });
  assert.notEqual(queueFileName(same), queueFileName(same));
});

test("writeEvent creates the queue dirs and never leaves partial files in the queue", async () => {
  const root = await tempRoot();
  try {
    const rec = buildRecord({ repo: "o/r", kind: "pull_request", number: 3, event: "review" }, { messageId: "9.9", channelId: CHANNEL });
    const dest = await writeEvent(root, rec);
    assert.equal(path.dirname(dest), path.join(root, "prbot"));
    assert.deepEqual(JSON.parse(await fs.readFile(dest, "utf8")), rec);
    const mode = (await fs.stat(dest)).mode & 0o777;
    assert.equal(mode, 0o600);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("register wires one before_dispatch handler, and none on bad config", () => {
  const calls = [];
  plugin.register({ pluginConfig: { queueRoot: "/tmp/q" }, logger: null, on: (name, fn) => calls.push([name, typeof fn]) });
  assert.deepEqual(calls, [["before_dispatch", "function"]]);
  const none = [];
  plugin.register({ pluginConfig: { queueRoot: "relative" }, logger: { warn() {} }, on: (n) => none.push(n) });
  assert.deepEqual(none, []);
  assert.equal(plugin.id, "github-event-router");
});
