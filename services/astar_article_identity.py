"""Conservative duplicate identity for bibliographic records.

Titles and years can repeat across distinct works, particularly book reviews,
editorials, and introductions. Only shared persistent identifiers justify
automatic hiding; conflicting DOI assignments remain visible for review.
"""

from collections import defaultdict
import re


def canonical_doi(value):
    text = str(value or '').strip().lower()
    text = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', text)
    return text if re.fullmatch(r'10\.\d{4,9}/\S+', text) else None


def canonical_openalex_id(value):
    text = str(value or '').strip()
    text = re.sub(r'^https?://openalex\.org/', '', text, flags=re.I).upper()
    return text if re.fullmatch(r'W\d+', text) else None


def duplicate_ids(rows):
    """Return later IDs in identifier-equivalent components, without mutations."""
    by_doi, by_openalex = defaultdict(list), defaultdict(list)
    parents, dois = {}, {}
    for row in rows:
        identifier = row['id']
        parents[identifier] = identifier
        doi = canonical_doi(row['doi'])
        dois[identifier] = doi
        if doi:
            by_doi[doi].append(identifier)
        openalex_id = canonical_openalex_id(row['openalex_id'])
        if openalex_id:
            by_openalex[openalex_id].append(identifier)

    def root(identifier):
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier

    def merge(group):
        keep = min(root(identifier) for identifier in group)
        for identifier in group:
            parents[root(identifier)] = keep

    for group in by_doi.values():
        if len(group) > 1:
            merge(group)
    conflicts = 0
    for group in by_openalex.values():
        if len({dois[identifier] for identifier in group if dois[identifier]}) > 1:
            conflicts += 1
            continue
        if len(group) > 1:
            merge(group)
    duplicates = sorted(identifier for identifier in parents if root(identifier) != identifier)
    return duplicates, conflicts
