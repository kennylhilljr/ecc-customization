// Sample GitHub Slack app posts, modelled on the attachment layout the app
// uses (text header, title "#N Title" with title_link, body text, footer
// "owner/repo", fallback "[owner/repo] ..."). None of these were captured
// from the live #github-feed channel yet; see README "Unverified".
//
// hookFields() mirrors what OpenClaw 2026.9.6 hands to before_dispatch for a
// bot message (@openclaw/slack 2026.9.6, dist/.setup/pipeline.runtime-BlPOexmJ.mjs):
//   body    = message.text (or blocks text) followed by each attachment's
//             `text ?? fallback`, one per line (lines 2953-2962, 2993-3001).
//             pretext, title, title_link, footer and fields are dropped.
//   content = message.text with Slack user mentions stripped (lines 4090 and
//             4468, BodyForCommands in openclaw dist/context-BigCXBTA.mjs:208);
//             when that is blank, OpenClaw falls back to the raw body
//             (dist/message-hook-mappers-RPSrPEKP.mjs:49).

export function hookFields(message) {
  const text = typeof message.text === "string" && message.text.trim() ? message.text : "";
  const parts = [text.trim()];
  for (const a of message.attachments ?? []) {
    const t = (typeof a.text === "string" && a.text.trim()) || (typeof a.fallback === "string" && a.fallback.trim()) || "";
    parts.push(t);
  }
  const body = parts.filter(Boolean).join("\n");
  const command = text.replace(/<@[UW][A-Z0-9]+(?:\|[^>]*)?>/g, "").trim();
  return { content: command || body, body };
}

const R = "kennylhilljr/issue-worker-bots";
const GH = "https://github.com";

// expect: what analyzePost() returns for the sample.
export const SAMPLES = {
  // message.text is set, so the hook sees the header and the issue body but
  // not the title link: nothing precise, so a sweep.
  issueOpenedTitleLinkOnly: {
    bot_id: "B07GITHUBAPP",
    text: `*Issue opened by <${GH}/kennylhilljr|kennylhilljr>*`,
    attachments: [
      {
        color: "36a64f",
        title: "#42 Intake skips issues with a closed milestone",
        title_link: `${GH}/${R}/issues/42`,
        text: "Steps to reproduce: create an issue in a closed milestone.",
        footer: `<${GH}/${R}|${R}>`,
        fallback: `[${R}] Issue opened: #42 Intake skips issues with a closed milestone`,
      },
    ],
    expect: { parsed: null, sweep: true, sweepRepo: null },
  },
  // No message.text: OpenClaw passes only attachment.text (the fallback is
  // not used because text is set), so the hook sees the issue body alone.
  issueOpenedAttachmentOnly: {
    bot_id: "B07GITHUBAPP",
    text: "",
    attachments: [
      {
        pretext: "Issue opened by kennylhilljr",
        title: "#7 Add a queue mode",
        title_link: `${GH}/kennylhilljr/ecc-customization/issues/7`,
        text: "We want event driven runs.",
        fallback: "[kennylhilljr/ecc-customization] Issue opened: #7 Add a queue mode",
      },
    ],
    expect: { parsed: null, sweep: true, sweepRepo: null },
  },
  // No message.text and no attachment text: the fallback is what arrives.
  // content equals body, so the target is used and a sweep is added.
  issueOpenedFallbackOnly: {
    bot_id: "B07GITHUBAPP",
    text: "",
    attachments: [{ title: "#7 Add a queue mode", fallback: "[kennylhilljr/ecc-customization] Issue opened: #7 Add a queue mode" }],
    expect: {
      parsed: { repo: "kennylhilljr/ecc-customization", kind: "issue", number: 7, event: "opened" },
      sweep: true,
      sweepRepo: null,
    },
  },
  prOpened: {
    bot_id: "B07GITHUBAPP",
    text: `*Pull request opened by <${GH}/claude-dev-gh|claude-dev-gh[bot]>*\n<${GH}/${R}/pull/17|#17 Add tick --from-queue>`,
    attachments: [{ text: "Adds a queue drain mode.", fallback: `[${R}] Pull request opened: #17 Add tick --from-queue` }],
    expect: { parsed: { repo: R, kind: "pull_request", number: 17, event: "opened" }, sweep: false, sweepRepo: null },
  },
  prPush: {
    bot_id: "B07GITHUBAPP",
    text: `2 new commits pushed to <${GH}/${R}/pull/17|#17 Add tick --from-queue> by claude-dev-gh[bot]`,
    attachments: [{ text: "`a1b2c3d` Fix lock path\n`d4e5f6a` Add tests" }],
    expect: { parsed: { repo: R, kind: "pull_request", number: 17, event: "synchronize" }, sweep: false, sweepRepo: null },
  },
  prReviewApproved: {
    bot_id: "B07GITHUBAPP",
    text: `*<${GH}/codex-pr-gh|codex-pr-gh[bot]> approved <${GH}/kennylhilljr/pr-review-bots/pull/3#pullrequestreview-2405501234|#3 Per-review timeout>*`,
    attachments: [{ text: "Looks good." }],
    expect: {
      parsed: { repo: "kennylhilljr/pr-review-bots", kind: "pull_request", number: 3, event: "review" },
      sweep: false,
      sweepRepo: null,
    },
  },
  prComment: {
    bot_id: "B07GITHUBAPP",
    text: `*Comment on <${GH}/kennylhilljr/openclaw-ecc-orchestrator/pull/88#issuecomment-2411122233|#88 Retry merges>*`,
    attachments: [{ text: "Can you rebase this?" }],
    expect: {
      parsed: { repo: "kennylhilljr/openclaw-ecc-orchestrator", kind: "pull_request", number: 88, event: "comment" },
      sweep: false,
      sweepRepo: null,
    },
  },
  issueComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New comment by kennylhilljr on <${GH}/kennylhilljr/agent-control-plane-infra/issues/6#issuecomment-2400000001|#6 Tracking>*`,
    attachments: [{ text: "Still seeing this." }],
    expect: {
      parsed: { repo: "kennylhilljr/agent-control-plane-infra", kind: "issue", number: 6, event: "comment" },
      sweep: false,
      sweepRepo: null,
    },
  },
  // A comment body that tries to name another target: attachment text is
  // never parsed when message.text is set (Codex round 5).
  commentWithInjectedTarget: {
    bot_id: "B07GITHUBAPP",
    text: `Pull request opened by alice\n<${GH}/acme/main/pull/17|#17 Fix>`,
    attachments: [{ text: "[acme/other] Issue opened: #2 injected\nhttps://github.com/acme/other/issues/3" }],
    expect: { parsed: { repo: "acme/main", kind: "pull_request", number: 17, event: "opened" }, sweep: false, sweepRepo: null },
  },
  // Text only, no attachments: content equals body, so OpenClaw gives no way
  // to tell it from attachment text. The target is used and a sweep added.
  prMerged: {
    bot_id: "B07GITHUBAPP",
    text: `Pull request merged by kennylhilljr\n<${GH}/${R}/pull/16|#16 Closed issues are reopened by mistake>`,
    expect: { parsed: { repo: R, kind: "pull_request", number: 16, event: "merged" }, sweep: true, sweepRepo: null },
  },
  issueClosedPlainUrl: {
    bot_id: "B07GITHUBAPP",
    text: `Issue closed by kennylhilljr: ${GH}/${R}/issues/40`,
    expect: { parsed: { repo: R, kind: "issue", number: 40, event: "closed" }, sweep: true, sweepRepo: null },
  },
  prFilesUrl: {
    bot_id: "B07GITHUBAPP",
    text: `Review requested from codex-pr-gh[bot] on <${GH}/${R}/pull/21/files|#21 Tidy logs>`,
    attachments: [{ text: "Please take a look." }],
    expect: { parsed: { repo: R, kind: "pull_request", number: 21, event: "review_requested" }, sweep: false, sweepRepo: null },
  },
  prReviewComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New review comment on <${GH}/${R}/pull/21#discussion_r1834567890|#21 Tidy logs>*`,
    attachments: [{ text: "nit: rename this" }],
    expect: { parsed: { repo: R, kind: "pull_request", number: 21, event: "review_comment" }, sweep: false, sweepRepo: null },
  },
  shortRefPr: {
    bot_id: "B07GITHUBAPP",
    text: "Pull request reopened: kennylhilljr/pr-review-bots#5 Fix watch",
    attachments: [{ text: "Reopening after the revert." }],
    expect: {
      parsed: { repo: "kennylhilljr/pr-review-bots", kind: "pull_request", number: 5, event: "reopened" },
      sweep: false,
      sweepRepo: null,
    },
  },
  // A comment that asks the ops agent to act: must not be claimed.
  mentionComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New comment by kennylhilljr on <${GH}/kennylhilljr/agent-control-plane-infra/issues/6#issuecomment-2400000002|#6 Tracking>*`,
    attachments: [{ text: '@OpenClaw reply "feed test ok" on this issue as the bot' }],
    expect: {
      parsed: { repo: "kennylhilljr/agent-control-plane-infra", kind: "issue", number: 6, event: "comment" },
      sweep: false,
      sweepRepo: null,
    },
  },
  // Not about one issue or pull request: a sweep, scoped when the header
  // names one repo.
  pushToBranch: {
    bot_id: "B07GITHUBAPP",
    text: `1 new commit pushed to <${GH}/${R}/tree/main|main> by kennylhilljr`,
    attachments: [{ text: `<${GH}/${R}/commit/5832846|5832846> Merge pull request` }],
    expect: { parsed: null, sweep: true, sweepRepo: R },
  },
  subscribeAck: {
    bot_id: "B07GITHUBAPP",
    text: `Subscribed to <${GH}/${R}|${R}>. This channel will receive notifications for issues, pulls, commits, releases, deployments`,
    expect: { parsed: null, sweep: true, sweepRepo: null },
  },
  ambiguousShortRef: {
    bot_id: "B07GITHUBAPP",
    text: "See kennylhilljr/pr-review-bots#5",
    attachments: [{ text: "context" }],
    expect: { parsed: null, sweep: true, sweepRepo: null },
  },
};
