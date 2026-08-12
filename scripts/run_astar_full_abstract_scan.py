#!/usr/bin/env python3
"""Run a resumable full inventory of missing ABDC A* abstracts.

Every non-duplicate article currently marked ``abstract_status='missing'`` is
snapshotted and receives one terminal result record.  Public publisher pages
are fetched only where a verified parser or a generic strong scholarly
metadata check can add information.  Publisher families whose ordinary
landing-page requests are blocked are represented article-by-article as
review-pending, never as article-level "abstract unavailable".  Elsevier can
be scanned through its official Article Retrieval API when an API key is
supplied; otherwise those records remain in the review queue.

Outputs are append-only JSONL plus an atomic progress file.  Re-running with
``--resume`` continues from the last complete result line.  Verified abstract
candidates can be written through the service's audited publisher-page writer
with ``--apply``.  No full text is extracted or stored.
"""

import argparse
from collections import Counter
import hashlib
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'pboc_data.db')
DEFAULT_RUN_DIR = os.path.join(
    ROOT, 'data', 'astar_abstract_full_scan_v2_20260803')

sys.path.insert(0, ROOT)
from scripts.probe_astar_publisher_abstracts import (  # noqa: E402
    DEFAULT_DELAY,
    DEFAULT_TIMEOUT,
    DEFAULT_UA,
    _doi,
    load_local_secret,
    probe_elsevier_api_row,
    probe_row,
)
from services.abdc_astar_research_service import (  # noqa: E402
    apply_verified_publisher_abstract,
)


POLICY_VERSION = 'publisher-route-v2.1-2026-08-03'
EVIDENCE_DATE = '2026-08-03 America/Denver'

# These routes were verified with low-frequency representative DOI landing-page
# checks on 2026-08-03.  They avoid turning one known publisher-level access
# outcome into tens of thousands of identical requests.  Every article still
# receives its own result row with the applicable evidence and reason.
REVIEW_RULES = (
    (('elsevier',),
     'sciencedirect_public_page_may_have_abstract_but_direct_automation_is_403'),
    (('psychological association',),
     'psycnet_landing_has_no_trusted_machine_readable_abstract'),
    (('sage',), 'publisher_landing_preflight_http_403'),
    (('wiley',), 'publisher_landing_preflight_http_403'),
    (('chicago',), 'publisher_landing_preflight_http_403'),
    (('academy of management',), 'publisher_landing_preflight_http_403'),
    (('public health association',), 'publisher_landing_preflight_http_403'),
    (('oxford university press',), 'publisher_landing_preflight_http_403'),
    (('operations research', 'management sciences'),
     'publisher_landing_preflight_http_403'),
    (('informa uk',), 'tandfonline_landing_preflight_http_403'),
    (('routledge',), 'tandfonline_landing_preflight_http_403'),
    (('taylor & francis',), 'tandfonline_landing_preflight_http_403'),
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def publisher_route(publisher, elsevier_api_enabled=False):
    value = (publisher or '').lower()
    if 'springer' in value or 'palgrave' in value:
        return 'live_springer', 'verified_springer_scholarly_metadata_adapter'
    if 'elsevier' in value and elsevier_api_enabled:
        return 'live_elsevier_api', 'authorized_elsevier_article_retrieval_meta'
    for needles, reason in REVIEW_RULES:
        if all(needle in value for needle in needles):
            return 'publisher_page_review', reason
    return 'live_generic', 'probe_doi_landing_for_strong_scholarly_metadata'


def _open_readonly(path):
    conn = sqlite3.connect(
        f'file:{os.path.abspath(path)}?mode=ro', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _compact(value):
    return ' '.join((value or '').split())


def snapshot_targets(db_path, publisher=None, limit=None,
                     elsevier_api_enabled=False):
    sql = """SELECT id,doi,title,publisher,journal_title,publication_date,
                    abstract,abstract_status,data_status
             FROM astar_articles
             WHERE abstract_status='missing' AND is_duplicate=0"""
    args = []
    if publisher:
        sql += " AND lower(COALESCE(publisher,'')) LIKE ?"
        args.append('%' + publisher.lower() + '%')
    sql += ' ORDER BY publication_date DESC,id DESC'
    if limit:
        sql += ' LIMIT ?'
        args.append(int(limit))

    with _open_readonly(db_path) as conn:
        rows = conn.execute(sql, args).fetchall()

    targets = []
    for row in rows:
        abstract_text = _compact(row['abstract'])
        doi = _doi(row['doi'])
        if not doi:
            route = 'no_doi'
            route_reason = 'article_has_no_doi_for_publisher_resolution'
        elif abstract_text:
            route = 'status_inconsistent_nonempty'
            route_reason = 'abstract_status_missing_but_abstract_text_is_nonempty'
        else:
            route, route_reason = publisher_route(
                row['publisher'],
                elsevier_api_enabled=elsevier_api_enabled)
        target = {
            'article_id': row['id'],
            'id': row['id'],  # probe_row compatibility
            'doi': doi or None,
            'title': row['title'],
            'publisher': row['publisher'],
            'journal_title': row['journal_title'],
            'publication_date': row['publication_date'],
            'route': route,
            'route_reason': route_reason,
            'snapshot_abstract_status': row['abstract_status'],
            'snapshot_data_status': row['data_status'],
            'snapshot_abstract_characters': len(abstract_text),
        }
        if abstract_text:
            target['snapshot_abstract_sha256'] = hashlib.sha256(
                abstract_text.encode('utf-8')).hexdigest()
        targets.append(target)
    return targets


def _atomic_json(path, payload):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _write_targets(path, targets):
    with open(path, 'x', encoding='utf-8', newline='\n') as handle:
        for target in targets:
            handle.write(json.dumps(target, ensure_ascii=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8') as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A hard stop can leave only the final line incomplete.  It is
                # safe to ignore because append/resume will process that id.
                if line_number == sum(1 for _ in open(path, encoding='utf-8')):
                    break
                raise
    return rows


def _load_targets(path):
    return _read_jsonl(path)


def _result_base(target, status, reason, network_request_performed=False):
    return {
        'article_id': target['article_id'],
        'doi': target.get('doi'),
        'title': target.get('title'),
        'publisher': target.get('publisher'),
        'journal_title': target.get('journal_title'),
        'route': target['route'],
        'status': status,
        'reason': reason,
        'network_request_performed': bool(network_request_performed),
        'scanned_at': utc_now(),
        'policy_version': POLICY_VERSION,
    }


def terminal_result(target):
    route = target['route']
    if route == 'no_doi':
        return _result_base(target, 'skipped_no_doi', target['route_reason'])
    if route == 'status_inconsistent_nonempty':
        result = _result_base(
            target, 'excluded_nonempty_abstract', target['route_reason'])
        result['abstract_characters'] = target['snapshot_abstract_characters']
        result['abstract_sha256'] = target.get('snapshot_abstract_sha256')
        return result
    if route in ('publisher_page_review', 'publisher_route_unavailable'):
        result = _result_base(
            target, 'publisher_page_review_pending', target['route_reason'])
        result.update({
            'evidence_scope': 'publisher_family_access_constraint',
            'evidence_checked_at': EVIDENCE_DATE,
            'article_level_abstract_availability': 'unknown',
            'review_requirement': 'browser_or_authorized_publisher_api',
            'source_url': ('https://doi.org/' + target['doi'])
            if target.get('doi') else None,
        })
        return result
    return None


def _summarize_existing(results):
    completed = {}
    for result in results:
        completed[result['article_id']] = result
    counts = Counter(result.get('status', 'unknown') for result in completed.values())
    route_counts = Counter(result.get('route', 'unknown') for result in completed.values())
    applied = sum(1 for result in completed.values()
                  if result.get('apply_status') == 'applied')
    apply_errors = sum(1 for result in completed.values()
                       if result.get('apply_status') == 'error')
    network_requests = sum(1 for result in completed.values()
                           if result.get('network_request_performed'))
    return completed, counts, route_counts, applied, apply_errors, network_requests


def _progress_payload(total, completed, counts, route_counts, applied,
                      apply_errors, network_requests, state, started_at,
                      current_article_id=None):
    done = len(completed)
    return {
        'success': state not in ('failed',),
        'state': state,
        'pid': os.getpid(),
        'started_at': started_at,
        'heartbeat_at': utc_now(),
        'total_targets': total,
        'completed': done,
        'remaining': max(0, total - done),
        'percent_complete': round(done * 100.0 / total, 3) if total else 100.0,
        'status_counts': dict(sorted(counts.items())),
        'completed_route_counts': dict(sorted(route_counts.items())),
        'network_requests': network_requests,
        'candidates_applied': applied,
        'candidate_apply_errors': apply_errors,
        'current_article_id': current_article_id,
        'policy_version': POLICY_VERSION,
    }


class RunLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding='utf-8') as handle:
                    old_pid = int(handle.read().strip())
                os.kill(old_pid, 0)
            except (OSError, ValueError):
                os.unlink(self.path)
            else:
                raise RuntimeError(f'full scan already running with PID {old_pid}')
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w', encoding='ascii') as handle:
            handle.write(str(os.getpid()))
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def run(args):
    os.makedirs(args.run_dir, exist_ok=True)
    targets_path = os.path.join(args.run_dir, 'targets.jsonl')
    results_path = os.path.join(args.run_dir, 'results.jsonl')
    manifest_path = os.path.join(args.run_dir, 'manifest.json')
    progress_path = os.path.join(args.run_dir, 'progress.json')
    summary_path = os.path.join(args.run_dir, 'summary.json')
    log_path = os.path.join(args.run_dir, 'scan.log')
    lock_path = os.path.join(args.run_dir, 'scan.lock')
    elsevier_authorization_source = load_local_secret(
        args.elsevier_api_key_env)
    elsevier_api_key = os.environ.get(args.elsevier_api_key_env, '')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(log_path, encoding='utf-8'),
                  logging.StreamHandler(sys.stdout)],
        force=True,
    )
    logger = logging.getLogger('astar_full_abstract_scan')

    with RunLock(lock_path):
        started_at = utc_now()
        if os.path.exists(targets_path):
            if not args.resume:
                raise RuntimeError(
                    f'{targets_path} already exists; pass --resume or choose a new --run-dir')
            targets = _load_targets(targets_path)
            logger.info('Resuming target snapshot with %s records', len(targets))
        else:
            targets = snapshot_targets(
                args.db, publisher=args.publisher, limit=args.limit,
                elsevier_api_enabled=bool(elsevier_api_key))
            _write_targets(targets_path, targets)
            route_counts = Counter(target['route'] for target in targets)
            _atomic_json(manifest_path, {
                'run_id': os.path.basename(os.path.abspath(args.run_dir)),
                'created_at': started_at,
                'db_path': os.path.abspath(args.db),
                'selection': {'publisher': args.publisher, 'limit': args.limit},
                'total_targets': len(targets),
                'target_route_counts': dict(sorted(route_counts.items())),
                'policy_version': POLICY_VERSION,
                'publisher_evidence_checked_at': EVIDENCE_DATE,
                'network_policy': {
                    'single_worker': True,
                    'delay_seconds': args.delay,
                    'timeout_seconds': args.timeout,
                    'full_text_extracted_or_stored': False,
                    'blocked_access_bypassed': False,
                    'elsevier_authorized_api_configured': bool(elsevier_api_key),
                    'elsevier_authorization_source':
                        elsevier_authorization_source,
                },
            })
            logger.info('Created target snapshot with %s records: %s',
                        len(targets), dict(route_counts))

        if (any(t.get('route') == 'live_elsevier_api' for t in targets)
                and not elsevier_api_key):
            raise RuntimeError(
                f'Elsevier API targets require {args.elsevier_api_key_env} '
                'to be set before starting or resuming this run')

        existing_results = _read_jsonl(results_path)
        (completed, counts, completed_routes, applied, apply_errors,
         network_requests) = _summarize_existing(existing_results)
        total = len(targets)
        _atomic_json(progress_path, _progress_payload(
            total, completed, counts, completed_routes, applied, apply_errors,
            network_requests, 'running', started_at))

        session = requests.Session()
        session.headers.update({
            'User-Agent': DEFAULT_UA,
            'Accept': 'text/html,application/xhtml+xml',
        })
        result_handle = open(results_path, 'a', encoding='utf-8',
                             newline='\n', buffering=1)
        writes_since_fsync = 0

        def append_result(result):
            nonlocal applied, apply_errors, network_requests, writes_since_fsync
            article_id = result['article_id']
            result_handle.write(json.dumps(result, ensure_ascii=False) + '\n')
            result_handle.flush()
            writes_since_fsync += 1
            if writes_since_fsync >= args.fsync_every:
                os.fsync(result_handle.fileno())
                writes_since_fsync = 0
            completed[article_id] = result
            counts[result.get('status', 'unknown')] += 1
            completed_routes[result.get('route', 'unknown')] += 1
            if result.get('apply_status') == 'applied':
                applied += 1
            elif result.get('apply_status') == 'error':
                apply_errors += 1
            if result.get('network_request_performed'):
                network_requests += 1

        try:
            # First account for every deterministic/non-network target.  This
            # makes the full inventory visible within seconds; live public-page
            # probes then fill the remaining routes with resumable checkpoints.
            terminal_written = 0
            for target in targets:
                if target['article_id'] in completed:
                    continue
                result = terminal_result(target)
                if result is None:
                    continue
                append_result(result)
                terminal_written += 1
                if terminal_written % args.status_every == 0:
                    _atomic_json(progress_path, _progress_payload(
                        total, completed, counts, completed_routes, applied,
                        apply_errors, network_requests, 'running', started_at,
                        target['article_id']))
            logger.info('Recorded %s deterministic terminal results', terminal_written)

            live_done_this_run = 0
            for target in targets:
                if target['article_id'] in completed:
                    continue
                if target['route'] not in (
                        'live_springer', 'live_generic', 'live_elsevier_api'):
                    continue
                if target['route'] == 'live_elsevier_api':
                    result = probe_elsevier_api_row(
                        session, target, elsevier_api_key,
                        delay=args.delay, timeout=args.timeout)
                else:
                    result = probe_row(
                        session, target, delay=args.delay, timeout=args.timeout)
                result['route'] = target['route']
                result['policy_version'] = POLICY_VERSION
                result['scanned_at'] = utc_now()
                result['network_request_performed'] = True
                if result.get('status') == 'candidate' and args.apply:
                    try:
                        applied_result = apply_verified_publisher_abstract(
                            doi=result['doi'],
                            abstract=result['abstract'],
                            source_url=result['source_url'],
                            source_name=result['source_name'],
                            source_id=result['source_id'],
                            verified_at=utc_now(),
                            verification_notes=result['verification_notes'],
                            expected_title=result['title'],
                            source_type=(result.get('source_type')
                                         or 'publisher_page'),
                            db_path=args.db,
                        )
                        result['apply_status'] = 'applied'
                        result['apply_changed'] = applied_result['changed']
                        result['applied_abstract_characters'] = applied_result[
                            'abstract_characters']
                    except Exception as exc:
                        result['apply_status'] = 'error'
                        result['apply_error'] = f'{type(exc).__name__}: {exc}'
                elif result.get('status') == 'candidate':
                    result['apply_status'] = 'not_requested'
                append_result(result)
                live_done_this_run += 1
                if live_done_this_run % args.status_every == 0:
                    _atomic_json(progress_path, _progress_payload(
                        total, completed, counts, completed_routes, applied,
                        apply_errors, network_requests, 'running', started_at,
                        target['article_id']))
                    logger.info(
                        'Progress %s/%s (%.2f%%), live=%s, applied=%s, statuses=%s',
                        len(completed), total,
                        len(completed) * 100.0 / total if total else 100.0,
                        live_done_this_run, applied, dict(counts))

            if writes_since_fsync:
                os.fsync(result_handle.fileno())
            final_state = 'complete' if len(completed) == total else 'incomplete'
            final = _progress_payload(
                total, completed, counts, completed_routes, applied,
                apply_errors, network_requests, final_state, started_at)
            final['finished_at'] = utc_now()
            _atomic_json(progress_path, final)
            _atomic_json(summary_path, final)
            logger.info('Full scan %s: %s', final_state, final)
            return final
        except Exception as exc:
            failed = _progress_payload(
                total, completed, counts, completed_routes, applied,
                apply_errors, network_requests, 'failed', started_at)
            failed['error'] = f'{type(exc).__name__}: {exc}'
            _atomic_json(progress_path, failed)
            logger.exception('Full scan failed and can be resumed')
            raise
        finally:
            result_handle.close()
            session.close()


def main():
    parser = argparse.ArgumentParser(
        description='Run resumable full missing-abstract inventory and backfill')
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--run-dir', default=DEFAULT_RUN_DIR)
    parser.add_argument('--publisher', help='optional publisher substring for smoke runs')
    parser.add_argument('--limit', type=int, help='optional bounded target count')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument('--elsevier-api-key-env', default='ELSEVIER_API_KEY',
                        help='environment variable containing an Elsevier API key')
    parser.add_argument('--status-every', type=int, default=25)
    parser.add_argument('--fsync-every', type=int, default=25)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit('--limit must be positive')
    if args.delay < 0 or args.timeout <= 0:
        raise SystemExit('--delay must be non-negative and --timeout positive')
    if args.status_every < 1 or args.fsync_every < 1:
        raise SystemExit('--status-every and --fsync-every must be positive')
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
