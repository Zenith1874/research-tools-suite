# -*- coding: utf-8 -*-
"""Discipline tags for the research catalog.

Two separate problems are fixed here.

**Methods had no discipline at all.** All 36 carried only a ``category``
(quantitative / experimental / computational / qualitative), while
``_catalog_search`` filters every kind by discipline. The result was a dead
filter: selecting any discipline on the Methods tab returned zero rows.
``METHOD_DISCIPLINES`` below fills that in.

**Theories and constructs were under-tagged.** 33 theories and 30 constructs
carried a single discipline even where the work plainly spans several - job
design is studied in OB and in management, TAM is studied in IS and in marketing.
``EXTRA_DISCIPLINES`` adds the missing ones.

**These tags are editorial judgement.** An attempt was made to ground them in the
A* corpus - ``research_discipline_evidence.py`` joins each entity's precisely
tagged papers to the ABDC field of the journal they appeared in and looks for
disciplines over-represented against the corpus baseline. It did not survive
scrutiny and nothing here rests on it:

* The first pass was polluted by umbrella tags. ``experiment`` alone covers seven
  method entries, so conjoint, RCT, vignette and lab experiment all reported the
  same ~4,800 papers and the same discipline mix.
* The second was polluted by keyword inference. The marketing "evidence" for the
  employee-engagement construct was 253 of 255 papers matching the bare word
  "engagement" in *consumer* engagement research; capital-structure matched
  "leverage" used as a verb in 109 of 110.
* The third ran while the paper-link index was still rebuilding, and its results
  did not replicate once it finished. Agency theory went from 262 mapped papers
  to 713 and its accounting share fell back to the corpus baseline; constructs
  turned out to have no precisely-tagged links at all.

Two structural limits would have remained even had it replicated. ABDC merges
strategy, management and organisational behaviour into a single field, so the
corpus cannot settle the OB versus Management question that prompted this pass;
and it has no field for Entrepreneurship, International Business, Computational
Social Science or Decision Sciences.

So the justification for each tag is that the theory, construct or method is part
of that discipline's literature or standard toolkit - agency theory is foundational
in accounting and finance, transaction cost economics runs through marketing
channel governance, conjoint analysis is a marketing instrument. That is a claim
about the fields, defensible on its own terms, and it is not dressed up as
measurement. The evidence script is kept because its negative results are worth
having, not because it decided anything here.

A discipline on a method means the method is part of that discipline's standard
toolkit, not that it was invented there.
"""

# The canonical fourteen. Kept here so the build script does not have to import
# from services/; tests/test_research_disciplines.py asserts this stays identical
# to DISCIPLINES in services/business_research_service.py, since a tag outside
# that tuple is one no filter in the UI can ever select.
VALID_DISCIPLINES = (
    'Information Systems',
    'Management / Strategy',
    'Marketing',
    'OB / HR',
    'Operations Management',
    'Supply Chain Management',
    'Decision Sciences',
    'Finance',
    'Accounting',
    'Entrepreneurship',
    'International Business',
    'Business Analytics / Operations Research',
    'Economics',
    'Computational Social Science',
)


# ─────────────────────────────────────────────────────────────────────────────
# Methods
# ─────────────────────────────────────────────────────────────────────────────

# Workhorse estimators taught and used everywhere in quantitative business
# research. Listing them narrowly would make the filter lie in the other
# direction.
_UNIVERSAL = [
    'Accounting', 'Business Analytics / Operations Research', 'Decision Sciences',
    'Economics', 'Entrepreneurship', 'Finance', 'Information Systems',
    'International Business', 'Management / Strategy', 'Marketing', 'OB / HR',
    'Operations Management', 'Supply Chain Management',
]

_PANEL = [
    'Accounting', 'Business Analytics / Operations Research', 'Economics',
    'Entrepreneurship', 'Finance', 'International Business',
    'Management / Strategy', 'Marketing', 'Operations Management',
    'Supply Chain Management',
]

_CAUSAL = [
    'Accounting', 'Economics', 'Entrepreneurship', 'Finance',
    'Information Systems', 'International Business', 'Management / Strategy',
    'Marketing', 'Operations Management',
]

_SURVEY_MODELLING = [
    'Decision Sciences', 'Entrepreneurship', 'Information Systems',
    'International Business', 'Management / Strategy', 'Marketing', 'OB / HR',
    'Operations Management', 'Supply Chain Management',
]

_QUALITATIVE = [
    'Entrepreneurship', 'Information Systems', 'International Business',
    'Management / Strategy', 'Marketing', 'OB / HR',
]

_COMPUTATIONAL = [
    'Business Analytics / Operations Research', 'Computational Social Science',
    'Finance', 'Information Systems', 'Management / Strategy', 'Marketing',
]

METHOD_DISCIPLINES = {
    # Regression and panel
    'ols-regression': _UNIVERSAL,
    'logistic-regression': _UNIVERSAL,
    'panel-data': _PANEL,
    'fixed-effects': _PANEL,
    'random-effects': _PANEL + ['OB / HR'],

    # Causal inference
    'difference-in-differences': _CAUSAL + ['Supply Chain Management'],
    'instrumental-variables': _CAUSAL,
    'regression-discontinuity': ['Accounting', 'Economics', 'Entrepreneurship',
                                 'Finance', 'Information Systems',
                                 'Management / Strategy', 'Marketing'],
    'synthetic-control': ['Accounting', 'Economics', 'Finance',
                          'Information Systems', 'Management / Strategy',
                          'Marketing'],
    # Event studies are the finance and accounting workhorse for announcement effects.
    'event-study': ['Accounting', 'Entrepreneurship', 'Finance',
                    'International Business', 'Management / Strategy',
                    'Marketing'],

    # Latent variables and measurement
    'structural-equation-modeling': _SURVEY_MODELLING,
    'confirmatory-factor-analysis': _SURVEY_MODELLING,
    'multilevel-modeling': ['Computational Social Science', 'Entrepreneurship',
                            'Information Systems', 'Management / Strategy',
                            'Marketing', 'OB / HR', 'Operations Management'],
    'mediation': _SURVEY_MODELLING,
    'moderation': _SURVEY_MODELLING,
    'meta-analysis': ['Accounting', 'Decision Sciences', 'Entrepreneurship',
                      'Finance', 'Information Systems', 'International Business',
                      'Management / Strategy', 'Marketing', 'OB / HR',
                      'Operations Management', 'Supply Chain Management'],

    # Experimental
    'experiment': ['Accounting', 'Computational Social Science',
                   'Decision Sciences', 'Economics', 'Finance',
                   'Information Systems', 'Management / Strategy', 'Marketing',
                   'OB / HR', 'Operations Management'],
    'lab-experiment': ['Accounting', 'Decision Sciences', 'Economics', 'Finance',
                       'Information Systems', 'Marketing', 'OB / HR'],
    'field-experiment': ['Computational Social Science', 'Economics',
                         'Entrepreneurship', 'Information Systems',
                         'Management / Strategy', 'Marketing', 'OB / HR',
                         'Operations Management'],
    'randomized-controlled-trial': ['Economics', 'Information Systems',
                                    'Management / Strategy', 'Marketing',
                                    'OB / HR', 'Operations Management'],
    'survey-experiment': ['Computational Social Science', 'Decision Sciences',
                          'Information Systems', 'Management / Strategy',
                          'Marketing', 'OB / HR'],
    'vignette-experiment': ['Accounting', 'Decision Sciences',
                            'Information Systems', 'Management / Strategy',
                            'Marketing', 'OB / HR'],
    # Conjoint is a marketing invention and remains concentrated there.
    'conjoint-experiment': ['Decision Sciences', 'Information Systems',
                            'Management / Strategy', 'Marketing',
                            'Operations Management', 'Supply Chain Management'],

    # Computational
    'topic-modeling': _COMPUTATIONAL + ['Accounting', 'Entrepreneurship'],
    'text-classification': _COMPUTATIONAL + ['Accounting'],
    'embeddings': _COMPUTATIONAL,
    'computational-content-analysis': _COMPUTATIONAL + ['Accounting', 'OB / HR'],
    'network-analysis': ['Computational Social Science', 'Finance',
                         'Information Systems', 'Management / Strategy',
                         'Marketing', 'OB / HR', 'Supply Chain Management'],
    'agent-based-modeling': ['Business Analytics / Operations Research',
                             'Computational Social Science', 'Economics',
                             'Management / Strategy', 'Marketing',
                             'Operations Management', 'Supply Chain Management'],
    'web-scraping': _COMPUTATIONAL + ['Entrepreneurship'],

    # Qualitative
    'interviews': _QUALITATIVE + ['Accounting', 'Operations Management',
                                  'Supply Chain Management'],
    'thematic-analysis': _QUALITATIVE,
    'grounded-theory': _QUALITATIVE,
    'case-study': _QUALITATIVE + ['Accounting', 'Operations Management',
                                  'Supply Chain Management'],
    'content-analysis': _QUALITATIVE + ['Accounting'],
    'ethnography': ['Accounting', 'Information Systems', 'Management / Strategy',
                    'Marketing', 'OB / HR'],
}


# ─────────────────────────────────────────────────────────────────────────────
# Theories and constructs — disciplines to add to what the entry already lists
# ─────────────────────────────────────────────────────────────────────────────

EXTRA_DISCIPLINES = {
    # ── Theories, corpus-corroborated ────────────────────────────────────────
    'agency-theory': ['Accounting', 'Finance', 'Entrepreneurship',
                      'International Business'],
    'stakeholder-theory': ['Accounting', 'Finance', 'Marketing',
                           'International Business'],
    'institutional-logics': ['Accounting', 'Marketing', 'OB / HR',
                             'Information Systems'],
    'institutional-theory': ['Accounting', 'Marketing', 'International Business',
                             'OB / HR'],
    'transaction-cost-economics': ['Marketing', 'Supply Chain Management',
                                   'Economics', 'Finance', 'Accounting',
                                   'International Business'],
    'sensemaking-theory': ['Accounting', 'Information Systems', 'Marketing'],
    'resource-based-view': ['Marketing', 'Information Systems',
                            'Operations Management', 'Supply Chain Management',
                            'Entrepreneurship', 'International Business'],
    'signaling-theory': ['Accounting', 'Finance', 'Entrepreneurship',
                         'International Business'],
    'game-theory': ['Economics', 'Operations Management',
                    'Supply Chain Management'],
    'human-capital-theory': ['Economics', 'Entrepreneurship'],
    # Capital-markets accounting research is built on the efficient-market
    # assumption, and conservation of resources carries the salesperson
    # depletion literature in marketing.
    'efficient-market-hypothesis': ['Accounting'],
    'conservation-of-resources': ['Marketing'],
    'social-network-theory': ['Finance'],

    # ── Theories, judgement: OB work that is equally management work ─────────
    # Job design, leadership and exchange theories publish in both channels; the
    # corpus cannot separate them because ABDC merges the two fields.
    'job-characteristics-model': ['Management / Strategy'],
    'leader-member-exchange': ['Management / Strategy'],
    'organizational-support-theory': ['Management / Strategy'],
    'psychological-contract-theory': ['Management / Strategy'],
    'goal-setting-theory': ['Management / Strategy'],
    'organizational-justice-theory': ['Management / Strategy', 'Marketing'],
    'affective-events-theory': ['Management / Strategy', 'Marketing'],
    'job-embeddedness-theory': ['Management / Strategy'],
    'person-environment-fit': ['Management / Strategy'],
    'implicit-leadership-theory': ['Management / Strategy'],

    # ── Theories, judgement: IS theories with a large consumer literature ────
    # TAM and UTAUT are applied to consumer technology adoption at least as often
    # as to workplace systems, and UTAUT2 was written for the consumer case.
    'technology-acceptance-model': ['Marketing', 'Management / Strategy', 'OB / HR'],
    'utaut': ['Marketing', 'Management / Strategy', 'OB / HR'],
    'is-success-model': ['Management / Strategy',
                         'Business Analytics / Operations Research'],
    'task-technology-fit': ['OB / HR', 'Operations Management'],
    'media-richness-theory': ['OB / HR', 'Management / Strategy'],
    'adaptive-structuration-theory': ['OB / HR', 'Management / Strategy'],

    # ── Theories, judgement: strategy theories used across the professions ───
    'dynamic-capabilities': ['Operations Management', 'Information Systems',
                             'International Business', 'Entrepreneurship',
                             'Marketing'],
    'knowledge-based-view': ['Information Systems', 'Operations Management',
                             'International Business'],
    'upper-echelons-theory': ['Accounting', 'Finance', 'Entrepreneurship',
                              'International Business', 'Marketing'],
    'behavioral-theory-of-the-firm': ['Decision Sciences', 'Entrepreneurship',
                                      'Operations Management'],
    'resource-dependence-theory': ['Supply Chain Management',
                                   'International Business', 'OB / HR'],
    'organizational-ambidexterity': ['Information Systems',
                                     'Operations Management', 'Entrepreneurship'],
    'attention-based-view': ['Accounting', 'OB / HR'],
    'organizational-learning-theory': ['Operations Management',
                                       'Information Systems', 'OB / HR'],
    'contract-theory': ['Economics', 'Finance', 'Accounting',
                        'Supply Chain Management'],
    'real-options-theory': ['Finance', 'Entrepreneurship', 'Operations Management',
                            'International Business'],

    # ── Theories, judgement: marketing theories reaching other channels ──────
    'service-dominant-logic': ['Operations Management', 'Supply Chain Management',
                               'Information Systems', 'Management / Strategy'],
    'brand-equity-theory': ['Finance', 'Accounting', 'Management / Strategy'],
    'consumer-culture-theory': ['Management / Strategy'],

    # ── Constructs, judgement: OB constructs with a sales-force literature ───
    # Role stress, burnout, satisfaction and turnover among salespeople are a
    # long-standing marketing literature, not a borrowing.
    'role-ambiguity': ['Marketing', 'Management / Strategy'],
    'burnout': ['Marketing', 'Operations Management'],
    'job-satisfaction': ['Marketing', 'Management / Strategy'],
    'affective-commitment': ['Marketing', 'Management / Strategy'],
    'turnover-intention': ['Marketing', 'Management / Strategy'],
    'organizational-citizenship-behavior': ['Marketing', 'Management / Strategy'],
    'procedural-justice': ['Marketing', 'Management / Strategy'],
    'psychological-safety': ['Management / Strategy', 'Operations Management'],
    'workload': ['Operations Management', 'Management / Strategy'],
    'job-insecurity': ['Management / Strategy'],
    'work-life-conflict': ['Management / Strategy'],
    'social-support': ['Management / Strategy'],
    'leader-support': ['Management / Strategy'],
    'perceived-organizational-support': ['Management / Strategy'],
    'employee-engagement': ['Management / Strategy'],
    'employee-voice': ['Management / Strategy'],
    'counterproductive-work-behavior': ['Management / Strategy'],

    # ── Constructs, judgement: IS beliefs applied to consumers ───────────────
    'perceived-usefulness': ['Marketing', 'Management / Strategy'],
    'perceived-ease-of-use': ['Marketing'],
    'technology-adoption-intention': ['Marketing', 'Operations Management'],

    # ── Constructs, judgement: strategy outcomes used across channels ────────
    'firm-performance': ['Accounting', 'Finance', 'Operations Management',
                         'Supply Chain Management', 'Marketing',
                         'Entrepreneurship', 'International Business'],
    'competitive-advantage': ['Marketing', 'Information Systems',
                              'Operations Management', 'Supply Chain Management',
                              'Entrepreneurship'],
    'absorptive-capacity-construct': ['Information Systems',
                                      'Operations Management',
                                      'International Business', 'Entrepreneurship'],
    'organizational-slack': ['Accounting', 'Finance', 'Entrepreneurship'],
    'risk-taking': ['Finance', 'Entrepreneurship', 'Accounting'],
    'legitimacy': ['Accounting', 'Entrepreneurship', 'International Business',
                   'Marketing'],

    # ── Constructs, judgement: marketing outcomes used across channels ───────
    'customer-satisfaction': ['Operations Management', 'Supply Chain Management',
                              'Information Systems'],
    'customer-loyalty': ['Information Systems', 'Operations Management'],
    'brand-equity': ['Finance', 'Accounting', 'Management / Strategy'],
    'opportunity-recognition': ['Management / Strategy', 'International Business'],
}


def apply_disciplines(theories, constructs, methods, valid=VALID_DISCIPLINES):
    """Attach method disciplines and merge the extras. Returns a change summary.

    ``valid`` is the canonical discipline tuple; anything outside it is a typo
    and raises rather than silently creating a discipline no filter offers.
    """
    valid = set(valid)
    changes = {'methods_set': 0, 'entities_extended': 0, 'disciplines_added': 0}

    for method in methods:
        assigned = METHOD_DISCIPLINES.get(method['id'])
        if assigned is None:
            raise KeyError('method %r has no discipline assignment' % method['id'])
        unknown = set(assigned) - valid
        if unknown:
            raise ValueError('method %r: unknown disciplines %s'
                             % (method['id'], sorted(unknown)))
        seen = []
        for discipline in assigned:
            if discipline not in seen:
                seen.append(discipline)
        method['discipline'] = seen
        changes['methods_set'] += 1

    by_id = {}
    for entity in list(theories) + list(constructs):
        by_id[entity['id']] = entity
    for entity_id, extra in EXTRA_DISCIPLINES.items():
        entity = by_id.get(entity_id)
        if entity is None:
            raise KeyError('EXTRA_DISCIPLINES names unknown entity %r' % entity_id)
        unknown = set(extra) - valid
        if unknown:
            raise ValueError('%r: unknown disciplines %s' % (entity_id, sorted(unknown)))
        # The first entry reads as the home field, so the existing order is kept
        # and anything new is appended. Sorting here would have made accounting
        # look like agency theory's home discipline.
        current = list(entity.get('discipline') or [])
        added = [d for d in extra if d not in current]
        if added:
            entity['discipline'] = current + added
            changes['entities_extended'] += 1
            changes['disciplines_added'] += len(added)
    return changes
