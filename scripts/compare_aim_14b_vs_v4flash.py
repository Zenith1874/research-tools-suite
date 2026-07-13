# -*- coding: utf-8 -*-
"""Compare local Qwen 14B stage-A outputs with V4-Flash and human checks."""
import argparse
import csv
import json
import math
import sqlite3
from collections import defaultdict


TARGET_PROFILES = ('ai_in_organizations', 'employee_wellbeing', 'digital_trace_methods')


def ro_connect(path):
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def json_list(value):
    try:
        parsed = json.loads(value or '[]')
        return parsed if isinstance(parsed, list) else [str(parsed)]
    except Exception:
        return []


def load_human(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return {int(row['article_id']): row for row in csv.DictReader(f)}


def load_scores(conn, table):
    scores = defaultdict(dict)
    for row in conn.execute(f'SELECT * FROM {table}'):
        scores[row['article_id']][row['profile_id']] = dict(row)
    return scores


def load_labels(conn, table):
    return {row['article_id']: dict(row) for row in conn.execute(f'SELECT * FROM {table}')}


def score(scores, article_id, profile_id):
    value = scores.get(article_id, {}).get(profile_id, {}).get('overall')
    return round(float(value), 1) if value is not None else None


def best(scores, article_id):
    choices = [(profile, row.get('overall'))
               for profile, row in scores.get(article_id, {}).items()
               if row.get('overall') is not None]
    if not choices:
        return None, None
    profile, value = max(choices, key=lambda item: float(item[1]))
    return profile, round(float(value), 1)


def human_class(value):
    if value.startswith('✓'):
        return 'positive'
    if value.startswith('✗'):
        return 'negative'
    if value.startswith('△'):
        return 'borderline'
    return 'unreviewed'


def safe_rate(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def global_metrics(reviewed_ids, human, scores, threshold, profiles=None):
    tp = fp = tn = fn = 0
    for article_id in reviewed_ids:
        cls = human_class(human[article_id]['my_judgement_相关吗'])
        if cls not in ('positive', 'negative'):
            continue
        use_profiles = profiles or tuple(scores.get(article_id, {}).keys())
        values = [score(scores, article_id, profile) for profile in use_profiles]
        predicted = max((v for v in values if v is not None), default=-1) >= threshold
        if cls == 'positive' and predicted:
            tp += 1
        elif cls == 'positive':
            fn += 1
        elif predicted:
            fp += 1
        else:
            tn += 1
    return {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
            'precision': safe_rate(tp, tp + fp), 'recall': safe_rate(tp, tp + fn),
            'false_positive_rate': safe_rate(fp, fp + tn)}


def profile_false_acceptance(negative_ids, scores, profile, threshold):
    accepted = [article_id for article_id in negative_ids
                if (score(scores, article_id, profile) or -1) >= threshold]
    return accepted, safe_rate(len(accepted), len(negative_ids))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--calibration', default='outputs/calibration_review.csv')
    parser.add_argument('--human', default='outputs/calibration_review_codex_checks.csv')
    parser.add_argument('--v4-db', default='data/astar_interest.db')
    parser.add_argument('--q14-db', default='outputs/astar_interest_14b_calibration.db')
    parser.add_argument('--main-db', default='pboc_data.db')
    parser.add_argument('--output', default='outputs/compare_14b_vs_v4flash.csv')
    parser.add_argument('--summary', default='outputs/compare_14b_vs_v4flash_summary.md')
    args = parser.parse_args()

    with open(args.calibration, encoding='utf-8-sig', newline='') as f:
        calibration = list(csv.DictReader(f))
    human = load_human(args.human)
    v4_conn = ro_connect(args.v4_db)
    q14_conn = ro_connect(args.q14_db)
    main_conn = ro_connect(args.main_db)
    v4_scores = load_scores(v4_conn, 'aim_profile_scores')
    q14_scores = load_scores(q14_conn, 'aim_profile_scores_14b')
    v4_labels = load_labels(v4_conn, 'aim_paper_labels')
    q14_labels = load_labels(q14_conn, 'aim_paper_labels_14b')

    fields = [
        'article_id', 'title', 'journal', 'human_label', 'human_notes',
        'v4_best_profile', 'v4_best_overall', 'q14_best_profile', 'q14_best_overall',
    ]
    for profile in TARGET_PROFILES:
        fields += [f'v4_{profile}', f'q14_{profile}', f'delta_{profile}']
    fields += ['v4_topics', 'q14_topics', 'v4_methods', 'q14_methods',
               'v4_evidence', 'q14_evidence', 'q14_uncertainty',
               'q14_validation_notes']

    output_rows = []
    for row in calibration:
        article_id = int(row['article_id'])
        v4_best_profile, v4_best_overall = best(v4_scores, article_id)
        q14_best_profile, q14_best_overall = best(q14_scores, article_id)
        h = human.get(article_id, {})
        out = {
            'article_id': article_id, 'title': row['title'], 'journal': row['journal'],
            'human_label': h.get('my_judgement_相关吗', ''),
            'human_notes': h.get('my_notes', ''),
            'v4_best_profile': v4_best_profile, 'v4_best_overall': v4_best_overall,
            'q14_best_profile': q14_best_profile, 'q14_best_overall': q14_best_overall,
        }
        for profile in TARGET_PROFILES:
            v4_value = score(v4_scores, article_id, profile)
            q14_value = score(q14_scores, article_id, profile)
            out[f'v4_{profile}'] = v4_value
            out[f'q14_{profile}'] = q14_value
            out[f'delta_{profile}'] = (round(q14_value - v4_value, 1)
                                       if v4_value is not None and q14_value is not None else None)
        vl = v4_labels.get(article_id, {})
        ql = q14_labels.get(article_id, {})
        out.update({
            'v4_topics': '; '.join(json_list(vl.get('research_topics_json'))),
            'q14_topics': '; '.join(json_list(ql.get('research_topics_json'))),
            'v4_methods': '; '.join(json_list(vl.get('methods_json'))),
            'q14_methods': '; '.join(json_list(ql.get('methods_json'))),
            'v4_evidence': ' | '.join(json_list(vl.get('evidence_spans_json'))),
            'q14_evidence': ' | '.join(json_list(ql.get('evidence_spans_json'))),
            'q14_uncertainty': ql.get('uncertainty'),
            'q14_validation_notes': ql.get('validation_notes'),
        })
        output_rows.append(out)

    with open(args.output, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    reviewed_ids = [article_id for article_id in human
                    if human_class(human[article_id]['my_judgement_相关吗']) != 'unreviewed']
    negative_ids = [article_id for article_id in human
                    if human_class(human[article_id]['my_judgement_相关吗']) == 'negative']
    positive_ids = [article_id for article_id in human
                    if human_class(human[article_id]['my_judgement_相关吗']) == 'positive']
    borderline_ids = [article_id for article_id in human
                      if human_class(human[article_id]['my_judgement_相关吗']) == 'borderline']

    lines = [
        '# Qwen2.5-14B-AWQ vs DeepSeek V4-Flash 校准对比', '',
        f'- 校准论文：{len(calibration)}篇',
        f'- 人工已审：{len(reviewed_ids)}篇（相关{len(positive_ids)}、边界{len(borderline_ids)}、不相关{len(negative_ids)}）',
        '- 分数阈值：60；边界样本不进入正负指标。',
        '- “三画像”指 ai_in_organizations / employee_wellbeing / digital_trace_methods。', '',
        '## 综合分类（六画像取最高分）', '',
        '| 模型 | TP | FP | TN | FN | Precision | Recall | FPR |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for label, scores in [('V4-Flash', v4_scores), ('Qwen14B', q14_scores)]:
        m = global_metrics(reviewed_ids, human, scores, 60)
        lines.append(f"| {label} | {m['tp']} | {m['fp']} | {m['tn']} | {m['fn']} | "
                     f"{m['precision']}% | {m['recall']}% | {m['false_positive_rate']}% |")

    lines += ['', '## 三画像对人工反例的误收', '',
              '| 画像 | V4误收/9 | V4 FPR | 14B误收/9 | 14B FPR |',
              '|---|---:|---:|---:|---:|']
    false_accept_details = []
    for profile in TARGET_PROFILES:
        v4_ids, v4_rate = profile_false_acceptance(negative_ids, v4_scores, profile, 60)
        q14_ids, q14_rate = profile_false_acceptance(negative_ids, q14_scores, profile, 60)
        lines.append(f'| {profile} | {len(v4_ids)}/9 | {v4_rate}% | '
                     f'{len(q14_ids)}/9 | {q14_rate}% |')
        false_accept_details.append((profile, v4_ids, q14_ids))

    lines += ['', '## 阈值敏感性（三画像取最高分）', '',
              '| 阈值 | V4 FP/9 | V4 Recall | 14B FP/9 | 14B Recall |',
              '|---:|---:|---:|---:|---:|']
    for threshold in (50, 60, 70):
        vm = global_metrics(reviewed_ids, human, v4_scores, threshold, TARGET_PROFILES)
        qm = global_metrics(reviewed_ids, human, q14_scores, threshold, TARGET_PROFILES)
        lines.append(f"| {threshold} | {vm['fp']}/9 | {vm['recall']}% | "
                     f"{qm['fp']}/9 | {qm['recall']}% |")

    dropped = sum(1 for label in q14_labels.values()
                  if label.get('validation_notes') != 'dropped_nonverbatim_evidence=0')
    dropped_spans = sum(
        int((label.get('validation_notes') or 'dropped_nonverbatim_evidence=0').rsplit('=', 1)[-1])
        for label in q14_labels.values()
    )
    uncertain = sum(int(label.get('uncertainty') or 0) for label in q14_labels.values())
    article_ids = [int(row['article_id']) for row in calibration]
    marks = ','.join('?' * len(article_ids))
    abstracts = {row['id']: row['abstract'] or '' for row in main_conn.execute(
        f'SELECT id,abstract FROM astar_articles WHERE id IN ({marks})', article_ids)}
    v4_nonverbatim = 0
    for article_id, label in v4_labels.items():
        if article_id not in abstracts:
            continue
        spans = json_list(label.get('evidence_spans_json'))
        if any(span not in abstracts.get(article_id, '') for span in spans):
            v4_nonverbatim += 1
    q14_incomplete_rows = q14_conn.execute("""SELECT COUNT(*) FROM aim_profile_scores_14b
        WHERE topic_match IS NULL OR theory_match IS NULL OR method_match IS NULL
           OR data_match IS NULL OR setting_match IS NULL OR opportunity IS NULL""").fetchone()[0]
    q14_incomplete_papers = q14_conn.execute("""SELECT COUNT(DISTINCT article_id)
        FROM aim_profile_scores_14b
        WHERE topic_match IS NULL OR theory_match IS NULL OR method_match IS NULL
           OR data_match IS NULL OR setting_match IS NULL OR opportunity IS NULL""").fetchone()[0]
    v4_best_values = [float(row['v4_best_overall']) for row in output_rows]
    q14_best_values = [float(row['q14_best_overall']) for row in output_rows]
    lines += ['', '## 数据纪律', '',
              f'- 14B完整结果：{len(q14_labels)}/200篇。',
              f'- 14B标记 uncertainty：{uncertain}篇。',
              f'- 14B产生非逐字证据：{dropped}篇、{dropped_spans}段；验证器已丢弃，未写入有效证据字段。',
              f'- V4-Flash原结果中有非逐字证据：{v4_nonverbatim}篇（旧流程未做写入前过滤）。',
              f'- 14B画像分存在缺失维度：{q14_incomplete_rows}/1200行，涉及{q14_incomplete_papers}篇。',
              f'- 最佳分等于0：V4 {sum(v == 0 for v in v4_best_values)}篇，14B {sum(v == 0 for v in q14_best_values)}篇；最佳分等于100：V4 {sum(v == 100 for v in v4_best_values)}篇，14B {sum(v == 100 for v in q14_best_values)}篇。',
              '- 原始V4-Flash表和主论文库均以只读方式打开。', '',
              '## 阶段A判定', '',
              '**未通过，不进入阶段B。** 原提示词下14B同时表现出更高误收、更低召回、分数两极化、画像维度偶发缺失和更高的非逐字证据产生率。建议先收紧画像与JSON schema，再用同一200篇复测。', '',
              '## 人工反例误收明细', '']
    title_by_id = {int(row['article_id']): row['title'] for row in calibration}
    for profile, v4_ids, q14_ids in false_accept_details:
        lines.append(f'### {profile}')
        lines.append('')
        lines.append('- V4：' + ('；'.join(f'{i} {title_by_id[i]}' for i in v4_ids) or '无'))
        lines.append('- 14B：' + ('；'.join(f'{i} {title_by_id[i]}' for i in q14_ids) or '无'))
        lines.append('')

    with open(args.summary, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines).rstrip() + '\n')
    v4_conn.close()
    q14_conn.close()
    main_conn.close()
    print(f'rows={len(output_rows)} output={args.output} summary={args.summary}')


if __name__ == '__main__':
    main()
