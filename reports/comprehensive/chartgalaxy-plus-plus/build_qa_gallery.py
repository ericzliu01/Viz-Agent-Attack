"""Build a local review gallery from downloaded, unmodified benchmark records."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
synthetic = json.loads((ROOT / 'provenance.json').read_text())
qa_images = json.loads((ROOT / 'qa-examples/download_manifest.json').read_text())
questions = json.loads((ROOT / 'upstream/qa/questions.json').read_text())
source = json.loads((ROOT / 'upstream/qa/download_provenance.json').read_text())
url = f"https://github.com/ChartGalaxyPP/ChartGalaxyPlusPlus/tree/{source['observed_commit']}/applications/qa"
displayed = sum(len(s['question_ids']) for s in qa_images)
lines = [
    '# ChartGalaxy++: chart and QA example gallery', '',
    f'This local gallery contains five synthetic charts with scene graphs, plus {len(qa_images)} official QA chart examples with {displayed} released question–answer pairs. No model evaluations have been run on these examples.', '',
    '## Dataset totals', '',
    '| Resource | Charts | Question–answer pairs |',
    '| --- | ---: | ---: |',
    '| Full ChartGalaxy++ scene-graph dataset | 217,195 | Not a QA count; annotations are scene graphs |',
    '| Real-chart component | 56,744 | — |',
    '| Synthetic-chart component | 160,451 | — |',
    '| Main dataset training split | 216,195 | — |',
    '| Main dataset test split | 1,000 | — |',
    '| Separate released QA benchmark | 1,000 unique chart IDs | 1,266 |',
    f'| This gallery | {5 + len(qa_images)} displayed charts | {displayed} official example QAs |', '',
    'The QA benchmark does not mean every chart in the 217,195-chart collection has a question. Its 1,000 chart IDs correspond to 1,006 historical image encodings; those encodings are not additional unique charts. The main test split and QA benchmark are separate resources.', '',
    f'Sources: [main dataset card](upstream/README.md), [official QA package]({url}), and [downloaded QA manifest](upstream/qa/manifest.json). The local questions file was counted directly: 1,266 records and 1,000 distinct chart IDs. All [1,266 questions and reference answers](upstream/qa/questions.json) are downloaded locally.', '',
    '## Official QA examples', '',
    'Questions, reference answers, question IDs, and qtype codes below are copied unchanged from the released benchmark. Qtype codes are retained rather than mapped to the task taxonomy in our earlier ChartGalaxy experiments.', '',
    'Image provenance: these JPEGs were downloaded from the URLs attached to the QA records and visually inspected. Their file hashes differ from the historical evaluation image hashes. They are review illustrations, not verified byte-identical benchmark inputs. Each example links both hashes in its provenance file. The QA release distributes URLs rather than image files.', '',
]
titles = ['Digital trade agreements', "Canada’s traded goods", 'Corporate profits and losses']
def cell(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')
for i, s in enumerate(qa_images):
    folder = s['folder']
    rows = json.loads((ROOT / folder / 'questions.json').read_text())
    lines += [f"### QA chart {i+1}: {titles[i]}", '', f"Chart ID: `{s['chart_id']}`. {len(rows)} official QAs.", '',
              f"![{titles[i]}]({folder}/{s['image']})", '',
              '| Question ID | qtype | Question | Official reference answer |',
              '| --- | ---: | --- | --- |']
    for q in rows:
        lines.append('| ' + ' | '.join(cell(q[k]) for k in ['qid', 'qtype', 'question', 'reference_answer']) + ' |')
    lines += ['', f"[Original QA records]({folder}/questions.json) · [Image provenance]({folder}/provenance.json) · [Source image]({s['image_url']})", '']
    if i == 1:
        lines += ['Review note: the released question says “Trucks parts”; the chart labels this row “Trucks.” The official answer is retained verbatim as `11`, representing CAD 11 billion in the image. This wording discrepancy should be reviewed before using the item in a new evaluation.', '']
lines += ['## Previously downloaded synthetic charts', '',
          'These five charts have no exact image-hash match in the released QA file. No official QAs are attached to them here, and no new questions have been invented. Their main-dataset `human_gold` flag refers to scene-graph annotation verification, not QA validation.', '',
          'Selection: first five records by name in synthetic test shard 00000; a convenience sample. The archive, PNG images, and canonical scene-graph hashes were verified. [Synthetic sample provenance](provenance.json).', '']
for s in synthetic['samples']:
    folder = s['folder']
    lines += [f"### Synthetic example {folder.split('/')[-1]}: {s['sample_id']}", '',
              f"{s['width']} × {s['height']} px; track: {s['track']}; human_gold: {s['human_gold']}; {s['nodes']} nodes; {s['spatial_relations']} spatial records.", '',
              f'![Synthetic chart]({folder}/image.png)', '',
              f'[Full record]({folder}/record.json) · [Scene graph]({folder}/scene_graph.json) · [Spatial relationships]({folder}/spatial_relations.json)', '']
lines += ['## Files and reuse', '',
          'The downloaded synthetic examples are PNG + JSON, without editable SVG files. Official QA source records and documentation are in `upstream/qa/`; source Git blob hashes and local SHA-256 hashes are recorded in [QA download provenance](upstream/qa/download_provenance.json).', '',
          'Contributed annotations and QAs follow CC BY-NC 4.0. Referenced chart imagery retains its owners’ rights and attribution. See [upstream licensing](upstream/LICENSE_AND_SOURCES.md) and [QA documentation](upstream/qa/README.md).', '',
          'To rebuild this page after downloading the examples: `python3 build_qa_gallery.py` from this folder.', '']
(ROOT / 'README.md').write_text('\n'.join(lines))
print(f'Gallery written: {len(qa_images)+5} charts, {displayed} official QAs; full QA file: {len(questions)} records.')
