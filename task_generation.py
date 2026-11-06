"""Generate auditable Netflix tasks; facts and solutions are computed locally."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import shlex
from collections import Counter

ROOT = Path(__file__).resolve().parent
PRIMITIVES = ['Retrieve Value', 'Find Extremum', 'Filter', 'Compute Derived Value']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def load_env(path):
    """Read literal KEY=VALUE entries, without executing shell code."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, sep, raw = line.partition('=')
        if not sep or not key.strip().replace('_', '').isalnum():
            raise ValueError('Invalid environment entry')
        parts = shlex.split(raw, comments=True)
        if len(parts) > 1:
            raise ValueError('Environment values containing spaces must be quoted')
        os.environ.setdefault(key.strip(), parts[0] if parts else '')


def load_source(path):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    required = {'show_id', 'type', 'release_year', 'rating'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('Expected Netflix schema')
    if len({r['show_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate show_id')
    return rows, hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_specs(rows):
    years = sorted({int(r['release_year']) for r in rows})
    result = []
    for start in years:
        for width in (3, 5, 10):
            end = start + width - 1
            if end > max(years):
                continue
            for kind in ('Movie', 'TV Show', 'all'):
                for group in ('release_year', 'rating'):
                    result.append({'start_year': start, 'end_year': end, 'type': kind, 'group_by': group})
    return result


def build_cases(rows, source_hash, seed=0):
    """Produce a deterministic pool; invalid/ambiguous candidates are omitted."""
    cases = []
    for spec in candidate_specs(rows):
        selected = [r for r in rows if spec['start_year'] <= int(r['release_year']) <= spec['end_year']
                    and (spec['type'] == 'all' or r['type'] == spec['type'])]
        # Blank ratings and known misplaced durations are not rating categories.
        selected = [r for r in selected if r[spec['group_by']].strip()
                    and (spec['group_by'] != 'rating' or not r['rating'].endswith(' min'))]
        counts = dict(sorted(Counter(r[spec['group_by']] for r in selected).items()))
        if len(counts) < 3:
            continue
        labels = list(counts)
        ordered = sorted(counts, key=lambda k: (-counts[k], k))
        scope = f"Netflix titles released from {spec['start_year']} through {spec['end_year']} (inclusive), type={spec['type']}, grouped by {spec['group_by']}"
        scope += '; only nonempty valid categories shown'
        variants = []
        a, b, c = ordered[:3]
        variants.append(('Retrieve Value', {'category': a}, f'For {scope}, how many titles are in category {a}?',
                         counts[a], [(counts[b], 'wrong_category', {'category': b}), (counts[c], 'wrong_category', {'category': c})],
                         f'Look up category {a}: {counts[a]} titles.'))
        if counts[a] > counts[b]:
            variants.append(('Find Extremum', {'direction': 'maximum'}, f'For {scope}, which category has the most titles?',
                             a, [(b, 'runner_up', {'rank': 2}), (c, 'third_rank', {'rank': 3})],
                             f'Sort counts descending. {a} has {counts[a]}, greater than every other category.'))
        threshold = counts[b]
        matching = sorted(k for k, v in counts.items() if v > threshold)
        inclusive = sorted(k for k, v in counts.items() if v >= threshold)
        opposite = sorted(k for k, v in counts.items() if v < threshold)
        if matching and opposite:
            variants.append(('Filter', {'operator': '>', 'threshold': threshold}, f'For {scope}, which categories have strictly more than {threshold} titles?',
                             matching, [(inclusive, 'inclusive_instead_of_strict', {'operator': '>='}), (opposite, 'flipped_comparison', {'operator': '<'})],
                             f'Keep exactly the categories whose count > {threshold}: {", ".join(matching)}.'))
        variants.append(('Compute Derived Value', {'operation': 'sum', 'categories': [a, b]}, f'For {scope}, what is the combined title count for categories {a} and {b}?',
                         counts[a] + counts[b], [(counts[a] - counts[b], 'difference_instead_of_sum', {}), (counts[a], 'omit_second_category', {})],
                         f'Add the two counts: {counts[a]} + {counts[b]} = {counts[a] + counts[b]}.'))
        for primitive, operation, question, truth, wrong, explanation in variants:
            values = [truth] + [w[0] for w in wrong]
            if len({json.dumps(v, sort_keys=True) for v in values}) != 3:
                continue
            identity = {'source_sha256': source_hash, 'view': spec, 'primitive': primitive, 'operation': operation}
            task_id = 'netflix_' + digest(identity)
            options = [{'option_id': 'truth', 'value': truth, 'misreading': None}]
            options += [{'option_id': f'wrong_{i}', 'value': value, 'misreading': tag, 'parameters': params}
                        for i, (value, tag, params) in enumerate(wrong, 1)]
            random.Random(f'{seed}:{task_id}').shuffle(options)
            for letter, option in zip('ABC', options):
                option['letter'] = letter
                option['text'] = ', '.join(option['value']) if isinstance(option['value'], list) else str(option['value'])
            cases.append({'task_id': task_id, 'dataset': 'netflix', 'primitive': primitive,
                          'question': question, 'options': options, 'answer': truth,
                          'answer_letter': next(o['letter'] for o in options if o['option_id'] == 'truth'),
                          'view_id': 'view_' + digest({'source': source_hash, **spec}),
                          'view': {'filters': spec, 'aggregation': 'count_rows', 'data': counts,
                                   'chart_type': 'bar', 'unit': 'titles'},
                          'operation': operation, 'solution': {'explanation': explanation,
                          'source_sha256': source_hash, 'selected_row_count': len(selected),
                          'selected_ids_sha256': hashlib.sha256(json.dumps(sorted(r['show_id'] for r in selected)).encode()).hexdigest(),
                          'group_counts': counts, 'result': truth}})
    return cases


def select_cases(pool, count, seed):
    rng = random.Random(seed)
    buckets = {p: [c for c in pool if c['primitive'] == p] for p in PRIMITIVES}
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected = []
    for i in range(count):
        bucket = buckets[PRIMITIVES[i % len(PRIMITIVES)]]
        if not bucket:
            raise ValueError('Not enough distinct tasks for requested count')
        selected.append(bucket.pop())
    return selected


def bedrock_select(pool, count, seed, model, trace_path, batch_size=10):
    """LLM selects task designs from a code-validated menu, never authors facts."""
    import bedrock_backend
    if count < 1 or batch_size < 1:
        raise ValueError('count and batch_size must be positive')
    # Preflight all quotas before any paid requests.
    candidates = select_cases(pool, count * 3, seed)
    chosen = []
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open('w') as trace:
        for offset in range(0, count, batch_size):
            needed = min(batch_size, count - offset)
            menu = candidates[offset * 3:(offset + needed) * 3]
            prompt = ('Select exactly ' + str(needed) + ' distinct task_ids from this menu for a varied chart-reading benchmark. '
                      'Balance task primitives and year ranges. Return only a JSON array of task_id strings. '
                      'Do not calculate answers or write extra text.\n' + json.dumps([
                          {'task_id': c['task_id'], 'primitive': c['primitive'], 'question': c['question']} for c in menu]))
            allowed = {c['task_id']: c for c in menu}
            for attempt in range(3):
                response = bedrock_backend.client().converse(
                    modelId=model, messages=[{'role': 'user', 'content': [{'text': prompt}]}],
                    inferenceConfig={'maxTokens': 2048})
                raw = ''.join(block.get('text', '') for block in response.get('output', {}).get('message', {}).get('content', []))
                usage = response.get('usage', {})
                trace.write(json.dumps({'model': model, 'seed': seed, 'offset': offset, 'attempt': attempt,
                                        'prompt': prompt, 'response': raw, 'usage': usage, 'stop_reason': response.get('stopReason')}) + '\n')
                trace.flush()
                try:
                    if response.get('stopReason') != 'end_turn':
                        raise ValueError('Incomplete Bedrock response')
                    ids = json.loads(raw)
                    if not isinstance(ids, list) or len(ids) != needed or any(not isinstance(x, str) for x in ids):
                        raise ValueError('Wrong selection shape')
                    if len(set(ids)) != needed or any(x not in allowed for x in ids):
                        raise ValueError('Unknown or duplicate selection')
                except (ValueError, TypeError):
                    continue
                chosen.extend(allowed[x] for x in ids)
                break
            else:
                raise ValueError('Bedrock failed to return a valid selection after three attempts')
    if len(chosen) != count or len({c['task_id'] for c in chosen}) != count:
        raise ValueError('Incorrect or duplicate final selection')
    return chosen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'datasets/netflix_titles.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'tasks/generated/netflix.json')
    parser.add_argument('--count', type=int, default=100)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--mode', choices=['template', 'bedrock'], default='template')
    parser.add_argument('--model', default=os.getenv('BEDROCK_MODEL_ID'))
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    if args.count < 1:
        parser.error('--count must be positive')
    rows, sha = load_source(args.source)
    pool = build_cases(rows, sha, args.seed)
    if args.mode == 'bedrock':
        load_env(args.env_file)
        model = args.model or os.getenv('BEDROCK_MODEL_ID') or os.getenv('AWS_BEDROCK_MODEL_ID')
        if not model:
            parser.error('--model or BEDROCK_MODEL_ID is required')
        cases = bedrock_select(pool, args.count, args.seed, model, args.output.with_suffix('.trace.jsonl'))
    else:
        model = None
        cases = select_cases(pool, args.count, args.seed)
    result = {'schema_version': 1, 'generator_version': 1, 'mode': args.mode, 'model': model,
              'seed': args.seed, 'source': str(args.source), 'source_sha256': sha,
              'source_rows': len(rows), 'case_count': len(cases),
              'cleaning': 'Exclude empty grouping categories; exclude rating values ending in min. Count each show_id once.',
              'cases': cases}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(args.output)
    print(f'Generated {len(cases)} cases: {args.output}')


if __name__ == '__main__':
    main()
