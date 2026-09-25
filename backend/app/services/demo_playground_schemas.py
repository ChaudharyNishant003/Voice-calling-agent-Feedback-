"""Structured LLM contracts for the Playground's four model-backed pipeline stages — deliberately
narrower than `demo_llm_schema.DemoTurnResponse`: each one asks a model to do exactly one job, so
stages can be compared/optimized independently. Reuses that module's `Topic`/`DetectedLanguage`/
`NextAction` Literal aliases rather than redefining them, so the vocabulary always matches the live
call's.

The live call's `DemoTurnResponse` and `demo_conversation_service.py` are untouched by this file —
the Playground is additive, parallel code (see docs/11_BUILD_PLAN.md's Demo MVP section).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.demo_llm_schema import DetectedLanguage, NextAction, Topic


class LanguageDetectionResult(BaseModel):
    detected_language: DetectedLanguage = Field(
        description=(
            "Language family the patient's message was in. Classify by VOCABULARY, not script — "
            "Hindi/Hinglish written in plain Roman letters (e.g. 'theek tha', 'haan', 'accha', "
            "'bahut zyada', 'kya hua') is still 'hi'/'hinglish', never 'en', just because it has "
            "no Devanagari. Only classify as 'en' when the actual words used are English."
        )
    )
    requested_language: Literal["hi", "en"] | None = Field(
        default=None,
        description=(
            "Set ONLY if the patient explicitly asked to switch language "
            "(e.g. 'English mein baat karo', 'please speak in Hindi'). Otherwise null."
        ),
    )


class TopicExtractionResult(BaseModel):
    topics: list[Topic] = Field(
        default_factory=list, description="Feedback topic(s) the patient's message touches on."
    )


class EndJudgmentResult(BaseModel):
    wants_to_end: bool = Field(
        description="True if enough useful feedback has been collected to close the call now."
    )
    summary: str | None = Field(
        default=None, description="One-line summary of the feedback, only set when wants_to_end."
    )


class ResponseGenerationResult(BaseModel):
    response: str = Field(description="What the agent says next — short, natural, one question.")
    next_action: NextAction
