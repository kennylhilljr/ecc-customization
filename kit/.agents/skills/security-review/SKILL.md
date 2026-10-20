---
name: security-review
description: Security review for changes to secrets, redaction, network access, storage, auth, untrusted input or .orchestration. Use for high-risk units and whenever a change handles credentials, untrusted content or network access.
---

# Security review

Review the unit's diff with an attacker's view. For each item, either show it holds or report a finding (`severity | file:line | issue | fix`).

1. **Secrets**: values never reach argv, logs, exceptions, reprs, fixtures or the handoff; references are validated before use.
2. **Redaction**: every registered secret is masked in every output path, including structured logs and error envelopes.
3. **Network**: listeners bind to loopback unless the specification says otherwise; tests cannot reach the network.
4. **Untrusted content**: input is never interpolated into SQL, shell, paths or prompts without validation.
5. **Storage**: parameterized SQL only; file paths are normalized before containment checks.
6. **Auth**: tokens compared in constant time; unauthenticated callers refused.
7. **Supply chain**: no dependency the specification does not allow; CI actions pinned by SHA.

Blockers stop the merge. Report what you could not check and why.
