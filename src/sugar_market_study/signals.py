"""Frozen, prior-only CFTC positioning rule transferred unchanged from cocoa."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Final

MIN_PRIOR_RELEASES: Final = 156
Q10: Final = Decimal("0.10")
SIGNAL_COOLDOWN: Final = timedelta(days=91)
SIGNAL_RULE_ID: Final = "cftc_normalized_net_q10_reversal_v1"


@dataclass(frozen=True, slots=True)
class PositioningRelease:
    """One publication-aware disaggregated futures-only COT observation."""

    report_date: date
    available_at_utc: datetime
    managed_money_long_contracts: int
    managed_money_short_contracts: int
    open_interest_contracts: int
    availability_basis: str
    source_id: str
    source_url: str
    source_sha256: str
    market_name: str
    cftc_contract_market_code: str

    def __post_init__(self) -> None:
        if self.available_at_utc.tzinfo is None or self.available_at_utc.utcoffset() is None:
            raise ValueError("available_at_utc must be timezone-aware")
        object.__setattr__(self, "available_at_utc", self.available_at_utc.astimezone(UTC))
        if self.open_interest_contracts <= 0:
            raise ValueError("open interest must be positive")
        if self.managed_money_long_contracts < 0 or self.managed_money_short_contracts < 0:
            raise ValueError("managed-money positions cannot be negative")
        if abs(self.managed_money_net_contracts) > self.open_interest_contracts:
            raise ValueError("absolute managed-money net cannot exceed open interest")

    @property
    def managed_money_net_contracts(self) -> int:
        return self.managed_money_long_contracts - self.managed_money_short_contracts

    @property
    def normalized_net(self) -> Decimal:
        """Managed-money net divided by total open interest."""

        return Decimal(self.managed_money_net_contracts) / Decimal(self.open_interest_contracts)


@dataclass(frozen=True, slots=True)
class PositioningEvaluation:
    """Frozen-rule fields for one release; early rows remain explicitly ineligible."""

    prior_release_count: int
    prior_q10: Decimal | None
    previous_normalized_net: Decimal | None
    previous_was_q10_extreme: bool | None
    positive_reversal: bool | None
    cooldown_eligible: bool | None
    signal_emitted: bool


def empirical_nearest_rank(values: Sequence[Decimal], quantile: Decimal) -> Decimal:
    """Return the empirical nearest-rank quantile without interpolation."""

    if not values:
        raise ValueError("at least one value is required")
    if not Decimal(0) < quantile <= Decimal(1):
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    rank = int((Decimal(len(ordered)) * quantile).to_integral_value(rounding=ROUND_CEILING))
    return ordered[max(rank, 1) - 1]


def evaluate_releases(
    releases: Iterable[PositioningRelease],
) -> tuple[tuple[PositioningRelease, PositioningEvaluation], ...]:
    """Evaluate the expanding prior-only Q10 reversal and elapsed-day cooldown.

    For release ``t``, the threshold uses only releases with strictly earlier
    public-availability timestamps. A signal requires at least 156 prior releases,
    the immediately previous normalized net at or below that threshold, and a current
    increase. Emitted signals then impose a 91 elapsed-day cooldown.
    """

    ordered = tuple(sorted(releases, key=lambda item: item.available_at_utc))
    if not ordered:
        return ()
    timestamps = [item.available_at_utc for item in ordered]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("CFTC releases must have unique availability timestamps")
    dates = [item.report_date for item in ordered]
    if len(dates) != len(set(dates)):
        raise ValueError("CFTC releases must have unique report dates")

    normalized = tuple(item.normalized_net for item in ordered)
    output: list[tuple[PositioningRelease, PositioningEvaluation]] = []
    last_signal_at: datetime | None = None
    for index, release in enumerate(ordered):
        if index < MIN_PRIOR_RELEASES:
            output.append(
                (
                    release,
                    PositioningEvaluation(
                        prior_release_count=index,
                        prior_q10=None,
                        previous_normalized_net=None,
                        previous_was_q10_extreme=None,
                        positive_reversal=None,
                        cooldown_eligible=None,
                        signal_emitted=False,
                    ),
                )
            )
            continue

        threshold = empirical_nearest_rank(normalized[:index], Q10)
        previous = normalized[index - 1]
        current = normalized[index]
        was_extreme = previous <= threshold
        reversed_positive = current > previous
        cooldown_eligible = (
            last_signal_at is None or release.available_at_utc - last_signal_at >= SIGNAL_COOLDOWN
        )
        emitted = was_extreme and reversed_positive and cooldown_eligible
        if emitted:
            last_signal_at = release.available_at_utc
        output.append(
            (
                release,
                PositioningEvaluation(
                    prior_release_count=index,
                    prior_q10=threshold,
                    previous_normalized_net=previous,
                    previous_was_q10_extreme=was_extreme,
                    positive_reversal=reversed_positive,
                    cooldown_eligible=cooldown_eligible,
                    signal_emitted=emitted,
                ),
            )
        )
    return tuple(output)
