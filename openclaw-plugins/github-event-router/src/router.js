// Claim decision for before_dispatch. Pure functions; no I/O.

import os from "node:os";
import path from "node:path";

import { extractRepo, parseGithubPost } from "./parse.js";

export const DEFAULT_CHANNEL_ID = "C0CEMPH1L0N";

// Same intent as the ops agent's mentionPatterns ("@[Oo]pen[Cc]law\b"), but
// case-insensitive as asked.
const OPENCLAW_MENTION = /@openclaw(?![A-Za-z0-9_])/i;

export class ConfigError extends Error {}

export function parseConfig(raw = {}, { home = os.homedir() } = {}) {
  const cfg = raw && typeof raw === "object" ? raw : {};
  const channelId = cfg.channelId ?? DEFAULT_CHANNEL_ID;
  if (typeof channelId !== "string" || !/^[CG][A-Z0-9]{6,}$/.test(channelId)) {
    throw new ConfigError("channelId must be a Slack channel id such as C0CEMPH1L0N");
  }
  const queueRoot = cfg.queueRoot ?? path.join(home, ".local", "state", "github-events");
  if (typeof queueRoot !== "string" || !path.isAbsolute(queueRoot) || queueRoot.split(path.sep).includes("..")) {
    throw new ConfigError("queueRoot must be an absolute path without ..");
  }
  const botSenderIds = cfg.botSenderIds ?? [];
  if (!Array.isArray(botSenderIds) || botSenderIds.some((id) => typeof id !== "string" || !/^[BUW][A-Z0-9]{6,}$/.test(id))) {
    throw new ConfigError("botSenderIds must be a list of Slack ids");
  }
  return { channelId, queueRoot: path.normalize(queueRoot), botSenderIds: [...botSenderIds] };
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * True when any routing field names the channel. Slack conversation ids show
 * up as "C0CEMPH1L0N", "channel:C0CEMPH1L0N" or
 * "team:T123:channel:C0CEMPH1L0N"; session keys are lower case and look like
 * "agent:ops:slack:channel:c0cemph1l0n[:thread:...]".
 */
export function isFeedChannel(event, ctx, channelId) {
  const surface = String(event?.channel ?? ctx?.channelId ?? "").toLowerCase();
  if (surface && surface !== "slack") return false;
  const token = new RegExp(`(^|[:/])${escapeRe(channelId)}($|[:/])`, "i");
  return [ctx?.conversationId, event?.sessionKey, ctx?.sessionKey].some(
    (v) => typeof v === "string" && token.test(v),
  );
}

export function senderOf(event, ctx) {
  const sender = event?.senderId ?? ctx?.senderId;
  return typeof sender === "string" && sender ? sender : null;
}

/** Only an explicitly listed sender is the GitHub app. There is no default. */
export function isGithubSender(event, ctx, botSenderIds) {
  const sender = senderOf(event, ctx);
  return sender !== null && botSenderIds.includes(sender);
}

// OpenClaw's Slack plugin passes message.user as the sender, falling back to
// bot_id, so a B-prefixed sender is always some bot.
export function isSlackBotId(sender) {
  return typeof sender === "string" && /^B[A-Z0-9]{6,}$/.test(sender);
}

export function mentionsOpenclaw(text) {
  return OPENCLAW_MENTION.test(text);
}

export function messageText(event) {
  const parts = [event?.content, event?.body].filter((s) => typeof s === "string" && s.trim());
  // body usually repeats content; keep both so neither form is lost.
  return parts.join("\n");
}

function trimmed(s) {
  return typeof s === "string" ? s.trim() : "";
}

/**
 * Split a post into what the GitHub app wrote itself and what came from the
 * issue or comment, then decide what to queue.
 *
 * OpenClaw 2026.9.6 (@openclaw/slack, dist/.setup/pipeline.runtime-*.mjs):
 *   event.content = message.text with Slack mentions stripped (commandBody);
 *     when message.text is blank it falls back to the raw body.
 *   event.body = raw body = message.text (or blocks text), then for a bot
 *     message each attachment's `text ?? fallback`, one per line.
 *
 * So content is trusted header/title text only when it differs from body
 * (message.text was set and attachments added more): parse content alone and
 * fall back to a sweep when it names no target.
 *
 * When the two are equal, the text is either message.text alone or
 * attachment text alone, and the hook cannot tell which. A target found
 * there is still queued, but a sweep (all repos) is always added, so a
 * target taken from issue or comment text can only cause an extra check of
 * that item, never a missed event.
 *
 * @returns {{parsed: object | null, sweep: boolean, sweepRepo: string | null}}
 */
export function analyzePost(event) {
  const content = trimmed(event?.content);
  const body = trimmed(event?.body);
  if (content && body && content !== body) {
    const parsed = parseGithubPost(content);
    return { parsed, sweep: !parsed, sweepRepo: parsed ? null : extractRepo(content) };
  }
  return { parsed: parseGithubPost(content || body), sweep: true, sweepRepo: null };
}

/**
 * @returns {{action: "ignore", hintSender?: string} |
 *   {action: "pass", reason: string, unknownBot?: string} |
 *   {action: "claim", parsed: object | null, sweep: boolean, sweepRepo: string | null, unknownBot?: string}}
 *   ignore: not ours, return undefined. hintSender is set when a sender that
 *     is neither listed nor a B id posted something GitHub-shaped (a
 *     github.com/owner/repo link or an "[owner/repo]" line), parsed or not,
 *     so the operator can tell whether it is the app.
 *   pass: let the normal agent turn run (the post contains @openclaw).
 *   claim: return { handled: true }. Queue parsed when it is not null, and a
 *     sweep (full pass) when sweep is true.
 *     unknownBot is set for a B sender that is not in botSenderIds: claimed
 *     so it cannot start a paid agent turn, but never queued.
 */
export function decide(event, ctx, cfg) {
  if (!isFeedChannel(event, ctx, cfg.channelId)) return { action: "ignore" };
  const sender = senderOf(event, ctx);
  const text = messageText(event);
  if (isGithubSender(event, ctx, cfg.botSenderIds)) {
    if (mentionsOpenclaw(text)) return { action: "pass", reason: "mention" };
    return { action: "claim", ...analyzePost(event) };
  }
  if (isSlackBotId(sender)) {
    if (mentionsOpenclaw(text)) return { action: "pass", reason: "mention", unknownBot: sender };
    return { action: "claim", parsed: null, sweep: false, sweepRepo: null, unknownBot: sender };
  }
  // Possibly a person (Kenny), or an app whose posts carry a U or W id. The
  // before_dispatch event in 2026.9.6 carries no bot_id, subtype or app id
  // (PluginHookBeforeDispatchEvent/Context in openclaw's d.ts, filled in
  // dist/dispatch-from-config-*.mjs), so the text is the only clue.
  if (sender && isGithubShaped(text)) return { action: "ignore", hintSender: sender };
  return { action: "ignore" };
}

const GITHUB_SHAPED_RE = /https?:\/\/(?:www\.)?github\.com\/[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}|^[*_\s]*\[[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}\]/m;

export function isGithubShaped(text) {
  return typeof text === "string" && GITHUB_SHAPED_RE.test(text);
}

export function queueFor(kind) {
  return kind === "pull_request" ? "prbot" : "iwb";
}
