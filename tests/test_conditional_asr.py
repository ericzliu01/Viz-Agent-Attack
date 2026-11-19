import json
import pytest
from qa_attacks.conditional_asr import score


def row(q, condition, ans, channel='cotta'):
    return {'id': f'{q}-{condition}-{channel}', 'base_id': q, 'condition': condition,
            'channel': channel, 'kind': 'choice', 'gold': 'A', 'target': 'B',
            'answer_options': ['A', 'B', 'C'], 'response_protocol': 'plain-json-v1',
            'response': json.dumps({'ans': ans, 'rationale': 'chart'}) if ans else 'invalid',
            'error': None}


def test_any_error_includes_off_target_and_invalid_but_excludes_bad_clean():
    records = []
    for q, clean, attacked in [('target', 'A', 'B'), ('off-target', 'A', 'C'),
                               ('invalid-attack', 'A', None), ('correct', 'A', 'A'),
                               ('wrong-clean', 'C', 'B'), ('invalid-clean', None, 'B')]:
        records += [row(q, 'clean', clean), row(q, 'attack', attacked), row(q, 'control', 'C')]
    # A failed construction has a clean record but no attack record.
    records.append(row('no-image', 'clean', 'A'))
    assert score(records)['cotta'] == dict(attacked_trials=6, eligible=4, failed=3, targeted=1, invalid=1)


def test_missing_baseline_and_duplicates_rejected():
    with pytest.raises(ValueError, match='no clean'):
        score([row('q', 'attack', 'B')])
    clean = row('q', 'clean', 'A')
    with pytest.raises(ValueError, match='Duplicate'):
        score([clean, clean])
