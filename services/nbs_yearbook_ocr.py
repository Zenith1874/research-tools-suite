# -*- coding: utf-8 -*-
"""Strict OCR fallback for official NBS yearbook table images.

The yearbook exposes some province tables only as high-resolution JPEG files.
This module reads only the first numeric columns and rejects the whole table
unless the layout resolves to exactly 31 province rows with adequate OCR
confidence.  It does not solve or replay website verification challenges.
"""
import re


NUMBER_RE = re.compile(r'-?[\d,]+(?:\.\d+)?')
_OCR_ENGINE = None


def _numeric_text(value):
    text = str(value or '').strip().replace('，', ',').replace(' ', '')
    if not NUMBER_RE.fullmatch(text):
        return None
    try:
        return float(text.replace(',', ''))
    except ValueError:
        return None


def parse_ocr_numeric_rows(ocr_result, needed_columns, expected_rows=31,
                           min_cells=3, min_confidence=0.90,
                           y_tolerance=8.0):
    """Turn RapidOCR boxes into province rows ordered from north to west.

    Official NBS tables have either 31 province rows or one national/local
    aggregate followed by those 31 rows.  Header/footer numbers are discarded
    because they do not form rows with at least ``min_cells`` numeric cells.
    """
    if needed_columns < 1:
        raise ValueError('needed_columns must be positive')
    numeric = []
    for item in ocr_result or []:
        if len(item) < 3:
            continue
        box, text, confidence = item[:3]
        value = _numeric_text(text)
        if value is None or not box:
            continue
        try:
            y = sum(float(point[1]) for point in box) / len(box)
            x = min(float(point[0]) for point in box)
            score = float(confidence)
        except (TypeError, ValueError, IndexError):
            continue
        numeric.append({'x': x, 'y': y, 'value': value,
                        'text': str(text), 'confidence': score})
    numeric.sort(key=lambda item: (item['y'], item['x']))

    grouped = []
    for item in numeric:
        if not grouped or abs(item['y'] - grouped[-1]['mean_y']) > y_tolerance:
            grouped.append({'mean_y': item['y'], 'cells': [item]})
        else:
            group = grouped[-1]
            group['cells'].append(item)
            group['mean_y'] = sum(cell['y'] for cell in group['cells']) / len(group['cells'])

    candidates = []
    for group in grouped:
        cells = sorted(group['cells'], key=lambda item: item['x'])
        if len(cells) < max(min_cells, needed_columns):
            continue
        candidates.append(cells)
    if len(candidates) not in (expected_rows, expected_rows + 1):
        raise ValueError(f'OCR table expected {expected_rows} or {expected_rows + 1} data rows, '
                         f'got {len(candidates)}')
    # Revenue/expenditure tables include one aggregate before the 31 provinces.
    candidates = candidates[-expected_rows:]

    rows = []
    for index, cells in enumerate(candidates):
        selected = cells[:needed_columns]
        low = [cell for cell in selected if cell['confidence'] < min_confidence]
        if low:
            raise ValueError(f'OCR row {index + 1} confidence below {min_confidence}: '
                             f'{min(cell["confidence"] for cell in low):.3f}')
        rows.append({'values': [cell['value'] for cell in selected],
                     'confidence': min(cell['confidence'] for cell in selected),
                     'raw': [cell['text'] for cell in selected]})
    return rows


def extract_nbs_yearbook_image_values(content, needed_columns, min_confidence=0.90):
    """Run local OCR on an official JPEG and return validated 31-row values."""
    if not content.startswith(b'\xff\xd8\xff'):
        raise ValueError('response is not a JPEG image')
    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError('NBS image OCR requires rapidocr_onnxruntime') from exc

    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[0] < 500 or image.shape[1] < 500:
        raise ValueError('NBS yearbook image is invalid or unexpectedly small')
    # The province name and requested totals are always in the leftmost quarter.
    # Cropping keeps OCR fast while retaining at least three numeric cells per row.
    crop_width = min(image.shape[1], max(450, 150 + 100 * needed_columns,
                                        int(image.shape[1] * 0.24)))
    cropped = image[:, :crop_width]
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    result, _elapsed = _OCR_ENGINE(cropped)
    return parse_ocr_numeric_rows(result, needed_columns,
                                  min_confidence=min_confidence)
