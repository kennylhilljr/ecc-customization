import assert from "node:assert/strict";
import { test } from "node:test";

import { classifyEvent, parseGithubPost } from "../src/parse.js";
import { SAMPLES, flattenLikeOpenClaw } from "./fixtures/github-slack-posts.js";

for (const [name, sample] of Object.entries(SAMPLES)) {
  test(`parses sample ${name}`, () => {
    assert.deepEqual(parseGithubPost(flattenLikeOpenClaw(sample)), sample.expect);
  });
}

test("handles the URL forms the app and users produce", () => {
  const cases = [
    ["<https://github.com/o-1/r.x/issues/9>", { repo: "o-1/r.x", kind: "issue", number: 9 }],
    ["https://www.github.com/o/r/pull/12?w=1", { repo: "o/r", kind: "pull_request", number: 12 }],
    ["http://github.com/o/r/pulls/3", { repo: "o/r", kind: "pull_request", number: 3 }],
    ["<https://github.com/o/r/pull/4/commits/abc123|#4>", { repo: "o/r", kind: "pull_request", number: 4 }],
    ["(see https://github.com/o/r/issues/5)", { repo: "o/r", kind: "issue", number: 5 }],
    ["https://github.com/o/r/issues/6&amp;x=1", { repo: "o/r", kind: "issue", number: 6 }],
  ];
  for (const [text, want] of cases) {
    const got = parseGithubPost(text);
    assert.ok(got, text);
    assert.deepEqual({ repo: got.repo, kind: got.kind, number: got.number }, want, text);
  }
});

test("prefers the structured fallback over links in the body (Codex counterexample)", () => {
  const text = "Issue commented\nSee https://github.com/acme/other/issues/2\n[acme/main] Pull request commented: #17";
  assert.deepEqual(parseGithubPost(text), { repo: "acme/main", kind: "pull_request", number: 17, event: "comment" });
});

test("kind comes from the structured prefix, not title words (Codex round 3)", () => {
  assert.deepEqual(parseGithubPost("[acme/r] Issue opened: #12 Review commit handling"), {
    repo: "acme/r",
    kind: "issue",
    number: 12,
    event: "opened",
  });
  assert.deepEqual(parseGithubPost("Issue reopened: acme/r#12 Merged PR review and pushed commits"), {
    repo: "acme/r",
    kind: "issue",
    number: 12,
    event: "reopened",
  });
  assert.deepEqual(parseGithubPost("[acme/r] Pull request opened by kenny: #13 Fix issue tracker"), {
    repo: "acme/r",
    kind: "pull_request",
    number: 13,
    event: "opened",
  });
  // The event also ignores the title.
  assert.equal(parseGithubPost("[acme/r] Issue commented: #14 Closed then reopened").event, "comment");
});

test("a header link beats bracket text in the body (Codex round 3)", () => {
  const text = "*Comment on <https://github.com/acme/main/issues/1#issuecomment-5|#1 Bug>*\n[acme/other] issue #2";
  assert.deepEqual(parseGithubPost(text), { repo: "acme/main", kind: "issue", number: 1, event: "comment" });
});

test("bracket fallback must be a whole line in the documented format", () => {
  for (const text of [
    "Issue commented\nas noted in [acme/other] issue #2 earlier",
    "Issue commented\n[acme/other] issue #2",
    "Issue commented\n[acme/other] see #2",
    "Issue commented\n> [acme/other] Issue opened: #2 quoted",
  ]) {
    assert.equal(parseGithubPost(text), null, text);
  }
});

test("ignores links that are only in the body", () => {
  assert.equal(parseGithubPost("Issue opened by kenny\nSee https://github.com/acme/other/issues/2 for context"), null);
  assert.equal(parseGithubPost("Pull request opened by kenny\nFixes <https://github.com/acme/other/issues/2|acme/other#2>"), null);
  // A title link must carry its own number as the label.
  assert.equal(parseGithubPost("Comment by kenny\n<https://github.com/acme/other/issues/2|#3 Wrong>"), null);
});

test("header link wins over a title link further down", () => {
  const text = "*Comment on <https://github.com/o/r/pull/8#issuecomment-1|#8 Fix>*\n<https://github.com/o/r/issues/2|#2 Other>";
  assert.deepEqual(parseGithubPost(text), { repo: "o/r", kind: "pull_request", number: 8, event: "comment" });
});

test("takes the header link, not a later body link", () => {
  const got = parseGithubPost(
    "Pull request opened <https://github.com/o/r/pull/8|#8 Fix>\nFixes https://github.com/o/r/issues/2",
  );
  assert.deepEqual(got, { repo: "o/r", kind: "pull_request", number: 8, event: "opened" });
});

test("rejects what it cannot trust", () => {
  for (const text of [
    "",
    "   ",
    null,
    undefined,
    42,
    "https://github.com/o/r/issues/0",
    "https://github.com/o/r/issues/abc",
    "https://github.com/o/r/commit/abcdef",
    "https://github.com/o/r/tree/main",
    "https://github.com/o/r",
    "https://gitlab.com/o/r/issues/3",
    "https://github.com/o/r.git/issues/3",
    "o/r#3",
    "#3 something happened",
  ]) {
    assert.equal(parseGithubPost(text), null, String(text));
  }
});

test("classifier ignores words inside link labels", () => {
  assert.equal(classifyEvent(["*Issue opened by kenny* <https://github.com/o/r/issues/1|#1 Merged PR closed the bug>"]), "opened");
  assert.equal(classifyEvent(["something else entirely"]), "unknown");
});
