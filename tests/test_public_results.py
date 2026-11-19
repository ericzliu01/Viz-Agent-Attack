import csv
import hashlib
import json

import pytest

from qa_attacks.public_results import browser_analyze, metrics, qa_observations


def reply(q, condition, ans, error=None):
    return {'id': f'{q}-{condition}', 'base_id': q, 'condition': condition,
            'channel': 'banner', 'kind': 'choice', 'gold': 'A', 'target': 'B',
            'answer_options': ['A', 'B', 'C'], 'response_protocol': 'plain-json-v1',
            'response': json.dumps({'ans': ans, 'rationale': 'observed chart'}) if ans else 'invalid',
            'error': error}


def test_failure_target_and_control_denominators_are_distinct():
    records = []
    for q, clean, attacked, control in [('target', 'A', 'B', 'A'),
            ('off-target', 'A', 'C', 'A'), ('invalid', 'A', None, 'A'),
            ('bad-control', 'A', 'B', 'C'), ('bad-clean', 'C', 'B', 'A'),
            ('right', 'A', 'A', 'A')]:
        records += [reply(q, 'clean', clean), reply(q, 'attack', attacked), reply(q, 'control', control)]
    records += [reply('transport', 'clean', 'A'), reply('transport', 'attack', None, 'timeout')]
    # No image was rendered: it must not be invented as an attack observation.
    records.append(reply('construction-failed', 'clean', 'A'))
    observed, _ = qa_observations(records)
    m = metrics(observed)
    assert (m['eligible'], m['failed'], m['targeted'], m['invalid_eligible']) == (5, 4, 2, 1)
    assert (m['paired_n'], m['paired_failed'], m['paired_targeted']) == (4, 3, 1)
    assert m['infrastructure_errors'] == 1


def test_duplicate_or_missing_clean_is_rejected():
    clean = reply('q', 'clean', 'A')
    with pytest.raises(ValueError, match='Duplicate'):
        qa_observations([clean, clean])
    with pytest.raises(ValueError, match='Missing clean'):
        qa_observations([reply('q', 'attack', 'B')])
    with pytest.raises(ValueError, match='Multiple clean'):
        qa_observations([clean, {**clean, 'id': 'different-id'}])


def test_browser_unresolved_and_chart_specific_baselines(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'tables').mkdir()
    fields = ['instance_id', 'base_id', 'question_id', 'cell', 'direction', 'subtype',
              'channel', 'model', 'target_option', 'predicted_option', 'status']
    rows = [
        ['q:bar:TT', 'q:bar', 'q', 'TT', 'none', '', '', 'model', '', 'A', 'true'],
        ['q:bar:MT', 'q:bar', 'q', 'MT', 'none', '', '', 'model', '', 'B', 'false'],
        ['q:bar:TM', 'q:bar', 'q', 'TM', 'same', 'facts', 'a11y', 'model', 'B', '', 'needs_review'],
        ['q:line:TM', 'q:line', 'q', 'TM', 'same', 'facts', 'a11y', 'model', 'B', 'B', 'false']]
    p = tmp_path / 'data/results.csv'
    with p.open('w', newline='') as f:
        w = csv.writer(f); w.writerow(fields); w.writerows(rows)
    specs = {r[0]: {'task_type': 'retrieve_value', 'chart_type': r[1].split(':')[1],
             'options': ['correct', 'misleader'], 'misleader': {'wrong_option': 'misleader'}} for r in rows}
    (tmp_path / 'data/specs.json').write_text(json.dumps(specs))
    index = {'browser_groups': [{'study': 'browser-test', 'responses': 'data/results.csv',
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'metadata': 'data/specs.json', 'planned': 5}]}
    (tmp_path / 'data/index.json').write_text(json.dumps(index))
    result, coverage = browser_analyze(tmp_path)
    overall = next(r for r in result if r['axis'] == 'all')
    assert (overall['eligible'], overall['failed'], overall['targeted']) == (1, 1, 1)
    assert overall['unresolved_eligible'] == 1
    assert overall['missing_baseline'] == 1
    assert coverage[0]['missing'] == 1
    assert coverage[0]['unresolved'] == 1
