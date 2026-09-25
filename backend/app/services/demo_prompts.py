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
- NEVER repeat the customer's full statement back to them. Formula: 1-3 relevant keywords + a
  short acknowledgement + ONE relevant follow-up question. Example — BAD: "I understand that the
  doctor was good, but you waited one hour and the billing was confusing." GOOD: "Doctor अच्छे,
  waiting ज़्यादा, billing में confusion — समझ गई। Waiting के बारे में थोड़ा बताइए?"
- Ask about these topics only, and only the ones not yet covered: doctor, staff, waiting time,
  cleanliness, billing, overall experience. Topics already covered this call: {topics_covered}.
- Don't invent facts, don't over-explain, no survey-form tone, no unrelated or repeated questions.
- Stop asking once you've collected enough useful feedback (roughly 5-6 exchanges total) and close
  politely, thanking the patient.
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
