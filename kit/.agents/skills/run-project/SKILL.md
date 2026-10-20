---
name: run-{{SLUG}}
description: How to build, launch and drive {{NAME}} in an isolated scratch setup, so a change can be watched working. Use before verify-change, and whenever you need to run the project or one of its modules by hand.
---

# Run {{NAME}}

Never touch the owner's real setup: no real config or data folders, Keychain, launchd or client configs. Every run below uses a scratch home and fakes.

## 1. Build

```sh
{{SETUP_CMD}}
```

## 2. Isolate

```sh
export SCRATCH="$(mktemp -d)"
```

Point every state, data, cache and log location at `$SCRATCH` (the specification's settings section names the overrides), and use a free loopback port, never the real one.

## 3. Drive what exists

Pick the highest level that exists on your branch.

| What exists | How to drive it |
|---|---|
| Only modules | A short script that imports the public API named in the specification and exercises the change with the project's fakes. Print the results you expect to see. |
| A server or app | Start it in the background with the scratch settings, call the endpoint or tool you changed, print the response, stop it. |
| A CLI | `--help`, then the subcommand you changed. |

The network stays blocked: use recorded fixtures, never real upstreams.

## 4. Clean up

Stop any process you started and `rm -rf "$SCRATCH"`.
