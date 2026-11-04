// OpenClaw plugin entry: github-event-router.
//
// Registers one before_dispatch handler. For a post in the GitHub feed
// channel from a sender listed in botSenderIds it writes a queue file
// (issues to <queueRoot>/iwb, pull requests to <queueRoot>/prbot) and returns
// { handled: true } so no model turn runs. A post from any other Slack bot
// (B id) is claimed but never queued, with a rate-limited "unknown bot
// sender" log line. A post that contains @openclaw is left to the normal ops
// agent turn. Messages from people are untouched.
//
// No runtime dependencies and no SDK import: the default export is the plain
// object definePluginEntry() returns, as in the ecc-orchestrator plugin.

import { buildRecord, buildSweep, recordUnparsed, writeEvent, writeSweep } from "./src/queue.js";
import { ConfigError, decide, parseConfig } from "./src/router.js";

export const PLUGIN_ID = "github-event-router";

export const SENDER_LOG_INTERVAL_MS = 10 * 60 * 1000;
const SENDER_LOG_MAX_IDS = 64;

/** One log line per sender id per interval, tracking at most 64 ids. */
export function createSenderLog(logger, { intervalMs = SENDER_LOG_INTERVAL_MS, clock = () => Date.now() } = {}) {
  const last = new Map();
  return (key, line) => {
    const t = clock();
    const prev = last.get(key);
    if (prev !== undefined && t - prev < intervalMs) return false;
    if (prev === undefined && last.size >= SENDER_LOG_MAX_IDS) return false;
    last.set(key, t);
    logger?.info?.(line);
    return true;
  };
}

export function createHandler(
  cfg,
  logger,
  { write = writeEvent, sweep = writeSweep, unparsed = recordUnparsed, now = () => new Date(), senderLog } = {},
) {
  const logSender = senderLog ?? createSenderLog(logger);
  return async function beforeDispatch(event, ctx) {
    let decision;
    try {
      decision = decide(event, ctx, cfg);
    } catch (err) {
      logger?.warn?.(`${PLUGIN_ID}: decision failed, leaving message to the agent: ${err?.message ?? err}`);
      return undefined;
    }
    if (decision.unknownBot) {
      logSender(decision.unknownBot, `${PLUGIN_ID}: unknown bot sender ${decision.unknownBot}`);
    }
    if (decision.hintSender) {
      logSender(
        decision.hintSender,
        `${PLUGIN_ID}: sender ${decision.hintSender} posted a GitHub notification but is not in botSenderIds; not queued`,
      );
    }
    if (decision.action !== "claim") return undefined;
    if (decision.unknownBot) return { handled: true };

    const messageId = event?.messageId ?? ctx?.messageId;
    if (decision.parsed) {
      const record = buildRecord(decision.parsed, { messageId, channelId: cfg.channelId, now: now() });
      try {
        const file = await write(cfg.queueRoot, record);
        logger?.info?.(`${PLUGIN_ID}: queued ${record.repo} ${record.kind} #${record.number} ${record.event} -> ${file}`);
      } catch (err) {
        // Still claim: the hourly backstop scan picks the item up, and an
        // unclaimed post would only wake the agent for nothing.
        logger?.warn?.(`${PLUGIN_ID}: could not write queue file for ${record.repo}#${record.number}: ${err?.message ?? err}`);
      }
    } else {
      try {
        await unparsed(cfg.queueRoot, { messageId, content: event?.content, body: event?.body, now: now() });
      } catch {
        // best effort only
      }
    }
    if (decision.sweep) {
      // The post did not name a target we can trust, so ask both consumers
      // for a full pass instead of depending on the parser.
      const record = buildSweep({ repo: decision.sweepRepo, messageId, channelId: cfg.channelId, now: now() });
      try {
        await sweep(cfg.queueRoot, record);
        logger?.info?.(`${PLUGIN_ID}: queued sweep for ${record.repo ?? "all repos"} (post ${messageId ?? "(no id)"})`);
      } catch (err) {
        logger?.warn?.(`${PLUGIN_ID}: could not write sweep: ${err?.message ?? err}`);
      }
    }
    return { handled: true };
  };
}

export function register(api) {
  const logger = api.logger;
  let cfg;
  try {
    cfg = parseConfig(api.pluginConfig ?? {});
  } catch (err) {
    const message = err instanceof ConfigError ? err.message : "invalid configuration";
    logger?.warn?.(`${PLUGIN_ID}: ${message}; the router is not active`);
    return;
  }
  api.on("before_dispatch", createHandler(cfg, logger));
  logger?.info?.(`${PLUGIN_ID}: watching Slack channel ${cfg.channelId}, queue root ${cfg.queueRoot}`);
}

export default {
  id: PLUGIN_ID,
  name: "GitHub Event Router",
  description: "Queues GitHub Slack app posts for issue-worker-bots and pr-review-bots without a model turn.",
  register,
};
