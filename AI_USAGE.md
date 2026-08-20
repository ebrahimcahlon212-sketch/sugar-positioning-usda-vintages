# AI usage

AI accelerated the workflow; it did not supply market observations.

## Where AI helped

- mapping official public CFTC and USDA sources;
- scaffolding parsers, validation tests, documentation and Power BI source definitions;
- proposing the report layout and concise explanatory language;
- reviewing timing, correction, unit, licensing and look-ahead failure modes; and
- checking that observations, interpretation and limitations remain separate.

## What remained deterministic

- source downloads, selected-field extraction and SHA-256 hashes;
- managed-money net and open-interest normalization;
- expanding prior-only nearest-rank thresholds and elapsed-day cooldowns;
- configured as-of filtering, CFTC publication-boundary handling and USDA point-in-time eligibility;
- raw/normalized unit handling;
- vintage matching, revision arithmetic and the July-to-August balance bridge;
- report-ready CSV/JSON bytes; and
- all integrity and regression tests.

Those operations are implemented in Python or Power BI model expressions. The language model did
not invent, interpolate or approve a CFTC/USDA value. Official source artifacts are the evidence of
record, and tests fail if inputs, timing rules, hashes or expected derived facts diverge.

The model suggested hypotheses and presentation choices. The rule itself was frozen in the public
cocoa repository at
[commit `20f1e81`](https://github.com/ebrahimcahlon212-sketch/cocoa-positioning-regime-study/commit/20f1e81afdccc7323af72f8c979da490c97ab21f)
(2026-08-20 14:09:06 UTC), before Sugar numbers were acquired (15:50:03 UTC), and was not retuned
in response to its output. An independent check confirmed 21-of-21 event-row parity. No model
decides, routes or executes a trade.
