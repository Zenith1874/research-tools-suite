# ABDC Business Research Theory Library Expansion Status

Date: 2026-08-25

## Outcome

The Business Research catalog now keeps the original curated scaffold and adds
two explicitly separated packs:

- **Management and Organization 60 book pack:** the 49 previously missing
  chapters were added, and the 11 pre-existing matching records were annotated;
  the attached scan now maps to 60/60 records.
- **Business-school domain expansion:** 42 additional theory/model records for
  Operations Management, Supply Chain Management, Decision Sciences, Finance,
  Accounting, Entrepreneurship, International Business, Economics, and
  Business Analytics / Operations Research.

The generated catalog now contains 151 theories, 79 constructs, and 36
methods. The 40 new constructs support the added operations, supply-chain,
decision, financial, accounting, entrepreneurship, international-business,
analytics, and book-theory relationships.

## Evidence and boundaries

- The book pack has `source_pack=management-organization-60`, a printed
  chapter-start page, and `source_status=book_scan_scaffold`.
- The chapter titles and starting pages were checked against the attached
  image-only scan. A resumable local OCR reading layer and a 60-chapter
  printed-to-PDF locator map now exist; the chapter arguments, definitions,
  boundary conditions, measurement scales, and cited works still require
  page-level human review against the original scan.
- Domain additions remain `curated_scaffold`; their classic works start as
  `pending_verification`. Existing verified DOI/source fields are preserved by
  the generator.
- The catalog remains `demo_catalog` and is not a publication-ready literature
  review. A zero linked-paper count still means classifier coverage is absent,
  not that the literature is absent.

## Coverage labels

The theory catalog filter now exposes:

`Information Systems`, `Management / Strategy`, `Marketing`, `OB / HR`,
`Operations Management`, `Supply Chain Management`, `Decision Sciences`,
`Finance`, `Accounting`, `Entrepreneurship`, `International Business`,
`Business Analytics / Operations Research`, `Economics`, and
`Computational Social Science`.

The labels are multi-valued: one theory may belong to multiple domains. This
is a catalog coverage taxonomy, not a claim that the existing A* article cache
has equal coverage in every domain.

## Reproducible commands

```bash
python3 -m py_compile scripts/research_catalog_expansion.py scripts/build_research_catalog.py services/business_research_service.py
python3 scripts/build_research_catalog.py
python3 -m unittest tests.test_business_research_service tests.test_business_research_contract tests.test_research_source_verification tests.test_research_navigation
"/mnt/c/Program Files/nodejs/node.exe" --check static/business_research.js
```

Latest theory/source/navigation targeted test result: 61 tests passed.

The follow-up source-evidence layer is documented in
`docs/business_research_source_evidence_STATUS_2026-08-25.md`. It extends the
same source-record shape to Construct and Method entries and separates
bibliographic verification from legal full-text access.

## Browser validation

Using an isolated copy of the research-tools runtime database (the original
database was not modified):

- `/abdc/theories` rendered 151 catalog records and all 14 catalog discipline
  options, including the newly added business-school domains.
- `discipline=Operations Management` rendered 15 records, including the new
  operations and supply-chain entries.
- The Supply Chain Resilience detail page rendered its linked constructs,
  outcomes, related theories, provenance label, source-status rows, boundary
  condition, and criticism scaffold.
- Desktop and 375px mobile screenshots were captured under
  `output/playwright/`.

The full test suite was also run: 795 tests completed with one unrelated
`sqlite3.OperationalError: disk I/O error` during the fiscal-debt test setup
while enabling WAL mode. The targeted Business Research/navigation/source
verification suite remains green at 57/57.

## Remaining work

1. Perform the page-by-page human evidence pass on the book OCR layer:
   reconcile each chapter’s definition, criticism, constructs,
   measurement-scale metadata, methods, cited works, and exact page
   references against the original scan.
2. Continue resolving the remaining `pending_verification` source records and
   human-review alternate editions; the current source-evidence status tracks
   DOI matches, legal OA locators, and private OA PDF copies separately.
3. Add dedicated domain coverage to the A* article classifier only when the
   underlying journal/article evidence and classifier vocabulary support it;
   do not infer literature completeness from the expanded theory count.
4. Re-run browser checks after future UI changes; the current expansion has
   passed the desktop/mobile filter and detail-page smoke checks above.
