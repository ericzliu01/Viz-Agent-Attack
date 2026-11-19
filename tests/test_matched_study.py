import json

from qa_attacks.matched_study import report


def test_shared_baseline_controls_and_generation_failures_across_trials(tmp_path):
    model = 'test-model'
    spec = {'models': [model], 'repeats': 2,
            'generation_failures': [{'base_id': 'q2', 'variant': 'ipi_combined'}]}
    (tmp_path / 'spec.json').write_text(json.dumps(spec))
    rows = []
    for q in ['q1', 'q2']:
        conditions = [('clean', None), ('attack', 'cotta_50'), ('control', 'cotta_50')]
        if q == 'q1':
            conditions += [('attack', 'ipi_combined'), ('control', 'ipi_combined')]
        for condition, channel in conditions:
            rows.append({'id': f'{q}-{condition}-{channel}',
                         'attack': {'base_id': q, 'condition': condition, 'channel': channel}})
    for trial in [1, 2]:
        d = tmp_path / f'r{trial}'
        (d / 'eval/json').mkdir(parents=True)
        (d / 'attacked.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        records = []
        for row in rows:
            a = row['attack']
            answer = 'B' if a['condition'] == 'attack' else 'A'
            # Trial 1: CoTTA's q1 control is wrong; trial 2: q1 clean is wrong.
            if (trial == 1 and a['base_id'] == 'q1' and a['condition'] == 'control'
                    and a['channel'] == 'cotta_50') or (
                    trial == 2 and a['base_id'] == 'q1' and a['condition'] == 'clean'):
                answer = 'B'
            records.append({'id': row['id'], **a, 'model': model, 'pred': answer,
                            'correct': answer == 'A', 'response_protocol': 'plain-json-v1',
                            'response': json.dumps({'ans': answer, 'rationale': 'chart'}),
                            'kind': 'choice', 'answer_options': ['A', 'B'],
                            'gold': 'A', 'target': 'B', 'error': None})
        (d / f'eval/json/{model}.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))
    result = report(tmp_path)
    assert result['complete']
    cotta = result['totals'][model]['cotta_50']
    ipi = result['totals'][model]['ipi_combined']
    assert (cotta['clean_hits'], cotta['clean_n']) == (3, 3)
    assert (cotta['paired_hits'], cotta['paired_n']) == (2, 2)
    assert (ipi['clean_hits'], ipi['clean_n']) == (1, 3)
    assert (ipi['paired_hits'], ipi['paired_n']) == (1, 1)
    assert ipi['generation_failed'] == 2
