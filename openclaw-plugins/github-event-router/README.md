# github-event-router

An OpenClaw plugin that turns GitHub Slack app posts in `#github-feed` (Slack channel `C0CEMPH1L0N`) into small queue files, so issue-worker-bots and pr-review-bots can react within seconds instead of on their 5 minute poll.

It registers one `before_dispatch` hook. For a message in that channel whose sender is a bot:

1. If the text contains `@openclaw` (any case), the hook does nothing and the normal ops agent turn runs, as today.
2. Otherwise it parses repo, kind (issue or pull request), number and event from the post, writes one JSON file, and returns `{ handled: true }`, so no model turn runs. Issues go to `~/.local/state/github-events/iwb/`, pull requests to `~/.local/state/github-events/prbot/`.
3. If it cannot find an issue or pull request in the post (a branch push, a release, a subscribe acknowledgement), it still claims the message, writes nothing to the queues and appends a 600 character sample to `~/.local/state/github-events/unparsed.jsonl` (capped at 1 MB) so the real shapes can be checked later.

Messages in other channels and messages from people are not touched. If the queue write fails, the hook logs a warning and still claims the post; the hourly backstop scan picks the item up.

## Queue file

Each file is written to `<queueRoot>/.tmp/` and renamed into the queue directory, so a reader never sees a partial file. Names sort by arrival time:

```
20261103T141502123Z-1730643302_123456-kennylhilljr__issue-worker-bots-pull_request-17-opened-3fa9c1.json
```

```json
{"repo":"kennylhilljr/issue-worker-bots","kind":"pull_request","number":17,"event":"opened","received_at":"2026-11-03T14:15:02.123Z","slack_message_id":"1730643302.123456","slack_channel":"C0CEMPH1L0N","source":"github-event-router","version":1}
```

`event` is one of `opened`, `reopened`, `closed`, `merged`, `ready_for_review`, `review_requested`, `review`, `review_comment`, `comment`, `synchronize`, `labeled`, `assigned`, `edited` or `unknown`. It is read from the post's header line and link fragment, so treat it as a hint: the consumers (`iwb tick --from-queue`, `prbot watch --from-queue`) fetch the current issue or pull request from GitHub before acting.

## Parsing

OpenClaw's Slack plugin flattens a bot message before the hook sees it. When `message.text` is set, the hook gets that text plus each attachment's `text` (or `fallback`). When it is empty, the hook gets the attachments' `pretext`, `title`, `text`, `fallback` and fields. Attachment `title_link` and footer links never reach the hook. The parser therefore accepts, in this order:

- the first `https://github.com/OWNER/REPO/issues/N`, `/pull/N` or `/pulls/N` link, bare or in Slack's `<url|label>` form, with any tail such as `/files`, `#issuecomment-…`, `#pullrequestreview-…` or `?w=1`;
- the legacy fallback form `[OWNER/REPO] Pull request opened: #N Title`;
- `OWNER/REPO#N`, but only when the header says issue or pull request. A bare reference could be either, so it is skipped.

## Configuration

All keys are optional and go under `plugins.entries.github-event-router.config`:

| Key | Default | Meaning |
| --- | --- | --- |
| `channelId` | `C0CEMPH1L0N` | Slack channel to watch |
| `queueRoot` | `~/.local/state/github-events` | Parent of the `iwb/`, `prbot/` and `.tmp/` directories |
| `botSenderIds` | `[]` | Slack ids that count as the GitHub app. Empty means any id starting with `B` |

OpenClaw passes `message.user` as the sender, falling back to `message.bot_id`. If the GitHub app's posts carry a `U…` user id, the default rule will not see them as bot posts; put that id in `botSenderIds`.

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

`before_dispatch` is not a conversation hook, so `hooks.allowConversationAccess` is not needed. Then change the channel and create the queue directories:

```sh
mkdir -p ~/.local/state/github-events/iwb ~/.local/state/github-events/prbot ~/.local/state/github-events/.tmp
openclaw config set channels.slack.channels.C0CEMPH1L0N.requireMention false --strict-json
```

Check it by commenting on a test issue in one of the subscribed repos and watching for a file in `~/.local/state/github-events/iwb/` and a `github-event-router: queued …` line in the gateway log. Until the queue launchd jobs are installed, the files simply wait there.

## Rollback

```sh
openclaw config set channels.slack.channels.C0CEMPH1L0N.requireMention true --strict-json
openclaw plugins disable github-event-router
openclaw plugins uninstall github-event-router
```

Disabling alone stops the hook. Queue files left behind are harmless; delete `~/.local/state/github-events` if the queue jobs are also removed.

## Tests

```sh
npm test    # node --test tests/*.test.js, no network, temp dirs only
```

The samples in `tests/fixtures/github-slack-posts.js` follow the GitHub Slack app's attachment layout but were not captured from the live channel.

## Unverified

- The exact shape of the GitHub Slack app's posts in this workspace. If the app sets `message.text` to a header without a link and keeps the issue link only in `title_link`, OpenClaw drops the link and those posts end up in `unparsed.jsonl` (see the `issueOpenedTitleLinkOnly` sample). Check that file after a day of traffic.
- Whether the app's messages carry a `B…` bot id or a `U…` user id as OpenClaw's sender id.
- That `before_dispatch` fires for these posts once `requireMention` is false. This follows from reading the 2026.9.6 Slack and dispatch code, not from a live run.
