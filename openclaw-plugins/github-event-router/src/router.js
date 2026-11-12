// Claim decision for before_dispatch. Pure functions; no I/O.

import os from "node:os";
import path from "node:path";

import { extractRepo, parseGithubPost } from "./parse.js";

export const DEFAULT_CHANNEL_ID = "C0CEMPH1L0N";

// "@openclaw" as a mention, any case: not inside an email address or a longer
// name ("me@openclaw.com", "@openclawbot", "@openclaw-bot"), but trailing
// punctuation is fine ("@OpenClaw,", "@openclaw."). lib/gh_command_drain.py
// uses the same pattern; tests/fixtures/mention-cases.json is shared by both
// test suites.
export const OPENCLAW_MENTION = /(?<![A-Za-z0-9_.+-])@openclaw(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])/i;

export class ConfigError extends Error {}

// An owner entry is a Slack user id (U or W, upper case), optionally prefixed,
// in any case, with "slack:", "user:" or "slack:user:", with optional
// whitespace around it. openclaw.plugin.json uses this same pattern for
// ownerSenderIds items; tests/fail-closed-owners.test.js checks that the two
// agree. A wildcard grants nobody owner status here.
export const OWNER_ID_PATTERN = "^\\s*(?:[Ss][Ll][Aa][Cc][Kk]:)?(?:[Uu][Ss][Ee][Rr]:)?[UW][A-Z0-9]{6,}\\s*$";
const OWNER_ID_RE = new RegExp(OWNER_ID_PATTERN, "u");

/** The bare user id an owner entry stands for, or null when it is not one. */
export function normalizeOwnerId(entry) {
  if (typeof entry !== "string" || !OWNER_ID_RE.test(entry)) return null;
  return entry.trim().replace(/^(?:slack:)?(?:user:)?/i, "");
}

// Slack allowFrom is OpenClaw's own setting and may hold other entries
// ("*", channel ids): keep the user ids, skip the rest, drop duplicates.
export function ownerIdsFrom(list) {
  if (!Array.isArray(list)) return [];
  const ids = [];
  for (const entry of list) {
    const id = normalizeOwnerId(entry);
    if (id !== null && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

/**
 * The owner ids for this plugin, independent of the rest of its config.
 * ownerSenderIds, when present (even empty), replaces channels.slack.allowFrom.
 * It must be a list of owner entries naming each id once; anything else
 * throws ConfigError, and callers then grant no owner exemption.
 *
 * @param raw plugins.entries.github-event-router.config
 * @param openclawConfig the full OpenClaw config (api.config)
 */
export function resolveOwnerIds(raw, openclawConfig) {
  const cfg = raw && typeof raw === "object" ? raw : {};
  if (cfg.ownerSenderIds === undefined) return ownerIdsFrom(openclawConfig?.channels?.slack?.allowFrom);
  if (!Array.isArray(cfg.ownerSenderIds)) throw new ConfigError("ownerSenderIds must be a list of Slack user ids");
  const ids = [];
  for (const entry of cfg.ownerSenderIds) {
    const id = normalizeOwnerId(entry);
    if (id === null) {
      throw new ConfigError("ownerSenderIds must be a list of Slack user ids such as U0ADXF02M4K, optionally prefixed with slack:, user: or slack:user:");
    }
    if (ids.includes(id)) throw new ConfigError(`ownerSenderIds names ${id} more than once`);
    ids.push(id);
  }
  return ids;
}

/**
 * @param raw plugins.entries.github-event-router.config
 * @param openclawConfig the full OpenClaw config (api.config); owners come
 *   from channels.slack.allowFrom unless the plugin config sets ownerSenderIds.
 */
export function parseConfig(raw = {}, { home = os.homedir(), openclawConfig } = {}) {
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
  const ownerSenderIds = resolveOwnerIds(cfg, openclawConfig);
  return { channelId, queueRoot: path.normalize(queueRoot), botSenderIds: [...botSenderIds], ownerSenderIds };
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
export function contentIsTrusted(event) {
  const content = trimmed(event?.content);
  const body = trimmed(event?.body);
  return Boolean(content && body && content !== body);
}

export function analyzePost(event) {
  const content = trimmed(event?.content);
  const body = trimmed(event?.body);
  if (contentIsTrusted(event)) {
    const parsed = parseGithubPost(content);
    return { parsed, sweep: !parsed, sweepRepo: parsed ? null : extractRepo(content) };
  }
  return { parsed: parseGithubPost(content || body), sweep: true, sweepRepo: null };
}

/**
 * Where a verified-command request should look. Only a target read from
 * trusted text is used; otherwise the drain scans every installed repo.
 */
function commandTarget(event, analysis) {
  if (!contentIsTrusted(event)) return { repo: null, number: null, target_kind: null };
  if (analysis.parsed) {
    return { repo: analysis.parsed.repo, number: analysis.parsed.number, target_kind: analysis.parsed.kind };
  }
  return { repo: analysis.sweepRepo, number: null, target_kind: null };
}

const NO_WORK = { parsed: null, sweep: false, sweepRepo: null, command: null };

/**
 * Nothing in a GitHub post ever reaches an agent turn directly: comment
 * bodies are written by whoever can comment on GitHub. Only owners
 * (channels.slack.allowFrom, or ownerSenderIds) get a normal turn.
 *
 * @returns {{action: "ignore"} |
 *   {action: "claim", parsed, sweep, sweepRepo, command, unknownBot?, hintSender?}}
 *   ignore: an owner's message; return undefined so the ops turn runs.
 *   claim: return { handled: true }. Queue parsed when not null, a sweep when
 *     sweep is true, and a command request (for the verified-command drain)
 *     when command is not null.
 *     unknownBot: a B sender not in botSenderIds; nothing is queued.
 *     hintSender: any other non-owner whose post is GitHub-shaped (a
 *     github.com/owner/repo link or an "[owner/repo]" line), so the operator
 *     can tell whether it is the app. Nothing is queued.
 */
export function decide(event, ctx, cfg) {
  if (!isFeedChannel(event, ctx, cfg.channelId)) return { action: "ignore" };
  const sender = senderOf(event, ctx);
  if (sender && (cfg.ownerSenderIds ?? []).includes(sender)) return { action: "ignore" };
  const text = messageText(event);
  if (isGithubSender(event, ctx, cfg.botSenderIds)) {
    const analysis = analyzePost(event);
    const command = mentionsOpenclaw(text) ? commandTarget(event, analysis) : null;
    return { action: "claim", ...analysis, command };
  }
  if (isSlackBotId(sender)) return { action: "claim", ...NO_WORK, unknownBot: sender };
  // Someone else: a person who is not an owner, or an app whose posts carry
  // a U or W id. The before_dispatch event in 2026.9.6 carries no bot_id,
  // subtype or app id (PluginHookBeforeDispatchEvent/Context in openclaw's
  // d.ts, filled in dist/dispatch-from-config-*.mjs), so the text is the only
  // clue for the hint.
  if (sender && isGithubShaped(text)) return { action: "claim", ...NO_WORK, hintSender: sender };
  return { action: "claim", ...NO_WORK };
}

const GITHUB_SHAPED_RE = /https?:\/\/(?:www\.)?github\.com\/[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}|^[*_\s]*\[[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}\]/m;

export function isGithubShaped(text) {
  return typeof text === "string" && GITHUB_SHAPED_RE.test(text);
}

export function queueFor(kind) {
  return kind === "pull_request" ? "prbot" : "iwb";
}
