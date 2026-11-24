# Check workflow

`.github/workflows/check.yml` runs `sh scripts/check.sh` for every pull request and every push to `main`. It runs on macOS with Python 3.9 and Python 3.13. With `fail-fast: false`, a failure on one Python version does not cancel the other job.

The workflow has read-only `contents` permission, does not keep the checkout credentials, uses no secrets and pins each action to a full commit SHA, with the release tag in a comment. To update an action, replace both the SHA and the tag comment.

Node 24 matches `NODE_VERSION` in `stack.conf`. Keep the workflow's `node-version` in sync when changing `NODE_VERSION`. macOS supplies `plutil` for the property list checks and `/bin/bash` for the Bash 3.2 syntax checks.

The `ruff-lint` check needs `ruff`, which macOS runners do not include, so the workflow installs a pinned version with pip before running the script.

`tests/test_ci_docs.py` checks the workflow file against these rules.
