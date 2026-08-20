# Power BI validation record

Validated on 20 August 2026 with Power BI Desktop `2.157.879.0`.

## Validated PBIX

- File: `powerbi/SugarNo11.pbix`
- Size: `350,195` bytes
- SHA-256: `902afdb7ee057d40e53214a5c80cf074468bd8a9400e2a0011bc054f263968c0`
- Container check: valid ZIP/PK container; all 25 entries streamed successfully,
  including a `331,500`-byte `DataModel` entry.
- Reopen check: Desktop was closed, the saved PBIX was opened directly from disk, and
  the Desktop bridge reported the PBIX as the current file with no unsaved changes.
- Offline check: both report pages rendered with populated imported data; no refresh,
  credentials, absolute paths, or network access were required.

The reviewed renders are the committed `powerbi/screenshots/decision-lens.png` and
`powerbi/screenshots/audit-sources.png`, so the report can be previewed on GitHub.

## Reopened-model query checks

The reopened PBIX was queried through its local Analysis Services model:

| Check | Result |
| --- | ---: |
| Positioning rows | 885 |
| WASDE vintage rows | 1,170 |
| WASDE revision rows | 1,064 |
| Audit rows | 900 |
| Latest managed-money net | 43,584 |
| Latest net / open interest | 3.9083286% |
| Previous managed-money net | -87,188 |
| Frozen-rule status | NO SIGNAL |
| U.S. 2026/27 stocks/use, July | 13.5% |
| U.S. 2026/27 stocks/use, August | 14.8% |
| Stocks/use move | +1.3 pp |
| Provenance complete | 100% |

## Source bytes embedded by the model

| Input | Rows | SHA-256 |
| --- | ---: | --- |
| `positioning_releases.csv` | 885 | `73fa67f819bd0c8ee820e3c8cec0b7541cff74584ece754e8f1883b4e4eab613` |
| `wasde_sugar_vintages.csv` | 1,170 | `c5c4433456c57f9fd69df89e5a86e84b0396ad0d69f3c397348f2eb05fedbb0c` |
| `wasde_sugar_revisions.csv` | 1,064 | `858c28ab7c2ccf2d2c368df32dce27fbb4eefacae3c0d1adfc4ddb706428dea5` |

The generated Power Query partitions carry deterministic raw-CSV Base64 payloads.
`data_manifest.json` records both input and embedded-payload hashes.

## Definition and build checks

- Repository test suite: 28 passed. Its 11 Power BI artifact tests include two
  consecutive builds with byte-equal PBIP/PBIR/TMDL output, plus PBIX container and
  pinned-hash checks.
- Ruff: clean.
- Mypy strict mode: clean.
- Microsoft's `powerbi-report-author` validator: 0 errors and 0 warnings.
- PBIR and TMDL definitions use the pinned Microsoft schemas under `schemas/`; the
  upstream Microsoft MIT notice is retained alongside them.

PBIP, PBIR, and TMDL remain Power BI Desktop preview formats. The committed PBIX is the
most broadly compatible review artifact, while the project definitions are the
auditable source of truth. This is a local Desktop report, not a published Power BI
Service report.
