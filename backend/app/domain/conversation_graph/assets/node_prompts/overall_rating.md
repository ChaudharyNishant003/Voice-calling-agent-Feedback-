# Node: overall_rating (PRD v2 §6, Node 4)

The FIXED rating question has already been spoken: "...ek se paanch ke beech batayein... aap apni
visit ko kitne denge?"

Parse the patient's answer into `rating`:
- Accept numbers in any form: digits ("4"), spelled-out Hindi/English ("chaar", "four"), or
  Devanagari digits ("४") → `rating.value`, `rating.inferred = false`.
- Accept purely verbal answers and map them: bahut bura → 1, achha nahi → 2, theek-thaak → 3,
  achha → 4, bahut achha → 5 → `rating.value` set, `rating.inferred = true`.
- "Pata nahi" / doesn't know → `rating.value = null`. Don't press — move on.

`intents`: include `correction` if they're revising a rating they already gave earlier in the call.

`proposed_next` must be exactly one of these two node names:
- **`probe_topics`** if there are still uncovered priority topics worth a follow-up question for
  this visit type. There is NO fixed line here — `reply_text` is what actually gets spoken: a
  brief acknowledgement of the rating, then your first follow-up question, one sentence, one
  question.
- **`anything_else`** otherwise. There's a FIXED question for this step, so `reply_text` is only a
  fallback here.

(The caller also enforces its own budget limits regardless of what you propose.)
