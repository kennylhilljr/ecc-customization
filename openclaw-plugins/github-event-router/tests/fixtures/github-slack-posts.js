// Sample GitHub Slack app posts, modelled on the attachment layout the app
// uses (pretext or text header, title "#N Title" with title_link, body text,
// footer "owner/repo", fallback "[owner/repo] ..."). None of these were
// captured from the live #github-feed channel yet; see README "Unverified".
//
// flattenLikeOpenClaw() mirrors what the OpenClaw 2026.9.6 Slack plugin hands
// to before_dispatch for a bot message: message.text when present, otherwise
// the attachments' pretext, title, text, fallback and fields; plus each
// attachment's text (or fallback) for bot messages. title_link and footer
// links are dropped, which is why some samples carry only "owner/repo#N".

export function flattenLikeOpenClaw(message) {
  const parts = [];
  const push = (s) => {
    if (typeof s === "string" && s.trim() && !parts.includes(s.trim())) parts.push(s.trim());
  };
  if (typeof message.text === "string" && message.text.trim()) {
    push(message.text);
  } else {
    for (const a of message.attachments ?? []) {
      push(a.pretext);
      push(a.title);
      push(a.text);
      push(a.fallback);
      for (const f of a.fields ?? []) {
        push(f.title);
        push(f.value);
      }
    }
  }
  for (const a of message.attachments ?? []) push(a.text ?? a.fallback);
  return parts.join("\n");
}

const R = "kennylhilljr/issue-worker-bots";
const GH = "https://github.com";

export const SAMPLES = {
  // message.text is set, so OpenClaw drops the attachment title, title_link
  // and fallback: the hook sees the header and the issue body only, which
  // name no issue. If the live app posts this shape, these land in
  // unparsed.jsonl and only the hourly backstop picks the issue up.
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
    expect: null,
  },
  // No message.text: OpenClaw falls back to attachment fields, so only the
  // fallback names the repo and number.
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
    expect: { repo: "kennylhilljr/ecc-customization", kind: "issue", number: 7, event: "opened" },
  },
  prOpened: {
    bot_id: "B07GITHUBAPP",
    text: `*Pull request opened by <${GH}/claude-dev-gh[bot]|claude-dev-gh[bot]>*\n<${GH}/${R}/pull/17|#17 Add tick --from-queue>`,
    attachments: [{ text: "Adds a queue drain mode.", fallback: `[${R}] Pull request opened: #17 Add tick --from-queue` }],
    expect: { repo: R, kind: "pull_request", number: 17, event: "opened" },
  },
  prPush: {
    bot_id: "B07GITHUBAPP",
    text: `2 new commits pushed to <${GH}/${R}/pull/17|#17 Add tick --from-queue> by claude-dev-gh[bot]`,
    attachments: [{ text: "`a1b2c3d` Fix lock path\n`d4e5f6a` Add tests" }],
    expect: { repo: R, kind: "pull_request", number: 17, event: "synchronize" },
  },
  prReviewApproved: {
    bot_id: "B07GITHUBAPP",
    text: `*<${GH}/codex-pr-gh|codex-pr-gh[bot]> approved <${GH}/kennylhilljr/pr-review-bots/pull/3#pullrequestreview-2405501234|#3 Per-review timeout>*`,
    attachments: [{ text: "Looks good." }],
    expect: { repo: "kennylhilljr/pr-review-bots", kind: "pull_request", number: 3, event: "review" },
  },
  prComment: {
    bot_id: "B07GITHUBAPP",
    text: `*Comment on <${GH}/kennylhilljr/openclaw-ecc-orchestrator/pull/88#issuecomment-2411122233|#88 Retry merges>*`,
    attachments: [{ text: "Can you rebase this?" }],
    expect: { repo: "kennylhilljr/openclaw-ecc-orchestrator", kind: "pull_request", number: 88, event: "comment" },
  },
  issueComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New comment by kennylhilljr on <${GH}/kennylhilljr/agent-control-plane-infra/issues/6#issuecomment-2400000001|#6 Tracking>*`,
    attachments: [{ text: "Still seeing this." }],
    expect: { repo: "kennylhilljr/agent-control-plane-infra", kind: "issue", number: 6, event: "comment" },
  },
  prMerged: {
    bot_id: "B07GITHUBAPP",
    text: `Pull request merged by kennylhilljr\n<${GH}/${R}/pull/16|#16 Closed issues are reopened by mistake>`,
    expect: { repo: R, kind: "pull_request", number: 16, event: "merged" },
  },
  issueClosedPlainUrl: {
    bot_id: "B07GITHUBAPP",
    text: `Issue closed by kennylhilljr: ${GH}/${R}/issues/40`,
    expect: { repo: R, kind: "issue", number: 40, event: "closed" },
  },
  prFilesUrl: {
    bot_id: "B07GITHUBAPP",
    text: `Review requested from codex-pr-gh[bot] on <${GH}/${R}/pull/21/files|#21 Tidy logs>`,
    expect: { repo: R, kind: "pull_request", number: 21, event: "review_requested" },
  },
  prReviewComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New review comment on <${GH}/${R}/pull/21#discussion_r1834567890|#21 Tidy logs>*`,
    expect: { repo: R, kind: "pull_request", number: 21, event: "review_comment" },
  },
  shortRefPr: {
    bot_id: "B07GITHUBAPP",
    text: "Pull request reopened: kennylhilljr/pr-review-bots#5 Fix watch",
    expect: { repo: "kennylhilljr/pr-review-bots", kind: "pull_request", number: 5, event: "reopened" },
  },
  // A comment that asks the ops agent to act: must not be claimed.
  mentionComment: {
    bot_id: "B07GITHUBAPP",
    text: `*New comment by kennylhilljr on <${GH}/kennylhilljr/agent-control-plane-infra/issues/6#issuecomment-2400000002|#6 Tracking>*`,
    attachments: [{ text: '@OpenClaw reply "feed test ok" on this issue as the bot' }],
    expect: { repo: "kennylhilljr/agent-control-plane-infra", kind: "issue", number: 6, event: "comment" },
  },
  // Things the app posts that are not about one issue or pull request.
  pushToBranch: {
    bot_id: "B07GITHUBAPP",
    text: `1 new commit pushed to <${GH}/${R}/tree/main|main> by kennylhilljr`,
    attachments: [{ text: `<${GH}/${R}/commit/5832846|5832846> Merge pull request` }],
    expect: null,
  },
  subscribeAck: {
    bot_id: "B07GITHUBAPP",
    text: `Subscribed to <${GH}/${R}|${R}>. This channel will receive notifications for issues, pulls, commits, releases, deployments`,
    expect: null,
  },
  ambiguousShortRef: {
    bot_id: "B07GITHUBAPP",
    text: "See kennylhilljr/pr-review-bots#5",
    expect: null,
  },
};
