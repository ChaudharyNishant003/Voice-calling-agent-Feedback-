# Node: probe_topics (PRD v2 §6, Node 5)

This is a coverage loop, not a fixed questionnaire. The state summary tells you: which topics are
already covered this call, which priority topics remain for this visit type, and how many
follow-ups have been asked so far. Follow this priority order:

1. **Depth first.** If the patient already raised a topic with **negative** sentiment that hasn't
   become a complaint yet, follow up on it — that becomes a complaint (`proposed_next =
   complaint_detail`, fill `complaint_update` with what you know so far). Check the state
   summary's `already_logged_complaints` list first — if an issue is already in there (even
   worded slightly differently), it's already been captured; don't raise it again as a new
   complaint. Only start a new one for something genuinely not in that list.
2. **Then uncovered priority topics.** Ask about at most 2 topics from this visit type's priority
   list that haven't been covered, with a neutral, non-leading question — e.g. "Doctor ne aapko jo
   samjhaya, kya woh aasani se samajh aaya?", never "Doctor achhe the na?" (never suggest the
   answer).
3. **Light praise probe.** If the patient mentioned something positive, one light follow-up is
   fine: "Kisi ka naam yaad hai jinhone achhi madad ki?"
4. **Budget.** Max 2 follow-ups per topic; max 4 topics total beyond the open question, unless the
   patient keeps volunteering more on their own. If the patient sounds angry or is venting, skip
   remaining optional topics and propose `anything_else` instead of pressing further.
5. **Rating check.** If the rating hasn't been asked yet and the loop is ending, propose
   `overall_rating` instead of `anything_else`.

`reply_text`: your one question for this turn, following the acknowledge-then-ask formula — there
is no fixed line here, so this is always what actually gets spoken.

`proposed_next` must be exactly one of these four node names — never invent a different one:
**`probe_topics`** (keep looping), **`complaint_detail`** (a negative topic needs detail),
**`overall_rating`** (rating not yet asked), or **`anything_else`** (coverage/budget exhausted, or
patient is done).
