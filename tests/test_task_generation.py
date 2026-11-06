"""Independent source checks for the task-generation experiment."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import task_generation as gen


class TaskGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = gen.ROOT / 'datasets/netflix_titles.csv'
        with cls.source.open(newline='', encoding='utf-8-sig') as handle:
            cls.rows = list(csv.DictReader(handle))
        cls.sha = hashlib.sha256(cls.source.read_bytes()).hexdigest()
        cls.pool = gen.build_cases(cls.rows, cls.sha, seed=42)
        cls.cases = gen.select_cases(cls.pool, 100, 42)

    def test_one_hundred_distinct_balanced_tasks(self):
        self.assertEqual(len(self.cases), 100)
        self.assertEqual(len({c['task_id'] for c in self.cases}), 100)
        self.assertEqual(len({c['question'] for c in self.cases}), 100)
        self.assertEqual(Counter(c['primitive'] for c in self.cases), dict.fromkeys(gen.PRIMITIVES, 25))

    def test_every_solution_and_distractor_recomputed_from_csv(self):
        for case in self.cases:
            with self.subTest(task=case['task_id']):
                spec = case['view']['filters']
                rows = [r for r in self.rows if spec['start_year'] <= int(r['release_year']) <= spec['end_year']
                        and (spec['type'] == 'all' or r['type'] == spec['type'])
                        and r[spec['group_by']].strip()
                        and not (spec['group_by'] == 'rating' and r['rating'].endswith(' min'))]
                counts = Counter(r[spec['group_by']] for r in rows)
                self.assertEqual(case['view']['data'], counts)
                self.assertEqual(case['solution']['group_counts'], counts)
                self.assertEqual(case['solution']['selected_row_count'], len(rows))
                self.assertEqual(case['solution']['source_sha256'], self.sha)
                op = case['operation']
                if case['primitive'] == 'Retrieve Value':
                    truth = counts[op['category']]
                elif case['primitive'] == 'Find Extremum':
                    winners = [k for k, v in counts.items() if v == max(counts.values())]
                    self.assertEqual(len(winners), 1)
                    truth = winners[0]
                elif case['primitive'] == 'Filter':
                    truth = sorted(k for k, v in counts.items() if v > op['threshold'])
                else:
                    truth = sum(counts[k] for k in op['categories'])
                self.assertEqual(case['answer'], truth)
                self.assertEqual(case['solution']['result'], truth)
                options = case['options']
                self.assertEqual({o['letter'] for o in options}, set('ABC'))
                self.assertEqual(len({json.dumps(o['value']) for o in options}), 3)
                self.assertEqual(next(o['value'] for o in options if o['letter'] == case['answer_letter']), truth)
                ranked = sorted(counts, key=lambda k: (-counts[k], k))
                for option in options:
                    tag = option['misreading']
                    if tag is None:
                        self.assertEqual(option['value'], truth)
                        continue
                    if tag == 'wrong_category':
                        expected = counts[option['parameters']['category']]
                    elif tag in ('runner_up', 'third_rank'):
                        expected = ranked[option['parameters']['rank'] - 1]
                    elif tag == 'inclusive_instead_of_strict':
                        expected = sorted(k for k, v in counts.items() if v >= op['threshold'])
                    elif tag == 'flipped_comparison':
                        expected = sorted(k for k, v in counts.items() if v < op['threshold'])
                    elif tag == 'difference_instead_of_sum':
                        a, b = op['categories']
                        expected = counts[a] - counts[b]
                    elif tag == 'omit_second_category':
                        expected = counts[op['categories'][0]]
                    else:
                        self.fail(f'Unknown misreading: {tag}')
                    self.assertEqual(option['value'], expected)
                    self.assertNotEqual(option['value'], truth)

    def test_same_seed_reproduces_cases_and_options(self):
        self.assertEqual(self.cases, gen.select_cases(gen.build_cases(self.rows, self.sha, 42), 100, 42))
        self.assertNotEqual(self.cases, gen.select_cases(self.pool, 100, 43))

    def test_insufficient_pool_is_explicit_error(self):
        with self.assertRaises(ValueError):
            gen.select_cases([], 1, 42)

    def test_duplicate_source_ids_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.csv'
            path.write_text('show_id,type,release_year,rating\nx,Movie,2000,PG\nx,Movie,2001,PG\n')
            with self.assertRaises(ValueError):
                gen.load_source(path)

    def test_bedrock_selection_and_trace(self):
        def converse(**request):
            prompt = request['messages'][0]['content'][0]['text']
            menu = json.loads(prompt.split('\n', 1)[1])
            needed = int(prompt.split()[2])
            return {'output': {'message': {'content': [{'text': json.dumps([c['task_id'] for c in menu[:needed]])}]}},
                    'stopReason': 'end_turn', 'usage': {'inputTokens': 100}}
        with tempfile.TemporaryDirectory() as directory, patch('bedrock_backend.client') as factory:
            factory.return_value.converse.side_effect = converse
            trace = Path(directory) / 'trace.jsonl'
            cases = gen.bedrock_select(self.pool, 13, 42, 'test-model', trace, batch_size=10)
            self.assertEqual(len(cases), 13)
            self.assertEqual(len({c['task_id'] for c in cases}), 13)
            self.assertEqual(factory.return_value.converse.call_count, 2)
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(len(records), 2)
            self.assertTrue(all(r['prompt'] and r['response'] and r['usage'] for r in records))

    def test_bedrock_rejects_invalid_selections_without_fallback(self):
        for payload, stop in [('{}', 'end_turn'), ('["unknown"]', 'end_turn'),
                              ('[]', 'max_tokens'), ('not json', 'end_turn')]:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory, patch('bedrock_backend.client') as factory:
                factory.return_value.converse.return_value = {
                    'output': {'message': {'content': [{'text': payload}]}}, 'stopReason': stop}
                trace = Path(directory) / 'trace.jsonl'
                with self.assertRaises(ValueError):
                    gen.bedrock_select(self.pool, 1, 42, 'test-model', trace)
                self.assertEqual(factory.return_value.converse.call_count, 3)
                self.assertEqual(len(trace.read_text().splitlines()), 3)


if __name__ == '__main__':
    unittest.main()
