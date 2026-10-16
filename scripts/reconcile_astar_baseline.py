#!/usr/bin/env python3
"""Prepare a baseline restoration for review; apply only an explicitly approved plan.

Preparation is read-only. Observed full rows and exact field changes are retained
in a new output folder. Application checks the approved file hash and every
observed value before restoring any protected baseline field in one transaction.
Blank-field enrichments, new articles, source rows, and affiliations are untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protected_article_changes(before, observed):
    changes = {}
    for column, value in before.items():
        if column in ('id', 'updated_at', 'abstract_status') or value in (None, ''):
            continue
        if observed[column] != value:
            changes[column] = {'baseline': value, 'observed': observed[column]}
    if before.get('abstract') not in (None, '') and before['abstract_status'] != observed['abstract_status']:
        changes['abstract_status'] = {'baseline': before['abstract_status'],
                                      'observed': observed['abstract_status']}
    return changes


def prepare(run_dir, output_dir):
    run_dir, output_dir = Path(run_dir).resolve(), Path(output_dir).resolve()
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    db_path, baseline_path = Path(manifest['db_path']).resolve(), Path(manifest['snapshot_path']).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    observed_rows, actions = {}, []
    try:
        db.execute('ATTACH DATABASE ? AS baseline', (baseline_path.as_uri() + '?mode=ro',))
        db.execute('BEGIN')
        for table in ('astar_articles', 'astar_article_classifications'):
            columns = [row['name'] for row in db.execute(f'PRAGMA baseline.table_info({table})')]
            if not columns:
                raise ValueError('Required baseline table is missing')
            missing = db.execute(f'SELECT COUNT(*) FROM baseline.{table} b '
                                 f'LEFT JOIN main.{table} a ON a.id=b.id WHERE a.id IS NULL').fetchone()[0]
            if missing:
                raise ValueError(f'Baseline {table} has missing rows; field restoration is insufficient')
            if table == 'astar_articles':
                expressions = [f"(b.{column} IS NOT NULL AND b.{column}!='' AND a.{column} IS NOT b.{column})"
                               for column in columns if column not in ('id', 'updated_at', 'abstract_status')]
                expressions.append("(b.abstract IS NOT NULL AND b.abstract!='' AND a.abstract_status IS NOT b.abstract_status)")
            else:
                expressions = [f'a.{column} IS NOT b.{column}' for column in columns if column != 'id']
            rows = db.execute(f'SELECT b.id FROM baseline.{table} b JOIN main.{table} a ON a.id=b.id '
                              'WHERE ' + ' OR '.join(expressions)).fetchall()
            observed_rows[table] = []
            for row in rows:
                before = dict(db.execute(f'SELECT * FROM baseline.{table} WHERE id=?', (row['id'],)).fetchone())
                observed = dict(db.execute(f'SELECT * FROM main.{table} WHERE id=?', (row['id'],)).fetchone())
                if table == 'astar_articles':
                    changes = protected_article_changes(before, observed)
                else:
                    if before.get('classification_method') != 'rules' or observed.get('classification_method') != 'rules':
                        raise ValueError('Changed non-rule decisions require a separate review')
                    changes = {column: {'baseline': value, 'observed': observed[column]}
                               for column, value in before.items()
                               if column not in ('id', 'article_id') and value != observed[column]}
                    if before['article_id'] != observed['article_id']:
                        raise ValueError('Classification article identity changed')
                if changes:
                    observed_rows[table].append(observed)
                    actions.append({'table': table, 'row_id': row['id'],
                                    'article_id': before.get('article_id', row['id']), 'changes': changes})
        max_id = db.execute('SELECT COALESCE(MAX(id),0) FROM baseline.astar_articles').fetchone()[0]
        db.rollback()
    finally:
        db.close()
    write_new(output_dir / 'observed_rows_preserved.json', observed_rows)
    plan = {'schema': 'astar-baseline-restoration-v1', 'prepared_at_utc': now(),
            'db_path': str(db_path), 'run_dir': str(run_dir), 'baseline_path': str(baseline_path),
            'baseline_sha256': manifest['snapshot_sha256'], 'baseline_max_id': max_id,
            'observed_rows_sha256': hash_file(output_dir / 'observed_rows_preserved.json'),
            'actions': actions, 'explicit_user_approval_required': True,
            'preserves_originally_blank_enrichment': True, 'modifies_new_articles': False}
    write_new(output_dir / 'repair_plan.json', plan)
    summary = {'prepared_at_utc': now(), 'plan_path': str(output_dir / 'repair_plan.json'),
               'plan_sha256': hash_file(output_dir / 'repair_plan.json'),
               'rows_by_table': dict(Counter(action['table'] for action in actions)),
               'fields_by_table': {table: dict(Counter(column for action in actions if action['table'] == table
                                                     for column in action['changes']))
                                   for table in observed_rows}, 'production_modified': False}
    write_new(output_dir / 'verification.json', summary)
    return summary


def apply_plan(plan_path, approved_sha256):
    plan_path = Path(plan_path).resolve()
    if not approved_sha256 or hash_file(plan_path) != approved_sha256:
        raise ValueError('The exact prepared plan hash must be explicitly approved')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan.get('schema') != 'astar-baseline-restoration-v1':
        raise ValueError('Unknown restoration plan schema')
    observed_path = plan_path.parent / 'observed_rows_preserved.json'
    if hash_file(observed_path) != plan['observed_rows_sha256']:
        raise ValueError('Preserved observed rows changed')
    manifest = json.loads((Path(plan['run_dir']) / 'manifest.json').read_text(encoding='utf-8'))
    if (str(Path(manifest['db_path']).resolve()) != plan['db_path'] or
            str(Path(manifest['snapshot_path']).resolve()) != plan['baseline_path'] or
            manifest['snapshot_sha256'] != plan['baseline_sha256']):
        raise ValueError('The original restoration scope changed')
    db = sqlite3.connect(Path(plan['db_path']).as_uri() + '?mode=rw', uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    counts = Counter()
    input_rows = {'astar_articles': [], 'astar_article_classifications': []}
    application_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    input_snapshot = plan_path.parent / ('application_inputs_' + application_stamp + '.json')
    try:
        db.execute('ATTACH DATABASE ? AS baseline', (Path(plan['baseline_path']).as_uri() + '?mode=ro',))
        db.execute('BEGIN IMMEDIATE')
        # Verify all actions against the immutable baseline and live values first.
        for action in plan['actions']:
            table, row_id = action['table'], action['row_id']
            if table not in ('astar_articles', 'astar_article_classifications') or action['article_id'] > plan['baseline_max_id']:
                raise ValueError('Plan includes an unprotected table or new article')
            before = db.execute(f'SELECT * FROM baseline.{table} WHERE id=?', (row_id,)).fetchone()
            observed = db.execute(f'SELECT * FROM main.{table} WHERE id=?', (row_id,)).fetchone()
            if before is None or observed is None:
                raise ValueError('A target row is unavailable')
            if before['article_id' if table == 'astar_article_classifications' else 'id'] != action['article_id']:
                raise ValueError('The restoration article identity changed')
            if table == 'astar_article_classifications' and (
                    before['classification_method'] != 'rules' or observed['classification_method'] != 'rules'):
                raise ValueError('A target is no longer an unpaid rule decision')
            allowed = protected_article_changes(dict(before), dict(observed)) if table == 'astar_articles' else {
                column: {'baseline': before[column], 'observed': observed[column]}
                for column in before.keys() if column not in ('id', 'article_id') and before[column] != observed[column]}
            for column, values in action['changes'].items():
                if column not in allowed or values != allowed[column]:
                    raise ValueError('A target field changed since review; nothing was restored')
            input_rows[table].append(dict(observed))
        # Preserve the exact current rows, including later blank-field fills,
        # before any update. A failed snapshot write rolls the transaction back.
        write_new(input_snapshot, {'captured_at_utc': now(), 'approved_plan_sha256': approved_sha256,
                                  'application_not_yet_committed': True, 'rows': input_rows})
        for action in plan['actions']:
            assignments = ','.join(f'{column}=?' for column in action['changes'])
            values = [entry['baseline'] for entry in action['changes'].values()]
            db.execute(f"UPDATE {action['table']} SET {assignments} WHERE id=?", values + [action['row_id']])
            counts[action['table']] += 1
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    receipt = {'applied_at_utc': now(), 'approved_plan_sha256': approved_sha256,
               'restored_rows': dict(counts), 'observed_values_preserved': str(observed_path),
               'immediate_input_snapshot': str(input_snapshot), 'immediate_input_snapshot_sha256': hash_file(input_snapshot),
               'new_articles_updated': False, 'sources_updated': False, 'affiliations_updated': False}
    write_new(plan_path.parent / ('application_' + stamp + '.json'), receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'apply'))
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--approved-plan-sha256')
    args = parser.parse_args()
    if args.action == 'prepare':
        if args.run_dir is None or args.output_dir is None:
            parser.error('prepare requires --run-dir and a new --output-dir')
        result = prepare(args.run_dir, args.output_dir)
    else:
        if args.plan is None or not args.approved_plan_sha256:
            parser.error('apply requires --plan and --approved-plan-sha256 after user approval')
        result = apply_plan(args.plan, args.approved_plan_sha256)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
