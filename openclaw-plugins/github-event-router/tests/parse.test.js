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

test("takes the first issue or pull request link in the post", () => {
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
