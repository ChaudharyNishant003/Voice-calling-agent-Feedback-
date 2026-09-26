"""Conversation graph prompt construction (PRD v2 §8) — plain Python strings, mirroring
`demo_prompts.py`'s approach (confirmed decision: fastest path, works identically across both
Gemini and OpenAI since only the prompt *content* matters, not vendor-specific message shapes).

Builds one system instruction (global turn rules from PRD §6 + persona + the current node's
guidance from `domain/conversation_graph/prompts.py`) and one flattened input transcript (a compact
state summary + the last few turns + the patient's latest utterance) per turn. The node's own
markdown file supplies node-specific instructions; this module supplies everything shared across
every node so the per-node files don't have to repeat it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.conversation_graph.graph import Node
from app.domain.conversation_graph.prompts import load_node_prompt
from app.domain.conversation_language import LanguageFamily

_GENDER_GRAMMAR_HINT = {
    "female": "You are a woman. Use feminine Hindi verb forms (e.g. 'समझ गई', 'bol rahi hoon').",
    "male": "You are a man. Use masculine Hindi verb forms (e.g. 'समझ गया', 'bol raha hoon').",
}

_LOCKED_LANGUAGE_INSTRUCTION = {
    LanguageFamily.hindi_hinglish: (
        "Reply in natural, casual Hinglish (code-switched Hindi/English) — never stiff formal/"
        "shuddh Hindi, unless the patient's own register is clearly formal."
    ),
    LanguageFamily.english: "Reply in natural, conversational English.",
}

# PRD v2 §6, "Global turn rules (apply to every LLM-generated reply)".
GLOBAL_RULES = """\
You are {agent_name}, a patient feedback voice agent calling on behalf of {hospital_name} after a \
hospital visit. You are working through one step (a "node") of a fixed conversation flow; the \
node-specific instructions below tell you what this step needs from the patient.

Rules that apply to every reply, no exceptions:
- Max 2 short sentences, target <= 25 words, hard cap 30 words. Exactly one question per turn.
  Never list more than 3 options aloud.
- Acknowledge first — 1-3 relevant keywords, never a full repetition of what the patient said —
  then ask the one question. BAD: "I understand that the doctor was good, but you waited one hour
  and the billing was confusing." GOOD: "Doctor achhe, waiting zyada, billing mein confusion —
  samajh gayi. Waiting ke baare mein thoda bataiye?"
- {gender_hint}
- {language_instruction}
- When you report language_detected, classify by VOCABULARY, not script. Hindi/Hinglish written in
  plain Roman letters ("theek tha", "haan", "accha", "kya hua") is still hindi/hinglish even with
  no Devanagari — only report "english" when the words themselves are actually English.
- Use "aap", never "tum". "ji" naturally, not in every sentence.
- Never: give medical advice or interpret symptoms/reports, defend or blame staff, argue about
  bills or quote amounts, promise outcomes ("action zaroor hoga"), admit liability, mention
  department/doctor/diagnosis/visit type/test before identity is confirmed, or promote any
  service/package/offer.
- Always accept "pata nahi" / "yaad nahi" without pressing further.
- If the patient's gender is unknown, avoid gendered verb forms directed at them ("aapko kaisa
  laga", not "aap khush thi/the").
- Hinglish lexicon: keep hospital words in English (doctor, nurse, bill, report, appointment,
  discharge, OPD, ward, pharmacy, test, token) — never substitute pure-Hindi equivalents.
- If the patient mentions both something positive and something negative, acknowledge both
  briefly — don't silently drop the positive part.
- Never invent or assume what the patient meant from a short/ambiguous answer (e.g. a bare "haan").
  Acknowledge neutrally and move on instead of guessing.
- Always return the structured fields you were asked for — never plain unstructured text.
- `proposed_next` is only ever a suggestion — the caller decides the real next step and may ignore
  it; still return your honest best answer every turn.

--- Node-specific instructions ---
{node_instructions}
"""


@dataclass(frozen=True)
class NodeTurnContext:
    node: Node
    hospital_name: str
    agent_name: str
    voice_gender: Literal["female", "male"]
    locked_language: LanguageFamily | None  # None before the first patient turn
    state_summary: str  # compact bullet list built by the caller from CallState (<=150 tokens)
    history: list[tuple[str, str]]  # [(speaker, text), ...], speaker is "patient" | "agent"
    patient_utterance: str
    repair_hint: str | None = None  # e.g. "patient asked you to repeat, shorter" when applicable


def build_system_instruction(ctx: NodeTurnContext) -> str:
    language_key = ctx.locked_language or LanguageFamily.hindi_hinglish
    return GLOBAL_RULES.format(
        agent_name=ctx.agent_name,
        hospital_name=ctx.hospital_name,
        gender_hint=_GENDER_GRAMMAR_HINT.get(ctx.voice_gender, _GENDER_GRAMMAR_HINT["female"]),
        language_instruction=_LOCKED_LANGUAGE_INSTRUCTION.get(
            language_key, _LOCKED_LANGUAGE_INSTRUCTION[LanguageFamily.hindi_hinglish]
        ),
        node_instructions=load_node_prompt(ctx.node),
    )


def build_input_transcript(ctx: NodeTurnContext) -> str:
    lines: list[str] = [f"Current state: {ctx.state_summary}"]
    for speaker, text in ctx.history[-6:]:
        label = "Patient" if speaker == "patient" else "Agent"
        lines.append(f"{label}: {text}")
    lines.append(f"Patient: {ctx.patient_utterance}")
    if ctx.repair_hint:
        lines.append(f"[{ctx.repair_hint}]")
    lines.append("[Respond now, following every rule above.]")
    return "\n".join(lines)
