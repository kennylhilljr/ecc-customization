---
name: simplify-change
description: Remove unnecessary complexity from the code you changed without changing behavior or tests. Use once the change works and its tests pass, before verify-change and review.
---

# Simplify a change

1. Read your own diff: `git diff $(git merge-base HEAD main)...HEAD` plus uncommitted changes.
2. Look for, and remove:
   - code no requirement asks for (speculative options, unused parameters, dead branches);
   - duplication a small helper would remove;
   - wrappers, layers or classes that add no behavior;
   - comments that restate the code; keep the ones that say why.
3. Keep every name the specification owns exactly as written, keep the public behavior, and change no test except to remove a duplicate.
4. Run your acceptance commands and `{{FAST_GATE_CMD}}` again; they must still pass.
5. Commit the simplification separately with a message starting "Simplify:".
