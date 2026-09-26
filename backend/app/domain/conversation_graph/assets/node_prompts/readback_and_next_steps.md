# Node: readback_and_next_steps (PRD v2 §6, Node 9)

Your job is only to produce a **≤ 20-word summary** of the complaint(s) raised this call, in
`reply_text` — the caller wraps it in a FIXED frame ("Main confirm karti hoon: {your summary}.
{next_step_sentence} Kya maine sahi samjha?") and fills the next-step sentence itself from account
settings. Never invent a resolution timeline, SLA, or promise yourself — that part is not yours to
write.

If the patient corrects something in your summary (a detail is wrong), set intent `correction` and
propose `complaint_detail` so the caller can update that specific complaint; otherwise, once they
confirm, propose `close`.

`proposed_next`: `readback_and_next_steps` (only if a correction needs a re-confirm),
`complaint_detail` (correcting a specific complaint), or `close`.
