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

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import pybreaker
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.interfaces import LLMAdapter
from app.adapters.registry import AdapterRegistry, call_with_breaker
from app.core.config import get_settings as get_core_settings
from app.core.errors import AdapterError
from app.core.errors import NotFoundError as PFANotFoundError
from app.core.errors import ValidationError as PFAValidationError
from app.core.ids import uuid7
from app.core.phone import phone_hash
from app.core.security import decrypt, encrypt, get_local_kek
from app.db.models.calls import Call, CallEvent, Transcript
from app.db.models.cases import Case, CaseEvent, Complaint, PfaEscalation
from app.db.models.demo import Callback, DemoSettings, DoNotCall
from app.db.models.enums import (
    CallStatus,
    CampaignType,
    CasePriority,
    CaseStatus,
    ConsentState,
    RespondentType,
    Speaker,
    VisitType,
)
from app.db.models.patients_visits import Patient, Visit
from app.db.models.tenancy import Department
from app.db.repositories.encryption_keys import get_or_create_dek
from app.domain.conversation_graph import (
    guards,
    normalizer,
    policy,
    prompts,
    repair,
    safety,
    scripts,
    severity,
)
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
    VisitKind,
    over_turn_ceiling,
)
from app.domain.conversation_language import LanguageFamily, LanguageState, decide_language
from app.domain.enums import Sentiment
from app.services import demo_conversation_service, demo_settings_service
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
) -> tuple[NodeContract, tuple[Event, ...], bool]:
    """Mirrors `demo_conversation_service._call_llm_with_retry`: one retry, then a FIXED-line
    fallback contract on a second failure (PRD §8 "Validation & failure handling") — the lexicon
    safety scan has already run by the time this is called, so safety is never lost to an LLM
    failure (CLAUDE.md rule 3). The third return value is True only for that fallback path — the
    caller must speak `_CONTRACT_FALLBACK_TEXT` verbatim in that case rather than letting the
    normal FIXED-script-wins rule silently swap in whatever line the (unchanged) current node
    happens to own, which would make the repair prompt invisible to the patient.
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
                (
                    "LLM_RESPONSE",
                    {
                        "node": node.value,
                        "proposed_next": contract.proposed_next,
                        "latency_ms": result.latency_ms,
                        "model": result.model,
                    },
                )
            )
            return contract, tuple(events), False
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
    return fallback, tuple(events), True


def _state_summary(state: CallState) -> str:
    open_complaint = None
    idx = state.current_complaint_index
    if idx is not None and idx < len(state.complaints):
        open_complaint = state.complaints[idx]
    known_fields = _known_complaint_fields(open_complaint) if open_complaint else []
    # Every complaint already logged this call, not just the currently-open one — without this,
    # probe_topics' own "depth first: follow up on a negative topic that hasn't become a complaint
    # yet" instruction has nothing to check against once a complaint is closed out (current_
    # complaint_index clears back to None at severity_gate), and the LLM re-raises the same issue
    # as a brand-new complaint. Confirmed live: a reception complaint was logged twice this way.
    already_logged = [c.description for c in state.complaints if c is not open_complaint]
    parts = [
        f"node={state.node.value}",
        f"identity_verified={state.identity_verified}",
        f"respondent_type={state.respondent_type.value}",
        f"topics_covered={sorted(t.value for t in state.topics_covered)}",
        f"rating_asked={state.rating_asked}",
        f"already_logged_complaints={already_logged}",
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
    # The LLM often re-reports a topic it already mentioned in an earlier turn (still visible in
    # its own recent-history window) — confirmed live: the same reception complaint showed up as
    # 3 identical topic entries on the results page. Dedupe by (category, verbatim) rather than
    # trusting the LLM to only ever report genuinely new mentions.
    seen = {(t.category, t.verbatim) for t in state.topics}
    new_topics = []
    for t in contract.topics:
        category = _map_topic_category(t.category)
        key = (category, t.verbatim)
        if key in seen:
            continue
        seen.add(key)
        new_topics.append(
            TopicMention(
                category=category,
                sentiment=Sentiment(t.sentiment),
                verbatim=t.verbatim,
                staff_name=t.staff_name,
            )
        )
    covered = state.topics_covered | {t.category for t in new_topics}
    return replace(state, topics=state.topics + tuple(new_topics), topics_covered=covered)


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

    contract, llm_events, contract_failed = await _call_node_llm(
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

    if contract_failed:
        # Speak the FIXED repair line verbatim — bypassing the normal FIXED-script-wins rule,
        # which would otherwise silently replace it with whatever line the (unchanged, since
        # proposed_next self-loops) current node owns, making the repair invisible to the patient.
        return _finalize(state, persona, contract.reply_text, events=tuple(events))

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

    # PRD §6 Node 1/1b: confirming identity (directly, or via an accompanying caregiver) is what
    # actually clears `identity_verified` — never set anywhere else. Without this, the pre-identity
    # disclosure guard (GUARD_PRIVACY) fires for the rest of the call the instant any reply
    # mentions "doctor"/"department"/etc., confirmed live: a normal open_experience
    # acknowledgement ("Doctor achhe...") got silently replaced by the consent FIXED line because
    # this was never set.
    if (
        state.node == Node.open_and_identify
        and resolved == Node.purpose_consent_time
        and "affirm" in contract.intents
    ):
        new_state = replace(
            new_state, identity_verified=True, respondent_type=RespondentType.patient
        )
    elif (
        state.node == Node.caregiver
        and resolved == Node.purpose_consent_time
        and "accompanied" in contract.intents
    ):
        new_state = replace(new_state, identity_verified=True, respondent_type=RespondentType.proxy)

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
            state,
            consecutive_silences=new_count,
            node=Node.callback,
            ended=True,
            call_outcome=CallOutcome.callback,
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


# ============================================================================
# Persistence & API wiring (PRD v2 Phase 5) — the thin DB-touching layer around the pure engine
# above. Reuses `demo_conversation_service`'s account/location/department bootstrap (same fixed
# demo account, now made public there for exactly this reuse) rather than duplicating that logic.
#
# State persistence: no new `pfa_call_state` table (see migration 0016's docstring) — `CallState`
# is serialized to/from `Call.state_snapshot` (JSONB), the same column/mechanism the existing Demo
# MVP engine already uses for resume-after-restart.
# ============================================================================

_TRANSCRIPT_RETENTION_DAYS = 30

_VISIT_KIND_TO_DB: dict[str, VisitType] = {
    "OPD": VisitType.outpatient,
    "IPD": VisitType.inpatient,
    "DIAGNOSTICS": VisitType.diagnostic,
    "EMERGENCY": VisitType.emergency,
}
_VISIT_KIND_TO_ENGINE: dict[str, VisitKind] = {
    "OPD": VisitKind.opd,
    "IPD": VisitKind.ipd,
    "DIAGNOSTICS": VisitKind.diagnostics,
    "EMERGENCY": VisitKind.emergency,
}
# Inverse of _VISIT_KIND_TO_DB — needed when a call starts from an already-ingested Visit row
# (PRD v2 Phase 8), which already has a DB VisitType, not a PRD-form VisitKind string.
_DB_VISIT_TYPE_TO_ENGINE: dict[VisitType, VisitKind] = {
    VisitType.outpatient: VisitKind.opd,
    VisitType.inpatient: VisitKind.ipd,
    VisitType.diagnostic: VisitKind.diagnostics,
    VisitType.emergency: VisitKind.emergency,
}

# S3/S4 severities always create a Case (PRD §7.1); the ack SLA hours are a Demo MVP simplification
# (the real SLA engine is Sprint 5, not yet built anywhere in this codebase) rather than reading
# from `Account.sla_config`, since the demo account's config isn't wired to these new severities.
_ACK_SLA_HOURS = {Severity.s4: 1, Severity.s3: 4}
_SEVERITY_TO_PRIORITY = {Severity.s4: CasePriority.p1, Severity.s3: CasePriority.p2}


class DemoCallNotFoundError(PFANotFoundError):
    pass


class DemoCallAlreadyEndedError(PFAValidationError):
    pass


class PatientOnDoNotCallError(PFAValidationError):
    pass


@dataclass(frozen=True)
class StartCallInput:
    provider: str
    patient_first_name: str
    patient_phone: str | None
    visit_type: str  # "OPD" | "IPD" | "DIAGNOSTICS" | "EMERGENCY"
    visit_date: date
    department: str | None = None
    doctor_name: str | None = None
    patient_age: int | None = None


@dataclass(frozen=True)
class TurnApiResult:
    call_id: UUID
    display_text: str
    speech_text: str
    speech_lang: str
    node: str
    ended: bool
    call_outcome: str | None
    escalated: bool


def _persona_from_settings(
    settings: DemoSettings,
    *,
    first_name: str,
    visit_date: date,
    locked_family: LanguageFamily | None,
) -> PersonaContext:
    family = locked_family or LanguageFamily.hindi_hinglish
    return PersonaContext(
        hospital_name=settings.hospital_name,
        agent_name=settings.agent_name,
        voice_gender=settings.voice_gender,  # type: ignore[arg-type]
        first_name=first_name,
        hospital_phone=settings.hospital_phone,
        escalation_sla_text=settings.escalation_sla_text,
        # `demo_settings.tts_script` stores "devanagari"/"roman" (matching ScriptForm's *member
        # names*, per its check constraint), not "deva"/"roman" (ScriptForm.devanagari's *value*) —
        # a by-name lookup, not a by-value one.
        tts_script=scripts.ScriptForm[settings.tts_script],
        visit_date_words=normalizer.date_words(visit_date.day, visit_date.month, family),
    )


def _serialize_state(state: CallState) -> dict[str, object]:
    return {
        "node": state.node.value,
        "visit_kind": state.visit_kind.value,
        "identity_verified": state.identity_verified,
        "respondent_type": state.respondent_type.value,
        "consent": state.consent.value,
        "language_locked": state.language.locked.value if state.language.locked else None,
        "language_consecutive_other_count": state.language.consecutive_other_count,
        "register": state.register.value,
        "topics": [
            {
                "category": t.category.value,
                "sentiment": t.sentiment.value,
                "verbatim": t.verbatim,
                "staff_name": t.staff_name,
            }
            for t in state.topics
        ],
        "topics_covered": sorted(t.value for t in state.topics_covered),
        "priority_topics_probed": state.priority_topics_probed,
        "complaints": [
            {
                "category": c.category.value,
                "description": c.description,
                "severity": c.severity.value if c.severity else None,
                "when_text": c.when_text,
                "where_text": c.where_text,
                "wants_contact": c.wants_contact,
                "preferred_time": c.preferred_time,
                "verbatim": c.verbatim,
                "staff_name": c.staff_name,
                "question_count": c.question_count,
            }
            for c in state.complaints
        ],
        "current_complaint_index": state.current_complaint_index,
        "rating": state.rating,
        "rating_inferred": state.rating_inferred,
        "rating_asked": state.rating_asked,
        "escalations": [
            {
                "complaint_index": e.complaint_index,
                "severity": e.severity.value,
                "category": str(e.category),
                "triggered_by": e.triggered_by,
            }
            for e in state.escalations
        ],
        "clinical_questions": list(state.clinical_questions),
        "readback_count": state.readback_count,
        "repair_count": state.repair_count,
        "consecutive_silences": state.consecutive_silences,
        "agent_turns": state.agent_turns,
        "wants_human": state.wants_human,
        "language_need": state.language_need,
        "do_not_call": state.do_not_call,
        "call_outcome": state.call_outcome.value if state.call_outcome else None,
        "ended": state.ended,
    }


def deserialize_state(data: dict[str, object]) -> CallState:
    # `Any`, deliberately: this whole function's job is un-typed JSON -> the real dataclass, so
    # every value here is inherently unchecked until the enum/dataclass constructors below validate
    # it. Keeping `_get` at `object` just forces a `type: ignore` at every call site instead of
    # actually checking anything, which is worse than being honest that this boundary is unchecked.
    def _get(key: str, default: Any = None) -> Any:  # noqa: ANN401
        return data.get(key, default)

    locked_raw = _get("language_locked")
    language = LanguageState(
        locked=LanguageFamily(locked_raw) if isinstance(locked_raw, str) else None,
        consecutive_other_count=int(_get("language_consecutive_other_count", 0) or 0),
    )
    topics = tuple(
        TopicMention(
            category=TopicCategory(t["category"]),
            sentiment=Sentiment(t["sentiment"]),
            verbatim=t["verbatim"],
            staff_name=t.get("staff_name"),
        )
        for t in _get("topics", [])
    )
    complaints = tuple(
        ComplaintDraft(
            category=TopicCategory(c["category"]),
            description=c["description"],
            severity=Severity(c["severity"]) if c.get("severity") else None,
            when_text=c.get("when_text"),
            where_text=c.get("where_text"),
            wants_contact=c.get("wants_contact"),
            preferred_time=c.get("preferred_time"),
            verbatim=c.get("verbatim", ""),
            staff_name=c.get("staff_name"),
            question_count=int(c.get("question_count", 0)),
        )
        for c in _get("complaints", [])
    )
    escalations = tuple(
        Escalation(
            complaint_index=e.get("complaint_index"),
            severity=Severity(e["severity"]),
            category=e["category"],
            triggered_by=e["triggered_by"],
        )
        for e in _get("escalations", [])
    )
    call_outcome_raw = _get("call_outcome")
    return CallState(
        node=Node(_get("node", Node.open_and_identify.value)),
        visit_kind=VisitKind(_get("visit_kind", VisitKind.opd.value)),
        identity_verified=bool(_get("identity_verified", False)),
        respondent_type=RespondentType(_get("respondent_type", RespondentType.unknown.value)),
        consent=ConsentState(_get("consent", ConsentState.not_asked.value)),
        language=language,
        register=Register(_get("register", Register.casual.value)),
        topics=topics,
        topics_covered=frozenset(TopicCategory(t) for t in _get("topics_covered", [])),
        priority_topics_probed=int(_get("priority_topics_probed", 0)),
        complaints=complaints,
        current_complaint_index=_get("current_complaint_index"),
        rating=_get("rating"),
        rating_inferred=bool(_get("rating_inferred", False)),
        rating_asked=bool(_get("rating_asked", False)),
        escalations=escalations,
        clinical_questions=tuple(_get("clinical_questions", [])),
        readback_count=int(_get("readback_count", 0)),
        repair_count=int(_get("repair_count", 0)),
        consecutive_silences=int(_get("consecutive_silences", 0)),
        agent_turns=int(_get("agent_turns", 0)),
        wants_human=bool(_get("wants_human", False)),
        language_need=_get("language_need"),
        do_not_call=bool(_get("do_not_call", False)),
        call_outcome=CallOutcome(call_outcome_raw) if call_outcome_raw else None,
        ended=bool(_get("ended", False)),
    )


async def _get_or_create_department(
    session: AsyncSession, account_id: UUID, name: str | None
) -> Department:
    if not name:
        return await demo_conversation_service.get_or_create_demo_department(session, account_id)
    code = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "demo-department"
    existing = await session.scalar(
        select(Department).where(Department.account_id == account_id, Department.code == code)
    )
    if existing is not None:
        return existing
    department = Department(account_id=account_id, code=code, name=name)
    session.add(department)
    await session.flush()
    return department


async def _emit_call_event(
    session: AsyncSession, call_id: UUID, event_type: str, data: dict[str, object]
) -> None:
    session.add(CallEvent(call_id=call_id, type=event_type, data=data))
    await session.flush()


async def _persist_transcript_turn(
    session: AsyncSession, call_id: UUID, account_id: UUID, speaker: str, text: str, turn_index: int
) -> None:
    kek = get_local_kek()
    dek = await get_or_create_dek(session, account_id, kek=kek)
    session.add(
        Transcript(
            transcript_id=uuid7(),
            call_id=call_id,
            turn_index=turn_index,
            speaker=Speaker(speaker),
            text_enc=encrypt(text, dek),
            start_ms=0,
            end_ms=0,
            retention_until=datetime.now(UTC) + timedelta(days=_TRANSCRIPT_RETENTION_DAYS),
        )
    )
    await session.flush()


async def start_call(session: AsyncSession, data: StartCallInput) -> TurnApiResult:
    account = await demo_conversation_service.get_or_create_demo_account(session)
    location = await demo_conversation_service.get_or_create_demo_location(
        session, account.account_id
    )
    department = await _get_or_create_department(session, account.account_id, data.department)
    settings = await demo_settings_service.get_settings(session)

    kek = get_local_kek()
    dek = await get_or_create_dek(session, account.account_id, kek=kek)
    pepper = get_core_settings().phone_hash_pepper
    phone_e164 = data.patient_phone or demo_conversation_service.DEMO_PHONE_E164
    phone_hash_bytes = bytes.fromhex(phone_hash(phone_e164, pepper=pepper))

    already_blocked = await session.scalar(
        select(DoNotCall).where(
            DoNotCall.account_id == account.account_id, DoNotCall.phone_hash == phone_hash_bytes
        )
    )
    if already_blocked is not None:
        raise PatientOnDoNotCallError(
            "PFA-DEMO-010", message="This patient has opted out of future calls."
        )

    patient = Patient(
        patient_ref_id=uuid7(),
        account_id=account.account_id,
        external_patient_id=f"demo-{uuid7().hex}",
        phone_hash=phone_hash_bytes,
        phone_e164_enc=encrypt(phone_e164, dek),
        phone_last4=phone_e164[-4:],
        first_name_enc=encrypt(data.patient_first_name, dek),
    )
    session.add(patient)
    await session.flush()

    visit = Visit(
        visit_id=uuid7(),
        account_id=account.account_id,
        location_id=location.location_id,
        patient_ref_id=patient.patient_ref_id,
        department_id=department.department_id,
        external_visit_key=f"demo-{uuid7().hex}",
        visit_date=data.visit_date,
        visit_type=_VISIT_KIND_TO_DB[data.visit_type],
        doctor_name=data.doctor_name,
        patient_age=data.patient_age or 35,
    )
    session.add(visit)
    await session.flush()

    now = datetime.now(UTC)
    call = Call(
        call_id=uuid7(),
        account_id=account.account_id,
        visit_id=visit.visit_id,
        campaign_type=CampaignType.service_feedback,
        attempt_no=1,
        scheduled_at=now,
        started_at=now,
        answered_at=now,
        status=CallStatus.in_progress,
        # Demo-specific, same reasoning as demo_conversation_service.start_call().
        consent_state=ConsentState.granted_unrecorded,
        consent_at=now,
        respondent=RespondentType.unknown,
        languages_used=[],
        turn_count=0,
    )
    session.add(call)
    await session.flush()

    await _emit_call_event(session, call.call_id, "CALL_STARTED", {"provider": data.provider})

    persona = _persona_from_settings(
        settings, first_name=data.patient_first_name, visit_date=data.visit_date, locked_family=None
    )
    result = start_turn(persona)
    state = replace(result.state, visit_kind=_VISIT_KIND_TO_ENGINE[data.visit_type])

    call.state_snapshot = _serialize_state(state)
    await _persist_transcript_turn(
        session, call.call_id, account.account_id, "agent", result.display_text, 0
    )
    await _emit_call_event(session, call.call_id, "AGENT_GREETING", {"text": result.display_text})
    await session.flush()

    return TurnApiResult(
        call_id=call.call_id,
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=state.node.value,
        ended=False,
        call_outcome=None,
        escalated=False,
    )


class VisitNotFoundError(PFANotFoundError):
    pass


async def start_call_from_visit(
    session: AsyncSession, *, visit_id: UUID, provider: str, patient_first_name: str | None
) -> TurnApiResult:
    """PRD v2 Phase 8: starts a call from a visit that already exists — via the existing S1.6 CSV
    ingestion, unmodified — instead of creating a fresh Patient/Visit like `start_call` does.

    Ingested rows never carry a patient name (`REQUIRED_COLUMNS` in `domain/ingestion_csv.py` has
    none — a deliberate data-minimisation choice, not an oversight) — the open_and_identify FIXED
    script needs one regardless, so the caller (the demo operator, who knows who they're calling)
    supplies it here. It's saved onto the patient record the first time, same encrypted-at-rest
    field `start_call` populates, so a second call to the same patient doesn't need it repeated.
    """
    visit = await session.get(Visit, visit_id)
    if visit is None:
        raise VisitNotFoundError("PFA-DEMO-012", message="That visit couldn't be found.")
    patient = await session.get(Patient, visit.patient_ref_id)
    assert patient is not None  # a visit always has a patient row (FK NOT NULL)

    already_blocked = await session.scalar(
        select(DoNotCall).where(
            DoNotCall.account_id == visit.account_id, DoNotCall.phone_hash == patient.phone_hash
        )
    )
    if already_blocked is not None:
        raise PatientOnDoNotCallError(
            "PFA-DEMO-010", message="This patient has opted out of future calls."
        )

    settings = await demo_settings_service.get_settings(session)
    kek = get_local_kek()
    dek = await get_or_create_dek(session, visit.account_id, kek=kek)
    if patient.first_name_enc is not None:
        first_name = decrypt(patient.first_name_enc, dek)
    elif patient_first_name:
        first_name = patient_first_name
        patient.first_name_enc = encrypt(patient_first_name, dek)
    else:
        first_name = "Patient"

    # `calls` has a UNIQUE(visit_id, attempt_no) constraint and a CHECK(attempt_no BETWEEN 1 AND
    # 3) (migration 0006, CLAUDE.md's "max 2 retries" rule) — unlike `start_call`, which always
    # creates a brand-new Visit and so never collides, this reuses the same Visit every time, so a
    # second demo call for it needs the next attempt number, not a hardcoded 1.
    existing_attempts = await session.scalar(
        select(func.max(Call.attempt_no)).where(Call.visit_id == visit.visit_id)
    )
    next_attempt_no = (existing_attempts or 0) + 1
    if next_attempt_no > 3:
        raise PFAValidationError(
            "PFA-DEMO-013", message="This visit has already had the maximum of 3 call attempts."
        )

    now = datetime.now(UTC)
    call = Call(
        call_id=uuid7(),
        account_id=visit.account_id,
        visit_id=visit.visit_id,
        campaign_type=CampaignType.service_feedback,
        attempt_no=next_attempt_no,
        scheduled_at=now,
        started_at=now,
        answered_at=now,
        status=CallStatus.in_progress,
        consent_state=ConsentState.granted_unrecorded,
        consent_at=now,
        respondent=RespondentType.unknown,
        languages_used=[],
        turn_count=0,
    )
    session.add(call)
    await session.flush()

    await _emit_call_event(
        session, call.call_id, "CALL_STARTED", {"provider": provider, "source": "csv_ingestion"}
    )

    persona = _persona_from_settings(
        settings, first_name=first_name, visit_date=visit.visit_date, locked_family=None
    )
    result = start_turn(persona)
    state = replace(result.state, visit_kind=_DB_VISIT_TYPE_TO_ENGINE[visit.visit_type])

    call.state_snapshot = _serialize_state(state)
    await _persist_transcript_turn(
        session, call.call_id, visit.account_id, "agent", result.display_text, 0
    )
    await _emit_call_event(session, call.call_id, "AGENT_GREETING", {"text": result.display_text})
    await session.flush()

    return TurnApiResult(
        call_id=call.call_id,
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=state.node.value,
        ended=False,
        call_outcome=None,
        escalated=False,
    )


async def load_history(session: AsyncSession, call: Call) -> list[tuple[str, str]]:
    rows = list(
        (
            await session.scalars(
                select(Transcript)
                .where(Transcript.call_id == call.call_id)
                .order_by(Transcript.turn_index)
            )
        ).all()
    )
    if not rows:
        return []
    kek = get_local_kek()
    dek = await get_or_create_dek(session, call.account_id, kek=kek)
    return [(row.speaker.value, decrypt(row.text_enc, dek)) for row in rows]


async def submit_turn(
    session: AsyncSession,
    registry: AdapterRegistry[LLMAdapter],
    call_id: UUID,
    provider: str,
    event_kind: Literal["utterance", "silence", "stt_error"],
    text: str | None,
) -> TurnApiResult:
    call = await session.get(Call, call_id)
    if call is None:
        raise DemoCallNotFoundError("PFA-DEMO-006", message="Demo call not found.")
    if call.status != CallStatus.in_progress:
        raise DemoCallAlreadyEndedError("PFA-DEMO-007", message="This demo call has already ended.")
    if not registry.has(provider):
        # Checked here, before any processing, same rationale as demo_conversation_service's own
        # submit_turn: a missing key is a setup problem, not a transient runtime failure, so it
        # doesn't belong in _call_node_llm's retry/fallback path.
        raise demo_conversation_service.DemoProviderNotConfiguredError(
            "PFA-DEMO-008",
            message=(
                f"{provider} isn't configured yet. Save and test a working API key for it in "
                "Settings, then try again."
            ),
        )

    settings = await demo_settings_service.get_settings(session)
    visit = await session.get(Visit, call.visit_id)
    assert visit is not None  # a call always has the visit created alongside it in start_call
    patient = await session.get(Patient, visit.patient_ref_id)
    assert patient is not None

    # `open_and_identify`'s FIXED script (which needs {first_name}) isn't limited to the very
    # first turn — an illegal `proposed_next` self-loops the state right back onto it, confirmed
    # live against the real Gemini API (it hallucinated a non-existent node name on turn 2 of a
    # real call). Decrypting the name every turn, not just at start_call, is the only correct fix.
    first_name = ""
    if patient.first_name_enc is not None:
        kek = get_local_kek()
        dek = await get_or_create_dek(session, call.account_id, kek=kek)
        first_name = decrypt(patient.first_name_enc, dek)

    state = deserialize_state(call.state_snapshot or {})
    persona = _persona_from_settings(
        settings,
        first_name=first_name,
        visit_date=visit.visit_date,
        locked_family=state.language.locked,
    )

    history = await load_history(session, call)
    next_index = len(history)
    if event_kind == "utterance":
        await _persist_transcript_turn(
            session, call_id, call.account_id, "patient", text or "", next_index
        )
        await _emit_call_event(session, call_id, "USER_INPUT", {"length": len(text or "")})

    result = await process_turn(
        state=state,
        event_kind=event_kind,
        event_text=text,
        persona=persona,
        history=history,
        registry=registry,
        provider=provider,
    )

    for evt_type, evt_data in result.events:
        await _emit_call_event(session, call_id, evt_type, evt_data)

    await _persist_transcript_turn(
        session, call_id, call.account_id, "agent", result.display_text, next_index + 1
    )

    call.state_snapshot = _serialize_state(result.state)
    call.turn_count = result.state.agent_turns
    locked_value = result.state.language.locked.value if result.state.language.locked else None
    if locked_value and locked_value not in (call.languages_used or []):
        call.languages_used = [*(call.languages_used or []), locked_value]

    escalated = bool(result.state.escalations)
    # Persisted every turn, not only at call-end: a medical/self-harm escalation asks a follow-up
    # question before the call actually ends (module docstring), so waiting for `result.ended`
    # would leave a live emergency sitting unrecorded in the escalations queue until the patient
    # answers that follow-up. `state.escalations` only ever grows, never mutates in place, so
    # diffing against what's already persisted for this call is safe.
    if escalated:
        await _persist_new_escalations(session, call, result.state)

    if result.ended:
        call.status = CallStatus.completed
        call.ended_at = datetime.now(UTC)
        outcome_value = (
            result.state.call_outcome.value if result.state.call_outcome else "completed"
        )
        call.end_reason = outcome_value
        await _emit_call_event(
            session, call_id, "CALL_ENDED", {"outcome": call.end_reason, "escalated": escalated}
        )
        await _finalize_call_records(session, call, visit, result.state)

    await session.flush()

    return TurnApiResult(
        call_id=call_id,
        display_text=result.display_text,
        speech_text=result.speech_text,
        speech_lang=result.speech_lang,
        node=result.state.node.value,
        ended=result.ended,
        call_outcome=result.state.call_outcome.value if result.state.call_outcome else None,
        escalated=escalated,
    )


async def _persist_new_escalations(session: AsyncSession, call: Call, state: CallState) -> None:
    """Persists every escalation in `state.escalations` beyond what's already in the DB for this
    call — called every turn an escalation is present (not just at call-end), so a live medical/
    self-harm handoff is visible in the escalations queue immediately, not delayed until the call
    actually finishes (see the note at its call site).

    `complaint_id`/`case_id` are deliberately left NULL here — linking to the eventual `Complaint`/
    `Case` row would need those to already exist, but complaints aren't finalized until
    `_finalize_call_records` at call-end. `handoff_json` already carries everything a human
    reviewer needs (category, severity, language, respondent type) without that join; a Demo MVP
    simplification, not a safety gap (the escalation itself is never delayed or dropped).
    """
    already_persisted = await session.scalar(
        select(func.count()).select_from(PfaEscalation).where(PfaEscalation.call_id == call.call_id)
    )
    new_escalations = state.escalations[already_persisted or 0 :]
    for escalation in new_escalations:
        session.add(
            PfaEscalation(
                id=uuid7(),
                account_id=call.account_id,
                call_id=call.call_id,
                complaint_id=None,
                case_id=None,
                type="urgent" if escalation.severity == Severity.s4 else "standard",
                category=str(escalation.category),
                triggered_by=escalation.triggered_by,
                handoff_json={
                    "call_id": str(call.call_id),
                    "severity": escalation.severity.value,
                    "category": str(escalation.category),
                    "triggered_by": escalation.triggered_by,
                    "language_mode": state.language.locked.value if state.language.locked else None,
                    "respondent_type": state.respondent_type.value,
                },
            )
        )
    await session.flush()


async def _finalize_call_records(
    session: AsyncSession, call: Call, visit: Visit, state: CallState
) -> None:
    """Runs once, when a call ends: turns the final `CallState` into the tracked records the
    product actually cares about (CLAUDE.md: "the case workflow is the product") — a `Complaint`
    row per complaint, a `Case` for anything S3+, do-not-call on opt-out, and a callback record
    when the call ended in one. Escalations are persisted separately, per turn — see
    `_persist_new_escalations`.
    """
    if state.do_not_call:
        patient = await session.get(Patient, visit.patient_ref_id)
        if patient is not None:
            session.add(
                DoNotCall(
                    id=uuid7(),
                    account_id=call.account_id,
                    phone_hash=patient.phone_hash,
                    source_call_id=call.call_id,
                )
            )

    if state.call_outcome == CallOutcome.callback:
        reason = "wants_human" if state.wants_human else "busy"
        session.add(
            Callback(
                id=uuid7(), account_id=call.account_id, call_id=call.call_id, reason=reason
            )
        )

    kek = get_local_kek()
    dek = await get_or_create_dek(session, call.account_id, kek=kek)
    for draft in state.complaints:
        complaint_id = uuid7()
        severity_val = draft.severity or Severity.s2
        session.add(
            Complaint(
                complaint_id=complaint_id,
                account_id=call.account_id,
                call_id=call.call_id,
                visit_id=visit.visit_id,
                reason_codes=[draft.category.value],
                sentiment=Sentiment.negative,
                sentiment_conf=0.8,
                urgency=severity.severity_to_urgency(severity_val),
                urgency_conf=0.8,
                urgency_source="llm",
                summary=draft.description[:500],
                verbatim_enc=encrypt(draft.verbatim or draft.description, dek),
                verbatim_start_ms=0,
                verbatim_end_ms=1,
                retention_until=datetime.now(UTC) + timedelta(days=30),
                when_text=draft.when_text,
                where_text=draft.where_text,
                wants_contact=draft.wants_contact,
                preferred_time=draft.preferred_time,
                staff_name=draft.staff_name,
                triggered_by=None,
            )
        )
        # Flushed immediately so the Case insert right below sees a real, committed-in-transaction
        # complaint_id to reference — deferring both to one flush at the end of the loop let the
        # session batch them in an order that tripped the FK constraint in practice.
        await session.flush()

        if severity_val in _SEVERITY_TO_PRIORITY:
            case_id = uuid7()
            ack_hours = _ACK_SLA_HOURS[severity_val]
            session.add(
                Case(
                    case_id=case_id,
                    account_id=call.account_id,
                    complaint_id=complaint_id,
                    location_id=visit.location_id,
                    department_id=visit.department_id,
                    status=CaseStatus.open,
                    priority=_SEVERITY_TO_PRIORITY[severity_val],
                    ack_due_at=datetime.now(UTC) + timedelta(hours=ack_hours),
                )
            )
            session.add(
                CaseEvent(
                    event_id=uuid7(),
                    case_id=case_id,
                    actor_type="system",
                    to_status=CaseStatus.open,
                    action="created_from_call",
                    note=f"Auto-created from call {call.call_id} (severity {severity_val.value}).",
                )
            )

    await session.flush()


async def end_call(session: AsyncSession, call_id: UUID) -> None:
    call = await session.get(Call, call_id)
    if call is None:
        raise DemoCallNotFoundError("PFA-DEMO-006", message="Demo call not found.")
    if call.status == CallStatus.in_progress:
        state = deserialize_state(call.state_snapshot or {})
        state = replace(state, ended=True, call_outcome=state.call_outcome or CallOutcome.abandoned)
        call.status = CallStatus.completed
        call.ended_at = datetime.now(UTC)
        call.end_reason = "manually_ended"
        call.state_snapshot = _serialize_state(state)
        await _emit_call_event(session, call_id, "CALL_ENDED", {"reason": "manually_ended"})
        visit = await session.get(Visit, call.visit_id)
        if visit is not None:
            await _finalize_call_records(session, call, visit, state)
        await session.flush()
