# Data sources and rights

This repository does not relicense upstream data. Code, original prose and original report
definitions are covered by the repository license; source data remains attributed to its official
provider.

## CFTC Commitments of Traders

Positioning comes from the U.S. Commodity Futures Trading Commission's public Disaggregated
Futures-Only dataset for Sugar No. 11 (`080732`). The release-calendar inputs are compact factual
extracts from official CFTC schedules and special announcements. U.S. federal government works are
generally public domain; appropriate CFTC acknowledgement is retained. Do not imply endorsement.

- Dataset: <https://publicreporting.cftc.gov/Commitments-of-Traders/Disaggregated-Futures-Only/72hh-3qpy>
- Historical compressed data: <https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm>
- Initial live Disaggregated COT release: <https://www.cftc.gov/PressRoom/PressReleases/5710-09>
- Release schedule: <https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm>
- Historical special announcements: <https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalSpecialAnnouncements/index.htm>
- CFTC web policy: <https://www.cftc.gov/WebPolicy/index.htm>

The public repository retains only selected fields required for the rule and compact factual
calendar rows. The manifest preserves exact query/source URLs, every public-extract hash, and
available single-artifact upstream hashes. The API
history is a retrieved current snapshot, not a complete archive of every later correction. Compact
timing ledgers retain exact official weekly-page URLs and factual `Updated` dates; volatile full
HTML bodies are not redistributed.

## USDA WASDE

Supply-and-demand vintages come from the U.S. Department of Agriculture's public Historical WASDE
Report Data. The repository retains only annual U.S. and Mexico sugar rows needed for the tracker,
with exact official URLs and hashes. USDA states that individual WASDE publications remain the
official record; the consolidated historical files preserve estimates as reported at each time
but are not the current revised official series for older periods.

- WASDE: <https://www.usda.gov/about-usda/general-information/staff-offices/office-chief-economist/commodity-markets/wasde-report>
- Historical WASDE data: <https://www.usda.gov/historical-wasde-report-data-3>
- Current revised PS&D history: <https://apps.fas.usda.gov/psdonline/app/index.html#/app/home>

The project's unit normalization, availability boundaries and revision calculations are analytical
metadata, not USDA statements. Do not imply USDA endorsement.

## Microsoft validation schemas

The unmodified JSON schemas under `powerbi/schemas/` retain Microsoft's upstream MIT license and
copyright notice. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the vendored license;
the repository's own license does not replace those terms.

## Derived outputs

Derived tables contain the minimum facts needed to reproduce the project. They preserve source
attribution, raw values, units, correction flags and checksums. U.S. and Mexico physical units are
not pooled. There is no ICE price or other licensed exchange dataset in the repository.
