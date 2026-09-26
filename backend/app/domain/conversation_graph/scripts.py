"""FIXED-line loader + renderer (PRD v2 §7.3). Every FIXED line in the graph comes from here, never
from the LLM. Resolves gendered verb tokens first (`{bol_rahi}` etc., from the persona's voice
gender), then the caller's own placeholders (`{hospital}`, `{agent}`, `{first_name}`, ...).

`ScriptForm` picks roman Hinglish vs Devanagari for the Hindi/Hinglish family (the account's
`tts_script` setting — PRD §10), or the English variant when the locked language is English. Same
"static asset read is still functionally pure" reasoning as `safety.py`.
"""

from __future__ import annotations

import enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

from app.domain.conversation_language import LanguageFamily

_ASSETS_DIR = Path(__file__).parent / "assets"

Gender = Literal["female", "male"]


class ScriptForm(enum.StrEnum):
    roman = "roman"
    devanagari = "deva"


@lru_cache(maxsize=1)
def _loaded() -> tuple[dict[str, dict[str, dict[str, str]]], dict[str, dict[str, str]]]:
    raw = yaml.safe_load((_ASSETS_DIR / "scripts.yaml").read_text(encoding="utf-8"))
    return raw["tokens"], raw["scripts"]


def _form_key(language: LanguageFamily, script: ScriptForm) -> str:
    return "english" if language == LanguageFamily.english else script.value


def render_script(
    key: str,
    *,
    gender: Gender,
    language: LanguageFamily,
    script: ScriptForm = ScriptForm.devanagari,
    **placeholders: str,
) -> str:
    tokens, scripts = _loaded()
    if key not in scripts:
        raise KeyError(f"unknown script key {key!r}")
    form_key = _form_key(language, script)
    template = scripts[key][form_key]

    if form_key != "english":
        gender_tokens = {
            name: variants[form_key] for name, variants in tokens.get(gender, {}).items()
        }
        stubs = _safe_placeholder_stubs(template, gender_tokens)
        template = template.format(**gender_tokens, **stubs)

    return template.format(**placeholders)


def _safe_placeholder_stubs(template: str, already_resolved: dict[str, str]) -> dict[str, str]:
    """`template.format` requires every `{token}` in the string to have a value in one call, but
    gender tokens and caller placeholders (hospital/agent/first_name/...) are resolved in two
    separate passes — this returns a no-op stub (`"{name}"` -> itself) for every placeholder that
    ISN'T a gender token, so the first `.format()` call only touches gender tokens and leaves the
    rest untouched for the second call.
    """
    import string

    names = {
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name and field_name not in already_resolved
    }
    return {name: f"{{{name}}}" for name in names}
