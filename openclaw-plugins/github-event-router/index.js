// OpenClaw plugin entry: github-event-router.
//
// Registers one before_dispatch handler for the GitHub feed channel:
// - An owner's message (channels.slack.allowFrom, or ownerSenderIds) goes to
//   the normal ops agent turn.
// - A post from the GitHub app (botSenderIds) is claimed, so no model turn
//   runs, and becomes queue files: an issue event in <queueRoot>/iwb, a pull
//   request event in <queueRoot>/prbot, a sweep request in both when no
//   precise target can be trusted, and a command request in <queueRoot>/ops
//   when the post mentions @openclaw. The command drain
//   (bin/openclaw-gh-command-drain) checks the comment's author with the
//   GitHub API before anything reaches the ops agent.
// - Every other message in the channel is claimed and dropped, with
//   rate-limited log lines that help find the GitHub app's sender id.
//
// No runtime dependencies and no SDK import: the default export is the plain
// object definePluginEntry() returns, as in the ecc-orchestrator plugin.

import {
  appendCommandJournal,
  buildCommand,
  buildRecord,
  buildSweep,
  COMMAND_JOURNAL,
  recordUnparsed,
  writeCommand,
  writeEvent,
  writeSweep,
} from "./src/queue.js";
import { ConfigError, DEFAULT_CHANNEL_ID, decide, isFeedChannel, ownerIdsFrom, parseConfig, senderOf } from "./src/router.js";

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

function errText(err) {
  return err?.message ?? String(err);
}

export function createHandler(
  cfg,
  logger,
  {
    write = writeEvent,
    sweep = writeSweep,
    command = writeCommand,
    journal = appendCommandJournal,
    unparsed = recordUnparsed,
    now = () => new Date(),
    senderLog,
  } = {},
) {
  const logSender = senderLog ?? createSenderLog(logger);
  return async function beforeDispatch(event, ctx) {
    let decision;
    try {
      decision = decide(event, ctx, cfg);
    } catch (err) {
      // Fail closed in the feed channel: a post we could not judge must not
      // reach an agent turn.
      let feed = false;
      try {
        feed = isFeedChannel(event, ctx, cfg.channelId);
      } catch {
        feed = false;
      }
      logger?.warn?.(`${PLUGIN_ID}: decision failed${feed ? ", message dropped" : ""}: ${errText(err)}`);
      return feed ? { handled: true } : undefined;
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

    const messageId = event?.messageId ?? ctx?.messageId;
    const stamp = now();
    if (decision.parsed) {
      const record = buildRecord(decision.parsed, { messageId, channelId: cfg.channelId, now: stamp });
      try {
        const file = await write(cfg.queueRoot, record);
        logger?.info?.(`${PLUGIN_ID}: queued ${record.repo} ${record.kind} #${record.number} ${record.event} -> ${file}`);
      } catch (err) {
        // Still claim: the hourly backstop scan picks the item up.
        logger?.warn?.(`${PLUGIN_ID}: could not write queue file for ${record.repo}#${record.number}: ${errText(err)}`);
      }
    } else if (decision.sweep) {
      try {
        await unparsed(cfg.queueRoot, { messageId, content: event?.content, body: event?.body, now: stamp });
      } catch {
        // best effort only
      }
    }
    if (decision.sweep) {
      // No target we can trust: ask both consumers for a full pass.
      const record = buildSweep({ repo: decision.sweepRepo, messageId, channelId: cfg.channelId, now: stamp });
      try {
        const { written, failed } = await sweep(cfg.queueRoot, record);
        for (const f of failed) logger?.warn?.(`${PLUGIN_ID}: could not write sweep to ${f.queue}: ${errText(f.error)}`);
        if (written.length) logger?.info?.(`${PLUGIN_ID}: queued sweep for ${record.repo ?? "all repos"} (post ${messageId ?? "(no id)"})`);
      } catch (err) {
        logger?.warn?.(`${PLUGIN_ID}: could not write sweep: ${errText(err)}`);
      }
    }
    if (decision.command) {
      const record = buildCommand(decision.command, { messageId, channelId: cfg.channelId, now: stamp });
      try {
        const file = await command(cfg.queueRoot, record);
        logger?.info?.(`${PLUGIN_ID}: queued @openclaw command check for ${record.repo ?? "all repos"}${record.number ? `#${record.number}` : ""} -> ${file}`);
      } catch (err) {
        // Keep the request: the drain replays this journal into ops/.
        try {
          await journal(cfg.queueRoot, record);
          logger?.error?.(`${PLUGIN_ID}: could not write command request (${errText(err)}); saved it to ${COMMAND_JOURNAL} for the drain to replay`);
        } catch (err2) {
          logger?.error?.(`${PLUGIN_ID}: could not write command request (${errText(err)}) or save it to ${COMMAND_JOURNAL} (${errText(err2)}); it is lost`);
        }
      }
    }
    return { handled: true };
  };
}

/**
 * Used when the plugin config is invalid. Fails closed: every message in the
 * feed channel is dropped except an owner's, and nothing is queued.
 */
export function createFailClosedHandler(raw, openclawConfig) {
  const channelId = typeof raw?.channelId === "string" && /^[CG][A-Z0-9]{6,}$/.test(raw.channelId) ? raw.channelId : DEFAULT_CHANNEL_ID;
  let owners = [];
  try {
    owners = ownerIdsFrom(openclawConfig?.channels?.slack?.allowFrom);
  } catch {
    owners = [];
  }
  return async function beforeDispatchFailClosed(event, ctx) {
    try {
      if (!isFeedChannel(event, ctx, channelId)) return undefined;
      const sender = senderOf(event, ctx);
      if (sender && owners.includes(sender)) return undefined;
    } catch {
      // cannot tell: drop
    }
    return { handled: true };
  };
}

export function register(api) {
  const logger = api.logger;
  let cfg;
  try {
    cfg = parseConfig(api.pluginConfig ?? {}, { openclawConfig: api.config });
  } catch (err) {
    const message = err instanceof ConfigError ? err.message : "invalid configuration";
    logger?.error?.(`${PLUGIN_ID}: ${message}; nothing is queued and every message in the feed channel except the owner's is dropped until the config is fixed`);
    api.on("before_dispatch", createFailClosedHandler(api.pluginConfig, api.config));
    return;
  }
  if (cfg.ownerSenderIds.length === 0) {
    logger?.warn?.(`${PLUGIN_ID}: no owner ids (channels.slack.allowFrom or ownerSenderIds); every message in ${cfg.channelId} will be dropped`);
  }
  api.on("before_dispatch", createHandler(cfg, logger));
  logger?.info?.(`${PLUGIN_ID}: watching Slack channel ${cfg.channelId}, queue root ${cfg.queueRoot}, ${cfg.ownerSenderIds.length} owner id(s)`);
}

export default {
  id: PLUGIN_ID,
  name: "GitHub Event Router",
  description: "Queues GitHub Slack app posts for issue-worker-bots, pr-review-bots and the verified-command drain without a model turn.",
  register,
};
