# Node: readback_and_next_steps (PRD v2 §6, Node 9)

The patient just heard a summary read back to them ("Main confirm karti hoon: ... Kya maine sahi
samjha?") and is now responding to it. Classify their reply. **`proposed_next` must be exactly one
of these three node names**:

- **They confirm it's correct** → `proposed_next`: **`close`**. `reply_text` isn't used (the
  caller speaks its own FIXED closing line).
- **They correct a detail** (something in the summary was wrong) → intent `correction`,
  `proposed_next`: **`complaint_detail`**, so the caller can update that specific complaint.
  `reply_text` isn't used here either.
- **A re-confirm is needed** (e.g. after a correction was already applied and you need to read the
  updated summary back once more) → `proposed_next`: **`readback_and_next_steps`**. This is the
  ONLY case where `reply_text` is used: produce a **≤ 20-word summary** of the complaint(s) raised
  this call — the caller wraps it in the same FIXED frame and fills the next-step sentence itself
  from account settings. Never invent a resolution timeline, SLA, or promise yourself.
