# ABDC Theory–Construct–Method Evidence Ledger

Date: 2026-08-25

## Purpose

`data/research_evidence/management-organization-60_evidence_queue.json` is a
local reading queue for the supplied `Management and Organization 60` scan. It
contains 60 chapter records with printed/PDF locators and blank coding fields
for:

- theory definition and core proposition;
- constructs and mechanisms;
- boundary conditions and criticisms;
- measurement/scales and methods;
- cited works and page-level evidence notes.

The queue is deliberately not a literature database and does not claim that a
catalog relationship is present in the original chapter. Every populated item
must be checked against the original scan or a legally accessible primary
source. OCR is a search aid, not the authoritative text.

## Evidence entry convention

Each page-level entry should record `printed_page`, `pdf_page`, a controlled
`kind` (`definition`, `construct`, `mechanism`, `measurement`, `method`,
`citation`, `boundary_condition`, or `criticism`), a short note or compliant
excerpt, and `source_check` (`unreviewed`, `checked_against_original`, or
`verified_primary_source`). Do not paste a full copyrighted chapter or scale
instrument into the ledger.

## Rebuild command

```bash
python3 scripts/build_research_evidence_queue.py
```

The builder refreshes page locators and preserves any existing user-entered
`coding` or `evidence` fields. The API does not serve the ledger or OCR text;
it only exposes safe OCR status and page locators on book-backed Theory pages.

## First seven page-level coding passes

On 2026-08-25, the first thirty-five chapters were partially human-coded after visual
review of the corresponding original scan pages:

- Affective Events Theory: printed pages 1–8 / PDF pages 18, 21–25;
- Broaden-and-Build Theory of Positive Emotions: printed pages 13–17 / PDF
  pages 30–34;
- Co-evolution Theory: printed pages 22–26 / PDF pages 39–43;
- Cognitive Appraisal Theory: printed pages 29–36 / PDF pages 46–53;
- Cognitive Dissonance Theory: printed pages 39–46 / PDF pages 56–63.
- Compensatory Ethics Theory: printed pages 48–56 / PDF pages 65–73;
- Complexity Theory and Organizations: printed pages 57–63 / PDF pages 74–80;
- Configural Organization Theory: printed pages 64–72 / PDF pages 81–89;
- Conservation of Resources Theory: printed pages 73–82 / PDF pages 90–99;
- Construal-Level Theory: printed pages 83–90 / PDF pages 100–107.
- Contingency Theory: printed pages 91–99 / PDF pages 108–116;
- Co-opetition Theory: printed pages 100–106 / PDF pages 117–123;
- Dual-System Theory: printed pages 107–116 / PDF pages 124–133;
- Ego-Depletion Theory: printed pages 117–125 / PDF pages 134–142;
- Emotional Contagion Theory: printed pages 126–134 / PDF pages 143–151.
- Emotion-as-Social-Information Theory: printed pages 135–142 / PDF pages 152–159;
- Ethical Leadership Theory: printed pages 143–151 / PDF pages 160–168;
- Event System Theory: printed pages 152–159 / PDF pages 169–176;
- Fairness Heuristic Theory: printed pages 160–167 / PDF pages 177–184;
- Feelings-as-Information Theory: printed pages 168–175 / PDF pages 185–192.
- Goal Orientation Theory: printed pages 176–185 / PDF pages 193–202;
- Implicit Leadership Theory: printed pages 186–192 / PDF pages 203–209;
- Interaction Ritual Chain Theory: printed pages 193–200 / PDF pages 210–217;
- Job Demands–Resources Model: printed pages 201–208 / PDF pages 218–225;
- Leader–Member Exchange Theory: printed pages 209–217 / PDF pages 226–234.
- Loose Coupling Theory: printed pages 218–224 / PDF pages 235–241;
- Middle-Status Conformity Theory: printed pages 225–232 / PDF pages 242–249;
- Minority Influence Theory: printed pages 233–241 / PDF pages 250–258;
- Moral Licensing Theory: printed pages 242–249 / PDF pages 259–266;
- Need-to-Belong Theory: printed pages 250–257 / PDF pages 267–274.
- Neo-Institutional Theory: printed pages 258–266 / PDF pages 275–283;
- Organizational Learning Theory: printed pages 267–275 / PDF pages 284–292;
- Person–Environment Fit Theory: printed pages 276–283 / PDF pages 293–300;
- Population Ecology Theory: printed pages 284–290 / PDF pages 301–307;
- Regulatory Focus Theory: printed pages 291–297 / PDF pages 308–314.

The queue now contains 330 short, paraphrased page notes with
`source_check=checked_against_original`. These rows are marked
`partially_human_coded`, retain `original_scan_required`, and add
`primary_source_crosscheck_required`; they are not marked `verified`. Scale
records contain metadata only, never item wording. The reproducible seed record
is `scripts/seed_book60_evidence.py`; it preserves non-empty user coding and is
safe to rerun.

The remaining 25 rows are still `needs_human_coding`. No Theory–Construct–Method
claim, definition, measurement scale, or method is promoted to verified primary
source evidence by this queue alone.

## Validation recorded

- `python3 scripts/seed_book60_evidence.py` is idempotent: the first seven-pass
  run added 330 notes and the rerun added 0.
- Targeted Python validation passed: 43 tests covering queue preservation, the
  evidence seed, source text handling, service metadata, and research contracts.
- The browser API returned `partially_human_coded`, seven page notes, and
  `human_coding_required=true` for Affective Events Theory. A real browser
  snapshot confirmed the global navigation, ABDC sub-navigation, original-page
  locator panel, and the human-readable “T–C–M evidence partially coded” label.
- The page JavaScript passed the available Windows Node runtime syntax check.
