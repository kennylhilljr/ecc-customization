---
name: verify-change
description: Confirm a change actually works end to end, not only that tests and types pass. Use after the acceptance commands and {{FAST_GATE_CMD}} pass, before review or handoff.
---

# Verify a change

Tests passing is necessary, not sufficient. This skill checks the behavior itself.

1. **State the claim.** From your unit's specification sections and its acceptance test ids, write down in one or two sentences what must now be true.
2. **Run the gates.** Your unit's acceptance commands, then `{{FAST_GATE_CMD}}`. Stop here if either fails.
3. **Exercise it directly.** Follow the run-{{SLUG}} skill and drive the changed behavior the way a caller would, including at least one input that must be refused. Use fakes and fixtures; the network stays blocked.
4. **Check the clarifications.** If the specification has a clarification for your unit, exercise each case it names.
5. **Record the evidence.** In your handoff's `commands`, list what you ran and what you saw. If something did not behave as the claim says, fix it or report it in `unresolved_failures`; never report success you did not observe.
