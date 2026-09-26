"""`domain/conversation_graph/scripts.py` — every script template renders for both genders × 3
forms with no unresolved tokens (PRD v2 §7.3, Phase 2 acceptance check)."""

from __future__ import annotations

import re

import pytest

from app.domain.conversation_graph.scripts import ScriptForm, _loaded, render_script
from app.domain.conversation_language import LanguageFamily

_PLACEHOLDER_STUBS = {
    "hospital": "Apollo Test Hospital",
    "agent": "Riya",
    "first_name": "Ramesh",
    "visit_date_words": "das September",
    "summary": "Waiting zyada thi.",
    "next_step_sentence": "Main yeh team tak bhej rahi hoon.",
    "hospital_phone_sentence": "",
    "hospital_phone_chunks": "ek do teen",
    "sla_words": "chaubees ghante",
    "sla_sentence": "Team chaubees ghante mein sampark karegi.",
    "slot_words": "aaj shaam",
}

_UNRESOLVED_TOKEN = re.compile(r"\{[a-zA-Z_]+\}")


def _all_script_keys() -> list[str]:
    _, scripts = _loaded()
    return list(scripts.keys())


@pytest.mark.parametrize("key", _all_script_keys())
@pytest.mark.parametrize("gender", ["female", "male"])
@pytest.mark.parametrize(
    "language,script",
    [
        (LanguageFamily.hindi_hinglish, ScriptForm.roman),
        (LanguageFamily.hindi_hinglish, ScriptForm.devanagari),
        (LanguageFamily.english, ScriptForm.roman),  # script form is ignored for english
    ],
)
def test_every_template_renders_with_no_unresolved_tokens(
    key: str, gender: str, language: LanguageFamily, script: ScriptForm
) -> None:
    rendered = render_script(
        key, gender=gender, language=language, script=script, **_PLACEHOLDER_STUBS
    )
    assert not _UNRESOLVED_TOKEN.search(
        rendered
    ), f"{key}/{gender}/{language}/{script}: {rendered!r}"
    assert rendered.strip()


def test_gender_actually_changes_the_rendered_text() -> None:
    female = render_script(
        "open_and_identify", gender="female", language=LanguageFamily.hindi_hinglish,
        script=ScriptForm.roman, **_PLACEHOLDER_STUBS,
    )
    male = render_script(
        "open_and_identify", gender="male", language=LanguageFamily.hindi_hinglish,
        script=ScriptForm.roman, **_PLACEHOLDER_STUBS,
    )
    assert female != male
    assert "bol rahi hoon" in female
    assert "bol raha hoon" in male


def test_devanagari_and_roman_forms_differ() -> None:
    roman = render_script(
        "opt_out", gender="female", language=LanguageFamily.hindi_hinglish,
        script=ScriptForm.roman, **_PLACEHOLDER_STUBS,
    )
    deva = render_script(
        "opt_out", gender="female", language=LanguageFamily.hindi_hinglish,
        script=ScriptForm.devanagari, **_PLACEHOLDER_STUBS,
    )
    assert roman != deva


def test_english_form_ignores_gender() -> None:
    female = render_script(
        "close", gender="female", language=LanguageFamily.english, **_PLACEHOLDER_STUBS
    )
    male = render_script(
        "close", gender="male", language=LanguageFamily.english, **_PLACEHOLDER_STUBS
    )
    assert female == male


def test_unknown_key_raises() -> None:
    with pytest.raises(KeyError):
        render_script(
            "not_a_real_key", gender="female", language=LanguageFamily.english, **_PLACEHOLDER_STUBS
        )
