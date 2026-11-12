// Owner ids: one accepted syntax for the manifest schema, parseConfig() and
// the fail-closed hook, and ownerSenderIds overriding channels.slack.allowFrom
// even when the rest of the plugin config is invalid.

import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

import plugin from "../index.js";
import * as router from "../src/router.js";
import { SAMPLES, hookFields } from "./fixtures/github-slack-posts.js";

const { ConfigError, parseConfig } = router;
const CHANNEL = "C0CEMPH1L0N";
const ALLOW_FROM = "U0ADXF02M4K";
const EXPLICIT = "U0EXPLICIT1";
const manifest = JSON.parse(await fs.readFile(new URL("../openclaw.plugin.json", import.meta.url), "utf8"));
// JSON Schema patterns are ECMA-262 regular expressions; OpenClaw's validator compiles them with the u flag.
const itemPattern = new RegExp(manifest.configSchema.properties.ownerSenderIds.items.pattern, "u");

// [entry, the id it stands for, or null when it must be refused]
const OWNER_ENTRIES = [
  ["U0ADXF02M4K", "U0ADXF02M4K"],
  ["W0ABCDEF12", "W0ABCDEF12"],
  ["U0ABCDE", "U0ABCDE"],
  ["slack:U0ADXF02M4K", "U0ADXF02M4K"],
  ["user:U0ADXF02M4K", "U0ADXF02M4K"],
  ["slack:user:U0ADXF02M4K", "U0ADXF02M4K"],
  ["SLACK:U0ADXF02M4K", "U0ADXF02M4K"],
  ["Slack:User:W0ABCDEF12", "W0ABCDEF12"],
  ["sLaCk:uSeR:U0ADXF02M4K", "U0ADXF02M4K"],
  ["USER:U0ADXF02M4K", "U0ADXF02M4K"],
  ["  U0ADXF02M4K  ", "U0ADXF02M4K"],
  ["\tslack:user:U0ADXF02M4K\n", "U0ADXF02M4K"],
  ["*", null],
  ["", null],
  ["   ", null],
  ["u0adxf02m4k", null],
  ["U0adxf02m4k", null],
  ["U0ABCD", null],
  ["B07GITHUBAPP", null],
  ["C0CEMPH1L0N", null],
  ["user:slack:U0ADXF02M4K", null],
  ["slack:slack:U0ADXF02M4K", null],
  ["user:user:U0ADXF02M4K", null],
  ["slack:user:user:U0ADXF02M4K", null],
  ["slack:", null],
  ["slack:user:", null],
  ["slack: U0ADXF02M4K", null],
  ["slack :U0ADXF02M4K", null],
  ["U0ADX F02M4K", null],
  ["U0ADXF02M4K!", null],
  ["U0ADXF02M4K,U0SECOND1", null],
  ["U0ADXF02M4K x", null],
  ["channel:U0ADXF02M4K", null],
  ["slackuser:U0ADXF02M4K", null],
];

function hookArgs(sample, overrides = {}) {
  const { content, body } = hookFields(sample);
  const event = {
    messageId: "1730643302.123456",
    content,
    body,
    channel: "slack",
    sessionKey: `agent:ops:slack:channel:${CHANNEL.toLowerCase()}`,
    senderId: sample.bot_id,
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

function from(sender, text = "hi") {
  return hookArgs({ text }, { event: { senderId: sender } });
}

function outsideFeed(sender) {
  return hookArgs({ text: "hi" }, {
    event: { senderId: sender, sessionKey: "agent:ops:slack:channel:c0cerfq8ujv" },
    ctx: { conversationId: "channel:C0CERFQ8UJV" },
  });
}

// Registers the plugin and returns its single before_dispatch hook and the errors it logged.
function registerHook(pluginConfig, allowFrom = [ALLOW_FROM]) {
  const hooks = [];
  const errors = [];
  plugin.register({
    pluginConfig,
    config: { channels: { slack: { allowFrom } } },
    logger: { error: (m) => errors.push(m), warn() {}, info() {} },
    on: (name, fn) => hooks.push([name, fn]),
  });
  assert.equal(hooks.length, 1);
  assert.equal(hooks[0][0], "before_dispatch");
  return { hook: hooks[0][1], errors };
}

test("the manifest's ownerSenderIds pattern and parseConfig accept exactly the same owner entries", () => {
  for (const [entry, id] of OWNER_ENTRIES) {
    const label = JSON.stringify(entry);
    assert.equal(itemPattern.test(entry), id !== null, `schema pattern on ${label}`);
    if (id === null) {
      assert.throws(() => parseConfig({ ownerSenderIds: [entry] }), ConfigError, `parseConfig on ${label}`);
    } else {
      assert.deepEqual(parseConfig({ ownerSenderIds: [entry] }).ownerSenderIds, [id], `parseConfig on ${label}`);
    }
  }
});

test("resolveOwnerIds: an explicit list overrides allowFrom; malformed lists and duplicates are refused", () => {
  assert.equal(typeof router.resolveOwnerIds, "function", "router.js exports resolveOwnerIds");
  const { resolveOwnerIds } = router;
  const openclawConfig = { channels: { slack: { allowFrom: ["*", "slack:U0ADXF02M4K", "U0ADXF02M4K", "U0SECOND1"] } } };
  assert.deepEqual(resolveOwnerIds({}, openclawConfig), ["U0ADXF02M4K", "U0SECOND1"]);
  assert.deepEqual(resolveOwnerIds(undefined, openclawConfig), ["U0ADXF02M4K", "U0SECOND1"]);
  assert.deepEqual(resolveOwnerIds({ ownerSenderIds: [EXPLICIT] }, openclawConfig), [EXPLICIT]);
  assert.deepEqual(resolveOwnerIds({ ownerSenderIds: [" slack:user:U0EXPLICIT1 ", "W0OTHER12"] }, openclawConfig), [EXPLICIT, "W0OTHER12"]);
  assert.deepEqual(resolveOwnerIds({ ownerSenderIds: [] }, openclawConfig), []);
  assert.deepEqual(resolveOwnerIds({}, {}), []);
  for (const bad of [null, "U0EXPLICIT1", {}, 7, [7], [null], ["kenny"], [EXPLICIT, "*"], [EXPLICIT, `slack:${EXPLICIT}`], [EXPLICIT, ` ${EXPLICIT}`]]) {
    assert.throws(() => resolveOwnerIds({ ownerSenderIds: bad }, openclawConfig), ConfigError, JSON.stringify(bad));
    assert.throws(() => parseConfig({ ownerSenderIds: bad }, { openclawConfig }), ConfigError, JSON.stringify(bad));
  }
});

test("ownerSenderIds holds at most the manifest's maxItems entries, in parseConfig and the fail-closed hook", async () => {
  const max = manifest.configSchema.properties.ownerSenderIds.maxItems;
  assert.equal(max, 16);
  const ids = Array.from({ length: max + 1 }, (_, i) => `U0OWNER${String(i).padStart(3, "0")}`);
  assert.deepEqual(parseConfig({ ownerSenderIds: ids.slice(0, max) }).ownerSenderIds, ids.slice(0, max));
  assert.throws(() => parseConfig({ ownerSenderIds: ids }), ConfigError);
  const { hook, errors } = registerHook({ queueRoot: "relative", ownerSenderIds: ids });
  assert.equal(errors.length, 1);
  for (const id of [ids[0], ids[max], ALLOW_FROM]) assert.deepEqual(await hook(...from(id)), { handled: true }, id);
});

test("bad config fails closed but keeps an explicit owner that differs from allowFrom", async () => {
  const { hook, errors } = registerHook({ queueRoot: "relative", botSenderIds: ["B07GITHUBAPP"], ownerSenderIds: [EXPLICIT] });
  assert.match(errors[0], /queueRoot must be an absolute path/);
  assert.equal(await hook(...from(EXPLICIT)), undefined, "the explicit owner gets the normal turn");
  assert.deepEqual(await hook(...from(ALLOW_FROM)), { handled: true }, "allowFrom is ignored when ownerSenderIds is set");
  assert.deepEqual(await hook(...from("U0STRANGER")), { handled: true });
  assert.deepEqual(await hook(...hookArgs(SAMPLES.mentionComment)), { handled: true });
  assert.equal(await hook(...outsideFeed("U0STRANGER")), undefined);
});

test("the fail-closed hook accepts prefixed and padded explicit owners", async () => {
  const { hook } = registerHook({ queueRoot: "relative", ownerSenderIds: [" slack:user:U0EXPLICIT1 ", "USER:W0OTHER12"] });
  assert.equal(await hook(...from(EXPLICIT)), undefined);
  assert.equal(await hook(...from("W0OTHER12")), undefined);
  assert.deepEqual(await hook(...from(ALLOW_FROM)), { handled: true });
});

test("invalid botSenderIds fails closed and still honors ownerSenderIds", async () => {
  const { hook, errors } = registerHook({ botSenderIds: ["not-an-id"], ownerSenderIds: [EXPLICIT] });
  assert.match(errors[0], /botSenderIds must be a list of Slack ids/);
  assert.equal(await hook(...from(EXPLICIT)), undefined);
  assert.deepEqual(await hook(...from(ALLOW_FROM)), { handled: true });
});

test("without ownerSenderIds the fail-closed hook falls back to allowFrom", async () => {
  const { hook } = registerHook({ queueRoot: "relative" }, ["*", `slack:${ALLOW_FROM}`]);
  assert.equal(await hook(...from(ALLOW_FROM)), undefined);
  assert.deepEqual(await hook(...from(EXPLICIT)), { handled: true });
  assert.deepEqual(await hook(...from("U0STRANGER")), { handled: true });
});

test("an empty ownerSenderIds list grants nobody an owner turn, even the allowFrom user", async () => {
  const { hook } = registerHook({ queueRoot: "relative", ownerSenderIds: [] });
  assert.deepEqual(await hook(...from(ALLOW_FROM)), { handled: true });
  assert.deepEqual(await hook(...from(EXPLICIT)), { handled: true });
});

test("a null, malformed or duplicated ownerSenderIds grants no owner exemption in the fail-closed hook", async () => {
  for (const ownerSenderIds of [null, "U0EXPLICIT1", [7], ["kenny"], [EXPLICIT, "*"], [EXPLICIT, `slack:${EXPLICIT}`]]) {
    const label = JSON.stringify(ownerSenderIds);
    for (const pluginConfig of [{ ownerSenderIds }, { queueRoot: "relative", ownerSenderIds }]) {
      const { hook, errors } = registerHook(pluginConfig);
      assert.equal(errors.length, 1, label);
      assert.deepEqual(await hook(...from(EXPLICIT)), { handled: true }, label);
      assert.deepEqual(await hook(...from(ALLOW_FROM)), { handled: true }, label);
      assert.equal(await hook(...outsideFeed(ALLOW_FROM)), undefined, label);
    }
  }
});

test("the fail-closed hook queues nothing", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "ger-owners-"));
  try {
    const { hook } = registerHook({ queueRoot: root, botSenderIds: ["B07GITHUBAPP", "bad"], ownerSenderIds: [EXPLICIT] });
    for (const sample of [SAMPLES.mentionComment, SAMPLES.prOpened, SAMPLES.pushToBranch]) {
      assert.deepEqual(await hook(...hookArgs(sample)), { handled: true });
    }
    assert.equal(await hook(...from(EXPLICIT, "@openclaw status")), undefined);
    assert.deepEqual(await fs.readdir(root), []);
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
