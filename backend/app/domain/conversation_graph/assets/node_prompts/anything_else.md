# Node: anything_else (PRD v2 §6, Node 8)

The FIXED question has already been spoken: "Kya aap kuch aur batana chahenge?"

Classify the reply:
- **New content** (another complaint or topic) → extract it into `topics[]` /
  `complaint_update` the same way `open_experience`/`probe_topics` would, and propose
  `complaint_detail` if it's a real complaint worth a detail pass, or `anything_else` again if it's
  minor and fully covered already.
- **"Nahi" / nothing else** → propose `readback_and_next_steps`.

`reply_text` is a fallback only — the next turn's actual line comes from wherever the caller
routes to (a FIXED readback frame, or another loop through this same question).
