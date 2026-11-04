// OpenClaw plugin entry: github-event-router.
//
// Registers one before_dispatch handler. For a bot-authored post in the
// GitHub feed channel it writes a queue file (issues to <queueRoot>/iwb,
// pull requests to <queueRoot>/prbot) and returns { handled: true } so no
// model turn runs. A post that contains @openclaw is left to the normal ops
// agent turn. Every other message is untouched.
//
// No runtime dependencies and no SDK import: the default export is the plain
// object definePluginEntry() returns, as in the ecc-orchestrator plugin.

import { buildRecord, recordUnparsed, writeEvent } from "./src/queue.js";
import { ConfigError, decide, messageText, parseConfig } from "./src/router.js";

export const PLUGIN_ID = "github-event-router";

export function createHandler(cfg, logger, { write = writeEvent, unparsed = recordUnparsed, now = () => new Date() } = {}) {
  return async function beforeDispatch(event, ctx) {
    let decision;
    try {
      decision = decide(event, ctx, cfg);
    } catch (err) {
      logger?.warn?.(`${PLUGIN_ID}: decision failed, leaving message to the agent: ${err?.message ?? err}`);
      return undefined;
    }
    if (decision.action !== "claim") return undefined;

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
        await unparsed(cfg.queueRoot, { messageId, text: messageText(event), now: now() });
      } catch {
        // best effort only
      }
      logger?.info?.(`${PLUGIN_ID}: claimed bot post ${messageId ?? "(no id)"} without a parsable issue or pull request`);
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
