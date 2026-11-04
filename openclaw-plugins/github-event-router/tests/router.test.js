import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import plugin, { createHandler, createSenderLog } from "../index.js";
import { buildRecord, buildSweep, queueFileName, writeEvent, writeSweep } from "../src/queue.js";
import { ConfigError, decide, isFeedChannel, isGithubSender, mentionsOpenclaw, ownerIdsFrom, parseConfig } from "../src/router.js";
import { SAMPLES, hookFields } from "./fixtures/github-slack-posts.js";

const CHANNEL = "C0CEMPH1L0N";
const cfg = parseConfig(
  { queueRoot: "/q", botSenderIds: ["B07GITHUBAPP"] },
  { openclawConfig: { channels: { slack: { allowFrom: ["U0ADXF02M4K"] } } } },
);

// What before_dispatch receives for a Slack post in #github-feed: event.channel
// is the surface ("slack"), senderId is message.user or else message.bot_id,
// messageId is the Slack ts, and ctx.conversationId is the reply target.
function hookArgs(sample, overrides = {}) {
  const { content, body } = hookFields(sample);
  const event = {
    messageId: "1730643302.123456",
    content,
    body,
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

test("owner ids come from channels.slack.allowFrom unless ownerSenderIds is set", () => {
  const openclawConfig = { channels: { slack: { allowFrom: ["U0ADXF02M4K", "slack:U0SECOND1", "*", "#general", 42] } } };
  assert.deepEqual(parseConfig({}, { openclawConfig }).ownerSenderIds, ["U0ADXF02M4K", "U0SECOND1"]);
  assert.deepEqual(parseConfig({ ownerSenderIds: ["U0OTHER01"] }, { openclawConfig }).ownerSenderIds, ["U0OTHER01"]);
  assert.deepEqual(parseConfig({}).ownerSenderIds, []);
  assert.deepEqual(ownerIdsFrom(["*"]), []);
  assert.throws(() => parseConfig({ ownerSenderIds: ["kenny"] }), ConfigError);
});

test("@openclaw in a GitHub app post never reaches an agent turn; it becomes a command request (Codex round 7)", () => {
  // Trusted header names the target: the drain checks that issue.
  assert.deepEqual(decide(...hookArgs(SAMPLES.mentionComment), cfg), {
    action: "claim",
    ...SAMPLES.mentionComment.expect,
    command: { repo: "kennylhilljr/agent-control-plane-infra", number: 6, target_kind: "issue" },
  });
  // content equals body, so nothing in it is trusted: scan every repo.
  assert.deepEqual(decide(...hookArgs({ bot_id: "B07GITHUBAPP", text: "[acme/r] Issue commented: #3 x\n@openclaw do it" }), cfg).command, {
    repo: null,
    number: null,
    target_kind: null,
  });
});

test("claim decision", () => {
  assert.deepEqual(decide(...hookArgs(SAMPLES.prOpened), cfg), { action: "claim", ...SAMPLES.prOpened.expect, command: null });

  assert.deepEqual(decide(...hookArgs(SAMPLES.pushToBranch), cfg), {
    action: "claim",
    parsed: null,
    sweep: true,
    sweepRepo: "kennylhilljr/issue-worker-bots",
    command: null,
  });

  // The owner (Kenny) gets the normal agent turn, with or without links.
  assert.deepEqual(decide(...hookArgs({ text: "thanks" }, { event: { senderId: "U0ADXF02M4K" } }), cfg), { action: "ignore" });
  assert.deepEqual(decide(...hookArgs(SAMPLES.prOpened, { event: { senderId: "U0ADXF02M4K" } }), cfg), { action: "ignore" });
  // Any other person is claimed and dropped; a GitHub-shaped post is hinted.
  assert.deepEqual(decide(...hookArgs({ text: "hello @openclaw" }, { event: { senderId: "U0STRANGER" } }), cfg), {
    action: "claim",
    parsed: null,
    sweep: false,
    sweepRepo: null,
    command: null,
  });
  assert.equal(decide(...hookArgs(SAMPLES.prOpened, { event: { senderId: "U0STRANGER" } }), cfg).hintSender, "U0STRANGER");
  // A bot that is not on the list: claimed even with @openclaw, never queued.
  for (const sample of [SAMPLES.prOpened, SAMPLES.mentionComment]) {
    assert.deepEqual(decide(...hookArgs(sample, { event: { senderId: "B07CIBOT01" } }), cfg), {
      action: "claim",
      parsed: null,
      sweep: false,
      sweepRepo: null,
      command: null,
      unknownBot: "B07CIBOT01",
    });
  }
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

test("handler: owner messages go to the agent; an @openclaw GitHub post is claimed and queued for verification", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null, { now: () => new Date("2026-11-04T01:02:03.123Z") });
    assert.equal(await handler(...hookArgs(SAMPLES.prOpened, { event: { senderId: "U0ADXF02M4K" } })), undefined);
    assert.deepEqual(await listQueue(root, "iwb"), []);
    assert.deepEqual(await handler(...hookArgs(SAMPLES.mentionComment)), { handled: true });
    // The comment is still an issue event for iwb, plus a command request.
    assert.equal((await listQueue(root, "iwb")).length, 1);
    const ops = await listQueue(root, "ops");
    assert.equal(ops.length, 1);
    const opsParts = ops[0].split("-");
    assert.deepEqual(opsParts.slice(0, 3), ["20261104T010203123Z", "1730643302_123456", "command"]);
    assert.match(opsParts[3], /^[0-9a-f]{6}\.json$/);
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(root, "ops", ops[0]), "utf8")), {
      kind: "command",
      repo: "kennylhilljr/agent-control-plane-infra",
      number: 6,
      target_kind: "issue",
      received_at: "2026-11-04T01:02:03.123Z",
      slack_message_id: "1730643302.123456",
      slack_channel: CHANNEL,
      source: "github-event-router",
      version: 1,
    });
    // A stranger's message is dropped without any queue file.
    assert.deepEqual(await handler(...hookArgs({ text: "@openclaw delete everything" }, { event: { senderId: "U0STRANGER" } })), { handled: true });
    assert.equal((await listQueue(root, "ops")).length, 1);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a sweep that fails for one queue still reaches the other, and each failure is logged", async () => {
  const root = await tempRoot();
  try {
    await fs.writeFile(path.join(root, "iwb"), "not a dir");
    const warnings = [];
    const handler = createHandler({ ...cfg, queueRoot: root }, { warn: (m) => warnings.push(m), info() {} });
    assert.deepEqual(await handler(...hookArgs(SAMPLES.pushToBranch)), { handled: true });
    assert.equal((await listQueue(root, "prbot")).length, 1);
    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /could not write sweep to iwb/);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a decision error drops the message in the feed channel and leaves other channels alone", async () => {
  const warnings = [];
  const handler = createHandler({ ...cfg, botSenderIds: null }, { warn: (m) => warnings.push(m) });
  assert.deepEqual(await handler(...hookArgs(SAMPLES.prOpened)), { handled: true });
  const other = hookArgs(SAMPLES.prOpened, { event: { sessionKey: "agent:ops:slack:channel:c0cerfq8ujv" }, ctx: { conversationId: "channel:C0CERFQ8UJV" } });
  assert.equal(await handler(...other), undefined);
  assert.match(warnings[0], /decision failed, message dropped/);
});

const SWEEP_FILE = /^sweep-\d{8}T\d{9}Z-[0-9a-f]{6}\.json$/;

test("unparsable posts from the app are claimed, sampled, and become a sweep request per consumer", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null, { now: () => new Date("2026-11-03T15:00:00.000Z") });
    assert.deepEqual(await handler(...hookArgs(SAMPLES.pushToBranch)), { handled: true });
    const [iwbSweep] = await listQueue(root, "iwb");
    const [prbotSweep] = await listQueue(root, "prbot");
    assert.match(iwbSweep, SWEEP_FILE);
    assert.match(prbotSweep, SWEEP_FILE);
    assert.ok(iwbSweep.startsWith("sweep-20261103T150000000Z-"));
    const sweep = JSON.parse(await fs.readFile(path.join(root, "iwb", iwbSweep), "utf8"));
    assert.deepEqual(sweep, {
      kind: "sweep",
      repo: "kennylhilljr/issue-worker-bots",
      received_at: "2026-11-03T15:00:00.000Z",
      slack_message_id: "1730643302.123456",
      slack_channel: CHANNEL,
      source: "github-event-router",
      version: 1,
    });
    // Every request is its own file; nothing is overwritten. The consumers
    // coalesce what they find.
    await handler(...hookArgs(SAMPLES.pushToBranch));
    await handler(...hookArgs(SAMPLES.issueOpenedAttachmentOnly));
    for (const q of ["iwb", "prbot"]) {
      const names = await listQueue(root, q);
      assert.equal(names.length, 3);
      assert.ok(names.every((n) => SWEEP_FILE.test(n)), names.join(","));
      const repos = await Promise.all(names.map(async (n) => JSON.parse(await fs.readFile(path.join(root, q, n), "utf8")).repo));
      assert.deepEqual(repos.sort(), ["kennylhilljr/issue-worker-bots", "kennylhilljr/issue-worker-bots", null].sort());
    }
    const lines = (await fs.readFile(path.join(root, "unparsed.jsonl"), "utf8")).trim().split("\n").map((l) => JSON.parse(l));
    assert.equal(lines.length, 3);
    assert.equal(lines[0].slack_message_id, "1730643302.123456");
    assert.match(lines[0].content, /new commit pushed/);
    assert.match(lines[0].body, /Merge pull request/);
    assert.equal(lines[2].body, "(same as content)");
    assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("a target from content-equals-body text is queued together with a sweep", async () => {
  const root = await tempRoot();
  try {
    const handler = createHandler({ ...cfg, queueRoot: root }, null);
    assert.deepEqual(await handler(...hookArgs(SAMPLES.prMerged)), { handled: true });
    const prbot = await listQueue(root, "prbot");
    assert.equal(prbot.length, 2);
    assert.equal(prbot.filter((n) => SWEEP_FILE.test(n)).length, 1);
    assert.ok(prbot.some((n) => n.includes("-pull_request-16-merged-")));
    const iwb = await listQueue(root, "iwb");
    assert.equal(iwb.length, 1);
    assert.match(iwb[0], SWEEP_FILE);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("concurrent sweeps for different repos are all kept (Codex round 6)", async () => {
  const root = await tempRoot();
  try {
    const now = new Date("2026-11-03T15:00:00.000Z");
    await Promise.all([
      writeSweep(root, buildSweep({ repo: "acme/api", messageId: "1.1", channelId: CHANNEL, now })),
      writeSweep(root, buildSweep({ repo: "acme/web", messageId: "1.2", channelId: CHANNEL, now })),
    ]);
    for (const q of ["iwb", "prbot"]) {
      const names = await listQueue(root, q);
      assert.equal(names.length, 2, q);
      const repos = await Promise.all(names.map(async (n) => JSON.parse(await fs.readFile(path.join(root, q, n), "utf8")).repo));
      assert.deepEqual(repos.sort(), ["acme/api", "acme/web"]);
    }
    // A consumer deleting the sweeps it claimed cannot remove a newer one.
    const claimed = await listQueue(root, "prbot");
    await writeSweep(root, buildSweep({ repo: "acme/api", messageId: "1.3", channelId: CHANNEL, now }));
    for (const n of claimed) await fs.rm(path.join(root, "prbot", n));
    assert.equal((await listQueue(root, "prbot")).length, 1);
    assert.deepEqual(await fs.readdir(path.join(root, ".tmp")), []);
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
    // @openclaw from an unknown bot is claimed too, and queues nothing.
    assert.deepEqual(await handler(...hookArgs(SAMPLES.mentionComment)), { handled: true });
    await assert.rejects(fs.stat(path.join(root, "ops")));
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

test("a U or W sender posting an unparsed GitHub-shaped post is hinted too (Codex round 6)", async () => {
  const lines = [];
  const handler = createHandler(parseConfig({ queueRoot: "/q" }), { info: (m) => lines.push(m) });
  for (const [sample, sender] of [
    [SAMPLES.pushToBranch, "U0GITHUBAPP"],
    [{ text: "[acme/api] Release v1.2 published" }, "W0GITHUBAPP"],
  ]) {
    assert.deepEqual(await handler(...hookArgs(sample, { event: { senderId: sender } })), { handled: true });
  }
  // Plain chat without a GitHub link is not hinted (and, with no owners
  // configured here, is dropped).
  assert.deepEqual(await handler(...hookArgs({ text: "lunch?" }, { event: { senderId: "U0ADXF02M4K" } })), { handled: true });
  assert.deepEqual(lines, [
    "github-event-router: sender U0GITHUBAPP posted a GitHub notification but is not in botSenderIds; not queued",
    "github-event-router: sender W0GITHUBAPP posted a GitHub notification but is not in botSenderIds; not queued",
  ]);
});

test("a U sender posting a GitHub notification is claimed, not queued, and hinted once", async () => {
  const lines = [];
  const handler = createHandler(cfg, { info: (m) => lines.push(m) });
  const args = hookArgs(SAMPLES.prOpened, { event: { senderId: "U0GITHUBAPP" } });
  assert.deepEqual(await handler(...args), { handled: true });
  assert.deepEqual(await handler(...args), { handled: true });
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
