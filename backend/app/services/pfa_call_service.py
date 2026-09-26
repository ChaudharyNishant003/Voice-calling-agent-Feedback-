"""Conversation graph orchestration (PRD v2 §5, §8; Phase 4). Wires the pure engine
(`domain/conversation_graph/*`) to an `LLMAdapter` and produces what a turn should say — I/O and
decision-*wiring* only, exactly like `demo_conversation_service.py`; every actual decision (safety,
severity, transitions, guards) is delegated to the pure `domain/conversation_graph` modules.

`process_turn()`/`start_turn()` deliberately take no DB session or ORM models — they're pure
functions of `(CallState, event, persona, history, an LLM caller)` returning a new `CallState` plus
what to say, so they're testable with `FakeLLM` and no database at all (PRD Phase 4's own
acceptance check: "mock-LLM integration tests pass"). `submit_turn()`/`start_call()` — the thin
DB-touching wrappers that load/save state via `pfa_call_state` and persist transcript/events,
mirroring `demo_conversation_service.py`'s shape — are Phase 5 (persistence & API), once that
migration exists.

Reply composition rule (not spelled out as a single rule in the PRD, but consistent with every node
description in §6): the text spoken this turn is the CURRENT node's LLM `reply_text` UNLESS the
code-decided next node has a FIXED opening script, in which case that FIXED script replaces it
entirely for this turn. This uniformly handles every node without per-transition special-casing,
except three genuine hybrids called out inline: `refuses_recording` (purpose_consent_time),
`complaint_acknowledge` (complaint_detail's first turn on a fresh complaint), and `readback_frame`
(the LLM only supplies the summary sentence inside a FIXED frame).

Known, deliberate simplifications versus the PRD's literal wording (documented here rather than in
a separate doc, per PRD §17 "decide, document the decision in the final report, continue" — these
don't touch safety, consent, or escalation correctness):
- `CALLBACK` is a true one-shot exit (matches `graph.py`'s already-tested `TERMINAL_NODES`, which
  has no self-loop for it): the call ends the turn it enters CALLBACK, so the PRD's two-step
  "ask when -> confirm slot" becomes one line asking, with no second turn to capture the answer.
- The `ESCALATE_URGENT` medical/self-harm follow-up question ("would you like a callback now?") is
  answered with a small deterministic yes/no check, not a tenth LLM node-prompt file — the call
  always proceeds to `CLOSE` either way, so the only thing at stake is which close line and a log
  entry, not a safety decision.
- The "other language" repair (§6.6) treats any `language_detected="other"` turn as one attempt at
  redirecting to Hindi/English before giving up to `CALLBACK`, without trying to identify which
  language it actually was beyond what's already in the transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pybreaker
from pydantic import ValidationError as PydanticValidationError

from app.adapters.interfaces import LLMAdapter
from app.adapters.registry import AdapterRegistry, call_with_breaker
from app.core.errors import AdapterError
from app.domain.conversation_graph import guards, policy, prompts, repair, safety, scripts, severity
from app.domain.conversation_graph.graph import TERMINAL_NODES, Node, next_node
from app.domain.conversation_graph.state import (
    CallOutcome,
    CallState,
    ComplaintDraft,
    Escalation,
    Register,
    SafetyCategory,
    Severity,
    TopicCategory,
    TopicMention,
    over_turn_ceiling,
)
from app.domain.conversation_language import LanguageFamily, decide_language
from app.domain.enums import Sentiment
from app.services.pfa_call_prompts import (
    NodeTurnContext,
    build_input_transcript,
    build_system_instruction,
)
from app.services.pfa_node_contract import NodeContract

# Same rationale/value as demo_conversation_service.py's _LLM_TIMEOUT_S — verified against the real
# Gemini API for this project.
_LLM_TIMEOUT_S = 12.0
_CONTRACT_FALLBACK_TEXT = "Maaf kijiye, ek baar phir bata sakte hain?"

Event = tuple[str, dict[str, object]]

# Nodes whose spoken line is always this literal FIXED script, independent of which node produced
# the turn — see the module docstring's "reply composition rule".
_SIMPLE_FIXED_SCRIPT: dict[Node, str] = {
    Node.open_and_identify: "open_and_identify",
    Node.purpose_consent_time: "purpose_consent_time",
    Node.caregiver: "caregiver_opener",
    Node.overall_rating: "overall_rating",
    Node.anything_else: "anything_else",
    Node.escalate_standard: "escalate_standard",
}

_SAFETY_TO_ESCALATE_SCRIPT: dict[str, str] = {
    "medical_now": "escalate_urgent_medical",
    "self_harm": "escalate_urgent_self_harm",
    "abuse": "escalate_urgent_abuse",
    "sexual_misconduct": "escalate_urgent_abuse",
    "privacy": "escalate_urgent_abuse",
    "discrimination": "escalate_urgent_abuse",
    "threat": "escalate_urgent_threat",
    "medication_error": "escalate_urgent_medical",
}
_SAFETY_WITH_FOLLOWUP: dict[str, str] = {
    "medical_now": "escalate_urgent_medical_followup",
    "medication_error": "escalate_urgent_medical_followup",
    "self_harm": "escalate_urgent_self_harm_followup",
}

_AFFIRMATIVE = {"haan", "ji", "yes", "ha", "theek", "ok", "okay", "sure"}
_NEGATIVE = {"nahi", "no", "nope", "mat"}


@dataclass(frozen=True)
class PersonaContext:
    hospital_name: str
    agent_name: str
    voice_gender: Literal["female", "male"]
    first_name: str
    hospital_phone: str | None
    escalation_sla_text: str | None
    tts_script: scripts.ScriptForm
    visit_date_words: str


@dataclass(frozen=True)
class TurnResult:
    state: CallState
    display_text: str
    speech_text: str
    speech_lang: str  # "hi-IN" | "en-IN"
    ended: bool
    events: tuple[Event, ...]


def _language_family(state: CallState) -> LanguageFamily:
    return state.language.locked or LanguageFamily.hindi_hinglish


def _speech_lang(family: LanguageFamily) -> str:
    return "en-IN" if family == LanguageFamily.english else "hi-IN"


def _render(state: CallState, persona: PersonaContext, key: str, **placeholders: str) -> str:
    gender = persona.voice_gender
    family = _language_family(state)
    hospital_phone_sentence = ""
    if key == "close" and persona.hospital_phone:
        hospital_phone_sentence = scripts.render_script(
            "hospital_phone_sentence",
            gender=gender,
            language=family,
            script=persona.tts_script,
            hospital_phone_chunks=persona.hospital_phone,
        )
    sla_sentence = (
        f"Team {persona.escalation_sla_text} mein sampark karegi."
        if persona.escalation_sla_text
        else ""
    )
    return scripts.render_script(
        key,
        gender=gender,
        language=family,
        script=persona.tts_script,
        hospital=persona.hospital_name,
        agent=persona.agent_name,
        first_name=persona.first_name,
        visit_date_words=persona.visit_date_words,
        hospital_phone_sentence=hospital_phone_sentence,
        hospital_phone_chunks=persona.hospital_phone or "",
        sla_words=persona.escalation_sla_text or "",
        sla_sentence=sla_sentence,
        **placeholders,
    )


def _finalize(
    state: CallState,
    persona: PersonaContext,
    text: str,
    *,
    events: tuple[Event, ...] = (),
    enforce_length: bool = False,
) -> TurnResult:
    """`enforce_length` defaults to False because almost every call site here speaks FIXED,
    pre-vetted script content (PRD §6/§7) — several of those lines are legitimately longer than the
    generic 25/30-word turn budget by design (the consent disclosure, the emergency-escalation
    scripts), and truncating them would be actively harmful (an emergency phone number cut off
    mid-sentence). The PRD's length rule is stated for LLM-*generated* replies (§6: "Global turn
    rules (apply to every LLM-generated reply)") — callers that actually pass raw or lightly-framed
    LLM text (`readback_and_next_steps`, the fresh-complaint acknowledgement, and the plain LLM-node
    fallback in `_apply_transition`) opt back in with `enforce_length=True`. Every other guard
    (promo/medical-advice/pre-identity disclosure) always runs regardless of this flag.
    """
    guard_result = guards.apply_guards(
        text,
        identity_verified=state.identity_verified,
        fallback_promo=_render(state, persona, "anything_else"),
        fallback_medical=_render(state, persona, "deflect_medical"),
        fallback_privacy=_render(state, persona, "purpose_consent_time"),
        enforce_length=enforce_length,
    )
    guard_events: tuple[Event, ...] = tuple(
        ("GUARD_EVENT", {"code": code}) for code in guard_result.triggered
    )
    # Numeric slots (ratings, dates, phone numbers) are already spoken as words in scripts.yaml and
    # in the persona's own precomputed fields; free-text LLM replies in this product rarely carry
    # raw digits (ratings/dates are always asked via FIXED lines). See normalizer.py for the
    # building blocks a fuller free-text digit pass would use if that ever changes.
    return TurnResult(
        state=state,
        display_text=guard_result.text,
        speech_text=guard_result.text,
        speech_lang=_speech_lang(_language_family(state)),
        ended=state.ended,
        events=events + guard_events,
    )


def start_turn(persona: PersonaContext) -> TurnResult:
    """The call's very first line — FIXED, no patient utterance yet, no LLM call (PRD §6 Node 1)."""
    state = CallState(node=Node.open_and_identify)
    text = _render(state, persona, "open_and_identify")
    return _finalize(state, persona, text, events=(("CALL_STARTED", {}),))


async def _call_node_llm(
    *,
    node: Node,
    persona: PersonaContext,
    state: CallState,
    history: list[tuple[str, str]],
    patient_text: str,
    repair_hint: str | None,
    registry: AdapterRegistry[LLMAdapter],
    provider: str,
) -> tuple[NodeContract, tuple[Event, ...]]:
    """Mirrors `demo_conversation_service._call_llm_with_retry`: one retry, then a FIXED-line
    fallback contract on a second failure (PRD §8 "Validation & failure handling") — the lexicon
    safety scan has already run by the time this is called, so safety is never lost to an LLM
    failure (CLAUDE.md rule 3).
    """
    ctx = NodeTurnContext(
        node=node,
        hospital_name=persona.hospital_name,
        agent_name=persona.agent_name,
        voice_gender=persona.voice_gender,
        locked_language=state.language.locked,
        state_summary=_state_summary(state),
        history=history,
        patient_utterance=patient_text,
        repair_hint=repair_hint,
    )
    variables: dict[str, object] = {
        "system_instruction": build_system_instruction(ctx),
        "input_transcript": build_input_transcript(ctx),
    }
    adapter = registry.get(provider)
    breaker = registry.breaker(provider)
    events: list[Event] = [("LLM_REQUEST", {"provider": provider, "node": node.value})]

    for attempt in (1, 2):
        try:
            result = await call_with_breaker(
                breaker, adapter.complete, "pfa_node_turn", variables, timeout_s=_LLM_TIMEOUT_S
            )
            contract = NodeContract.model_validate(result.data)
            events.append(
                ("LLM_RESPONSE", {"node": node.value, "proposed_next": contract.proposed_next})
            )
            return contract, tuple(events)
        except pybreaker.CircuitBreakerError as exc:
            events.append(("ERROR", {"attempt": attempt, "message": f"circuit breaker: {exc}"}))
        except AdapterError as exc:
            events.append(
                ("ERROR", {"attempt": attempt, "code": exc.code, "message": exc.message})
            )
        except PydanticValidationError as exc:
            events.append(
                ("ERROR", {"attempt": attempt, "message": f"malformed structured output: {exc}"})
            )

    events.append(("ERROR", {"message": "LLM failed twice in a row; using fallback response"}))
    events.append(("LLM_CONTRACT_ERROR", {"node": node.value}))
    fallback_language = (
        "hindi" if _language_family(state) == LanguageFamily.hindi_hinglish else "english"
    )
    fallback = NodeContract(
        reply_text=_CONTRACT_FALLBACK_TEXT,
        language_detected=fallback_language,
        proposed_next=node.value,
    )
    return fallback, tuple(events)


def _state_summary(state: CallState) -> str:
    open_complaint = None
    idx = state.current_complaint_index
    if idx is not None and idx < len(state.complaints):
        open_complaint = state.complaints[idx]
    known_fields = _known_complaint_fields(open_complaint) if open_complaint else []
    parts = [
        f"node={state.node.value}",
        f"identity_verified={state.identity_verified}",
        f"respondent_type={state.respondent_type.value}",
        f"topics_covered={sorted(t.value for t in state.topics_covered)}",
        f"rating_asked={state.rating_asked}",
        f"open_complaint={open_complaint.description if open_complaint else None}",
        f"open_complaint_questions_asked={open_complaint.question_count if open_complaint else 0}",
        f"open_complaint_known_fields={known_fields}",
        f"agent_turns={state.agent_turns}",
    ]
    return "; ".join(parts)


def _known_complaint_fields(draft: ComplaintDraft) -> list[str]:
    known = []
    if draft.when_text or draft.where_text:
        known.append("when_where")
    if draft.wants_contact is not None:
        known.append("contact")
    if draft.staff_name:
        known.append("staff_name")
    if len(draft.description) > 15:
        known.append("specifics")
    return known


def _resolve_next(state: CallState, proposed_raw: str, events: list[Event]) -> Node:
    try:
        proposed = Node(proposed_raw)
    except ValueError:
        events.append(
            ("ILLEGAL_TRANSITION_PROPOSED", {"from": state.node.value, "proposed": proposed_raw})
        )
        return state.node
    resolved = next_node(state.node, proposed)
    if resolved != proposed and state.node not in TERMINAL_NODES:
        events.append(
            ("ILLEGAL_TRANSITION_PROPOSED", {"from": state.node.value, "proposed": proposed_raw})
        )
    return resolved


def _map_topic_category(raw: str) -> TopicCategory:
    try:
        return TopicCategory(raw)
    except ValueError:
        return TopicCategory.other


def _merge_topics(state: CallState, contract: NodeContract) -> CallState:
    new_topics = tuple(
        TopicMention(
            category=_map_topic_category(t.category),
            sentiment=Sentiment(t.sentiment),
            verbatim=t.verbatim,
            staff_name=t.staff_name,
        )
        for t in contract.topics
    )
    covered = state.topics_covered | {t.category for t in new_topics}
    return replace(state, topics=state.topics + new_topics, topics_covered=covered)


def _merge_complaint(state: CallState, contract: NodeContract) -> CallState:
    if contract.complaint_update is None:
        return state
    update = contract.complaint_update
    idx = state.current_complaint_index
    if idx is not None and idx < len(state.complaints):
        existing = state.complaints[idx]
        wants_contact = (
            update.wants_contact if update.wants_contact is not None else existing.wants_contact
        )
        merged = replace(
            existing,
            description=update.description or existing.description,
            when_text=update.when or existing.when_text,
            where_text=update.where or existing.where_text,
            wants_contact=wants_contact,
            preferred_time=update.preferred_time or existing.preferred_time,
            question_count=existing.question_count + 1,
        )
        complaints = state.complaints[:idx] + (merged,) + state.complaints[idx + 1 :]
        return replace(state, complaints=complaints)

    draft = ComplaintDraft(
        category=_map_topic_category(update.category),
        description=update.description,
        when_text=update.when,
        where_text=update.where,
        wants_contact=update.wants_contact,
        preferred_time=update.preferred_time,
        question_count=1,
    )
    complaints = state.complaints + (draft,)
    return replace(state, complaints=complaints, current_complaint_index=len(complaints) - 1)


def _apply_language(state: CallState, contract: NodeContract) -> tuple[CallState, bool]:
    hinglish_aliases = ("hindi", "hinglish")
    if contract.language_detected == "english":
        detected = LanguageFamily.english
    elif contract.language_detected in hinglish_aliases:
        detected = LanguageFamily.hindi_hinglish
    else:
        return state, True  # "other" — handled by the caller as the other-language repair path

    decision = decide_language(state.language, detected)
    register = (
        Register(contract.register) if contract.register in ("formal", "casual") else state.register
    )
    return replace(state, language=decision.state, register=register), False


async def process_turn(
    *,
    state: CallState,
    event_kind: Literal["utterance", "silence", "stt_error"],
    event_text: str | None,
    persona: PersonaContext,
    history: list[tuple[str, str]],
    registry: AdapterRegistry[LLMAdapter],
    provider: str,
) -> TurnResult:
    if state.node in TERMINAL_NODES or state.ended:
        # Defensive only — the caller (submit_turn, Phase 5) is expected to have already ended the
        # call once a terminal node is reached; a turn should never arrive after that.
        return _finalize(state, persona, _render(state, persona, "close_short"), events=())

    events: list[Event] = []
    state = replace(state, agent_turns=state.agent_turns + 1)

    if event_kind == "silence":
        return _handle_silence(state, persona)
    if event_kind == "stt_error":
        return _handle_stt_error(state, persona)

    text = event_text or ""

    # Turn continuing an urgent-escalation follow-up question: deterministic yes/no, no LLM call
    # (see module docstring).
    if state.node == Node.escalate_urgent:
        return _handle_escalate_urgent_followup(state, persona, text)

    # Step 1 (PRD §5): safety pre-scan on the raw text. A keyword hit is safety-critical and
    # time-critical, so it skips the LLM entirely rather than waiting up to 12s for a reply that
    # would only be overridden anyway (CLAUDE.md rule 6 — never let latency delay an escalation).
    keyword_category = safety.scan_lexicon(text)
    if keyword_category is not None:
        events.append(
            ("SAFETY_TRIGGERED", {"category": keyword_category.value, "triggered_by": "keyword"})
        )
        return _escalate_urgent(state, persona, keyword_category.value, "keyword", events)

    # Step 2: policy pre-checks (opt-out / wants-human / repeat-request) — deterministic, never the
    # LLM's call (CLAUDE.md rule 3).
    intent = policy.detect_policy_intent(text)
    if intent == policy.PolicyIntent.opt_out:
        new_state = replace(
            state, node=Node.opt_out, do_not_call=True, call_outcome=CallOutcome.opt_out, ended=True
        )
        events.append(("POLICY_OPT_OUT", {}))
        text = _render(new_state, persona, "opt_out")
        return _finalize(new_state, persona, text, events=tuple(events))
    if intent == policy.PolicyIntent.wants_human:
        new_state = replace(
            state,
            node=Node.callback,
            wants_human=True,
            call_outcome=CallOutcome.callback,
            ended=True,
        )
        events.append(("POLICY_WANTS_HUMAN", {}))
        return _finalize(
            new_state, persona, _render(new_state, persona, "wants_human"), events=tuple(events)
        )

    repair_hint: str | None = None
    if intent == policy.PolicyIntent.repeat_request:
        action, new_count = repair.on_repeat_request(state.repair_count)
        if action == repair.RepairAction.give_up_to_callback:
            new_state = replace(
                state,
                repair_count=new_count,
                node=Node.callback,
                call_outcome=CallOutcome.callback,
                ended=True,
            )
            events.append(("REPAIR_GIVE_UP", {}))
            text = _render(new_state, persona, "callback_ask")
            return _finalize(new_state, persona, text, events=tuple(events))
        state = replace(state, repair_count=new_count)
        repair_hint = (
            "The patient didn't understand — rephrase your last question, shorter, max 12 words."
        )
        events.append(("REPAIR_REPEAT", {"count": new_count}))
    else:
        state = replace(state, repair_count=0)

    if not prompts.has_node_prompt(state.node):
        # Defensive: every node an "utterance" can legitimately arrive on has a prompt file.
        new_state = replace(state, node=Node.close, ended=True, call_outcome=CallOutcome.abandoned)
        events.append(("ERROR", {"message": f"no LLM prompt for node {state.node.value}"}))
        return _finalize(
            new_state, persona, _render(new_state, persona, "close_short"), events=tuple(events)
        )

    contract, llm_events = await _call_node_llm(
        node=state.node,
        persona=persona,
        state=state,
        history=history,
        patient_text=text,
        repair_hint=repair_hint,
        registry=registry,
        provider=provider,
    )
    events.extend(llm_events)

    state, is_other_language = _apply_language(state, contract)
    if is_other_language:
        return _handle_other_language(state, persona, events)

    state = _merge_topics(state, contract)
    state = _merge_complaint(state, contract)

    if contract.rating is not None:
        rating_value = (
            contract.rating.value if contract.rating.value is not None else state.rating
        )
        state = replace(
            state, rating=rating_value, rating_inferred=contract.rating.inferred, rating_asked=True
        )

    # Step 5: post-LLM safety check (OR with the pre-scan, which already returned above if it hit).
    safety_result = safety.evaluate_safety(
        patient_text=text,
        llm_flag=contract.safety.flag,
        llm_category=SafetyCategory(contract.safety.category),
    )
    if safety_result.triggered:
        events.append(
            ("SAFETY_TRIGGERED", {"category": safety_result.category.value, "triggered_by": "llm"})
        )
        return _escalate_urgent(state, persona, safety_result.category.value, "llm", events)

    if repair_hint is not None:
        # A repair turn never actually moves the graph — only real content does.
        resolved = state.node
    else:
        resolved = _resolve_next(state, contract.proposed_next, events)

    if resolved == Node.severity_gate:
        state, resolved = _resolve_severity_gate(state, contract, events)

    ceiling_exempt = (
        Node.close,
        Node.callback,
        Node.opt_out,
        Node.close_wrong,
        Node.escalate_urgent,
        Node.readback_and_next_steps,
    )
    if over_turn_ceiling(state) and resolved not in ceiling_exempt:
        events.append(("TURN_CEILING_REACHED", {"agent_turns": state.agent_turns}))
        resolved = Node.readback_and_next_steps if state.complaints else Node.close

    return _apply_transition(state, persona, resolved, contract, events)


def _apply_transition(
    state: CallState,
    persona: PersonaContext,
    resolved: Node,
    contract: NodeContract,
    events: list[Event],
) -> TurnResult:
    new_state = replace(state, node=resolved)

    if resolved == Node.close_wrong:
        new_state = replace(new_state, ended=True, call_outcome=CallOutcome.wrong_number)
        text = _render(new_state, persona, "close_wrong")
        return _finalize(new_state, persona, text, events=tuple(events))

    if resolved == Node.callback:
        new_state = replace(new_state, ended=True, call_outcome=CallOutcome.callback)
        text = _render(new_state, persona, "callback_ask")
        return _finalize(new_state, persona, text, events=tuple(events))

    if resolved == Node.opt_out:
        new_state = replace(
            new_state, ended=True, do_not_call=True, call_outcome=CallOutcome.opt_out
        )
        text = _render(new_state, persona, "opt_out")
        return _finalize(new_state, persona, text, events=tuple(events))

    if (
        state.node == Node.purpose_consent_time
        and resolved == Node.close
        and "refuses_recording" in contract.intents
    ):
        new_state = replace(new_state, ended=True, call_outcome=CallOutcome.no_consent)
        events.append(("NO_CONSENT_WANTS_CONTACT", {}))
        text = _render(new_state, persona, "refuses_recording")
        return _finalize(new_state, persona, text, events=tuple(events))

    asks_if_ai_repeat = (
        state.node == Node.purpose_consent_time
        and "asks_if_ai" in contract.intents
        and resolved == Node.purpose_consent_time
    )
    if asks_if_ai_repeat:
        answer = _render(new_state, persona, "asks_if_ai")
        question = _render(new_state, persona, "purpose_consent_time")
        return _finalize(new_state, persona, f"{answer} {question}", events=tuple(events))

    if resolved == Node.close:
        outcome = new_state.call_outcome or CallOutcome.completed
        new_state = replace(new_state, ended=True, call_outcome=outcome)
        text = _render(new_state, persona, "close")
        return _finalize(new_state, persona, text, events=tuple(events))

    if resolved == Node.escalate_urgent:
        # Reached via severity_gate (a complaint the LLM itself judged S4) rather than the safety
        # lexicon/flag path (`_escalate_urgent`, which picks a category-specific script) — there's
        # no safety category here to pick a more specific line, so the generic serious-escalation
        # wording is the safe default (never a downgrade, per CLAUDE.md rule 6).
        new_state = replace(new_state, ended=True, call_outcome=CallOutcome.escalated)
        text = _render(new_state, persona, "escalate_urgent_abuse")
        return _finalize(new_state, persona, text, events=tuple(events), enforce_length=False)

    if resolved == Node.escalate_standard:
        # Transient (PRD §7.5): speak the line now, but the state is already positioned for the
        # patient's next utterance to be interpreted fresh under probe_topics.
        new_state = replace(new_state, node=Node.probe_topics)
        text = _render(state, persona, "escalate_standard")
        return _finalize(new_state, persona, text, events=tuple(events))

    if resolved == Node.readback_and_next_steps:
        summary = contract.reply_text.strip() or "Aapne kuch complaints share ki."
        if persona.escalation_sla_text:
            next_step_sentence = _render(new_state, persona, "next_step_with_sla")
        else:
            next_step_sentence = _render(new_state, persona, "next_step_no_sla")
        text = _render(
            new_state,
            persona,
            "readback_frame",
            summary=summary,
            next_step_sentence=next_step_sentence,
        )
        # The summary embedded in this frame is LLM-authored (PRD §6 asks for <=20 words, but
        # nothing stops the LLM from ignoring that) — unlike the pure-FIXED branches, this needs
        # the length guard as a real safety net against rambling.
        return _finalize(new_state, persona, text, events=tuple(events), enforce_length=True)

    if resolved == Node.complaint_detail and _is_fresh_complaint_turn(state, resolved):
        opener = _render(new_state, persona, "complaint_acknowledge")
        text = f"{opener} {contract.reply_text.strip()}"
        return _finalize(new_state, persona, text, events=tuple(events), enforce_length=True)

    if resolved in _SIMPLE_FIXED_SCRIPT:
        text = _render(new_state, persona, _SIMPLE_FIXED_SCRIPT[resolved])
        return _finalize(new_state, persona, text, events=tuple(events))

    # open_experience, probe_topics, complaint_detail (continuing), anything_else's own
    # new-content branch: no FIXED line applies — the LLM's own reply_text is the turn, and needs
    # the same length guard.
    return _finalize(
        new_state, persona, contract.reply_text.strip(), events=tuple(events), enforce_length=True
    )


def _is_fresh_complaint_turn(prior_state: CallState, resolved: Node) -> bool:
    return prior_state.node != Node.complaint_detail and resolved == Node.complaint_detail


def _resolve_severity_gate(
    state: CallState, contract: NodeContract, events: list[Event]
) -> tuple[CallState, Node]:
    """Node 7 (PRD §6/§7.1): code decides the final severity and the routing — the LLM's
    `severity_proposal` is only ever a suggestion (`severity.resolve_severity`). A safety-lexicon
    trigger would already have short-circuited this turn in `process_turn` before reaching here, so
    `safety_triggered=False` is correct here: this gate only runs for complaints, never a keyword
    hit.
    """
    llm_severity = Severity(contract.severity_proposal) if contract.severity_proposal else None
    resolved_severity = severity.resolve_severity(llm_proposed=llm_severity, safety_triggered=False)
    events.append(("SEVERITY_RESOLVED", {"severity": resolved_severity.value}))
    route = severity.route_after_severity(resolved_severity)

    idx = state.current_complaint_index
    if idx is not None and idx < len(state.complaints):
        updated = replace(state.complaints[idx], severity=resolved_severity)
        complaints = state.complaints[:idx] + (updated,) + state.complaints[idx + 1 :]
        escalation = Escalation(
            complaint_index=idx,
            severity=resolved_severity,
            category=state.complaints[idx].category.value,
            triggered_by="llm",
        )
        is_escalation = resolved_severity in (Severity.s3, Severity.s4)
        escalations = state.escalations + (escalation,) if is_escalation else state.escalations
        # This complaint is fully processed once severity is resolved, regardless of where it
        # routes next — clearing the index means the *next* complaint_update starts a fresh draft
        # instead of silently overwriting this one (ComplaintDraft is append-only in
        # `state.complaints`).
        state = replace(
            state, complaints=complaints, escalations=escalations, current_complaint_index=None
        )

    return state, route


def _escalate_urgent(
    state: CallState, persona: PersonaContext, category: str, triggered_by: str, events: list[Event]
) -> TurnResult:
    escalation = Escalation(
        complaint_index=state.current_complaint_index,
        severity=Severity.s4,
        category=category,
        triggered_by=triggered_by,
    )
    new_state = replace(
        state, node=Node.escalate_urgent, escalations=state.escalations + (escalation,)
    )
    script_key = _SAFETY_TO_ESCALATE_SCRIPT.get(category, "escalate_urgent_abuse")
    text = _render(new_state, persona, script_key)
    followup_key = _SAFETY_WITH_FOLLOWUP.get(category)
    if followup_key:
        text = f"{text} {_render(new_state, persona, followup_key)}"
    else:
        new_state = replace(new_state, ended=True, call_outcome=CallOutcome.escalated)
    return _finalize(new_state, persona, text, events=tuple(events), enforce_length=False)


def _handle_escalate_urgent_followup(
    state: CallState, persona: PersonaContext, text: str
) -> TurnResult:
    lowered = text.strip().lower()
    said_yes = any(w in lowered for w in _AFFIRMATIVE)
    said_no = any(w in lowered for w in _NEGATIVE)
    wants_callback = said_yes and not said_no
    new_state = replace(
        state,
        node=Node.close,
        ended=True,
        call_outcome=CallOutcome.escalated,
        wants_human=wants_callback or state.wants_human,
    )
    reply = _render(new_state, persona, "close_short")
    event: Event = ("ESCALATE_FOLLOWUP", {"wants_callback": wants_callback})
    return _finalize(new_state, persona, reply, events=(event,))


def _handle_silence(state: CallState, persona: PersonaContext) -> TurnResult:
    action, new_count = repair.on_silence(state.consecutive_silences)
    if action == repair.RepairAction.end_call_silence:
        new_state = replace(
            state, consecutive_silences=new_count, ended=True, call_outcome=CallOutcome.callback
        )
        text = _render(new_state, persona, "silence_second")
        return _finalize(new_state, persona, text, events=(("SILENCE_END", {}),))
    new_state = replace(state, consecutive_silences=new_count)
    text = _render(new_state, persona, "silence_first")
    return _finalize(new_state, persona, text, events=(("SILENCE", {}),))


def _handle_stt_error(state: CallState, persona: PersonaContext) -> TurnResult:
    action, new_count = repair.on_repeat_request(state.repair_count)
    if action == repair.RepairAction.give_up_to_callback:
        new_state = replace(
            state,
            repair_count=new_count,
            node=Node.callback,
            ended=True,
            call_outcome=CallOutcome.callback,
        )
        text = _render(new_state, persona, "callback_ask")
        return _finalize(new_state, persona, text, events=(("STT_ERROR_GIVE_UP", {}),))
    new_state = replace(state, repair_count=new_count)
    text = _render(new_state, persona, "stt_could_not_hear")
    return _finalize(new_state, persona, text, events=(("STT_ERROR", {}),))


def _handle_other_language(
    state: CallState, persona: PersonaContext, events: list[Event]
) -> TurnResult:
    if state.language_need is not None:
        new_state = replace(
            state, node=Node.callback, ended=True, call_outcome=CallOutcome.callback
        )
        events.append(("OTHER_LANGUAGE_GIVE_UP", {}))
        text = _render(new_state, persona, "callback_ask")
        return _finalize(new_state, persona, text, events=tuple(events))
    new_state = replace(state, language_need="other")
    events.append(("OTHER_LANGUAGE", {}))
    text = _render(new_state, persona, "other_language")
    return _finalize(new_state, persona, text, events=tuple(events))
