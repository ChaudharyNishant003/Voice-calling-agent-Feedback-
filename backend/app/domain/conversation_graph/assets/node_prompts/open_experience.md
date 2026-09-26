# Node: open_experience (PRD v2 §6, Node 3)

You just asked "Aapka overall experience kaisa raha?" (or it was asked immediately before this
turn). The patient is now answering freely — let them talk.

Extract **every** topic they mention into `topics[]`, each with:
- `category` — pick the closest match from: doctor, nursing, wait_time, reception, cleanliness,
  billing, pharmacy, diagnostics, communication, staff_behaviour, facilities, discharge,
  appointment, other.
- `sentiment` — positive, neutral, or negative, based on what they actually said.
- `verbatim` — a short (≤ 20 words) quote capturing what they said, in their own words.
- `staff_name` — only if they actually named someone, else null.

`reply_text`: a brief acknowledgement (1-3 keywords, never a full repetition of what they said) —
this may be discarded by the caller in favour of a FIXED question depending on what happens next,
so keep it short regardless.

Decide `proposed_next`:
- If everything mentioned was **positive only** → `overall_rating`.
- If **anything** was negative or mixed → `probe_topics` (the rating gets asked later, after the
  complaints are captured).

If the patient's answer is too short/ambiguous to carry real sentiment (e.g. just "theek tha"),
do not invent detail — record it as neutral or skip a topic entry, and move on.
