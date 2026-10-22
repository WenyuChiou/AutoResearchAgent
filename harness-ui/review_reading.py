"""Pinned, project-scoped reading of original reviews; no selection authority."""
import json
import re
from pathlib import Path

MAX_REVIEWS_BYTES = 4 * 1024 * 1024
HASH = re.compile(r'[a-f0-9]{64}')


def load_review_sources(path=None, expected_sha256=None):
    from manual_materials import digest, require
    if path is None and expected_sha256 is None:
        return []
    require(path is not None and isinstance(expected_sha256, str)
            and HASH.fullmatch(expected_sha256), 'review-config-pin-required')
    path = Path(path).absolute()
    require(not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                    for p in (path, *path.parents)), 'review-config-links-rejected')
    require(path.stat().st_size <= 128 * 1024, 'review-config-too-large')
    data = path.read_bytes()
    require(len(data) <= 128 * 1024, 'review-config-too-large')
    require(digest(data) == expected_sha256, 'review-config-hash-differs')
    value = json.loads(data)
    require(isinstance(value, dict) and set(value) == {'schema_version', 'entries'}
            and type(value['schema_version']) is int and value['schema_version'] == 1
            and isinstance(value['entries'], list)
            and len(value['entries']) <= 100, 'review-config-shape-invalid')
    seen = set()
    for entry in value['entries']:
        require(isinstance(entry, dict) and set(entry) == {
            'project_ref', 'packet_file_sha256', 'delivery_root', 'delivery_manifest_sha256'
        }, 'review-source-shape-invalid')
        require(isinstance(entry['project_ref'], str) and 0 < len(entry['project_ref']) <= 128
                and isinstance(entry['delivery_root'], str), 'review-source-identity-invalid')
        require(all(isinstance(entry[k], str) and HASH.fullmatch(entry[k])
                    for k in ('packet_file_sha256', 'delivery_manifest_sha256')),
                'review-source-pin-invalid')
        key = (entry['project_ref'], entry['packet_file_sha256'])
        require(key not in seen, 'review-source-duplicate')
        seen.add(key)
    return value['entries']


def project_reviews(store, item, packet, packet_file_sha256):
    from manual_materials import digest, require
    from stage2_common import canonical_hash
    matches = [entry for entry in store.review_sources
               if entry['project_ref'] == item['project_ref']
               and entry['packet_file_sha256'] == packet_file_sha256]
    if not matches:
        return None
    require(len(matches) == 1, 'review-source-duplicate')
    entry = matches[0]
    root = store.safe_incoming(entry['delivery_root'], True)
    path = store.safe_incoming(str(root / 'review_results.json'))
    require(path.stat().st_size <= MAX_REVIEWS_BYTES, 'review-file-too-large')
    data = path.read_bytes()
    require(len(data) <= MAX_REVIEWS_BYTES, 'review-file-too-large')
    # The existing inspector authenticates all original package/selection bytes.
    # A draft may be read; its readiness and authority must never be upgraded.
    from stage2_workflow.delivery import inspect_delivery
    delivery = inspect_delivery(root, entry['delivery_manifest_sha256'])
    require(delivery['input_packet'] == packet, 'review-packet-differs')
    row = next((row for row in delivery['manifest']['files']
                if row['path'] == 'review_results.json'), None)
    require(row is not None and len(data) == row['size'] and digest(data) == row['sha256'],
            'review-file-hash-differs')
    reviews = json.loads(data)
    require(isinstance(reviews, list) and len(reviews) <= 200, 'review-records-invalid')
    candidates = {(c['candidate_id'], c['version']) for c in packet['candidates']}
    seen = set()
    for review in reviews:
        require(isinstance(review, dict), 'review-record-invalid')
        key = (review.get('candidate_id'), review.get('candidate_version'), review.get('role'))
        require(key[:2] in candidates and isinstance(key[2], str)
                and key not in seen, 'review-candidate-role-differs')
        seen.add(key)
    manifest = delivery['manifest']
    resolution_counts = {}
    for candidate in delivery['reconciliation']['candidates']:
        status = candidate['reconciliation']['status']
        resolution_counts[status] = resolution_counts.get(status, 0) + 1
    return dict(kind='V9IndependentReviewReading', project_ref=item['project_ref'],
                material_id=item['id'], packet_file_sha256=packet_file_sha256,
                packet_sha256=canonical_hash(packet),
                delivery_manifest_sha256=manifest['manifest_sha256'],
                snapshot_sha256=manifest['snapshot_sha256'], batch_sha256=manifest['batch_sha256'],
                reviews_file_sha256=digest(data), reviews_text=data.decode('utf-8'),
                delivery_status=manifest['delivery_status'], resolution_counts=resolution_counts,
                recommendations_count=len(manifest['recommendation_candidate_versions']),
                human_selection='pending',
                formal_selection_available=False, stage3_execution_authorized=False,
                scientific_acceptance=False)
