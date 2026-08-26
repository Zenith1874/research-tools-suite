# ABDC Theory–Construct–Method Source Evidence Status

Date: 2026-08-25

## Outcome

The Business Research catalog now gives every Theory, Construct, and Method a
shared source-record shape. The 318 records are separated by evidence role:

- 203 theory sources: origin, review, or extension;
- 79 construct sources: definition, measurement, or definition/measurement;
- 36 method sources: estimator/design origin, method foundation, or method
  review.

The source record carries candidate bibliographic data, verification provider,
DOI, landing page, legal open-access locator, version, license, local-copy
path/hash where applicable, and an explicit access status.

## Current evidence counts

After conservative OpenAlex/Crossref matching plus one PubMed primary-index
correction for the JD-R origin paper:

| Evidence field | Count |
| --- | ---: |
| Total source records | 318 |
| `verified_openalex` | 10 |
| `verified_crossref` | 236 |
| `verified_pubmed` | 1 |
| `pending_verification` | 71 |
| OA records with direct full-text locator | 20 |
| OA records with an open landing page | 19 |
| Publisher/institutional access page | 208 |
| Metadata-only / access not yet checked | 71 |
| Unique private OA PDFs downloaded | 12 |

The local OA PDFs occupy about 29 MB. Fourteen source rows reference those
files because some DOI records are shared by both a theory and a construct;
the file is stored once and identified by DOI-derived filename and SHA-256.

## Data and rights boundaries

- A Crossref/OpenAlex/PubMed match verifies bibliographic identity; it does not
  prove that the full text is open or that the source was read in full.
- `open_full_text` means an OA PDF locator was returned by Unpaywall and a PDF
  was either validated or retained as the recorded legal locator. A publisher
  page is never labelled as an original full text.
- Only OA PDF URLs were eligible for opt-in local download. No login, paywall,
  robots restriction, or access control was bypassed. Copyrighted scale items
  remain metadata-only.
- The source-access recheck now records SHA-256 for every existing local OA
  PDF row; the 14 row references resolve to 12 unique local files with no
  missing hash.
- The catalog still contains curated definitions and relationships. It does
  not infer that a source empirically tested a Theory–Construct–Method link;
  that requires reading and coding the paper itself.

## User-supplied book scan: derived OCR reading layer

The supplied image-only `Management and Organization 60` scan was preserved
unchanged outside the repository. A separate local OCR layer was created for
page search and resumable reading:

- 520/520 PDF pages completed; 0 OCR page failures;
- Tesseract 5.3.4 with `eng+chi_sim`, 180 DPI, page segmentation mode 3;
- 781,742 derived OCR characters;
- 60 chapter locator rows, with 59 title matches and one title-variant row
  (`Job Demands–Resources`) marked for human review;
- the manifest and per-page text are gitignored under
  `data/research_source_text/` and are not exposed by the API.

The catalog and Theory detail API now expose only the safe OCR status and
printed/PDF page locators. `ocr_derived_available` does not mean that the
chapter has been read, that OCR is error-free, or that a Theory–Construct–
Method claim has been verified. Definitions, boundary conditions, cited works,
constructs, scales, and methods still require page-level human review against
the original scan.

The same local reading area now has an embedded-text extraction index for the
12 unique OA PDFs already downloaded by the source-access workflow. PDFs with
usable embedded text are split into page files; a PDF without a usable text
layer is explicitly marked `text_layer_missing` and is not treated as read.

## Reproducible commands

```bash
python3 scripts/build_research_catalog.py
python3 scripts/verify_research_sources.py --kind constructs
python3 scripts/verify_research_sources.py --kind methods
python3 scripts/verify_research_sources.py --kind theories
python3 scripts/resolve_research_source_access.py
python3 scripts/resolve_research_source_access.py --download
python3 scripts/extract_research_source_text.py
python3 -m unittest tests.test_research_source_verification tests.test_business_research_service tests.test_business_research_contract tests.test_research_navigation
```

The original article database was not modified. `data/research_sources/` is a
gitignored derived OA-copy directory.

## UI/API validation

- Theory detail: classic source rows show role, DOI, original/full-text link
  when available, verification provider, and access state.
- Construct detail: `Origin & measurement sources` shows the construct
  definition/scale source without copying scale items.
- Method detail: `Foundational method sources` shows the estimator/design or
  qualitative-method source and its legal access state.
- The shared top navigation and ABDC sub-navigation remain present. Desktop
  and 375px mobile browser checks passed for the three detail types.

## Remaining work

1. Resolve the 71 pending book/older/emerging records against authoritative
   publisher, repository, library, or author sources without weakening the
   title-author-year match rule.
2. Human-review alternate editions, working-paper versions, and reprints before
   calling a source the exact version of record.
3. Add paper-level Theory–Construct–Method evidence only after reading the
   original text; catalog relationships and keyword links are not empirical
   evidence.
4. Perform the page-level human evidence pass on the book OCR layer: code
   definitions, constructs, measurement/scales, methods, citations, and exact
   page locators into a separate evidence ledger. Do not promote OCR text or
   catalog relationships to verified Theory–Construct–Method evidence.
