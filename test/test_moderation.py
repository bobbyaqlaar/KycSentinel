"""test/test_moderation.py — the tenant's output classifier (SEC-MOD-001).

Declared in tenant.yaml, so the framework runtime auto-registers it and the
security harness verifies it (framework G10). These tests cover the policy
it enforces; the harness only checks the contract.
"""

from __future__ import annotations

import pytest

from agents.moderation import classify_output


@pytest.mark.parametrize(
    "text",
    [
        "Rating LOW: no sanctions hits, complete source of funds. Basis: [policy-005]",
        "Rating HIGH: 1 sanctions hit against Al-Noor Trading Company [policy-003]",
        "Applicant is a Swiss national operating an agritech exporter.",  # mention != justification
    ],
)
def test_allows_clean_rationales(text):
    assert classify_output(text).allowed is True


def test_blocks_emirates_id_in_output():
    """The input guardrail scrubs prompts; this is the symmetric check that a
    model did not reconstruct PII into the rationale a reviewer will read."""
    result = classify_output("Verified against Emirates ID 784-1985-1234567-1.")
    assert result.allowed is False
    assert "pii_emirates_id_in_output" in result.reasons


def test_blocks_card_number_in_output():
    result = classify_output("Payment instrument 4111 1111 1111 1111 on file.")
    assert result.allowed is False
    assert "pii_card_in_output" in result.reasons


@pytest.mark.parametrize(
    "text",
    [
        "Rating HIGH because of the applicant's nationality.",
        "Elevated risk due to gender of the beneficial owner.",
        "MEDIUM based on the applicant's religion.",
    ],
)
def test_blocks_protected_attribute_justification(text):
    """policy-007: a rationale that justifies a rating with a protected
    attribute is a fairness breach even when the rating itself is right."""
    result = classify_output(text)
    assert result.allowed is False
    assert "protected_attribute_justification" in result.reasons


def test_short_digit_strings_are_not_cards():
    assert classify_output("Reference number 12345678 filed.").allowed is True


def test_long_non_luhn_digit_runs_are_not_cards():
    """Regression: the hand-rolled card regex here matched any 13-19 digit run
    with no Luhn check, so a registry filing reference was blocked as a leaked
    card while the pre-call input guardrail — which does check Luhn — left the
    identical digits alone. Two symmetric PII controls disagreeing about what
    PII *is* is the exact failure runtime/luhn.py exists to prevent. This hook
    now asks runtime.input_guardrail.detect_pii instead of re-deriving it."""
    text = "Registry filing 2024 0918 3345 1207 66 shows no adverse record."
    result = classify_output(text)
    assert result.allowed is True, result.reasons

    from runtime.input_guardrail import detect_pii

    assert "card" not in detect_pii(text)


def test_output_check_agrees_with_the_pre_call_guard():
    """The two directions must classify the same text identically."""
    from runtime.input_guardrail import detect_pii, scrub_text

    text = "Emirates ID 784-1985-1234567-1 and card 4111 1111 1111 1111."
    scrubbed, scrub_counts = scrub_text(text, mode="default")

    assert set(detect_pii(text)) == set(scrub_counts)
    assert "784-1985" not in scrubbed and "4111 1111" not in scrubbed
    reasons = classify_output(text).reasons
    assert "pii_emirates_id_in_output" in reasons
    assert "pii_card_in_output" in reasons


def test_never_raises_on_odd_input():
    """A classifier that throws would take the LLM call down with it."""
    for text in ("", "   ", "🙂" * 50, "-" * 500):
        assert classify_output(text) is not None
