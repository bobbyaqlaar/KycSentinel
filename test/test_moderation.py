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


# ── policy-007: a model names the instance, not the category ─────────────────
#
# The check matched a justifier near a CATEGORY NAME — "because of nationality"
# — and a rationale almost never says that. It says "because the applicant is
# Syrian", "because she is a woman", "because the applicant is Muslim". Every
# one of those passed a control whose entire purpose is to catch them, and the
# demo script says on stage that it catches them.
#
# What it cannot catch is stated in the module: an implication with no
# justifying construction at all ("The applicant is Iranian. Risk is elevated.")
# reads as two facts to a regex. The judge is the control for that; this hook is
# the cheap backstop that must at least catch the explicit form.


@pytest.mark.parametrize(
    "rationale",
    [
        "Rated HIGH because of the applicant nationality.",
        "Rated HIGH because the applicant is Syrian.",
        "Rated HIGH because the applicant holds a Syrian passport.",
        "Rated HIGH because the applicant is Sudanese.",
        "Rated HIGH because he is Emirati.",
        # The explicit -i list. These are not reachable by shape at all, so
        # each one is held by its entry and nothing else.
        "Rated HIGH because the applicant is Saudi.",
        "Rated HIGH because the customer is Pakistani, per the profile.",
        # A following capital does NOT disqualify a listed demonym — the
        # lookahead exists to protect given names, and a list entry is a
        # nationality whatever follows it.
        "Rated HIGH because the applicant is Saudi Arabian.",
        "Rated HIGH because the applicant is Muslim.",
        "Rated HIGH because she is a woman.",
        "Rated HIGH because of the applicant age.",
        "Rated HIGH due to religion.",
        "Elevated based on the client is Iranian.",
    ],
)
def test_a_rating_justified_by_a_protected_attribute_is_blocked(rationale: str) -> None:
    result = classify_output(rationale)
    assert not result.allowed, f"not blocked: {rationale}"
    assert "protected_attribute_justification" in result.reasons


@pytest.mark.parametrize(
    "rationale",
    [
        "Rated HIGH because sanctions screening returned a confirmed match.",
        "Applicant is a Syrian national; sanctions screening returned no match, rated LOW.",
        "Rated HIGH because Al-Noor Trading appeared on the sanctions list.",
        "Rated LOW because the applicant provided complete source-of-funds evidence.",
        "Rated HIGH because adverse media links the applicant to a supplier dispute.",
        "The applicant is Emirati. Rated LOW: no sanctions or adverse media hits.",
        "Rated HIGH because the company is registered in a high-risk jurisdiction.",
        "Rated LOW because the applicant is compliant with all requirements.",
        "Rated HIGH because the applicant is listed on a watchlist.",
        # A protected attribute named as a PROFILE FIELD, with no justifying
        # construction anywhere. Mutation testing found this missing: removing
        # the justifier requirement from the category branch left every other
        # case in this list green, because none of them said "nationality"
        # outside a justification.
        "Applicant nationality is recorded in the profile. Rated LOW: no hits.",
        "Gender and age are captured on the intake form; neither affects scoring.",
        # GIVEN NAMES in the exact position the demonym shape looks at. All of
        # these fit -ian/-ese/-ish/-i and all were blocked before the trailing
        # lookahead: a correct, specific rationale refused because the person
        # was called Ravi. What disqualifies them is the surname that follows.
        "Rated HIGH because the applicant is Ravi Kumar, a listed PEP.",
        "Rated HIGH because the applicant is Levi Stern, a confirmed sanctions match.",
        "Rated HIGH because the applicant is Yuki Tanaka, adverse media confirmed.",
        "Rated HIGH because the applicant is Julian Reyes, adverse media confirmed.",
        # Given names ending in -i, with a COMMA rather than a surname, so the
        # lookahead cannot help. These were blocked until the -i suffix stopped
        # being matched by shape; each is a correct rationale refused because of
        # what the person is called.
        "Rated HIGH because the applicant is Ravi, a listed PEP.",
        "Rated HIGH because the applicant is Heidi, a confirmed sanctions match.",
        "Rated HIGH because the applicant is Naomi, adverse media confirmed.",
        # Held by the `{2,}` bound alone: T + r + ish. The only case here that
        # is, so it is what the bound's mutation has to fail on.
        "Rated HIGH because the applicant is Trish, a listed PEP.",
    ],
)
def test_a_correct_rationale_is_not_blocked(rationale: str) -> None:
    """The half that matters as much. Blocking a correct rationale stops a real
    decision path, so over-reach is not the safe direction — and a KYC rationale
    legitimately states nationality as a profile field. Every case here mentions
    a protected attribute or a demonym WITHOUT justifying the rating by it.
    """
    assert classify_output(rationale).allowed, f"wrongly blocked: {rationale}"


def test_the_demonym_shape_needs_a_capital() -> None:
    """`(?-i:...)` scopes the case-sensitivity off for the demonym alone.

    The compiled pattern is IGNORECASE for the English around it, which would
    otherwise discard the one signal separating a demonym from an ordinary word
    ending in -ian, -ese or -ish.

    The `-i` suffix used to be here too and no longer is: it could not be made
    safe by case, length or lookahead, so it moved to an explicit list. See
    test_the_i_demonyms_are_an_explicit_list.

    The cases below are chosen to DISCRIMINATE. An earlier version used
    "compliant", which fails the suffix either way, so the assertion held with
    the case-sensitivity removed — a test that passed for a reason unrelated to
    what it claimed. Mutation testing is what surfaced that.
    """
    # Lowercase, realistic in a KYC rationale, and matches the suffix: these
    # are wrongly blocked the moment the demonym stops requiring a capital.
    assert classify_output(
        "Rated HIGH because the applicant is multi-national in structure."
    ).allowed
    assert classify_output("Rated LOW because they are semi-retired.").allowed
    # And the capitalised demonym is still caught.
    assert not classify_output("Rated LOW because the applicant is Italian.").allowed


def test_a_demonym_is_disqualified_by_a_following_surname() -> None:
    """The lookahead that keeps given names out, asserted in both directions.

    A capitalised word ending in -ian/-ese/-ish is as often a person as a
    nationality, and it appears in the same position: right after "the applicant
    is". What separates them is what follows — a demonym ends the noun phrase, a
    given name runs on into a surname.

    Both directions are here because the lookahead can fail either way, and the
    failures are not symmetric in cost: a missed rationale is caught downstream
    by the judge, a wrongly blocked one stops a real decision path.
    """
    # Disqualified by the surname — a real rationale that must survive.
    assert classify_output(
        "Rated HIGH because the applicant is Ravi Kumar, a listed PEP."
    ).allowed

    # Nothing following, so the shape stands and the rationale is blocked.
    assert not classify_output("Rated HIGH because the applicant is Syrian.").allowed

    # The lookahead must not swallow an ordinary lowercase continuation. This
    # regressed once already: `[A-Z]` outside the `(?-i:...)` scope matches
    # lowercase under IGNORECASE, so every rationale with a word after the
    # demonym was let through.
    assert not classify_output(
        "Rated HIGH because the applicant is Iranian and the funds are unexplained."
    ).allowed
    assert not classify_output(
        "Rated HIGH because the applicant holds a Syrian passport."
    ).allowed


def test_the_i_demonyms_are_an_explicit_list() -> None:
    """The -i suffix is matched by enumeration, not by shape, and this is why.

    "Saudi" and "Heidi" are the same shape — capital, three lowercase, a bare
    `i`. No case rule, length bound or lookahead separates them, and the comma
    form ("is Ravi, a listed PEP") defeats the lookahead that saves the -ian
    names. Shape matching here means refusing correct rationales because of what
    the applicant is called.

    The cost of the list is bounded recall, asserted below as plainly as the
    hits: an -i demonym that is not an entry is MISSED, and the judge is the
    control for that. This test exists so that the trade is visible to whoever
    edits the list next, rather than being rediscovered.
    """
    # On the list — held by the entry alone, unreachable by shape.
    for rationale in (
        "Rated HIGH because the applicant is Saudi.",
        "Rated HIGH because the applicant is Emirati.",
        "Rated HIGH because the customer is Pakistani.",
        "Rated HIGH because he is Iraqi.",
    ):
        assert not classify_output(rationale).allowed, f"not blocked: {rationale}"

    # Given names of the same shape — the whole reason the list exists.
    for rationale in (
        "Rated HIGH because the applicant is Heidi, a listed PEP.",
        "Rated HIGH because the applicant is Ravi, a listed PEP.",
        "Rated HIGH because the applicant is Naomi, adverse media confirmed.",
    ):
        assert classify_output(rationale).allowed, f"wrongly blocked: {rationale}"

    # THE COST, asserted rather than described: an -i demonym off the list is
    # missed. If this ever starts failing, someone added the entry — delete the
    # line, do not weaken the assertion.
    assert classify_output("Rated HIGH because the applicant is Malawi.").allowed
