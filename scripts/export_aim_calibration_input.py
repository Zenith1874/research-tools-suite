# -*- coding: utf-8 -*-
"""Export the exact 200-paper calibration sample to portable JSONL."""
import argparse
import csv
import json
import sqlite3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--review-csv', default='outputs/calibration_review.csv')
    parser.add_argument('--main-db', default='pboc_data.db')
    parser.add_argument('--output', default='outputs/calibration_input_200.jsonl')
    args = parser.parse_args()

    with open(args.review_csv, encoding='utf-8-sig', newline='') as f:
        ids = [int(row['article_id']) for row in csv.DictReader(f)]
    conn = sqlite3.connect(f'file:{args.main_db}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    marks = ','.join('?' * len(ids))
    rows = conn.execute(
        f"""SELECT id,title,abstract,journal_title,publication_date
            FROM astar_articles WHERE id IN ({marks})""", ids).fetchall()
    conn.close()
    by_id = {row['id']: dict(row) for row in rows}
    missing = [article_id for article_id in ids if article_id not in by_id]
    if missing:
        raise RuntimeError(f'missing article ids: {missing}')
    with open(args.output, 'w', encoding='utf-8', newline='\n') as f:
        for article_id in ids:
            f.write(json.dumps(by_id[article_id], ensure_ascii=False) + '\n')
    print(f'exported={len(ids)} output={args.output}')


if __name__ == '__main__':
    main()
