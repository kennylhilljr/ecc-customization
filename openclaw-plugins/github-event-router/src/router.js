// Claim decision for before_dispatch. Pure functions; no I/O.

import os from "node:os";
import path from "node:path";

import { parseGithubPost } from "./parse.js";

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

export function isBotSender(event, ctx, botSenderIds) {
  const sender = event?.senderId ?? ctx?.senderId;
  if (typeof sender !== "string" || !sender) return false;
  if (botSenderIds.length > 0) return botSenderIds.includes(sender);
  // OpenClaw's Slack plugin uses message.user, falling back to bot_id. A
  // B-prefixed id is therefore always a bot. An app that also sets
  // message.user shows up as a U id: list it in botSenderIds.
  return /^B[A-Z0-9]{6,}$/.test(sender);
}

export function mentionsOpenclaw(text) {
  return OPENCLAW_MENTION.test(text);
}

export function messageText(event) {
  const parts = [event?.content, event?.body].filter((s) => typeof s === "string" && s.trim());
  // body usually repeats content; keep both so neither form is lost.
  return parts.join("\n");
}

/**
 * @returns {{action: "ignore"} | {action: "pass", reason: string} |
 *   {action: "claim", parsed: object | null}}
 *   ignore: not ours, return undefined.
 *   pass: ours, but let the normal agent turn run.
 *   claim: return { handled: true }; queue parsed when it is not null.
 */
export function decide(event, ctx, cfg) {
  if (!isFeedChannel(event, ctx, cfg.channelId)) return { action: "ignore" };
  if (!isBotSender(event, ctx, cfg.botSenderIds)) return { action: "ignore" };
  const text = messageText(event);
  if (mentionsOpenclaw(text)) return { action: "pass", reason: "mention" };
  return { action: "claim", parsed: parseGithubPost(text) };
}

export function queueFor(kind) {
  return kind === "pull_request" ? "prbot" : "iwb";
}
