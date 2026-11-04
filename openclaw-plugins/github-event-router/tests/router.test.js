import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import plugin, { createHandler, createSenderLog } from "../index.js";
import { buildRecord, queueFileName, writeEvent } from "../src/queue.js";
import { ConfigError, decide, isFeedChannel, isGithubSender, mentionsOpenclaw, parseConfig } from "../src/router.js";
import { SAMPLES, flattenLikeOpenClaw } from "./fixtures/github-slack-posts.js";

const CHANNEL = "C0CEMPH1L0N";
const cfg = parseConfig({ queueRoot: "/q", botSenderIds: ["B07GITHUBAPP"] });

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

test("GitHub sender: only an explicit botSenderIds entry counts, no default", () => {
  assert.ok(!isGithubSender({ senderId: "B07GITHUBAPP" }, {}, []));
  assert.ok(!isGithubSender({ senderId: "U0ADXF02M4K" }, {}, []));
  assert.ok(!isGithubSender({}, {}, ["B07GITHUBAPP"]));
  assert.ok(isGithubSender({ senderId: "B07GITHUBAPP" }, {}, ["B07GITHUBAPP"]));
  assert.ok(isGithubSender({ senderId: "U0GITHUBAPP" }, {}, ["U0GITHUBAPP"]));
  assert.ok(!isGithubSender({ senderId: "B07OTHERBOT" }, {}, ["B07GITHUBAPP"]));
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

  // Kenny typing in the channel: untouched. A pasted GitHub notification only
  // yields a hint so an app with a U id can be identified.
  assert.deepEqual(decide(...hookArgs({ text: "thanks" }, { event: { senderId: "U0ADXF02M4K" } }), cfg), { action: "ignore" });
  assert.deepEqual(decide(...hookArgs(SAMPLES.prOpened, { event: { senderId: "U0ADXF02M4K" } }), cfg), {
    action: "ignore",
    hintSender: "U0ADXF02M4K",
  });
  // A bot that is not on the list (a CI bot posting a GitHub link): claimed
  // so it cannot start an agent turn, never queued.
  assert.deepEqual(decide(...hookArgs(SAMPLES.prOpened, { event: { senderId: "B07CIBOT01" } }), cfg), {
    action: "claim",
    parsed: null,
    unknownBot: "B07CIBOT01",
  });
  assert.deepEqual(decide(...hookArgs(SAMPLES.mentionComment, { event: { senderId: "B07CIBOT01" } }), cfg), {
    action: "pass",
    reason: "mention",
    unknownBot: "B07CIBOT01",
  });
  // Default config trusts nobody.
  assert.equal(decide(...hookArgs(SAMPLES.prOpened), parseConfig({ queueRoot: "/q" })).unknownBot, "B07GITHUBAPP");
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
    // The consumers' safety marker is in the root, beside the queues, and a
    // second write leaves it alone. Nothing but events lands in a queue dir.
    const marker = path.join(root, ".github-events-queue");
    assert.ok((await fs.lstat(marker)).isFile());
    await writeEvent(root, rec);
    assert.ok((await fs.lstat(marker)).isFile());
    assert.deepEqual((await fs.readdir(path.join(root, "prbot"))).filter((n) => !n.endsWith(".json")), []);
    assert.deepEqual((await fs.readdir(root)).sort(), [".github-events-queue", ".tmp", "prbot"]);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

// Wraps node:fs/promises and makes one step of the write fail.
function failingFs(step) {
  const boom = () => Promise.reject(new Error(`injected ${step} failure`));
  return {
    ...fs,
    mkdir: fs.mkdir,
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

test("writeEvent removes its temp file when any step fails", async () => {
  for (const step of ["open", "write", "sync", "close", "rename"]) {
    const root = await tempRoot();
    try {
      const rec = buildRecord({ repo: "o/r", kind: "issue", number: 4, event: "opened" }, { messageId: "1.2", channelId: CHANNEL });
      await assert.rejects(writeEvent(root, rec, { fsImpl: failingFs(step) }), new RegExp(`injected ${step}`));
      assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), [], step);
      assert.deepEqual(await listQueue(root, "iwb"), [], step);
    } finally {
      await fs.rm(root, { recursive: true, force: true });
    }
  }
});

test("posts from an unknown bot are claimed, not queued, and logged at most once per interval", async () => {
  const root = await tempRoot();
  try {
    const lines = [];
    let t = 0;
    const logger = { info: (m) => lines.push(m), warn: (m) => lines.push(m) };
    const handler = createHandler(parseConfig({ queueRoot: root }), logger, {
      senderLog: createSenderLog(logger, { intervalMs: 1000, clock: () => t }),
    });
    for (let i = 0; i < 5; i++) {
      assert.deepEqual(await handler(...hookArgs(SAMPLES.prOpened)), { handled: true });
    }
    t = 1500;
    assert.deepEqual(await handler(...hookArgs(SAMPLES.issueComment)), { handled: true });
    // @openclaw from an unknown bot still reaches the agent.
    assert.equal(await handler(...hookArgs(SAMPLES.mentionComment)), undefined);
    assert.deepEqual(lines, [
      "github-event-router: unknown bot sender B07GITHUBAPP",
      "github-event-router: unknown bot sender B07GITHUBAPP",
    ]);
    assert.deepEqual(await listQueue(root, "iwb"), []);
    assert.deepEqual(await listQueue(root, "prbot"), []);
    await assert.rejects(fs.stat(path.join(root, "unparsed.jsonl")));
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("sender log tracks a bounded number of ids", () => {
  const lines = [];
  const log = createSenderLog({ info: (m) => lines.push(m) }, { intervalMs: 1000, clock: () => 0 });
  for (let i = 0; i < 200; i++) log(`B0BOT${String(i).padStart(4, "0")}`, `line ${i}`);
  assert.equal(lines.length, 64);
});

test("a U sender posting a GitHub notification is not claimed but is hinted once", async () => {
  const lines = [];
  const handler = createHandler(cfg, { info: (m) => lines.push(m) });
  const args = hookArgs(SAMPLES.prOpened, { event: { senderId: "U0GITHUBAPP" } });
  assert.equal(await handler(...args), undefined);
  assert.equal(await handler(...args), undefined);
  assert.equal(lines.length, 1);
  assert.match(lines[0], /sender U0GITHUBAPP posted a GitHub notification but is not in botSenderIds/);
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
