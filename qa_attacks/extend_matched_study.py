"""Evaluate additional Bedrock vision models on an unchanged matched corpus."""
import argparse
import json
from pathlib import Path

from qa_attacks.evaluate import JSON_PROTOCOL, run
from qa_attacks.matched_study import digest, report, write


def prepare(parent, out, models, region):
    parent, out = Path(parent).resolve(), Path(out).resolve()
    if parent == out or not models or len(set(models)) != len(models):
        raise ValueError('Use a separate output directory and unique nonempty model IDs')
    source = json.loads((parent / 'spec.json').read_text())
    if source['protocol'] != JSON_PROTOCOL:
        raise ValueError('Source protocol differs')
    for key, path in [('evaluator_sha256', Path(__file__).with_name('evaluate.py')),
                      ('client_sha256', Path(__file__).parent.parent / 'pipeline/converse_agent.py')]:
        if source[key] != digest(path):
            raise ValueError(f'Evaluation code changed: {key}')
    for path, expected in source['image_hashes'].items():
        if digest(path) != expected:
            raise ValueError(f'Source image changed: {path}')
    corpora = {f'r{trial}': (parent / f'r{trial}/attacked.jsonl').read_bytes()
               for trial in range(1, source['repeats'] + 1)}
    spec = {**source, 'models': models, 'region': region,
            'parent_study': str(parent), 'parent_spec_sha256': digest(parent / 'spec.json'),
            'parent_runner_sha256': source['runner_sha256'],
            'runner_sha256': digest(__file__),
            'trial_corpus_sha256': {trial: digest(parent / trial / 'attacked.jsonl') for trial in corpora},
            'note': 'Additional models; byte-identical trial corpora and image inputs; fresh clean baselines for each model/trial; provider-default sampling; 2048 output tokens; no constrained decoding.'}
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'spec.json').exists() and json.loads((out / 'spec.json').read_text()) != spec:
        raise ValueError('Extension configuration changed; choose a new directory')
    for trial, corpus in corpora.items():
        path = out / trial / 'attacked.jsonl'
        if path.exists() and path.read_bytes() != corpus:
            raise ValueError('Existing trial corpus differs')
    write(out / 'spec.json', spec)
    for trial, corpus in corpora.items():
        path = out / trial / 'attacked.jsonl'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(corpus)
    return spec


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--models', required=True)
    p.add_argument('--region', default='us-west-2')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--prepare-only', action='store_true')
    args = p.parse_args()
    spec = prepare(args.parent, args.out, args.models.split(','), args.region)
    if args.prepare_only:
        return
    from pipeline.converse_agent import BedrockConverseClient
    client = BedrockConverseClient(region=args.region)
    for trial in range(1, spec['repeats'] + 1):
        print(f'Trial {trial}/{spec["repeats"]}', flush=True)
        run(Path(args.out) / f'r{trial}', spec['models'], mode='json',
            workers=args.workers, client=client)
        report(args.out)


if __name__ == '__main__':
    main()
