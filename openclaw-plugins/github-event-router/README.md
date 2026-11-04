# github-event-router

An OpenClaw plugin that turns GitHub Slack app posts in `#github-feed` (Slack channel `C0CEMPH1L0N`) into small queue files, so issue-worker-bots and pr-review-bots can react within seconds instead of on their 5 minute poll.

It registers one `before_dispatch` hook. GitHub comment bodies are written by anyone who can comment, so no GitHub post ever reaches an agent turn directly. For a message in that channel:

1. A message from an owner (the Slack user ids in `channels.slack.allowFrom`, or `ownerSenderIds` in the plugin config) is left alone and the normal ops agent turn runs. Today that is Kenny, `U0ADXF02M4K`.
2. A post from the GitHub app (a sender listed in `botSenderIds`) is claimed with `{ handled: true }`, so no model turn runs, and becomes queue files. When the post's own text names an issue or pull request, it writes one event file: issues to `~/.local/state/github-events/iwb/`, pull requests to `~/.local/state/github-events/prbot/`.
3. When it cannot name a precise target (a branch push, a release, a post whose link OpenClaw dropped), it writes a sweep request instead, one file in each of `iwb/` and `prbot/`, which asks each consumer for a full pass, limited to one repo when the post's own text names exactly one. Each queue is written independently, and a failure for one is logged without stopping the other. It also appends the post's `content` and `body` (600 characters each) to `~/.local/state/github-events/unparsed.jsonl` (capped at 1 MB) so real fixtures can be added later. The router therefore never depends on parsing: every GitHub app post leads to either a targeted event or a sweep.
4. When a GitHub app post mentions `@openclaw` (any case, as a mention: `me@openclaw.com` and `@openclawbot` do not count; the cases are in `tests/fixtures/mention-cases.json`, shared with the drain's tests), it also writes a command request into `~/.local/state/github-events/ops/` with the repo and number when the post's own text names them (otherwise null, meaning every installed repo). If that write fails, the request is appended to `~/.local/state/github-events/ops-failed.jsonl` with an error log line, and the drain replays that file into `ops/`. The command drain, `bin/openclaw-gh-command-drain` in this repository, reads the comments through the GitHub API, keeps only comments by `kennylhilljr` that mention `@openclaw`, and wakes the ops agent with that verified text and its URL. See the repository README.
5. A post from any other Slack bot (a `B…` id not in `botSenderIds`) is claimed, queues nothing, and logs `github-event-router: unknown bot sender <id>`. The line is logged at most once per sender every 10 minutes, for at most 64 distinct ids.
6. A message from anyone else is claimed and dropped. If it is GitHub-shaped (a `github.com/OWNER/REPO` link or a line starting with `[OWNER/REPO]`), parsed or not, the hook logs `github-event-router: sender <id> posted a GitHub notification but is not in botSenderIds; not queued` (same rate limit). This covers an app whose posts carry a `U…` or `W…` id. In 2026.9.6 the `before_dispatch` event and context carry only the sender id, with no `bot_id`, subtype or app id, so the text is the only clue.

`botSenderIds` has no default. Until it is set, nothing is queued: GitHub app posts fall under rule 5 or 6. Owners default to `channels.slack.allowFrom`; if neither that nor `ownerSenderIds` names a user id, the plugin logs a warning at startup and every message in the channel is dropped. If the hook cannot judge a message in the channel, it drops it rather than let it through. If the plugin config is invalid, the plugin logs an error and still registers a hook that drops every message in the feed channel except an owner's and queues nothing, until the config is fixed. If a queue write fails, the hook logs a warning and still claims the post; the hourly backstop scan picks the item up.

## Queue file

Each file is written to `<queueRoot>/.tmp/` and renamed into the queue directory, so a reader never sees a partial file. `.tmp/` is a sibling of `iwb/` and `prbot/`, never inside them. If any step of the write fails, the temp file is removed. Names sort by arrival time:

```
20261103T141502123Z-1730643302_123456-kennylhilljr__issue-worker-bots-pull_request-17-opened-3fa9c1.json
```

```json
{"repo":"kennylhilljr/issue-worker-bots","kind":"pull_request","number":17,"event":"opened","received_at":"2026-11-03T14:15:02.123Z","slack_message_id":"1730643302.123456","slack_channel":"C0CEMPH1L0N","source":"github-event-router","version":1}
```

Each sweep request gets its own name, `sweep-<UTC time>-<6 hex>.json` (for example `sweep-20261103T150000000Z-3fa9c1.json`), and is published the same way. The router never reads or replaces a pending sweep, so two posts arriving together cannot overwrite or narrow each other, and a consumer deleting the sweeps it handled cannot remove one that arrived meanwhile. `"repo": null` means all repos:

```json
{"kind":"sweep","repo":"kennylhilljr/issue-worker-bots","received_at":"2026-11-03T15:00:00.000Z","slack_message_id":"1730643302.123456","slack_channel":"C0CEMPH1L0N","source":"github-event-router","version":1}
```

`iwb tick --from-queue` and `prbot watch --from-queue` recognize sweeps by content (`"kind": "sweep"`), not by name. Each run coalesces all the sweep requests it finds into one full pass, after the per-item events, scoped to the union of their repos (all repos if any says `null`), and deletes exactly the files it claimed once the pass succeeds.

`event` is one of `opened`, `reopened`, `closed`, `merged`, `ready_for_review`, `review_requested`, `review`, `review_comment`, `comment`, `synchronize`, `labeled`, `assigned`, `edited` or `unknown`. It is read from the post's header line and link fragment, so treat it as a hint: the consumers (`iwb tick --from-queue`, `prbot watch --from-queue`) fetch the current issue or pull request from GitHub before acting.

Each write also creates `<queueRoot>/.github-events-queue` if it is missing. The consumers drain a queue directory only when it is their default path or when its parent holds this marker, so a mistyped `--from-queue` path cannot move unrelated files. The marker sits in the root, not inside a queue directory, because launchd keeps a `QueueDirectories` job running while the watched directory has any entry.

The consumers keep two more directories next to each queue, both outside the directory that launchd watches:

| Directory | Written by | Contents |
| --- | --- | --- |
| `iwb-deferred/`, `prbot-deferred/` | the queue drains | Events that failed, timed out or are waiting out a retry delay, with an `attempts` count. The hourly backstop run moves them back into the queue. |
| `iwb-rejected/`, `prbot-rejected/` | the queue drains | Entries that can never succeed: malformed JSON, unknown repos, stray files such as `.DS_Store`, and events that reached 24 attempts. Nothing reads them; clear them by hand now and then. |

## Parsing

What the hook receives in OpenClaw 2026.9.6 (`@openclaw/slack`, `dist/.setup/pipeline.runtime-BlPOexmJ.mjs`):

- `event.body` is `message.text` (or the blocks text), then one line per attachment with that attachment's `text`, or its `fallback` when `text` is empty (lines 2953 to 2962 and 2993 to 3001). Attachment `pretext`, `title`, `title_link`, footer and fields never reach the hook.
- `event.content` is `message.text` with Slack user mentions removed (lines 4090 and 4468; `BodyForCommands` in `openclaw/dist/context-BigCXBTA.mjs:208`). When `message.text` is blank, OpenClaw uses the body instead (`openclaw/dist/message-hook-mappers-RPSrPEKP.mjs:49`).

So attachment text, which for comments and issues is user-written, is only ever in `body`. The router works from that:

- `content` differs from `body`: `message.text` was set and attachments added more. Only `content` is parsed. No target there means a sweep, scoped to the one repo `content` links to, if any.
- `content` equals `body`: the text is either `message.text` alone or attachment text alone, and the hook cannot tell which. A target found there is queued, and a sweep for all repos is always added, so a target taken from user text can only cause an extra check of that item, never a missed event.

Within the text it parses, the parser looks in this order and stops at the first hit:

1. a `https://github.com/OWNER/REPO/issues/N`, `/pull/N` or `/pulls/N` link in the header (the first non-empty line), bare or in Slack's `<url|label>` form, with any tail such as `/files`, `#issuecomment-…`, `#pullrequestreview-…` or `?w=1`;
2. a title line: a Slack link to an issue or pull request whose label starts with that number, such as `<https://github.com/o/r/pull/17|#17 Add queue>`;
3. a line that is exactly the structured fallback `[OWNER/REPO] Issue <action>: #N Title` or `[OWNER/REPO] Pull request <action>: #N Title`;
4. `Issue … OWNER/REPO#N` or `Pull request … OWNER/REPO#N` in the header. A bare reference could be either, so it is skipped.

The kind comes from the link path or from the `Issue` / `Pull request` words in front of the number, never from the title: `[acme/r] Issue opened: #12 Review commit handling` is an issue. The event is also read only from text in front of the number.

## Configuration

Keys go under `plugins.entries.github-event-router.config` and match the schema in `openclaw.plugin.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `botSenderIds` | `[]` | Slack sender ids of the GitHub app (`B…`, `U…` or `W…`, up to 16). Required for anything to be queued |
| `channelId` | `C0CEMPH1L0N` | Slack channel to watch |
| `queueRoot` | `~/.local/state/github-events` | Parent of the `iwb/`, `prbot/` and `.tmp/` directories |

OpenClaw passes `message.user` as the sender, falling back to `message.bot_id`, so the GitHub app shows up either as its bot id (`B…`) or as its bot user id (`U…`). The log lines in rules 4 and 5 tell you which.

## Slack channel settings this needs

The hook only sees messages that the Slack plugin admits. With the current `#github-feed` settings (`requireMention: true`, `allowBots: true`), a GitHub post without `@openclaw` is dropped as `missing-mention` before dispatch, so the router never sees it. For every GitHub post to reach the hook, set `requireMention: false` on that channel and keep `allowBots: true`. Bot posts also pass only while the owner listed in `channels.slack.allowFrom` (`U0ADXF02M4K`) is a member of the channel, or when the bot's id is listed in the channel's `users`.

Side effect: with `requireMention: false`, any message Kenny types in `#github-feed`, with or without `@openclaw`, starts an ops turn. Messages from everyone else in the channel are dropped by the hook.

The ops agent's channel `systemPrompt` currently tells it to check GitHub comment authors itself when a GitHub app post wakes it. With this plugin that no longer happens: verified commands arrive through `openclaw agent` from the command drain instead. The prompt can stay as a second check.

## Install

From the merged checkout (not a worktree):

```sh
cd ~/Documents/GitHub/ecc-customization/openclaw-plugins/github-event-router
npm test
openclaw plugins install --link "$PWD" --force
openclaw plugins enable github-event-router
openclaw plugins inspect github-event-router --runtime --json
```

`before_dispatch` is not a conversation hook, so `hooks.allowConversationAccess` is not needed. Then create the queue directories and change the channel:

```sh
mkdir -p ~/.local/state/github-events/iwb ~/.local/state/github-events/iwb-code ~/.local/state/github-events/prbot ~/.local/state/github-events/.tmp
touch ~/.local/state/github-events/.github-events-queue
openclaw config set channels.slack.channels.C0CEMPH1L0N.requireMention false --strict-json
```

Learn the GitHub app's sender id. Comment on a test issue in one of the subscribed repos, then look for the router's line in the gateway log:

```sh
grep -E 'github-event-router: (unknown bot sender|sender )' ~/.openclaw/logs/gateway.log | tail -5
```

Check that the line appeared within seconds of the comment, so it is the GitHub app and not another bot, then allow that id (replace the example id with the one from the log):

```sh
openclaw config set plugins.entries.github-event-router.config.botSenderIds '["B0EXAMPLE1"]' --strict-json
openclaw plugins inspect github-event-router --runtime --json
```

Comment again and look for a file in `~/.local/state/github-events/iwb/` and a `github-event-router: queued …` line in the log. Until the queue launchd jobs are installed, the files simply wait there.

## Rollback

```sh
openclaw config set channels.slack.channels.C0CEMPH1L0N.requireMention true --strict-json
openclaw plugins disable github-event-router
openclaw plugins uninstall github-event-router
```

Disabling alone stops the hook. Queue files left behind are harmless. If the queue jobs are also removed, delete `~/.local/state/github-events`, which holds the queues, the `-deferred` and `-rejected` directories, `.tmp`, `.github-events-queue` and `unparsed.jsonl`.

## Tests

```sh
npm test    # node --test tests/*.test.js, no network, temp dirs only
```

The samples in `tests/fixtures/github-slack-posts.js` follow the GitHub Slack app's attachment layout but were not captured from the live channel. `hookFields()` there turns a Slack message into the `content` and `body` pair described under Parsing.

## Unverified

- The exact shape of the GitHub Slack app's posts in this workspace. If the app keeps the issue link only in `title_link`, the router cannot see it and those posts become sweeps (see the `issueOpenedTitleLinkOnly` sample). That is correct but slower to process than a targeted event. Check `unparsed.jsonl` after a day of traffic and add real samples to the fixtures.
- Whether the app's messages carry a `B…` bot id or a `U…` user id as OpenClaw's sender id. The install steps find out.
- That `before_dispatch` fires for these posts once `requireMention` is false. This follows from reading the 2026.9.6 Slack and dispatch code, not from a live run.
