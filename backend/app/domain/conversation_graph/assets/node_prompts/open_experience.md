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

Decide `proposed_next` — **it must be exactly one of these two node names**, never anything else:
- If everything mentioned was **positive only** → **`overall_rating`**. There's a FIXED question
  for this step, so `reply_text` is only a fallback here — keep it short regardless.
- If **anything** was negative or mixed → **`probe_topics`** (the rating gets asked later, after
  the complaints are captured). There is NO fixed line for this step — `reply_text` is what
  actually gets spoken: a brief acknowledgement (1-3 keywords, never a full repetition of what
  they said) followed by your first follow-up question, one sentence, one question.

If the patient's answer is too short/ambiguous to carry real sentiment (e.g. just "theek tha"),
do not invent detail — record it as neutral or skip a topic entry, and move on.
