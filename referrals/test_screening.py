"""Screening heuristics (task #479).

The junk tokens below are verbatim from referral request 26-0727, and the
clean payloads are verbatim from 26-0727-2 (Tina) and 26-0722 (Maloney).
Real data is the whole point: a synthetic test would not have caught that
the originally-specified vowel-ratio rule flags "Pittsburgh".
"""

import pytest

from referrals import screening

JUNK_TOKENS = [
    "LEIAZKMKtfUBswyJuaS",
    "IzNydkEnQFrKxxKl",
    "lfNxcMPRAZNciaxtfNPOMQK",
    "iIcIlrhZIIwEImoxJld",
    "GtDlqAgHoujeYbXggDwPs",
]

# Every one of these must screen clean. Pittsburgh and they/them are here
# specifically because the rejected vowel-ratio rule flagged both.
CLEAN_TOKENS = [
    "Pittsburgh", "Edmonton", "English", "Spanish", "Frankfurt",
    "Bydgoszcz", "MacDonald", "McCann", "they/them", "she/her",
    "San Antonio Texas", "Edmonton, Alberta, Canada",
]

JUNK_PAYLOAD = {
    "name": "LEIAZKMKtfUBswyJuaS",
    "pronouns": "IzNydkEnQFrKxxKl",
    "email": "lauren_michele2005@hotmail.com",
    "location": "lfNxcMPRAZNciaxtfNPOMQK",
    "language": "iIcIlrhZIIwEImoxJld",
    "modality": "In person, By phone, By online video platform",
    "additional_information": "GtDlqAgHoujeYbXggDwPs",
}

CLEAN_PAYLOAD = {
    "name": "Tina",
    "pronouns": "she/her",
    "email": "tina@example.com",
    "location": "San Antonio Texas",
    "language": "English",
    "modality": "By online video platform",
    "additional_information": (
        "I am 58 years old and currently the primary caregiver for my 83 "
        "year old father, who has dementia. We had a difficult childhood, "
        "and caring for him has brought many unresolved emotions to the "
        "surface. I am looking for a therapist who can help me process "
        "those feelings and develop healthy tools for navigating this "
        "stage of my life."
    ),
}


@pytest.mark.parametrize("token", JUNK_TOKENS)
def test_junk_tokens_are_gibberish(token):
    assert screening.looks_like_gibberish(token) is True


@pytest.mark.parametrize("token", CLEAN_TOKENS)
def test_real_values_are_not_gibberish(token):
    assert screening.looks_like_gibberish(token) is False


def test_short_tokens_are_never_gibberish():
    # Below the length floor, even with many case transitions.
    assert screening.looks_like_gibberish("aBcDeF") is False


def test_non_alpha_tokens_are_never_screened():
    # The isalpha gate is what keeps "they/them" and hyphenated names out.
    assert screening.looks_like_gibberish("aBcDeFgHiJ/kL") is False


def test_case_transitions_counts_adjacent_changes():
    assert screening.count_case_transitions("Edmonton") == 1
    assert screening.count_case_transitions("MacDonald") == 3
    assert screening.count_case_transitions("LEIAZKMKtfUBswyJuaS") == 6


def test_junk_payload_is_held():
    assert screening.screen(JUNK_PAYLOAD) != ""


def test_clean_payload_screens_clean():
    assert screening.screen(CLEAN_PAYLOAD) == ""


def test_short_narrative_is_held():
    data = dict(CLEAN_PAYLOAD, additional_information="Need help.")
    assert "short" in screening.screen(data).lower()


def test_url_in_narrative_is_held():
    data = dict(
        CLEAN_PAYLOAD,
        additional_information=(
            "Great deals at http://spam.example.com, click now! " * 3
        ),
    )
    assert "link" in screening.screen(data).lower()


def test_url_in_short_field_is_held():
    data = dict(CLEAN_PAYLOAD, location="www.spam.example.com")
    assert "link" in screening.screen(data).lower()


def test_reason_names_the_field():
    # screen() returns on the first hit, and SCREENED_SHORT_FIELDS puts
    # "name" first — so the reason names that field, not a later one.
    assert "name" in screening.screen(JUNK_PAYLOAD)


def test_missing_keys_do_not_crash():
    assert screening.screen({}) != ""
