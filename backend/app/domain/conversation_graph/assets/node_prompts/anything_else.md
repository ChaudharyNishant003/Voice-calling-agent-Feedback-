# Node: anything_else (PRD v2 §6, Node 8)

The FIXED question has already been spoken: "Kya aap kuch aur batana chahenge?"

Classify the reply. **`proposed_next` must be exactly one of the three node names in bold below**:
- **New content** (another complaint or topic) → extract it into `topics[]` /
  `complaint_update` the same way `open_experience`/`probe_topics` would, then `proposed_next`:
  **`complaint_detail`** if it's a real complaint worth a detail pass, or **`anything_else`** again
  if it's minor and fully covered already. When you propose `complaint_detail`, the caller speaks
  a FIXED acknowledgement opener first, then your `reply_text` right after it — write only the
  fact-specific part (e.g. "Do ghante wait karna sach mein mushkil hai.") plus your next question,
  not a second generic "sorry to hear that."
- **"Nahi" / nothing else** → `proposed_next`: **`readback_and_next_steps`**. For this case only,
  `reply_text` is actually used: write a ≤20-word summary of the complaint(s) raised this call (not
  a question) — the caller wraps it in a fixed frame. Never invent a resolution timeline or
  promise — that part isn't yours to write.

For the other two cases, `reply_text` is a fallback only — the caller's own FIXED line is what
actually gets spoken.
