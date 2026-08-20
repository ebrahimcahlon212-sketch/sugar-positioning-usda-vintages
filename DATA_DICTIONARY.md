# Data dictionary

## `data/derived/positioning_releases.csv`

Grain: one Sugar No. 11 CFTC release, ordered by public eligibility.

| Field | Meaning |
|---|---|
| `report_date` | CFTC position observation date, ISO date |
| `available_at_utc` | verified, scheduled, correction-aware or explicitly modelled publication boundary, normalized to UTC |
| `availability_basis` | exact provenance class for the timing boundary; ordinary unverified rows remain visibly rule-modelled |
| `managed_money_*_contracts` | futures-only managed-money long, short and derived net contract counts |
| `open_interest_contracts` | total futures-only open interest used as denominator |
| `normalized_net` | `(long - short) / open interest`, unrounded decimal export |
| `prior_release_count` | number of strictly earlier eligible releases |
| `prior_q10` | expanding, prior-only empirical nearest-rank Q10; blank before 156 prior releases |
| `previous_normalized_net` | immediately prior eligible normalized-net value |
| `previous_was_q10_extreme` | whether the prior value was at/below the current prior-only Q10 |
| `positive_reversal` | whether current normalized net exceeded the previous value |
| `cooldown_eligible` | whether 91 elapsed days had passed since the last emitted event |
| `signal_emitted` | conjunction of the frozen event conditions |
| `source_*` | exact selected-history source identity, URL and public-extract checksum |

## `data/derived/wasde_sugar_vintages.csv`

Grain: one artifact version × region × market year × attribute.

| Field | Meaning |
|---|---|
| `vintage_id` | source version plus content-hash prefix; immutable artifact identity |
| `wasde_number` | official issue number |
| `report_date` / `report_label` | official release date and source month label |
| `effective_at_utc` | official noon ET report release in UTC |
| `available_at_utc` | conservative structured-artifact eligibility boundary |
| `retrieved_at_utc` | acquisition timestamp for the exact bytes |
| `source_version` | e.g. `WASDE-672-V2` |
| `is_corrected_repost` | whether the linked artifact is explicitly version 2 |
| `region` | exact `United States` or `Mexico` source label |
| `market_year` | exact source marketing-year label |
| `projection_status` | blank, `Est.` or `Proj.` as reported |
| `attribute` | exact USDA row label |
| `raw_value` | original structured-source value string |
| `value` | parsed deterministic decimal; no cross-region unit pooling |
| `raw_unit` | original USDA unit string |
| `normalized_unit` | raw physical unit, except ratio rows explicitly normalized to `Percent` |
| `unit_warning` | nonblank on the USDA Stocks to Use Ratio unit anomaly |
| `source_*` | exact artifact identity, URL and public-extract checksum |

## `data/derived/wasde_sugar_revisions.csv`

Grain: one current fact with an immediately prior eligible matching fact. `revision = value -
prior_value`. Matching requires identical region, market year, attribute and normalized unit.

## `data/source_manifest.csv`

Grain: one immutable public extract. It records available upstream metadata, public-extract byte
counts/hashes, source/effective/available/retrieved times, corrections, and the rights-minimal
extraction method. Multi-page timing ledgers retain row-level official URLs rather than volatile
HTML bodies. The manifest is the audit boundary for all derived outputs.
