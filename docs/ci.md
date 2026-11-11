# Install the check workflow

Kenny, save the YAML below as `.github/workflows/check.yml` at the repository root, then commit that file. This document supplies the workflow for you to install.

```yaml
name: Repository checks

on:
  pull_request:
  push:
    branches:
      - main

permissions:
  contents: read

jobs:
  check:
    runs-on: macos-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.9', '3.13']
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
      - run: sh scripts/check.sh
```

Once installed, the workflow runs for pull requests and pushes to `main`. Each Python version runs the full check script. With `fail-fast: false`, a failure in one matrix job does not cancel the other.

Node 24 matches `NODE_VERSION` in `stack.conf`. macOS supplies `plutil` for the property list checks and `/bin/bash` for the Bash 3.2 syntax checks. Keep the documented Node version in sync when changing `NODE_VERSION`.
