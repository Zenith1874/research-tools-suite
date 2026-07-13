# -*- coding: utf-8 -*-
"""Run the A* interest calibration set against a local OpenAI-compatible model.

This is the stage-A runner for Qwen2.5-14B-Instruct-AWQ on iverson. It reads
exported JSONL only and writes a dedicated SQLite database; the main article
database and the V4-Flash interest database are never opened.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.aim_extract import PROMPT_VERSION, build_messages, prompt_hash
from services.astar_interest_service import DIMENSIONS, overall_from_dims


def load_profiles(profile_dir):
    profiles = []
    for name in sorted(os.listdir(profile_dir)):
        if name.endswith('.json'):
            with open(os.path.join(profile_dir, name), encoding='utf-8') as f:
                profile = json.load(f)
            if profile.get('enabled', True):
                profiles.append(profile)
    return profiles


def load_articles(path):
    with open(path, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def input_hash(article):
    text = (article.get('title') or '') + '\n' + (article.get('abstract') or '')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS aim_paper_labels_14b (
        article_id INTEGER PRIMARY KEY,
        research_topics_json TEXT, constructs_json TEXT, theories_json TEXT,
        methods_json TEXT, data_sources_json TEXT, settings_json TEXT,
        analysis_levels_json TEXT, country TEXT, time_range TEXT,
        research_question TEXT, key_findings TEXT, evidence_spans_json TEXT,
        uncertainty INTEGER DEFAULT 0,
        model TEXT, prompt_version TEXT, prompt_hash TEXT, input_hash TEXT,
        run_at TEXT, validation_notes TEXT
    );
    CREATE TABLE IF NOT EXISTS aim_profile_scores_14b (
        article_id INTEGER, profile_id TEXT,
        topic_match REAL, theory_match REAL, method_match REAL,
        data_match REAL, setting_match REAL, opportunity REAL, overall REAL,
        rationale TEXT, model TEXT, prompt_version TEXT, prompt_hash TEXT,
        input_hash TEXT, run_at TEXT,
        PRIMARY KEY (article_id, profile_id)
    );
    CREATE TABLE IF NOT EXISTS aim_runs_14b (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage TEXT, model TEXT, prompt_version TEXT, prompt_hash TEXT,
        n_input INTEGER, n_output INTEGER, n_error INTEGER,
        started TEXT, finished TEXT, notes TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_aim14_scores_profile
        ON aim_profile_scores_14b(profile_id, overall);
    """)
    conn.commit()


def clean_score(value):
    if value is None or value == '':
        return None
    try:
        return round(max(0.0, min(100.0, float(value))), 1)
    except (TypeError, ValueError):
        return None


def clean_text(value):
    """Normalize occasional local-model list/dict values into auditable text."""
    if value is None:
        return None
    if isinstance(value, list):
        return '; '.join(str(item) for item in value if item not in (None, '')) or None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def validate_result(result, article, profiles):
    if not isinstance(result, dict):
        raise ValueError('response is not a JSON object')
    labels = result.get('labels')
    profile_results = result.get('profiles')
    if not isinstance(labels, dict) or not isinstance(profile_results, dict):
        raise ValueError('response missing labels/profiles objects')

    for field in ('research_topics', 'constructs', 'theories', 'methods',
                  'data_sources', 'settings', 'analysis_levels'):
        value = labels.get(field)
        if value is None:
            labels[field] = []
        elif not isinstance(value, list):
            labels[field] = [str(value)]
    for field in ('country', 'time_range', 'research_question', 'key_findings'):
        labels[field] = clean_text(labels.get(field))

    abstract = article.get('abstract') or ''
    spans = labels.get('evidence_spans') or []
    exact_spans = [s for s in spans if isinstance(s, str) and s and s in abstract]
    dropped = len(spans) - len(exact_spans)
    labels['evidence_spans'] = exact_spans
    if not abstract or dropped:
        labels['uncertainty'] = True

    normalized_profiles = {}
    for profile in profiles:
        pid = profile['profile_id']
        raw = profile_results.get(pid) or {}
        normalized_profiles[pid] = {
            d: clean_score(raw.get(d)) for d in DIMENSIONS
        }
        normalized_profiles[pid]['rationale'] = str(raw.get('rationale') or '')
    return labels, normalized_profiles, f'dropped_nonverbatim_evidence={dropped}'


def call_model(article, profiles, base_url, model, timeout, retries):
    system, user = build_messages(article, profiles)
    body = {
        'model': model,
        'max_tokens': 1600,
        'temperature': 0.0,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }
    last_error = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(
                base_url.rstrip('/') + '/chat/completions',
                headers={'Authorization': 'Bearer local-calibration',
                         'Content-Type': 'application/json'},
                json=body,
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if not match:
                raise ValueError('model response contains no JSON object')
            return json.loads(match.group(0))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_error


def save_result(conn, article, labels, profile_results, profiles, metadata, notes):
    dump = lambda key: json.dumps(labels.get(key) or [], ensure_ascii=False)
    conn.execute("""INSERT INTO aim_paper_labels_14b
        (article_id,research_topics_json,constructs_json,theories_json,methods_json,
         data_sources_json,settings_json,analysis_levels_json,country,time_range,
         research_question,key_findings,evidence_spans_json,uncertainty,model,
         prompt_version,prompt_hash,input_hash,run_at,validation_notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(article_id) DO UPDATE SET
          research_topics_json=excluded.research_topics_json,
          constructs_json=excluded.constructs_json,
          theories_json=excluded.theories_json,
          methods_json=excluded.methods_json,
          data_sources_json=excluded.data_sources_json,
          settings_json=excluded.settings_json,
          analysis_levels_json=excluded.analysis_levels_json,
          country=excluded.country,time_range=excluded.time_range,
          research_question=excluded.research_question,key_findings=excluded.key_findings,
          evidence_spans_json=excluded.evidence_spans_json,
          uncertainty=excluded.uncertainty,model=excluded.model,
          prompt_version=excluded.prompt_version,prompt_hash=excluded.prompt_hash,
          input_hash=excluded.input_hash,run_at=excluded.run_at,
          validation_notes=excluded.validation_notes""",
        (article['id'], dump('research_topics'), dump('constructs'), dump('theories'),
         dump('methods'), dump('data_sources'), dump('settings'), dump('analysis_levels'),
         labels.get('country'), labels.get('time_range'), labels.get('research_question'),
         labels.get('key_findings'), dump('evidence_spans'),
         1 if labels.get('uncertainty') else 0, metadata['model'], PROMPT_VERSION,
         metadata['prompt_hash'], metadata['input_hash'], metadata['run_at'], notes))

    for profile in profiles:
        pid = profile['profile_id']
        scores = profile_results[pid]
        overall = overall_from_dims(scores, profile.get('weights') or {})
        conn.execute("""INSERT INTO aim_profile_scores_14b
            (article_id,profile_id,topic_match,theory_match,method_match,data_match,
             setting_match,opportunity,overall,rationale,model,prompt_version,
             prompt_hash,input_hash,run_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(article_id,profile_id) DO UPDATE SET
              topic_match=excluded.topic_match,theory_match=excluded.theory_match,
              method_match=excluded.method_match,data_match=excluded.data_match,
              setting_match=excluded.setting_match,opportunity=excluded.opportunity,
              overall=excluded.overall,rationale=excluded.rationale,model=excluded.model,
              prompt_version=excluded.prompt_version,prompt_hash=excluded.prompt_hash,
              input_hash=excluded.input_hash,run_at=excluded.run_at""",
            (article['id'], pid, scores['topic'], scores['theory'], scores['method'],
             scores['data'], scores['setting'], scores['opportunity'], overall,
             scores['rationale'], metadata['model'], PROMPT_VERSION,
             metadata['prompt_hash'], metadata['input_hash'], metadata['run_at']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--profiles', required=True)
    parser.add_argument('--output-db', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--model', default='Qwen/Qwen2.5-14B-Instruct-AWQ')
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()

    profiles = load_profiles(args.profiles)
    articles = load_articles(args.input)
    if args.limit:
        articles = articles[:args.limit]
    os.makedirs(os.path.dirname(os.path.abspath(args.output_db)), exist_ok=True)
    conn = sqlite3.connect(args.output_db, timeout=30)
    ensure_tables(conn)
    phash = prompt_hash(profiles)
    started = datetime.now().isoformat()
    run_id = conn.execute("""INSERT INTO aim_runs_14b
        (stage,model,prompt_version,prompt_hash,n_input,n_output,n_error,started,notes)
        VALUES (?,?,?,?,?,0,0,?,?)""",
        ('calibration_baseline', args.model, PROMPT_VERSION, phash,
         len(articles), started, 'original aim-v1 prompt; local vLLM')).lastrowid
    conn.commit()

    done = 0
    errors = 0
    t0 = time.time()
    pending = []
    for index, article in enumerate(articles, 1):
        ihash = input_hash(article)
        existing = conn.execute(
            """SELECT 1 FROM aim_paper_labels_14b
               WHERE article_id=? AND input_hash=? AND model=?""",
            (article['id'], ihash, args.model),
        ).fetchone()
        if existing:
            done += 1
            print(f'[{index}/{len(articles)}] skip article={article["id"]}', flush=True)
            continue
        pending.append((index, article, ihash))

    def process_one(index, article, ihash):
        result = call_model(article, profiles, args.base_url, args.model,
                            args.timeout, args.retries)
        labels, profile_results, notes = validate_result(result, article, profiles)
        metadata = {'model': args.model, 'prompt_hash': phash,
                    'input_hash': ihash, 'run_at': datetime.now().isoformat()}
        return index, article, labels, profile_results, metadata, notes

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(process_one, index, article, ihash): (index, article)
            for index, article, ihash in pending
        }
        for future in as_completed(futures):
            index, article = futures[future]
            try:
                _, article, labels, profile_results, metadata, notes = future.result()
                save_result(conn, article, labels, profile_results, profiles, metadata, notes)
                conn.commit()
                done += 1
                print(f'[{done}/{len(articles)} completed; source_row={index}] '
                      f'ok article={article["id"]} elapsed={time.time()-t0:.1f}s', flush=True)
            except Exception as exc:
                errors += 1
                print(f'[source_row={index}] ERROR article={article["id"]}: {exc}', flush=True)

    conn.execute("""UPDATE aim_runs_14b SET n_output=?,n_error=?,finished=?,notes=?
                    WHERE run_id=?""",
                 (done, errors, datetime.now().isoformat(),
                  f'completed={done}; errors={errors}', run_id))
    conn.commit()
    conn.close()
    print(json.dumps({'input': len(articles), 'completed': done, 'errors': errors,
                      'seconds': round(time.time()-t0, 1)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
