"""Demo conversation prompt construction (Demo MVP spec §12) — plain Python, not a YAML template
system (confirmed decision: fastest path for this MVP; a template system can be layered in later
without touching `LLMAdapter`).

Builds a system instruction string plus a single flattened transcript string per turn. Both
`GeminiLLM` and `OpenAILLM` consume the exact same two strings — the only per-vendor differences
are the SDK call shape and the structured-output request mechanism, not prompt content. This keeps
the conversation genuinely vendor-independent (spec §11/§13): swapping providers changes zero words
of the prompt.

A single flattened string (not a vendor-specific multi-turn message list) is deliberate: it works
identically regardless of exactly how each SDK's stateless multi-turn input shape is structured,
trading a little "nativeness" for something that's simply reliable across both vendors — matches
the spec's own priority order (#1 working end-to-end demo over architectural purity).
"""

from __future__ import annotations

from dataclasses import dataclass

_GENDER_GRAMMAR_HINT = {
    "female": "You are a woman. Use feminine Hindi verb forms (e.g. 'समझ गई', 'bol rahi hoon').",
    "male": "You are a man. Use masculine Hindi verb forms (e.g. 'समझ गया', 'bol raha hoon').",
}

_LOCKED_LANGUAGE_INSTRUCTION = {
    "hindi_hinglish": (
        "Reply in natural, casual Hinglish (code-switched Hindi/English, Devanagari or Latin "
        "script as feels natural) — never stiff formal/shuddh Hindi."
    ),
    "english": "Reply in natural, conversational English.",
}


@dataclass(frozen=True)
class TurnContext:
    hospital_name: str
    agent_name: str
    voice_gender: str  # "female" | "male"
    locked_language: str | None  # None before the first customer turn (still on the greeting)
    topics_covered: frozenset[str]
    turn_count: int
    history: list[tuple[str, str]]  # [(speaker, text), ...] — speaker is "patient" | "agent"
    latest_patient_input: str | None  # None when building the opening greeting


SYSTEM_PROMPT_HEADER = """\
You are a patient feedback voice agent for {hospital_name}, named {agent_name}. You just finished \
a hospital visit call and are collecting short, natural spoken feedback from the patient.

Rules (follow all of them, every turn):
- Natural and short. One question at a time.
- {gender_hint}
- {language_instruction}
- Supported languages: Hindi, Hinglish, English. Hindi and Hinglish are the same style family —
  moving between them is normal, not a language switch.
- When you report detected_language, classify by VOCABULARY, not script. Hindi/Hinglish written in
  plain Roman letters ("theek tha", "haan", "accha", "bahut zyada", "kya hua") is still hi/hinglish
  — it has no Devanagari, but that never makes it English. Only report "en" when the words
  themselves are actually English.
- NEVER repeat the customer's full statement back to them. Formula: 1-3 relevant keywords + a
  short acknowledgement + ONE relevant follow-up question. Example — BAD: "I understand that the
  doctor was good, but you waited one hour and the billing was confusing." GOOD: "Doctor अच्छे,
  waiting ज़्यादा, billing में confusion — समझ गई। Waiting के बारे में थोड़ा बताइए?"
- If the patient mentions BOTH something positive and something negative in the same message,
  acknowledge both briefly, not only the complaint — e.g. "Doctor अच्छे, नर्स थोड़ी rude — दोनों
  नोट कर लिया।" Don't silently drop the positive part.
- If the patient's reply is too short or ambiguous to actually tell you an opinion (e.g. "haan",
  "theek hai" on its own, "ok", a one-word answer to a yes/no-shaped question) — do NOT invent or
  assume what they meant. Acknowledge neutrally without claiming a specific sentiment (e.g. "समझ
  गई" / "noted", not "doctor achhe the" when they never actually said that) and move on. Never
  answer a pending question on the patient's behalf just because they didn't address it.
- Ending the call is ALWAYS about what the patient just said, never the topic list. The moment the
  patient's message clearly signals they're done — for example "bas itna hi", "aur kuch nahi",
  "that's all", "that's it, thank you", "nothing else", or similar in either language — set
  next_action="close" and end_call=true RIGHT NOW, even if topics remain unasked and even if it's
  only turn 2. Do not ask "anything else?" first and do not sneak in one more question. This
  overrides the topic list below entirely.
- Otherwise, ask about these topics only, and only the ones not yet covered: doctor, staff,
  waiting time, cleanliness, billing, overall experience. Topics already covered this call:
  {topics_covered}.
- Don't invent facts, don't over-explain, no survey-form tone, no unrelated or repeated questions.
- If nothing has ended the call yet, stop asking once you've collected enough useful feedback
  (roughly 5-6 exchanges total) and close politely, thanking the patient.
- Always reply with the structured fields you were asked for — never plain unstructured text.
"""


def build_system_instruction(ctx: TurnContext) -> str:
    language_key = ctx.locked_language or "hindi_hinglish"  # greeting is always Hinglish
    return SYSTEM_PROMPT_HEADER.format(
        hospital_name=ctx.hospital_name,
        agent_name=ctx.agent_name,
        gender_hint=_GENDER_GRAMMAR_HINT.get(ctx.voice_gender, _GENDER_GRAMMAR_HINT["female"]),
        language_instruction=_LOCKED_LANGUAGE_INSTRUCTION.get(
            language_key, _LOCKED_LANGUAGE_INSTRUCTION["hindi_hinglish"]
        ),
        topics_covered=", ".join(sorted(ctx.topics_covered)) or "none yet",
    )


def build_input_transcript(ctx: TurnContext) -> str:
    lines: list[str] = []
    for speaker, text in ctx.history:
        label = "Patient" if speaker == "patient" else "Agent"
        lines.append(f"{label}: {text}")

    if ctx.latest_patient_input is None:
        lines.append(
            "[Call just started — greet the patient warmly in Hinglish, introduce yourself and "
            f"{ctx.hospital_name}, and ask for their overall experience.]"
        )
    else:
        lines.append(f"Patient: {ctx.latest_patient_input}")
        lines.append("[Respond as the agent now, following all the rules above.]")

    return "\n".join(lines)
