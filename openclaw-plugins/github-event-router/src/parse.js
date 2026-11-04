// Parse a GitHub Slack app post (as OpenClaw hands it to before_dispatch)
// into { repo, kind, number, event }, or null when it names no issue or pull
// request we can trust.
//
// OpenClaw flattens the Slack message before the hook sees it: message.text
// (or the blocks text) plus attachment pretext, title, text, fallback and
// fields. Attachment title_link and footer links are not included, so a post
// may carry a github.com URL, only an "owner/repo#N" reference, or only the
// legacy "[owner/repo] Issue opened: #N Title" fallback.
//
// Kind always comes from the URL path or from the words in front of the
// number, never from the title after it: "Issue opened: #12 Review commit
// handling" is an issue.

const OWNER = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})";
const REPO = "[A-Za-z0-9._-]{1,100}";

// https://github.com/OWNER/REPO/issues/N, /pull/N, /pulls/N, with an optional
// tail such as /files, #issuecomment-123 or ?w=1. Slack wraps links as
// <url|label> or <url>, so the tail stops at whitespace, "|" and ">".
const URL_RE = new RegExp(
  `https?://(?:www\\.)?github\\.com/(${OWNER})/(${REPO})/(issues|pulls?)/(\\d{1,9})([/#?][^\\s|>)\\]]*)?`,
  "gi",
);

// owner/repo#N in a line.
const SHORT_REF_RE = new RegExp(`(?<![\\w/.-])(${OWNER})/(${REPO})#(\\d{1,9})\\b`, "g");

// The structured fallback, as a whole line:
//   [owner/repo] Issue opened: #12 Title
//   [owner/repo] Pull request opened by someone: #12 Title
// Group 3 is the kind word, group 4 the action text, group 5 the number.
const BRACKET_LINE_RE = new RegExp(
  `^[*_\\s]*\\[(${OWNER})/(${REPO})\\]\\s+(issue|pull request)\\b([^#\\n]*?):?\\s*#(\\d{1,9})(?:\\s.*)?$`,
  "i",
);

// Ordered: the first match wins. The classifier only reads text in front of
// the first "#N", with Slack links removed, so titles do not steer it. The
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

function stripLinks(line) {
  // <url|label> and <url> go entirely, so titles inside labels do not count;
  // bare URLs are removed for the same reason.
  return line.replace(/<[^<>]*>/g, " ").replace(/https?:\/\/\S+/g, " ");
}

function beforeNumber(line) {
  const cut = line.search(/#\d/);
  return cut === -1 ? line : line.slice(0, cut);
}

export function classifyEvent(lines) {
  for (const raw of lines) {
    const line = beforeNumber(stripLinks(raw)).toLowerCase();
    for (const [name, re] of EVENT_RULES) {
      if (re.test(line)) return name;
    }
  }
  return "unknown";
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

function positive(n) {
  const v = Number(n);
  return Number.isSafeInteger(v) && v > 0 ? v : null;
}

// A title line is a Slack link to an issue or pull request whose label starts
// with that number, e.g. "<https://github.com/o/r/pull/17|#17 Add queue>",
// optionally wrapped in * or _. Links inside body text do not qualify.
function isTitleLine(line, match) {
  const trimmed = line.trim().replace(/^[*_]+/, "");
  const label = /^<[^|>]+\|#(\d+)\b/.exec(trimmed);
  return Boolean(label) && label[1] === match[4];
}

function fromUrl(match, header, line) {
  const number = positive(match[4]);
  if (!number) return null;
  const kind = match[3].toLowerCase() === "issues" ? "issue" : "pull_request";
  const event = eventFromFragment(match[5]) ?? classifyEvent([header, line]);
  return { repo: `${match[1]}/${match[2]}`, kind, number, event };
}

function fromBracketLine(line, header) {
  const m = BRACKET_LINE_RE.exec(line);
  // The documented format always names an action ("opened", "commented").
  if (!m || !validRepoName(m[2]) || !/[A-Za-z]/.test(m[4])) return null;
  const number = positive(m[5]);
  if (!number) return null;
  const kind = m[3].toLowerCase() === "issue" ? "issue" : "pull_request";
  return { repo: `${m[1]}/${m[2]}`, kind, number, event: classifyEvent([m[4], header]) };
}

function fromHeaderShortRef(header) {
  const m = earliest(header, SHORT_REF_RE);
  if (!m) return null;
  const number = positive(m[3]);
  if (!number) return null;
  // Only the words in front of the reference decide the kind. A bare
  // owner/repo#N could be either; leave it to the backstop.
  const prefix = stripLinks(header.slice(0, m.index));
  let kind;
  if (/\bpull[ -]?request\b|\bPR\b/i.test(prefix)) kind = "pull_request";
  else if (/\bissue\b/i.test(prefix)) kind = "issue";
  else return null;
  return { repo: `${m[1]}/${m[2]}`, kind, number, event: classifyEvent([header.slice(0, m.index)]) };
}

/**
 * Parse trusted notification text: the message's own text (header and title
 * lines), never attachment body text. The caller decides what is trusted;
 * see analyzePost in router.js. In order:
 *   1. an issue or pull request link in the header (first non-empty line);
 *   2. a title link whose label starts with the same number;
 *   3. a line that is exactly the structured fallback
 *      "[owner/repo] Issue|Pull request <action>: #N Title";
 *   4. "Issue|Pull request ... owner/repo#N" in the header.
 * A post with none of these stays unparsed.
 *
 * @param {string} text trusted header/title text
 * @returns {{repo: string, kind: "issue"|"pull_request", number: number, event: string} | null}
 */
export function parseGithubPost(text) {
  if (typeof text !== "string" || !text.trim()) return null;
  const body = unescapeSlack(text);
  const header = firstLine(body);
  const lines = body.split("\n");

  const headerUrl = earliest(header, URL_RE);
  if (headerUrl) return fromUrl(headerUrl, header, header);

  for (const line of lines) {
    const m = earliest(line, URL_RE);
    if (m && isTitleLine(line, m)) return fromUrl(m, header, line);
  }

  for (const line of lines) {
    const got = fromBracketLine(line, header);
    if (got) return got;
  }

  return fromHeaderShortRef(header);
}

const ANY_REPO_URL_RE = new RegExp(`https?://(?:www\\.)?github\\.com/(${OWNER})/(${REPO})(?=[/|>\\s]|$)`, "gi");
const BRACKET_PREFIX_RE = new RegExp(`^[*_\\s]*\\[(${OWNER})/(${REPO})\\]`, "gm");
const NOT_REPOS = new Set(["orgs", "settings", "notifications", "marketplace", "apps", "sponsors", "topics", "users"]);

/**
 * The single repository that trusted text points at (any github.com/OWNER/REPO
 * link, or a "[owner/repo]" line prefix), or null when there is none or more
 * than one. Used to scope a sweep.
 */
export function extractRepo(text) {
  if (typeof text !== "string" || !text.trim()) return null;
  const body = unescapeSlack(text);
  const seen = new Map(); // lower case -> first spelling seen
  for (const re of [ANY_REPO_URL_RE, BRACKET_PREFIX_RE]) {
    re.lastIndex = 0;
    for (let m = re.exec(body); m; m = re.exec(body)) {
      if (!validRepoName(m[2]) || NOT_REPOS.has(m[1].toLowerCase())) continue;
      const repo = `${m[1]}/${m[2]}`;
      if (!seen.has(repo.toLowerCase())) seen.set(repo.toLowerCase(), repo);
    }
  }
  return seen.size === 1 ? [...seen.values()][0] : null;
}
