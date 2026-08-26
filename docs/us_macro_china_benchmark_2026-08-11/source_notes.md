# U.S. macro / China benchmark report — source and status notes

Date: 2026-08-11  
Audience: product stakeholders and research owner  
Delivery mode: one self-contained portable HTML report generated from canonical `artifact.json`  
Repository state audited: branch `codex/one-plus-five-migration`, commit `7b7656f`

## Scope and output status

- Inspected the project structure, root/project READMEs, migration and coverage status documents, service/UI code, targeted tests, current API responses, and the live SQLite database through a read-only Windows connection.
- Produced a decision report and a reproducible read-only audit notebook.
- Added `build_report.mjs`, a report-local reproducible wrapper around the installed Data Analytics portable builder, static-chart extractor, and browser verifier.
- Did **not** modify service code, UI code, configuration, database contents, models, or prior outputs.
- The report is a snapshot assessment, not a forecast and not an authorization to ingest or overwrite new data.

## Required report-structure mapping

| Required role | Artifact block(s) |
|---|---|
| Title | `report_title` |
| Executive summary | `executive_summary` |
| Key findings with visual evidence | `coverage_finding`, `coverage_chart_block`, `product_gap`, `alignment_finding`, `alignment_chart_block`, `comparison_model` |
| Recommended next steps | `roadmap_heading`, `roadmap_table_block` |
| Further questions | `further_questions` |
| Caveats and assumptions | `caveats` |

## Chart map

| Report segment | Analytical question | Family / type | Fields | Supported claim | Palette | Source |
|---|---|---|---|---|---|---|
| Existing asset coverage | How many cataloged U.S. series are represented on the main page? | Comparison / horizontal bar | `status`, `series_count`, `share_pct` | 36 of 45 are represented; 9 are not | Sequential blue, no redundant category color | SQLite `us_macro_observations` joined to the frozen UI representation set |
| CPI transformation audit | How do row-lag and calendar-aligned YoY results differ in the latest reviewed month? | Comparison / grouped bar | `indicator`, `method`, `value_pct`, `difference_pp` | Row lag overstates June 2026 CPI and core CPI YoY by about 0.24–0.26 pp | Categorical comparison | SQLite `us_macro_observations` with row lag and exact one-year date join |

No trend chart was added because this report's decision hinges on asset coverage and method variance, not on re-presenting macro time series already available in the product.

## Evidence and quality checks

- `us_macro_observations`: 183,365 rows, 45 distinct series, 1854-12-01 to 2026-08-11.
- Provenance completeness in current rows: no missing `source_url`, no duplicate `(indicator_code, period)` keys, and all rows have `data_status='official'` under the FRED source name. The separate `source_type='us_macro'` value is a domain label, not an authority tier.
- Main-page representation baseline: 36 represented codes and 9 unrepresented codes.
- Missing raw period: `2025-10-01` for both `CPIAUCSL` and `CPILFESL`.
- Calendar mismatch: eight periods per reviewed CPI series, from 2025-11-01 through 2026-06-01.
- Latest reviewed values (2026-06-01):
  - CPI: row lag 3.7265%; calendar aligned 3.4635%; difference +0.2630 pp.
  - Core CPI: row lag 2.8058%; calendar aligned 2.5658%; difference +0.2400 pp.
- Cross-module comparison: `/macro-analytics` uses a calendar-aware transform and reports U.S. CPI at about 3.5%, confirming that the inconsistency is localized to the main U.S. macro service's row-lag helper.

Validation completed:

- The executed notebook contains five executed code cells and zero error outputs.
- All three SQL statements embedded as report provenance executed successfully; their result rows match the reviewed snapshot datasets.
- `tests.test_rates_macro_parsers` and `tests.test_macro_analytics`: **53 tests passed** on Windows Python 3.12.
- Portable report verifier: **passed** with 12 blocks, 2 native charts, 1 native table, working source dialog, and responsive checks at 1440 px and 390 px.
- SHA-256: `artifact.json` = `9403f875a32abed53013453ccbf6e465a49285665e0e49e5ec92e3c6118f8180`; `report.html` = `fdd6ed6dbd03c3c856353499e1694e88d060fefa4c369ce7e185bbad7d2fe35c`; executed notebook = `2438666a142ee286b8b70188cf01eac303811ac51c87d862b1aedbb96d0e10b1`.

## Official-source capability inventory

- BEA Developer Resources: <https://www.bea.gov/resources/for-developers>
- BLS Public Data API v2: <https://www.bls.gov/developers/api_signature_v2.htm>
- Census Economic Indicators API: <https://www.census.gov/data/developers/data-sets/economic-indicators.html>
- Treasury Fiscal Data, Debt to the Penny: <https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/>
- Federal Reserve H.8 bank balance sheets: <https://www.federalreserve.gov/releases/H8/about.htm>
- Treasury International Capital system: <https://home.treasury.gov/data/treasury-international-capital-tic-system-home-page/description-of-TIC-system>
- FHFA House Price Index datasets: <https://www.fhfa.gov/house-price-index?tab=HPI+Datasets>
- FRED observations and metadata: <https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- ALFRED vintages: <https://alfred.stlouisfed.org/help>
- OECD API guidance: <https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html>
- IMF Data API: <https://data.imf.org/en/Resource-Pages/IMF-API>
- China NBS national data: <https://data.stats.gov.cn/easyquery.htm?cn=E0103&zb=A0201>

## Reproduction commands

From the repository root:

```bash
PYTHONIOENCODING=utf-8 python.exe -X utf8 -m jupyter nbconvert \
  --execute --to notebook --inplace \
  docs/us_macro_china_benchmark_2026-08-11/us_macro_china_benchmark_audit.ipynb \
  --ExecutePreprocessor.timeout=120

PYTHONIOENCODING=utf-8 python.exe -X utf8 -m unittest \
  tests.test_rates_macro_parsers tests.test_macro_analytics -q
```

Generate, extract static chart fallbacks, and verify the portable report with the report-local wrapper. The plugin root is explicit so the package version is auditable:

```bash
node.exe D:/claude/docs/us_macro_china_benchmark_2026-08-11/build_report.mjs \
  --plugin-root C:/Users/cui10/.codex/plugins/cache/openai-curated-remote/data-analytics/0.2.8-13ceeea1f599
```

The packaged v0.2.8 reader uses `width:100vw` for its sticky top bar. On Windows Chromium, a vertical scrollbar reduces `documentElement.clientWidth` by 15 px while `100vw` remains unchanged, producing an 8 px page overflow. The report-local wrapper applies a narrowly scoped packaging override (`width:100%; margin-inline:0`) to the enhanced-reader and semantic-fallback top bars. The canonical artifact payload is unchanged, and the plugin's original verifier passes after this fix.

## Remaining work

- Phase 0 implementation is intentionally not included in this report-only pass.
- Before changing the main service, add a failing gap regression test for CPI/core CPI and confirm expected missing-period behavior.
- After any fix, reconcile `/api/us-macro`, `/api/macro-analytics`, and the rendered `/us-macro` page against the notebook baseline.
- Before direct-source expansion, freeze authority tiers, release/vintage fields, seasonal-adjustment metadata, and the comparison-registry schema.
