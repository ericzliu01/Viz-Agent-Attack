"""Fresh, paired JSON evaluation of existing IPI and CoTTA pilot images."""
import argparse
from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import random

from qa_attacks.evaluate import run, _NOTICED, JSON_PROTOCOL
from qa_attacks.ipi_study import load_rows, summarize_trial


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def prepare(out, ipi, cotta, repeats=5):
    out, ipi, cotta = map(lambda p: Path(p).resolve(), (out, ipi, cotta))
    sources = [(ipi, {'combined': 'ipi_combined'}),
               (cotta, {'cotta': 'cotta_50', 'trigger_only': 'trigger_only'})]
    rows, clean, image_hashes = [], {}, {}
    for source, channels in sources:
        for original in load_rows(source / 'attacked.jsonl'):
            row = copy.deepcopy(original)
            a = row['attack']
            if a['condition'] != 'clean' and a['channel'] not in channels:
                continue
            row['images'] = [str((source / p).resolve()) for p in row['images']]
            hashes = [digest(p) for p in row['images']]
            image_hashes.update(zip(row['images'], hashes))
            if a['condition'] == 'clean':
                identity = (row['conversation'], hashes, a['target'])
                if a['base_id'] in clean:
                    if clean[a['base_id']] != identity:
                        raise ValueError('Sources differ in question, gold, target or clean image')
                    continue
                clean[a['base_id']] = identity
            else:
                if a['base_id'] not in clean:
                    raise ValueError('Attack lacks baseline')
                conversation, originals, target = clean[a['base_id']]
                if row['conversation'] != conversation or hashes[1:] != originals[1:] or a['target'] != target:
                    raise ValueError('Attack changes task or reference crops')
                a['channel'] = channels[a['channel']]
                row['id'] = f"{a['base_id']}__{a['channel']}__{a['condition']}"
                a['audit'] = str((source / a['audit']).resolve())
                audit = json.loads(Path(a['audit']).read_text())
                if audit.get('output_sha256') and audit['output_sha256'] != hashes[0]:
                    raise ValueError('Attack hash differs from audit')
            row['source_run'] = str(source)
            rows.append(row)
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate corpus IDs')
    failures = [{'base_id': f['base_id'], 'variant': 'ipi_combined', 'error': f['error']}
                for f in json.loads((ipi / 'manifest.json').read_text())['failures']
                if f['variant'] == 'combined']
    spec = {'models': ['us.anthropic.claude-haiku-5-5', 'us.openai.gpt-5.6-luna'],
            'repeats': repeats, 'protocol': JSON_PROTOCOL, 'rows_per_trial': len(rows),
            'base_ids': sorted(clean), 'sources': {str(p): digest(p / 'attacked.jsonl') for p, _ in sources},
            'image_hashes': image_hashes, 'generation_failures': failures,
            'evaluator_sha256': digest(Path(__file__).with_name('evaluate.py')),
            'client_sha256': digest(Path(__file__).parent.parent / 'pipeline/converse_agent.py'),
            'runner_sha256': digest(__file__), 'shuffle_seed': 20261119,
            'note': 'Fresh calls; same clean response shared by methods within each trial; original payloads and budgets retained.'}
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'spec.json').exists() and json.loads((out / 'spec.json').read_text()) != spec:
        raise ValueError('Study changed; choose a fresh output directory')
    write(out / 'spec.json', spec)
    for trial in range(1, repeats + 1):
        directory = out / f'r{trial}'
        directory.mkdir(exist_ok=True)
        shuffled = rows.copy()
        random.Random(spec['shuffle_seed'] + trial).shuffle(shuffled)
        corpus = ''.join(json.dumps(r) + '\n' for r in shuffled)
        path = directory / 'attacked.jsonl'
        if path.exists() and path.read_text() != corpus:
            raise ValueError('Trial corpus changed')
        path.write_text(corpus)
    return spec


def report(out):
    out = Path(out)
    spec = json.loads((out / 'spec.json').read_text())
    totals = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    trials, mentions = {}, []
    for trial in range(1, spec['repeats'] + 1):
        directory = out / f'r{trial}'
        expected = load_rows(directory / 'attacked.jsonl')
        for model in spec['models']:
            path = directory / 'eval/json' / f'{model}.jsonl'
            records = load_rows(path) if path.exists() else []
            if not {r['id'] for r in records} <= {r['id'] for r in expected}:
                raise ValueError('Unexpected response ID')
            summary = summarize_trial(expected, records, spec['generation_failures'])
            trials[f'{model}/r{trial}'] = summary
            for variant, counts in summary['groups'].items():
                for key, value in counts.items():
                    totals[model][variant][key] += value
            for r in records:
                text = r.get('rationale') or r.get('response') or ''
                if _NOTICED.search(text):
                    mentions.append({'trial': trial, 'model': model, 'id': r['id'],
                                     'condition': r['condition'], 'channel': r['channel'],
                                     'pred': r['pred'], 'correct': r['correct'], 'text': text})
    complete = all(v['missing'] == 0 for v in trials.values())
    result = {'complete': complete, 'totals': totals, 'trials': trials,
              'mention_candidates': mentions, 'mention_note': 'Broad keyword screen, requires manual adjudication; absence is not evidence of non-perception.'}
    lines = ['# Matched IPI / CoTTA JSON pilot', '', f'Complete: **{complete}**. Five questions, five fresh trials, shared clean baseline per trial.',
             'Original questions, gold answers, wrong targets, source images and reference crops verified equal. Payload wording and pixel budgets are method-specific.',
             'Construction failures remain in clean-correct denominators. Missing/invalid responses are not successes. Repeated trials are not independent images.', '']
    for model, variants in totals.items():
        mine = [v for k, v in trials.items() if k.startswith(model + '/')]
        lines += [f'## {model}', '', f"Clean correct: {sum(v['clean_correct'] for v in mine)}/{sum(v['clean_planned'] for v in mine)}. Responses: {sum(v['answered'] for v in mine)}/{sum(v['expected'] for v in mine)}. Invalid: {sum(v['invalid'] for v in mine)}.", '',
                  '| Method | Clean-correct targeted ASR | Clean + control correct ASR | Generation failures | Missing / invalid attacks |',
                  '|---|---:|---:|---:|---:|']
        for variant, g in variants.items():
            lines.append(f"| {variant} | {g['clean_hits']}/{g['clean_n']} | {g['paired_hits']}/{g['paired_n']} | {g['generation_failed']} | {g['missing']} / {g['invalid']} |")
        lines.append('')
    write(out / 'results.json', result)
    (out / 'results.md').write_text('\n'.join(lines) + '\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['run', 'prepare', 'report'])
    p.add_argument('--out', required=True)
    p.add_argument('--ipi')
    p.add_argument('--cotta')
    p.add_argument('--workers', type=int, default=8)
    args = p.parse_args()
    if args.command == 'report':
        report(args.out)
        return
    spec = prepare(args.out, args.ipi, args.cotta)
    if args.command == 'run':
        for trial in range(1, spec['repeats'] + 1):
            print(f'Trial {trial}/{spec["repeats"]}', flush=True)
            run(Path(args.out) / f'r{trial}', spec['models'], mode='json', workers=args.workers)
            report(args.out)


if __name__ == '__main__':
    main()
