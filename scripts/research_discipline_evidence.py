# -*- coding: utf-8 -*-
"""Check the catalog's hand-assigned disciplines against the A* corpus.

For every catalog entity that has entity-specific paper links, this joins those
papers to their journal's ABDC field of research and asks whether the discipline
mix looks different from the corpus as a whole.

Three decisions in here matter more than the code:

1. **Umbrella links are excluded.** 78% of ``research_paper_links`` rows carry a
   broad tag: ``experiment`` alone covers seven method entries, so a broad link
   says a paper ran some experiment, not that it used conjoint analysis. Left in,
   conjoint, RCT, vignette and lab experiment all report the same ~4,800 papers
   and therefore the same apparent discipline mix, which is an artefact.

2. **Shares are compared against the corpus baseline, not against zero.** Applied
   Economics and Economic Theory journals are ~24% of the corpus, so a construct
   whose linked papers are 22% economics is *under*-represented there. Reporting
   raw shares would recommend tagging almost everything Economics. What counts as
   evidence here is lift over the baseline.

3. **Two fields cannot be resolved and are not guessed.** ABDC merges strategy,
   management and organisational behaviour into one field, so the corpus cannot
   settle the OB/HR versus Management/Strategy question - which is the one most
   often in doubt. Transportation/Logistics likewise merges supply chain with
   operations. Both are counted separately as ``ambiguous`` and reported, never
   split.

Entrepreneurship, International Business, Computational Social Science and
Decision Sciences have no ABDC field of their own in this corpus, so it is silent
on them and their tags stay a judgement call.

Read-only. Prints a report; ``--json-out`` writes the findings.
"""

import argparse
import collections
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DB = os.path.join(ROOT, 'data', 'business_research_state.db')
CORPUS_DB = os.path.join(ROOT, 'pboc_data.db')
CATALOG = os.path.join(ROOT, 'data', 'research_catalog.json')

FIELD_TO_DISCIPLINE = {
    'Human Resources & Industrial Relations': 'OB / HR',
    'Marketing': 'Marketing',
    'Information Systems': 'Information Systems',
    'Banking, Finance & Investment': 'Finance',
    'Accounting': 'Accounting',
    'Applied Economics': 'Economics',
    'Economic Theory': 'Economics',
    'Econometrics': 'Business Analytics / Operations Research',
    'Statistics & Probability': 'Business Analytics / Operations Research',
    # Deliberately unmapped: Law, Tourism, Commercial Services, Other
    # Commerce/Management - outside the catalog's fourteen disciplines. Forcing
    # them into one would inflate it.
}

# Fields covering more than one catalog discipline. Counted, reported, never split.
AMBIGUOUS_FIELDS = {
    'Strategy, Management & Organisational Behaviour': ('Management / Strategy', 'OB / HR'),
    'Transportation, Logistics & Supply Chains': ('Supply Chain Management', 'Operations Management'),
}

NO_CORPUS_SIGNAL = (
    'Entrepreneurship', 'International Business',
    'Computational Social Science', 'Decision Sciences',
)

# Disciplines whose ABDC field is a clean one-to-one match with their own set of
# journals. Lift for these is interpretable.
RELIABLE = ('Marketing', 'Information Systems', 'Accounting', 'Finance', 'Economics')

# OB/HR keeps only the 'Human Resources & Industrial Relations' journals once the
# merged strategy/management/OB field is set aside, which is 3.3% of the
# resolvable baseline. That residual is a biased slice of OB work - most of it
# publishes in the merged field - so OB/HR lift is computed but not recommended
# on. Business Analytics / OR resolves to econometrics and statistics journals,
# where a hit means the method is being studied methodologically rather than used
# in business research, so it is treated the same way.
LOW_CONFIDENCE = ('OB / HR', 'Business Analytics / Operations Research')

# Keyword inference is excluded too. Spot checks showed it matching single
# generic words: the Marketing "evidence" for employee-engagement was 253 of 255
# papers matching the bare word 'engagement' in consumer-engagement research, and
# capital-structure matched 'leverage' used as a verb. Only the classifier's own
# precise tag vocabulary is treated as evidence of what a paper is about.
ENTITY_SPECIFIC_BASES = ('precise_classification_tag',)


def load_field_by_paper():
    corpus = sqlite3.connect('file:%s?mode=ro' % CORPUS_DB.replace('\\', '/'), uri=True)
    rows = corpus.execute(
        'SELECT a.id, j.discipline FROM astar_articles a '
        'JOIN abdc_astar_journals j ON ('
        '  a.journal_issn = j.issn_print OR a.journal_issn = j.issn_online '
        '  OR a.journal_issn = j.issn_l)'
    ).fetchall()
    corpus.close()
    return dict(rows)


def load_links():
    state = sqlite3.connect('file:%s?mode=ro' % STATE_DB.replace('\\', '/'), uri=True)
    links = collections.defaultdict(list)
    placeholders = ','.join('?' * len(ENTITY_SPECIFIC_BASES))
    for paper_id, kind, entity_id in state.execute(
            'SELECT paper_id, kind, entity_id FROM research_paper_links '
            'WHERE basis IN (%s)' % placeholders, ENTITY_SPECIFIC_BASES):
        links[(kind, entity_id)].append(paper_id)
    state.close()
    return links


def baseline_shares(field_by_paper):
    """Share of the whole corpus falling in each mapped discipline."""
    counts = collections.Counter()
    total = 0
    for field in field_by_paper.values():
        disc = FIELD_TO_DISCIPLINE.get(field)
        if disc is None:
            continue
        counts[disc] += 1
        total += 1
    return {d: n / total for d, n in counts.items()}, total


def profile(paper_ids, field_by_paper):
    counts = collections.Counter()
    ambiguous = collections.Counter()
    mapped_total = 0
    for pid in paper_ids:
        field = field_by_paper.get(pid)
        if field is None:
            continue
        if field in AMBIGUOUS_FIELDS:
            ambiguous[AMBIGUOUS_FIELDS[field]] += 1
            continue
        disc = FIELD_TO_DISCIPLINE.get(field)
        if disc is None:
            continue
        counts[disc] += 1
        mapped_total += 1
    return counts, ambiguous, mapped_total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-papers', type=int, default=50,
                    help='minimum papers mapped to a resolvable discipline')
    ap.add_argument('--min-share', type=float, default=0.10,
                    help='minimum share of that entity mapped papers')
    ap.add_argument('--min-lift', type=float, default=1.5,
                    help='minimum share/baseline ratio to count as over-represented')
    ap.add_argument('--kind', choices=('theory', 'construct', 'method'))
    ap.add_argument('--json-out')
    args = ap.parse_args()

    catalog = json.load(open(CATALOG, encoding='utf-8'))
    kinds = {'theory': 'theories', 'construct': 'constructs', 'method': 'methods'}
    tagged = {}
    for kind, key in kinds.items():
        for entity in catalog[key]:
            tagged[(kind, entity['id'])] = set(entity.get('discipline') or [])

    field_by_paper = load_field_by_paper()
    links = load_links()
    base, base_total = baseline_shares(field_by_paper)

    print('corpus:   %d papers joined to a journal discipline' % len(field_by_paper))
    print('baseline: %d in a resolvable catalog discipline' % base_total)
    for disc, share in sorted(base.items(), key=lambda kv: -kv[1]):
        print('    %-44s %5.1f%%' % (disc, share * 100))
    print('\nlinks:    %d entity-specific links across %d entities' % (
        sum(len(v) for v in links.values()), len(links)))
    print('excluded: umbrella broad_classification_tag links\n')

    findings = []
    thin = collections.Counter()
    for (kind, entity_id), paper_ids in sorted(links.items()):
        if args.kind and kind != args.kind:
            continue
        if (kind, entity_id) not in tagged:
            continue
        counts, ambiguous, mapped_total = profile(paper_ids, field_by_paper)
        if mapped_total < args.min_papers:
            thin[kind] += 1
            continue
        current = tagged[(kind, entity_id)]
        over = []
        for disc, n in counts.items():
            share = n / mapped_total
            lift = share / base[disc] if base.get(disc) else 0.0
            if share >= args.min_share and lift >= args.min_lift and disc not in current:
                over.append((disc, share, lift, n, disc in RELIABLE))
        if not over:
            continue
        over.sort(key=lambda t: (not t[4], -t[2]))
        findings.append({
            'kind': kind, 'id': entity_id, 'mapped_papers': mapped_total,
            'current': sorted(current),
            'over_represented': [
                {'discipline': d, 'share': round(sh, 3), 'lift': round(l, 2),
                 'papers': n, 'reliable': rel}
                for d, sh, l, n, rel in over],
            'ambiguous_papers': {' / '.join(k): v for k, v in ambiguous.items()},
        })

    findings.sort(key=lambda f: (-max(x['lift'] for x in f['over_represented']),))
    print('entities over-represented in a discipline the catalog does not list: %d' % len(findings))
    print('(thresholds: >=%d mapped papers, >=%.0f%% share, >=%.1fx baseline)\n'
          % (args.min_papers, args.min_share * 100, args.min_lift))
    for f in findings:
        print('%-9s %-40s n=%d' % (f['kind'], f['id'], f['mapped_papers']))
        print('          current : %s' % (', '.join(f['current']) or '(none)'))
        for x in f['over_represented']:
            print('          %-9s %-42s %4.0f%%  %.1fx baseline  (%d papers)'
                  % ('evidence:' if x['reliable'] else 'weak:',
                     x['discipline'], x['share'] * 100, x['lift'], x['papers']))

    print('\nskipped, under %d mapped papers: %s' % (args.min_papers, dict(thin)))
    print('corpus silent on:   %s' % ', '.join(NO_CORPUS_SIGNAL))
    print('low confidence on:  %s' % ', '.join(LOW_CONFIDENCE))
    print('  (their ABDC field is either merged with another discipline or is a')
    print('   methods field, so lift there reflects the journal set, not usage)')
    for field, pair in AMBIGUOUS_FIELDS.items():
        print('corpus cannot split: %s  (field: %s)' % (' vs '.join(pair), field))

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as fh:
            json.dump(findings, fh, ensure_ascii=False, indent=2)
        print('\nwrote %s' % args.json_out)


if __name__ == '__main__':
    main()
