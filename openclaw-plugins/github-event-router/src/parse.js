// Parse a GitHub Slack app post (as OpenClaw hands it to before_dispatch)
// into { repo, kind, number, event }, or null when it names no issue or pull
// request we can trust.
//
// OpenClaw flattens the Slack message before the hook sees it: message.text
// (or the blocks text) plus attachment pretext, title, text, fallback and
// fields. Attachment title_link and footer links are not included, so a post
// may carry a github.com URL, only an "owner/repo#N" reference, or only the
// legacy "[owner/repo] ... #N" fallback. All three are handled.

const OWNER = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})";
const REPO = "[A-Za-z0-9._-]{1,100}";

// https://github.com/OWNER/REPO/issues/N, /pull/N, /pulls/N, with an optional
// tail such as /files, #issuecomment-123 or ?w=1. Slack wraps links as
// <url|label> or <url>, so the tail stops at whitespace, "|" and ">".
const URL_RE = new RegExp(
  `https?://(?:www\\.)?github\\.com/(${OWNER})/(${REPO})/(issues|pulls?)/(\\d{1,9})([/#?][^\\s|>)\\]]*)?`,
  "gi",
);

// owner/repo#N anywhere in the text.
const SHORT_REF_RE = new RegExp(`(?<![\\w/.-])(${OWNER})/(${REPO})#(\\d{1,9})\\b`, "g");

// "[owner/repo] Pull request opened: #12 Title" on one line.
const BRACKET_REF_RE = new RegExp(`\\[(${OWNER})/(${REPO})\\][^\\n#]*#(\\d{1,9})\\b`, "g");

const PR_WORDS = /\b[Pp]ull[ -]?[Rr]equests?\b|\bPRs?\b|\b[Mm]erged\b|\b[Rr]eview(?:ed|s)?\b|\b[Aa]pproved\b|\b[Cc]ommits?\b|\b[Pp]ushed\b/;
const ISSUE_WORDS = /\bissues?\b/i;

// Ordered: the first match wins. Titles can contain these words too, so the
// classifier only reads header lines with Slack link labels removed, and the
// result is advisory: consumers fetch the current state from GitHub.
const EVENT_RULES = [
  ["merged", /\bmerged\b/],
  ["reopened", /\bre-?opened\b/],
  ["closed", /\bclosed\b/],
  ["ready_for_review", /\bready for review\b/],
  ["review_requested", /\breview requested\b|\brequested (?:a )?review\b/],
  ["review", /\bapproved\b|\brequested changes\b|\bchanges requested\b|\breviewed\b|\breview submitted\b|\bleft a review\b|\bsubmitted a review\b/],
  ["comment", /\bcomment(?:ed|s)?\b/],
  ["synchronize", /\bpushed\b|\bnew commits?\b|\b\d+ commits?\b|\bsynchroni[sz]ed?\b|\bforce-pushed\b/],
  ["opened", /\bopened\b|\bcreated\b|\bnew issue\b|\bnew pull request\b/],
  ["labeled", /\blabel(?:l)?ed\b/],
  ["assigned", /\bassigned\b/],
  ["edited", /\bedited\b/],
];

function unescapeSlack(text) {
  return text.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");
}

function validRepoName(name) {
  return name !== "." && name !== ".." && !name.endsWith(".git");
}

function eventFromFragment(tail) {
  if (!tail) return null;
  if (/#issuecomment-\d+/i.test(tail)) return "comment";
  if (/#pullrequestreview-\d+/i.test(tail)) return "review";
  if (/#discussion_r\d+/i.test(tail)) return "review_comment";
  return null;
}

function stripLinkLabels(line) {
  // <url|label> -> "" and <url> -> "" so titles inside labels do not steer the
  // classifier; bare URLs are removed for the same reason.
  return line.replace(/<[^<>]*>/g, " ").replace(/https?:\/\/\S+/g, " ");
}

export function classifyEvent(headerLines) {
  for (const raw of headerLines) {
    const line = stripLinkLabels(raw).toLowerCase();
    for (const [name, re] of EVENT_RULES) {
      if (re.test(line)) return name;
    }
  }
  return "unknown";
}

function lineAt(text, index) {
  const start = text.lastIndexOf("\n", index) + 1;
  const end = text.indexOf("\n", index);
  return text.slice(start, end === -1 ? text.length : end);
}

function firstLine(text) {
  for (const line of text.split("\n")) {
    if (line.trim()) return line;
  }
  return "";
}

function earliest(text, re) {
  re.lastIndex = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (validRepoName(m[2])) return m;
  }
  return null;
}

// A title line is a Slack link to an issue or pull request whose label starts
// with that number, e.g. "<https://github.com/o/r/pull/17|#17 Add queue>",
// optionally wrapped in * or _. Links inside body text do not qualify.
function isTitleLine(line, match) {
  const trimmed = line.trim().replace(/^[*_]+/, "");
  if (!trimmed.startsWith("<")) return false;
  const label = /^<[^|>]+\|#(\d+)\b/.exec(trimmed);
  return Boolean(label) && label[1] === match[4];
}

function kindFromWords(lines) {
  // Drop links and every owner/repo token so a repo named "pr-review-bots"
  // does not read as "PR" or "review".
  for (const line of lines) {
    const words = stripLinkLabels(line).replace(new RegExp(`${OWNER}/${REPO}`, "g"), " ");
    if (PR_WORDS.test(words)) return "pull_request";
    if (ISSUE_WORDS.test(words)) return "issue";
  }
  return null;
}

function fromUrl(match, header, line) {
  const number = Number(match[4]);
  if (!Number.isSafeInteger(number) || number <= 0) return null;
  const kind = match[3].toLowerCase() === "issues" ? "issue" : "pull_request";
  const event = eventFromFragment(match[5]) ?? classifyEvent([header, line]);
  return { repo: `${match[1]}/${match[2]}`, kind, number, event };
}

function fromRef(match, header, line) {
  const number = Number(match[3]);
  if (!Number.isSafeInteger(number) || number <= 0) return null;
  // The reference's own line decides first, then the header. A bare
  // owner/repo#N could be either kind; leave it to the backstop.
  const kind = kindFromWords([line, header]);
  if (!kind) return null;
  return { repo: `${match[1]}/${match[2]}`, kind, number, event: classifyEvent([header, line]) };
}

/**
 * Only the notification itself names the target: the structured
 * "[owner/repo] ... #N" fallback, the header (first non-empty line), or a
 * title link. Links further down are usually the issue or comment body
 * ("See https://github.com/acme/other/issues/2") and are ignored.
 *
 * @param {string} text combined event.content and event.body
 * @returns {{repo: string, kind: "issue"|"pull_request", number: number, event: string} | null}
 */
export function parseGithubPost(text) {
  if (typeof text !== "string" || !text.trim()) return null;
  const body = unescapeSlack(text);
  const header = firstLine(body);

  // 1. Structured fallback, wherever OpenClaw placed it.
  const bracket = earliest(body, BRACKET_REF_RE);
  if (bracket) return fromRef(bracket, header, lineAt(body, bracket.index));

  // 2. A link in the header line.
  const headerUrl = earliest(header, URL_RE);
  if (headerUrl) return fromUrl(headerUrl, header, header);

  // 3. A title link on its own line.
  for (const line of body.split("\n")) {
    const m = earliest(line, URL_RE);
    if (m && isTitleLine(line, m)) return fromUrl(m, header, line);
  }

  // 4. owner/repo#N in the header.
  const short = earliest(header, SHORT_REF_RE);
  if (short) return fromRef(short, header, header);

  return null;
}
