# github-event-router

An OpenClaw plugin that turns GitHub Slack app posts in `#github-feed` (Slack channel `C0CEMPH1L0N`) into small queue files, so issue-worker-bots and pr-review-bots can react within seconds instead of on their 5 minute poll.

It registers one `before_dispatch` hook. For a message in that channel:

1. If the text contains `@openclaw` (any case), the hook does nothing and the normal ops agent turn runs, as today.
2. If the sender is listed in `botSenderIds` (the GitHub app), it parses repo, kind (issue or pull request), number and event from the post, writes one JSON file, and returns `{ handled: true }`, so no model turn runs. Issues go to `~/.local/state/github-events/iwb/`, pull requests to `~/.local/state/github-events/prbot/`.
3. If a listed sender's post names no issue or pull request (a branch push, a release, a subscribe acknowledgement), it still claims the message, writes nothing to the queues and appends a 600 character sample to `~/.local/state/github-events/unparsed.jsonl` (capped at 1 MB) so the real shapes can be checked later.
4. If the sender is some other Slack bot (a `B…` id not in `botSenderIds`), it claims the message so it cannot start a paid agent turn, queues nothing, and logs `github-event-router: unknown bot sender <id>`. The line is logged at most once per sender every 10 minutes, for at most 64 distinct ids.
5. Messages from people are not claimed. If a sender that is neither listed nor a `B…` id posts something that parses as a GitHub notification, the hook logs `github-event-router: sender <id> posted a GitHub notification but is not in botSenderIds; not queued` (same rate limit) and leaves the message alone. This covers an app whose posts carry a `U…` id.

`botSenderIds` has no default. Until it is set, nothing is queued: GitHub app posts fall under rule 4. If the queue write fails, the hook logs a warning and still claims the post; the hourly backstop scan picks the item up.

## Queue file

Each file is written to `<queueRoot>/.tmp/` and renamed into the queue directory, so a reader never sees a partial file. `.tmp/` is a sibling of `iwb/` and `prbot/`, never inside them. If any step of the write fails, the temp file is removed. Names sort by arrival time:

```
20261103T141502123Z-1730643302_123456-kennylhilljr__issue-worker-bots-pull_request-17-opened-3fa9c1.json
```

```json
{"repo":"kennylhilljr/issue-worker-bots","kind":"pull_request","number":17,"event":"opened","received_at":"2026-11-03T14:15:02.123Z","slack_message_id":"1730643302.123456","slack_channel":"C0CEMPH1L0N","source":"github-event-router","version":1}
```

`event` is one of `opened`, `reopened`, `closed`, `merged`, `ready_for_review`, `review_requested`, `review`, `review_comment`, `comment`, `synchronize`, `labeled`, `assigned`, `edited` or `unknown`. It is read from the post's header line and link fragment, so treat it as a hint: the consumers (`iwb tick --from-queue`, `prbot watch --from-queue`) fetch the current issue or pull request from GitHub before acting.

The consumers keep two more directories next to each queue, both outside the directory that launchd watches:

| Directory | Written by | Contents |
| --- | --- | --- |
| `iwb-deferred/`, `prbot-deferred/` | the queue drains | Events that failed, timed out or are waiting out a retry delay, with an `attempts` count. The hourly backstop run moves them back into the queue. |
| `iwb-rejected/`, `prbot-rejected/` | the queue drains | Entries that can never succeed: malformed JSON, unknown repos, stray files such as `.DS_Store`, and events that reached 24 attempts. Nothing reads them; clear them by hand now and then. |

## Parsing

OpenClaw's Slack plugin flattens a bot message before the hook sees it. When `message.text` is set, the hook gets that text plus each attachment's `text` (or `fallback`). When it is empty, the hook gets the attachments' `pretext`, `title`, `text`, `fallback` and fields. Attachment `title_link` and footer links never reach the hook.

Only the notification itself names the target, so the parser looks in this order and stops at the first hit:

1. the structured fallback `[OWNER/REPO] Pull request opened: #N Title`, on any line;
2. a `https://github.com/OWNER/REPO/issues/N`, `/pull/N` or `/pulls/N` link in the header (the first non-empty line), bare or in Slack's `<url|label>` form, with any tail such as `/files`, `#issuecomment-…`, `#pullrequestreview-…` or `?w=1`;
3. a title line: a Slack link to an issue or pull request whose label starts with that number, such as `<https://github.com/o/r/pull/17|#17 Add queue>`;
4. `OWNER/REPO#N` in the header, but only when the header says issue or pull request. A bare reference could be either, so it is skipped.

Links anywhere else, such as `See https://github.com/acme/other/issues/2` in an issue body, are ignored. A post with no target in those places is left unparsed (rule 3 above).

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

Side effect: with `requireMention: false`, a message Kenny types in `#github-feed` without `@openclaw` also starts an ops turn. The hook does not claim human messages.

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
mkdir -p ~/.local/state/github-events/iwb ~/.local/state/github-events/prbot ~/.local/state/github-events/.tmp
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

Disabling alone stops the hook. Queue files left behind are harmless. If the queue jobs are also removed, delete `~/.local/state/github-events`, which holds the queues, the `-deferred` and `-rejected` directories, `.tmp` and `unparsed.jsonl`.

## Tests

```sh
npm test    # node --test tests/*.test.js, no network, temp dirs only
```

The samples in `tests/fixtures/github-slack-posts.js` follow the GitHub Slack app's attachment layout but were not captured from the live channel.

## Unverified

- The exact shape of the GitHub Slack app's posts in this workspace. If the app sets `message.text` to a header without a link and keeps the issue link only in `title_link`, OpenClaw drops the link and those posts end up in `unparsed.jsonl` (see the `issueOpenedTitleLinkOnly` sample). Check that file after a day of traffic.
- Whether the app's messages carry a `B…` bot id or a `U…` user id as OpenClaw's sender id. The install steps find out.
- That `before_dispatch` fires for these posts once `requireMention` is false. This follows from reading the 2026.9.6 Slack and dispatch code, not from a live run.
