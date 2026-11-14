"""
The user's trade-offs (2026-11-14), checked at the default scoring parameters on the example, the input the scoring
docs use (ADR 0039). Each test is a rule the defaults were chosen to keep; one that fails means the defaults (or the
scoring) no longer keep it. The costs are tools/tune.py's unit trade-offs: one event of each kind, for an average
worker and an average shift.
"""
from typing import Any

import pytest

import tune


@pytest.fixture(scope="module")
def tradeoffs() -> dict[str, Any]:
    """The default parameters' unit trade-offs on the example."""
    return tune.unit_tradeoffs(tune.DEFAULTS)


def test_an_avoidable_gap_of_two_shifts_outweighs_three_pairings(tradeoffs: dict[str, Any]) -> None:
    # "a 2-2-4 distribution is an outrage and cannot be made up for with a liked worker"
    assert tradeoffs["outrage_outweighs_pairings"]


def test_an_avoidable_gap_of_two_shifts_outweighs_one_worker_resting_at_the_minimum_twice(
        tradeoffs: dict[str, Any]) -> None:
    # "one worker resting at a minimum is acceptable, 2-2-4 is virtually never acceptable"
    assert tradeoffs["outrage_outweighs_twice_at_minimum"]


def test_a_pairing_cannot_make_up_for_a_second_short_rest(tradeoffs: dict[str, Any]) -> None:
    # a like or dislike justifies "getting screwed over once", but "shouldn't be a persistent punishment"
    assert tradeoffs["second_short_rest_outweighs_pairing"]


def test_a_like_is_worth_about_one_short_rest(tradeoffs: dict[str, Any]) -> None:
    # a like: "I would be okay with doing an earlier shift to be posted with them", one shift sooner
    assert tradeoffs["like_about_one_short_rest"]


def test_a_dislike_outweighs_a_like(tradeoffs: dict[str, Any]) -> None:
    # so that sharing a shift is a net cost when one of the two likes the other and the other dislikes them (ADR 0023)
    assert tradeoffs["dislike"] > tradeoffs["like"]
