"""Offline regression tests for the frozen cross-commodity signal rule."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sugar_market_study.signals import (
    MIN_PRIOR_RELEASES,
    SIGNAL_RULE_ID,
    PositioningRelease,
    empirical_nearest_rank,
    evaluate_releases,
)


def _release(index: int, net: int, *, available_at: datetime | None = None) -> PositioningRelease:
    timestamp = available_at or datetime(2020, 1, 3, tzinfo=UTC) + timedelta(days=index * 7)
    return PositioningRelease(
        report_date=date(2020, 1, 1) + timedelta(days=index * 7),
        available_at_utc=timestamp,
        managed_money_long_contracts=max(net, 0),
        managed_money_short_contracts=max(-net, 0),
        open_interest_contracts=100,
        availability_basis="synthetic test timing",
        source_id="synthetic",
        source_url="https://example.invalid/synthetic",
        source_sha256="0" * 64,
        market_name="SYNTHETIC SUGAR",
        cftc_contract_market_code="080732",
    )


def test_empirical_quantile_is_nearest_rank_without_interpolation() -> None:
    values = tuple(Decimal(index) for index in range(1, 11))
    assert empirical_nearest_rank(values, Decimal("0.10")) == Decimal(1)
    assert empirical_nearest_rank(values, Decimal("0.25")) == Decimal(3)


def test_threshold_is_prior_only_and_cooldown_uses_elapsed_days() -> None:
    releases = [_release(index, 0) for index in range(MIN_PRIOR_RELEASES - 1)]
    releases.append(_release(MIN_PRIOR_RELEASES - 1, -100))
    releases.append(_release(MIN_PRIOR_RELEASES, -50))
    releases.append(_release(MIN_PRIOR_RELEASES + 1, -40))

    evaluated = evaluate_releases(releases)
    first = evaluated[MIN_PRIOR_RELEASES][1]
    next_week = evaluated[MIN_PRIOR_RELEASES + 1][1]

    assert first.prior_release_count == 156
    assert first.prior_q10 == 0
    assert first.previous_normalized_net == Decimal(-1)
    assert first.signal_emitted is True
    assert next_week.previous_was_q10_extreme is True
    assert next_week.positive_reversal is True
    assert next_week.cooldown_eligible is False
    assert next_week.signal_emitted is False


def test_early_rows_are_retained_but_explicitly_ineligible() -> None:
    evaluated = evaluate_releases(_release(index, index % 3) for index in range(20))
    assert len(evaluated) == 20
    assert SIGNAL_RULE_ID == "cftc_normalized_net_q10_reversal_v1"
    assert all(evaluation.prior_q10 is None for _, evaluation in evaluated)
    assert all(evaluation.signal_emitted is False for _, evaluation in evaluated)
