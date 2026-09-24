from app.domain.password_policy import validate


def test_short_password_rejected() -> None:
    result = validate("Short1!")
    assert not result.ok
    assert any("12 characters" in r for r in result.reasons)


def test_weak_but_long_password_rejected() -> None:
    result = validate("aaaaaaaaaaaaaaaaaaaa")  # 20 chars, trivially guessable
    assert not result.ok
    assert any("weak" in r for r in result.reasons)


def test_strong_password_accepted() -> None:
    result = validate("Xk9#mQ2vR8$pL4wZ")
    assert result.ok
    assert result.reasons == ()


def test_length_boundary_exactly_12_can_pass_if_strong_enough() -> None:
    result = validate("Xk9#mQ2vR8$p")  # exactly 12 chars
    assert len(result.reasons) == 0 or "12 characters" not in result.reasons[0]
