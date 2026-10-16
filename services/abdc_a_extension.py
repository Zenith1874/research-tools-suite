"""Append the authorized A-rated scope without replacing existing journals.

Collection groups only order acquisition. Official FoR, rank and journal
discipline remain independent of title cues used for collection priority.
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from services import abdc_astar_research_service as radar
from services.astar_history_service import digest, journal_key, utc_now, write_new_json

MANAGEMENT_FIELDS = {'3503', '3504', '3505', '3507', '3508', '3509', '3599'}
COMPUTING_TITLES = {
    'computers & industrial engineering', 'human-computer interaction',
    'computers in human behavior', 'journal of computer information systems',
    'journal of database management', 'informs journal on computing',
    'journal of organizational computing and electronic commerce',
}
PSYCHOLOGY_CUES = re.compile(
    r'psycholog|personality|work.*stress|stress.*health|human performance|'
    r'judgment and decision|motivation and emotion|small group research|'
    r'career assessment|selection and assessment|behavioral decision', re.I)


def acquisition_group(journal):
    title = journal['title'].strip().casefold()
    field = str(journal.get('for') or '').strip()
    if title in COMPUTING_TITLES:
        return 2, 'Computing / HCI', 'Reviewed title cue; acquisition order only'
    if field == '4609':
        return 0, 'Information Systems', 'Official FoR 4609'
    if PSYCHOLOGY_CUES.search(title):
        return 3, 'Psychology / work behaviour', 'Title cue; acquisition order only'
    if field in MANAGEMENT_FIELDS:
        return 1, 'Management and adjacent subfields', 'Official commerce/management FoR groups'
    if field == '3506':
        return 4, 'Marketing', 'Official FoR 3506'
    return 5, 'Other A journals', 'Remaining authorized A-rated scope'


def journal_row(item, version='2025'):
    title = item['title'].strip()
    normalized = radar.normalize_title(title)
    print_issn, online_issn = radar.normalize_issn(item.get('issn')), radar.normalize_issn(item.get('issnOnline'))
    if normalized in radar.ISSN_OVERRIDES:
        print_issn, online_issn = radar.ISSN_OVERRIDES[normalized]
    discipline, _ = radar.discipline_for(item)
    level, group, basis = acquisition_group(item)
    return {'abdc_journal_id': None, 'journal_title': title,
            'journal_title_normalized': normalized, 'issn_print': print_issn,
            'issn_online': online_issn, 'issn_l': print_issn or online_issn,
            'abdc_rating': 'A', 'abdc_version': version,
            'field_of_research': str(item.get('for') or '').strip(),
            'discipline': discipline, 'publisher': str(item.get('publisher') or '').strip(),
            'is_active': 1, 'source_table': 'abdc_A_extension_v3',
            'collection_priority': level, 'collection_group': group,
            'priority_basis': basis, 'official_source_row': item.get('source_row')}


def prepare_plan(catalog_path, db_path, plan_dir):
    catalog_path, db_path, plan_dir = map(lambda path: path.resolve(), (catalog_path, db_path, plan_dir))
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    targets = [journal_row(item) for item in catalog if item.get('rating') == 'A']
    names = [row['journal_title_normalized'] for row in targets]
    if not targets or len(set(names)) != len(names):
        raise ValueError('A-rated catalogue must contain unique journal titles')
    from services.astar_history_service import connect
    conn = connect(db_path, readonly=True)
    try:
        existing = [dict(row) for row in conn.execute('SELECT * FROM abdc_astar_journals')]
        before_count = conn.execute('SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0').fetchone()[0]
    finally:
        conn.close()
    active = {row['journal_title_normalized']: row for row in existing
              if row['is_active'] and row['abdc_version'] == '2025'}
    overlaps = [row for row in targets if row['journal_title_normalized'] in active]
    if any(active[row['journal_title_normalized']]['abdc_rating'] != 'A' for row in overlaps):
        raise ValueError('Existing rank differs from the official source; manual reconciliation required')
    additions = [row for row in targets if row['journal_title_normalized'] not in active]
    additions.sort(key=lambda row: (row['collection_priority'], row['journal_title']))
    missing_issns = [row['journal_title'] for row in additions if not row['issn_l']]
    if missing_issns:
        raise ValueError('Source journals without ISSN: ' + ', '.join(missing_issns))
    plan_dir.mkdir(parents=True, exist_ok=False)
    scope = {'created_at': utc_now(), 'catalog_path': str(catalog_path),
             'catalog_sha256': digest(catalog_path), 'db_path': str(db_path),
             'rank': 'A', 'version': '2025', 'from_year': 2010,
             'A_target_count': len(targets), 'already_tracked_A_count': len(overlaps),
             'new_tracking_count': len(additions), 'before_article_count': before_count,
             'expected_active_total': len(active) + len(additions),
             'new_by_acquisition_group': dict(Counter(row['collection_group'] for row in additions)),
             'A_by_official_field': dict(Counter(row['field_of_research'] for row in targets)),
             'already_tracked_A': [active[row['journal_title_normalized']] for row in overlaps],
             'priority_groups_are_research_validation': False,
             'journals': additions}
    write_new_json(plan_dir / 'scope.json', scope)
    write_new_json(plan_dir / 'existing_journals.before.json', existing)
    return scope


def apply_plan(plan_path):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if digest(plan['catalog_path']) != plan['catalog_sha256']:
        raise ValueError('Frozen official catalogue hash changed')
    source = json.loads(Path(plan['catalog_path']).read_text(encoding='utf-8'))
    official = {radar.normalize_title(item['title']): journal_row(item)
                for item in source if item.get('rating') == 'A'}
    journals = plan['journals']
    if not journals or len({journal_key(row) for row in journals}) != len(journals):
        raise ValueError('New scope must be unique and nonempty')
    for row in journals:
        if row != official.get(row['journal_title_normalized']):
            raise ValueError('Plan row differs from official A-rated source')
    from services.astar_history_service import connect
    conn = connect(plan['db_path'])
    inserted, retained = [], []
    columns = ('abdc_journal_id', 'journal_title', 'journal_title_normalized',
               'issn_print', 'issn_online', 'issn_l', 'abdc_rating', 'abdc_version',
               'field_of_research', 'discipline', 'publisher', 'is_active', 'source_table')
    now = datetime.now().isoformat(timespec='seconds')
    try:
        conn.execute('BEGIN IMMEDIATE')
        for row in journals:
            existing = conn.execute('''SELECT * FROM abdc_astar_journals
                WHERE journal_title_normalized=? AND abdc_version=?''',
                (row['journal_title_normalized'], row['abdc_version'])).fetchall()
            if existing:
                if not any(journal['is_active'] and journal['abdc_rating'] == 'A' for journal in existing):
                    raise ValueError('Existing inactive/conflicting journal requires reconciliation')
                retained.append(row['journal_title'])
                continue
            cursor = conn.execute('INSERT INTO abdc_astar_journals (' + ','.join(columns) +
                ',created_at,updated_at) VALUES (' + ','.join('?' for _ in columns) + ',?,?)',
                tuple(row.get(column) for column in columns) + (now, now))
            inserted.append({'id': cursor.lastrowid, 'title': row['journal_title'],
                             'official_source_row': row['official_source_row']})
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    receipt = {'applied_at': utc_now(), 'plan_path': str(plan_path),
               'plan_sha256': digest(plan_path), 'inserted': inserted, 'retained': retained,
               'existing_journal_values_updated': False, 'article_values_updated': False}
    from datetime import timezone
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_new_json(plan_path.parent / ('tracking_applied_' + stamp + '.json'), receipt)
    return receipt
