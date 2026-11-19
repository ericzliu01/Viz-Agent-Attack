"""Generation invariants; actual browser validation is a separate CLI."""
import json
import copy
from pathlib import Path
import tempfile
import unittest

import generated_attack_pipeline as pipeline
from validate_generated_corpus import check_manifest, representatives

ROOT = Path(__file__).resolve().parents[1]


class GeneratedAttackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        source = json.loads((ROOT/'tasks/generated/netflix-bedrock.json').read_text())
        # Include each primitive so compatibility rejection is exercised.
        chosen = {}
        for case in source['cases']:
            chosen.setdefault(case['primitive'], case)
        source['cases'] = list(chosen.values())
        source['case_count'] = len(source['cases'])
        cls.source = cls.root / 'tasks.json'
        cls.source.write_text(json.dumps(source))
        cls.output = cls.root / 'corpus'
        cls.manifest = pipeline.build_corpus(cls.source, cls.output)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_all_libraries_have_clean_views(self):
        self.assertEqual(len(self.manifest['clean']), 16)
        self.assertEqual({c['library'] for c in self.manifest['clean']}, {'d3','plotly','chartjs','vega-lite'})
        check_manifest(self.output)

    def test_every_library_has_every_attack_family(self):
        for library in ('d3','plotly','chartjs','vega-lite'):
            types = {a['attack_type'] for a in self.manifest['attacks'] if a['library'] == library}
            for kind in ('mt_highlight','tm_aria','tm_css_hidden','tm_alt','tm_console',
                         'reasoning_title','reasoning_annotation','reasoning_persona',
                         'cognitive_rag','cognitive_memory','cognitive_icl','action_marker'):
                self.assertIn(kind, types)

    def test_incompatible_mt_is_skipped(self):
        derived = {c['task_id'] for c in self.manifest['cases'] if c['primitive'] == 'Compute Derived Value'}
        self.assertTrue(derived)
        self.assertFalse(any(a['task_id'] in derived and a['attack_type'] == 'mt_highlight' for a in self.manifest['attacks']))
        self.assertTrue(self.manifest['skipped'])

    def test_cognitive_controls_and_safe_metadata(self):
        for attack in self.manifest['attacks']:
            html = (self.output/'public'/attack['page']).read_text()
            self.assertNotIn('"solution":', html)
            self.assertNotIn('"option_id": "truth"', html)
            if attack['attack_type'].startswith('cognitive_'):
                self.assertTrue(attack['memory'])
                self.assertTrue(attack['baseline_memory'])
                self.assertNotEqual(attack['memory'], attack['baseline_memory'])

    def test_untrusted_text_is_escaped(self):
        case = copy.deepcopy(self.manifest['cases'][0])
        marker = '</script><script>window.INJECTED=1</script>'
        case['question'] = marker
        case['view']['filters']['type'] = marker
        case['view']['data'][marker] = 17
        for library in ('d3', 'plotly', 'chartjs', 'vega-lite'):
            page = pipeline.clean_page(case, library)
            self.assertNotIn(marker, page)
            self.assertIn('\\u003c/script\\u003e', page)
            self.assertIn('&lt;script&gt;', page)

    def test_nonfinite_counts_and_unsafe_ids_rejected(self):
        for value in (float('nan'), float('inf'), -1, True):
            case = copy.deepcopy(self.manifest['cases'][0])
            case['view']['data'][next(iter(case['view']['data']))] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                pipeline.validate_case(case)
        case = copy.deepcopy(self.manifest['cases'][0])
        case['task_id'] = '../escape'
        with self.assertRaises(ValueError):
            pipeline.validate_case(case)

    def test_aria_payload_has_renderer_independent_wrapper(self):
        for attack in self.manifest['attacks']:
            if attack['attack_type'] == 'tm_aria':
                page = (self.output / 'public' / attack['page']).read_text()
                self.assertIn('id="attack-aria"', page)
                self.assertIn('aria-label=', page)

    def test_representative_selection_covers_library_type_pairs(self):
        selected = representatives(self.manifest)
        expected = {(a['library'],a['attack_type']) for a in self.manifest['attacks']}
        self.assertEqual(len(selected), len(expected))
        self.assertEqual({(a['library'],a['attack_type']) for a in selected}, expected)


if __name__ == '__main__':
    unittest.main()
