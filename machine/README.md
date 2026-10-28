# Machine snapshot

Written by `bin/ecc-snapshot`, read by `bootstrap.sh` (step `machine`). Holds only this README until the first snapshot.

- `manifest.json`: what was captured, which secret-looking entries were removed (names only), what was skipped and why, and the plugins and marketplaces installed in each harness.
- `home/`: the captured files under their paths relative to the home folder, with the home folder written as `__HOME__`.

Never edit secrets into these files. The pre-commit hook refuses them once `core.hooksPath` is set to `.githooks`, which `bootstrap.sh` does.
