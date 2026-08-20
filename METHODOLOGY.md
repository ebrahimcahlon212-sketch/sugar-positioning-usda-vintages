# Methodology

## Research question

Can a positioning condition specified for another soft commodity be transferred unchanged to
Sugar No. 11, while current physical-balance revisions are tracked with genuine point-in-time
controls and historical CFTC publication uncertainty is made explicit?

The artifact answers a narrower question than a backtest. It identifies positioning events and
shows the public USDA information that was available by each vintage. It does **not** test whether
those events predicted Sugar No. 11 returns.

## Frozen positioning rule

The contract is CFTC market code `080732`, Sugar No. 11, Disaggregated Futures-Only. The primary
sample starts on 1 September 2009, the live-publication-era boundary used by the original cocoa
study. CFTC release 5710-09 confirms that the first 22-market Disaggregated report was published
on 4 September for positions dated 1 September; the official Agriculture page includes Sugar
No. 11 (`080732`). Earlier backcast classifications are excluded from the primary calculation.

For each report release `t`:

```text
x_t = (managed_money_long_t - managed_money_short_t) / total_open_interest_t
```

The rule is applied exactly as transferred:

1. Require at least 156 strictly prior eligible releases.
2. Calculate Q10 from `x_0 ... x_(t-1)` using the empirical nearest-rank method without
   interpolation: rank `ceil(0.10 × n)` in ascending order.
3. Require `x_(t-1) <= Q10_t`.
4. Require a positive reversal, `x_t > x_(t-1)`.
5. Emit only if at least 91 elapsed days have passed since the last emitted event.

The threshold excludes the current observation. The cooldown is measured on timezone-aware
public-availability timestamps, not row counts. The rule was not optimized on sugar, and all early
ineligible rows remain in the export with blank evaluation fields.

The public cocoa rule was frozen at
[commit `20f1e81`](https://github.com/ebrahimcahlon212-sketch/cocoa-positioning-regime-study/commit/20f1e81afdccc7323af72f8c979da490c97ab21f)
on 20 August 2026 at 14:09:06 UTC, before the Sugar numeric extract was acquired at 15:50:03 UTC.
An independent parity check confirmed the same rule implementation produced the same 21 of 21
event rows; no Sugar result was available when the rule was frozen.

## CFTC timing

The CFTC report date is the position observation date, not the publication time. Compact official
evidence ledgers override known historical shutdown, cyber-incident, holiday and correction dates;
retained 2025/26 announcements and schedules also take precedence. The 21 emitted event dates are
individually checked against official weekly Agriculture Disaggregated Futures-Only page `Updated`
footers and the standing 15:30 America/New_York policy.

Elsewhere, an ordinary Friday 15:30 America/New_York release is modelled for a Tuesday report
date; a Monday holiday-shifted observation is modelled for the following Friday. Every export row
identifies whether the boundary is verified, scheduled, correction-aware or rule-modelled. CFTC
does not publish a consolidated historical release-date ledger, so the wider positioning history
is a retrospective, publication-aware timing approximation rather than a strict point-in-time
dataset.

The CFTC selected-field history comes from public dataset `72hh-3qpy`. It is a snapshot retrieved
on the timestamp in the manifest. It is not represented as a complete archive of historical CFTC
corrections or reclassifications. For the known Sugar corrections dated 28 March 2017 and 26 March
2019, current-snapshot values become eligible only at conservative end-of-announcement-day Eastern
boundaries because exact correction times were not stated. The all-market 27 November 2012
correction uses the CFTC's stated 15:30 Eastern publication time.

## USDA WASDE vintage tracker

The acquisition uses exact official links retained from USDA's Historical WASDE Report Data page.
It selects annual rows from two tables without filtering out blank, estimate or projection flags:

- `U.S. Sugar Supply and Use` / `United States`;
- `Mexico Sugar Supply and Use and High Fructose Corn Syrup Consumption` / `Mexico`.

The immutable fact key is:

```text
source artifact version × report title × region × market year × attribute
```

Each fact retains the original value string, source unit, normalized unit, effective report time,
structured-artifact eligibility time, retrieval time, source version, correction flag, official
URL and checksum. New artifact bytes create a new content-addressed record; historical records are
not mutated or deleted.

The tracker covers May 2025 to August 2026. October 2025 is absent because no report was released;
it is not interpolated. Report defaults expose U.S. 2024/25, 2025/26 and 2026/27, plus Mexico
2025/26 and 2026/27, while the long-form table preserves every selected market year in the source.

## Effective time versus availability time

`effective_at_utc` is the official report release (12:00 America/New_York, converted to UTC).
`available_at_utc` governs when the consolidated structured artifact may enter a point-in-time
query. USDA states that the consolidated CSV is updated the day after the report but gives no
exact time, so ordinary files are conservatively eligible only at 23:59:59
America/New_York on the following calendar day, then normalized to UTC.

May and June 2026 are V2 links. May's embedded date is 13 May and sugar values were not the reason
for the correction; it becomes eligible at the conservative end of that embedded date. June V2
corrected sugar and retains the original report date, but USDA gives no exact repost time. It is
therefore eligible only at 23:59:59 America/New_York on 12 June
(`2026-06-13T03:59:59Z`), never at the original 11 June report instant.

These timestamps are conservative eligibility models, not fabricated claims of exact upload time.
If a previously acquired official URL later yields different bytes, the new content is appended
as a new source version and becomes eligible only at its first confirmed retrieval; it is never
backdated from the embedded report date.

## Units and revisions

U.S. physical values retain `1000 Short Tons, Raw Value`; Mexico retains
`1000 Metric Tons, Actual Weight`. They are never pooled or silently converted.

The USDA historical CSV labels `Stocks to Use Ratio` with the U.S. table's tonnage unit even though
the values are ratios. The source string is preserved as `raw_unit`; `normalized_unit` is set to
`Percent`; and a warning is repeated on every affected fact. The pipeline does not recompute or
silently substitute the USDA-reported ratio.

A revision compares a fact with the immediately prior publicly eligible fact having the same
region, market year, attribute and normalized unit. The October gap and market-year entries/exits
remain visible rather than imputed.

## Reproducibility controls

- Network acquisition retains downloaded payloads under ignored `data/external/` when available;
  these files are not distributed and are not required by the offline build. Multi-page CFTC
  verification ledgers retain exact row URLs and audit metadata, not volatile HTML page bodies.
- Public extracts are rights-minimal and content-addressed.
- `data/source_manifest.csv` preserves official URLs, public byte counts/SHA-256 and available
  single-artifact upstream byte counts/SHA-256.
- The offline pipeline verifies every committed extract before parsing.
- Tests block common Python socket calls and never invoke the acquisition script.
- Derived CSV/JSON bytes are generated deterministically and checked against committed outputs.
- Synthetic fixtures and test-only records are plainly labelled synthetic.

## Interpretation boundary

Twenty-one historical positioning events are descriptive outputs of the frozen rule. Without a
licensed tradable price history, a preregistered horizon, transaction costs and robust inference,
they are not evidence of alpha. The August 2026 balance bridge is a source-derived revision, not a
claim about subsequent price direction. There is no order, broker, risk limit or automated action.
