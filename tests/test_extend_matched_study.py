import json
from pathlib import Path

import pytest

from qa_attacks.extend_matched_study import prepare
from qa_attacks.matched_study import digest


@pytest.fixture
def parent(tmp_path):
    root = Path(__file__).resolve().parent.parent
    source = tmp_path / 'parent'
    source.mkdir()
    image = source / 'image.png'
    image.write_bytes(b'frozen image payload')
    spec = {'protocol': 'plain-json-v1', 'models': ['original'], 'repeats': 2,
            'image_hashes': {str(image): digest(image)}, 'runner_sha256': 'original-runner',
            'evaluator_sha256': digest(root / 'qa_attacks/evaluate.py'),
            'client_sha256': digest(root / 'pipeline/converse_agent.py')}
    (source / 'spec.json').write_text(json.dumps(spec))
    for trial in [1, 2]:
        (source / f'r{trial}').mkdir()
        (source / f'r{trial}/attacked.jsonl').write_text('{"id": "original-order"}\n')
    return source


def test_extension_preserves_exact_inputs_and_blocks_changed_image(parent, tmp_path):
    out = tmp_path / 'extension'
    spec = prepare(parent, out, ['new-model'], 'us-west-2')
    assert spec['models'] == ['new-model']
    for trial in [1, 2]:
        assert (out / f'r{trial}/attacked.jsonl').read_bytes() == (parent / f'r{trial}/attacked.jsonl').read_bytes()
    assert prepare(parent, out, ['new-model'], 'us-west-2') == spec
    assert json.loads((parent / 'spec.json').read_text())['models'] == ['original']
    (parent / 'image.png').write_bytes(b'changed payload')
    with pytest.raises(ValueError, match='Source image changed'):
        prepare(parent, out, ['new-model'], 'us-west-2')


def test_extension_rejects_incompatible_resume(parent, tmp_path):
    out = tmp_path / 'extension'
    prepare(parent, out, ['new-model'], 'us-west-2')
    with pytest.raises(ValueError, match='configuration changed'):
        prepare(parent, out, ['different-model'], 'us-west-2')
    (out / 'r1/attacked.jsonl').write_text('{"id": "different-order"}\n')
    with pytest.raises(ValueError, match='trial corpus differs'):
        prepare(parent, out, ['new-model'], 'us-west-2')
