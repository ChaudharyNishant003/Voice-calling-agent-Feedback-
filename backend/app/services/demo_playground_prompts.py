"""Narrow, single-purpose prompts for the Playground's four model-backed pipeline stages (see
`services/demo_playground_service.py`). Each builder returns the same `(system_instruction,
input_text)` two-string shape `demo_prompts.py` already uses, so no adapter interface changes are
needed — only `adapters/*/llm.py`'s `_PROMPT_SCHEMAS` dict gains new entries.

Deliberately not shared with `demo_prompts.py`: that module's `SYSTEM_PROMPT_HEADER` asks one model
to do all four jobs at once, which is exactly what the Playground exists to pull apart. Some
phrasing is intentionally similar (e.g. the acknowledgement formula) since the *rules* haven't
changed, only which stage is responsible for applying them.
"""

from __future__ import annotations

_GENDER_GRAMMAR_HINT = {
    "female": "You are a woman. Use feminine Hindi verb forms (e.g. 'समझ गई', 'bol rahi hoon').",
    "male": "You are a man. Use masculine Hindi verb forms (e.g. 'समझ गया', 'bol raha hoon').",
}

_LOCKED_LANGUAGE_INSTRUCTION = {
    "hindi_hinglish": (
        "Reply in natural, casual Hinglish (code-switched Hindi/English) — never stiff formal/"
        "shuddh Hindi."
    ),
    "english": "Reply in natural, conversational English.",
}


def build_language_detection_prompt(patient_text: str) -> tuple[str, str]:
    system = (
        "You are analyzing exactly one message from a patient during a hospital feedback call. "
        "Determine which language family it's in — Hindi, Hinglish (code-switched Hindi/English), "
        "or English — and whether the patient explicitly asked to switch the conversation's "
        "language (e.g. 'English mein baat karo', 'please speak in Hindi'). Hindi and Hinglish "
        "count as the same family for detection purposes; if the message is a genuine mix, "
        "classify it as 'hinglish'. Only set a requested language if they explicitly asked — a "
        "message merely being in that language is not a request. Respond only with the "
        "structured fields you were asked for."
    )
    input_text = f"Patient: {patient_text}"
    return system, input_text


def build_topic_extraction_prompt(patient_text: str) -> tuple[str, str]:
    system = (
        "You are analyzing exactly one message from a patient during a hospital feedback call. "
        "The hospital tracks feedback on these topics only: doctor, staff, waiting_time, "
        "cleanliness, billing, overall_experience. Identify which of these topics (if any) the "
        "message touches on — a message can mention zero, one, or several. Don't infer a topic "
        "that isn't actually referenced. Respond only with the structured fields you were asked "
        "for."
    )
    input_text = f"Patient: {patient_text}"
    return system, input_text


def build_end_judgment_prompt(
    *, patient_text: str, topics_covered: frozenset[str], turn_count: int
) -> tuple[str, str]:
    system = (
        "You are deciding whether a hospital patient-feedback call has collected enough useful "
        "feedback to close now, or whether it should continue with another question. Judge based "
        "on how much substantive feedback has actually been given, not just the turn count alone "
        "— but also don't drag the call out once the patient has covered the topics that matter "
        "to them. If you judge it's time to end, also give a one-line summary of the feedback "
        "collected; otherwise leave the summary null. Respond only with the structured fields you "
        "were asked for."
    )
    topics_str = ", ".join(sorted(topics_covered)) or "none yet"
    input_text = (
        f"Turn number: {turn_count}\n"
        f"Topics covered so far: {topics_str}\n"
        f"Patient's latest message: {patient_text}"
    )
    return system, input_text


def build_response_generation_prompt(
    *,
    hospital_name: str,
    agent_name: str,
    voice_gender: str,
    locked_language: str | None,
    topics_covered: frozenset[str],
    is_ending: bool,
    patient_text: str,
) -> tuple[str, str]:
    language_key = locked_language or "hindi_hinglish"
    closing_instruction = (
        "This is the closing turn — thank the patient warmly and end the call, don't ask another "
        "question."
        if is_ending
        else (
            "Ask about ONE topic not yet covered from: doctor, staff, waiting time, cleanliness, "
            "billing, overall experience."
        )
    )
    system = (
        f"You are a patient feedback voice agent for {hospital_name}, named {agent_name}, "
        "continuing an ongoing call. The language, topics-so-far, and whether this is the closing "
        "turn have already been decided by earlier steps — your only job is to generate the "
        "actual reply text.\n\n"
        f"- {_GENDER_GRAMMAR_HINT.get(voice_gender, _GENDER_GRAMMAR_HINT['female'])}\n"
        "- "
        + _LOCKED_LANGUAGE_INSTRUCTION.get(
            language_key, _LOCKED_LANGUAGE_INSTRUCTION["hindi_hinglish"]
        )
        + "\n"
        "- NEVER repeat the patient's full statement back to them. Formula: 1-3 relevant keywords "
        "+ a short acknowledgement + ONE relevant follow-up question. Example — BAD: \"I "
        "understand that the doctor was good, but you waited one hour and the billing was "
        "confusing.\" GOOD: \"Doctor अच्छे, waiting ज़्यादा — समझ गई। Waiting के बारे में थोड़ा "
        "बताइए?\"\n"
        f"- {closing_instruction}\n"
        "- Don't invent facts, don't over-explain, no survey-form tone, no unrelated or repeated "
        "questions. Respond only with the structured fields you were asked for."
    )
    topics_str = ", ".join(sorted(topics_covered)) or "none yet"
    input_text = f"Topics already covered: {topics_str}\nPatient just said: {patient_text}"
    return system, input_text
