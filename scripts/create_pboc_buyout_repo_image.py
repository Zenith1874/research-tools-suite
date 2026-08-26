"""Render a screenshot-style monthly buyout reverse repo table.

The image keeps the exact-date and screenshot-style calendar-month series
separate. It is a reproducible presentation artifact, not a new data source.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import sys

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / 'pboc_data.db'
DEFAULT_OUTPUT = ROOT / 'outputs' / 'pboc_buyout_reverse_repo_table_2026-08-16.png'
sys.path.insert(0, str(ROOT))

from services.pboc_buyout_reverse_repo_service import build_monthly_bucket_stock


def _periods_through_current(stock_rows, current_period):
    periods = sorted({row['period'] for row in stock_rows if row['period'] <= current_period})
    return periods


def _fmt(value, signed=False):
    if value is None or abs(float(value)) < 0.0001:
        return '—'
    number = int(round(float(value)))
    return f'{number:+,}' if signed else f'{number:,}'


def load_data(db_path, current_period):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        operations = [dict(row) for row in conn.execute('''
            SELECT operation_id,operation_date,buy_date,maturity_date,maturity_date_status,
                   amount,term_months,term_days,announcement_kind,source_title,source_url
            FROM pboc_buyout_reverse_repo_operations
            ORDER BY operation_date,amount,operation_id
        ''').fetchall()]
        stocks = [dict(row) for row in conn.execute('''
            SELECT period,outstanding_amount,monthly_bucket_outstanding_amount
            FROM pboc_buyout_reverse_repo_monthly_stock
            ORDER BY period
        ''').fetchall()]
    if not operations:
        raise RuntimeError('数据库中没有买断式逆回购逐笔操作。')
    periods = _periods_through_current(stocks, current_period)
    if not periods:
        raise RuntimeError(f'数据库中没有截至 {current_period} 的月末记录。')
    bucket_by_period = build_monthly_bucket_stock(operations)
    bucket_values = {
        period: bucket_by_period.get(period, {}).get('amount', 0.0)
        for period in periods
    }
    exact_values = {
        row['period']: row.get('outstanding_amount')
        for row in stocks if row['period'] in periods
    }
    operation_bucket_values = []
    for operation in operations:
        operation_buckets = build_monthly_bucket_stock([operation])
        operation_bucket_values.append({
            period: operation_buckets.get(period, {}).get('amount', 0.0)
            for period in periods
        })
    return operations, periods, bucket_values, exact_values, operation_bucket_values


def render(db_path, output_path, current_period, as_of):
    operations, periods, bucket_values, exact_values, operation_values = load_data(
        db_path, current_period)
    diff_values = {
        period: bucket_values.get(period, 0) - (exact_values.get(period) or 0)
        for period in periods
    }
    current_value = exact_values.get(current_period)
    current_bucket = bucket_values.get(current_period)
    previous_period = periods[-2] if len(periods) > 1 else None
    previous_value = exact_values.get(previous_period) if previous_period else None

    plt.rcParams.update({
        'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS', 'DejaVu Sans'],
        'axes.unicode_minus': False,
    })
    figure_width = max(18, 2.9 + len(periods) * 0.78)
    figure_height = max(13, 3.0 + (len(operations) + 4) * 0.30)
    fig, ax = plt.subplots(figsize=(figure_width, figure_height), dpi=180)
    fig.patch.set_facecolor('#f7f8fa')
    ax.set_facecolor('#f7f8fa')
    ax.axis('off')

    fig.text(0.03, 0.975, '央行买断式逆回购余额｜逐笔月度归集表',
             fontsize=18, fontweight='bold', color='#172033', va='top')
    fig.text(0.03, 0.948,
             f'单位：亿元｜截至 {as_of}｜业务公告从次月归集，招标公告从操作月归集；底部同时列出 exact-date 对照',
             fontsize=9.5, color='#586174', va='top')

    cards = [
        ('截至当前未到期余额', current_value, '#1d4ed8'),
        (f'{previous_period} exact-date月末', previous_value, '#475569'),
        (f'{current_period}月末已知操作路径', current_bucket, '#b45309'),
    ]
    card_y = 0.895
    card_width = 0.28
    for index, (label, value, color) in enumerate(cards):
        x = 0.03 + index * 0.31
        rect = plt.Rectangle((x, card_y - 0.045), card_width, 0.055,
                             transform=fig.transFigure, facecolor='white',
                             edgecolor='#d7dce5', linewidth=0.8)
        fig.patches.append(rect)
        fig.text(x + 0.012, card_y - 0.006, label, fontsize=8.5, color='#586174', va='top')
        fig.text(x + 0.012, card_y - 0.035, f'{_fmt(value)} 亿元', fontsize=13,
                 fontweight='bold', color=color, va='top')

    columns = ['逐笔操作（日期｜类型｜期限）'] + periods
    rows = []
    for index, operation in enumerate(operations, start=1):
        kind = '业务' if operation.get('announcement_kind') == 'business' else '招标'
        term = operation.get('term_months') or f"{operation.get('term_days')}天"
        label = f"{index:02d}  {operation['buy_date']}｜{kind}｜{term}{'M' if operation.get('term_months') else ''}｜{_fmt(operation['amount'])}"
        values = operation_values[index - 1]
        rows.append([label] + [_fmt(values[period]) for period in periods])
    rows.extend([
        ['月度归集合计'] + [_fmt(bucket_values[period]) for period in periods],
        ['exact-date月末余额'] + [_fmt(exact_values.get(period)) for period in periods],
        ['归集 − exact-date'] + [_fmt(diff_values[period], signed=True) for period in periods],
    ])

    table = ax.table(
        cellText=rows,
        colLabels=columns,
        colWidths=[0.235] + [0.765 / len(periods)] * len(periods),
        cellLoc='center',
        colLoc='center',
        bbox=[0.02, 0.075, 0.96, 0.785],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.0)

    reference_months = {'2025-07', '2025-08'}
    current_months = {'2026-07', '2026-08'}
    total_start = len(operations) + 1
    for (row_index, col_index), cell in table.get_celld().items():
        cell.set_edgecolor('#c8ced8')
        cell.set_linewidth(0.45)
        cell.PAD = 0.18
        if row_index == 0:
            cell.set_facecolor('#26354a')
            cell.get_text().set_color('white')
            cell.get_text().set_fontweight('bold')
            if col_index > 0:
                period = periods[col_index - 1]
                if period in reference_months:
                    cell.set_facecolor('#9a6700')
                if period in current_months:
                    cell.set_facecolor('#1d4ed8')
        elif col_index == 0:
            cell.get_text().set_ha('left')
            cell.set_facecolor('#eef1f5' if row_index < total_start else '#fff5cc')
            cell.get_text().set_fontweight('bold' if row_index >= total_start else 'normal')
        elif row_index >= total_start:
            if row_index == total_start:
                cell.set_facecolor('#fff1a8')
                cell.get_text().set_fontweight('bold')
            elif row_index == total_start + 1:
                cell.set_facecolor('#dbeafe')
                cell.get_text().set_fontweight('bold')
            else:
                cell.set_facecolor('#f1f5f9')
            period = periods[col_index - 1]
            if period in current_months:
                cell.set_edgecolor('#1d4ed8')
                cell.set_linewidth(1.1)
        else:
            period = periods[col_index - 1]
            text = cell.get_text().get_text()
            cell.set_facecolor('#e5eefc' if text != '—' else 'white')
            if period in reference_months:
                cell.set_facecolor('#fff7d6' if text == '—' else '#ffe7a3')
            if period in current_months:
                cell.set_facecolor('#dbeafe' if text == '—' else '#bfdbfe')

    fig.text(0.03, 0.035,
             '来源：中国人民银行买断式逆回购业务/招标公告（当前库 44 笔）。所有余额为 derived；2026-08 尚未结束，月末值是截至当前已知操作路径。',
             fontsize=8.5, color='#586174', va='bottom')
    fig.text(0.97, 0.035, '蓝色：2026-07/08｜金色：截图对照 2025-07/08',
             fontsize=8.5, color='#586174', ha='right', va='bottom')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.18)
    plt.close(fig)
    return {
        'output': str(output_path),
        'operations': len(operations),
        'periods': [periods[0], periods[-1]],
        'current_exact': current_value,
        'current_bucket': current_bucket,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--period', default='2026-08')
    parser.add_argument('--as-of', default='2026-08-16')
    args = parser.parse_args()
    result = render(args.db, args.output, args.period, args.as_of)
    print(result)


if __name__ == '__main__':
    main()
