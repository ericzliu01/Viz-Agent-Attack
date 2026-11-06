"""Validate generated attack manifests and optionally render them in Chromium."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def check_manifest(root):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    cases = {c['task_id']: c for c in manifest['cases']}
    baselines = {c['baseline_id']: c for c in manifest['clean']}
    if len(baselines) != len(manifest['clean']):
        raise ValueError('Duplicate baseline IDs')
    attacks = manifest['attacks']
    if len({a['attack_id'] for a in attacks}) != len(attacks):
        raise ValueError('Duplicate attack IDs')
    for entry in manifest['clean'] + attacks:
        path = (root / 'public' / entry['page']).resolve()
        if not path.is_relative_to((root / 'public').resolve()) or not path.is_file():
            raise ValueError('Missing or unsafe page path')
        html = path.read_text()
        match = re.search(r'const CFG = (.*?);\n', html, re.DOTALL)
        if not match:
            raise ValueError('Missing chart configuration')
        cfg = json.loads(match.group(1))
        expected = cases[entry['task_id']]['view']['data']
        if dict(zip(cfg['labels'], cfg['values'])) != expected:
            raise ValueError('Chart configuration changed source data')
        for forbidden in ('"solution":', '"answer_letter":', '"option_id": "truth"'):
            if forbidden in html:
                raise ValueError('Evaluator metadata exposed')
    for attack in attacks:
        baseline = baselines[attack['baseline_id']]
        case = cases[attack['task_id']]
        for key in ('task_id', 'view_id', 'library'):
            if baseline[key] != attack[key]:
                raise ValueError('Incorrect baseline pairing')
        if attack.get('bait_option_id'):
            option = next(o for o in case['options'] if o['option_id'] == attack['bait_option_id'])
            if option['value'] == case['answer']:
                raise ValueError('Bait is correct')
        if attack['attack_type'].startswith('cognitive_'):
            if (root/'public'/attack['page']).read_bytes() != (root/'public'/baseline['page']).read_bytes():
                raise ValueError('Cognitive page differs from clean')
    return manifest


def representatives(manifest, all_pages=False):
    if all_pages:
        return manifest['attacks']
    chosen = {}
    for attack in manifest['attacks']:
        chosen.setdefault((attack['library'], attack['attack_type']), attack)
    return list(chosen.values())


def validate(root, all_pages=False, screenshot_dir=None):
    from playwright.sync_api import sync_playwright
    from browser_environment import serve_chart
    root = Path(root)
    manifest = check_manifest(root)
    baselines = {x['baseline_id']: x for x in manifest['clean']}
    cases = {x['task_id']: x for x in manifest['cases']}
    records, cache = [], {}
    screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
    if screenshot_dir:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        def render(entry):
            if entry['page'] in cache:
                return cache[entry['page']]
            context = browser.new_context(viewport={'width': 1100, 'height': 900}, device_scale_factor=1)
            page = context.new_page()
            errors, logs = [], []
            page.on('console', lambda message: logs.append(message.text))
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                with serve_chart(root / 'public' / entry['page']) as url:
                    page.goto(url, wait_until='networkidle')
                    page.wait_for_function("document.querySelector('#chart svg, #chart canvas') !== null")
                    page.evaluate('document.fonts.ready')
                    page.wait_for_timeout(100)
                    library = entry['library']
                    if library == 'chartjs':
                        marks = page.evaluate("Chart.getChart(document.querySelector('#chart canvas')).getDatasetMeta(0).data.filter(x => x.height > 0).length")
                    else:
                        selector = {'d3': '#chart rect', 'plotly': '#chart .barlayer .point path', 'vega-lite': '#chart .mark-rect path'}[library]
                        marks = page.locator(selector).count()
                    if marks < len(cases[entry['task_id']]['view']['data']):
                        raise ValueError('Missing rendered bars')
                    kind, payload = entry.get('attack_type'), entry.get('payload')
                    if kind == 'tm_console' and payload not in logs:
                        raise ValueError('Console payload not delivered')
                    if kind == 'tm_aria' and page.locator('#attack-aria').get_attribute('aria-label') != payload:
                        raise ValueError('ARIA payload missing')
                    if kind == 'tm_alt' and page.locator('img[alt]').get_attribute('alt') != payload:
                        raise ValueError('Alt payload missing')
                    if kind == 'tm_css_hidden' and page.locator('[data-injection=claim]').text_content() != payload:
                        raise ValueError('Hidden DOM payload missing')
                    cfg = page.evaluate('({labels: CFG.labels, values: CFG.values})')
                    expected = cases[entry['task_id']]['view']['data']
                    if dict(zip(cfg['labels'], cfg['values'])) != expected:
                        raise ValueError('Rendered CFG does not match source view')
                    if errors:
                        raise ValueError('JavaScript errors: ' + '; '.join(errors))
                    if page.evaluate("document.body.getAttribute('data-agent-action')") is not None:
                        raise ValueError('Action marker executed without agent')
                    for forbidden in ('/manifest.json', '/.env'):
                        if page.evaluate('async path => (await fetch(path)).status', forbidden) != 404:
                            raise ValueError('Evaluator path is accessible')
                    pixels = page.screenshot(animations='disabled')
                    if screenshot_dir:
                        name = entry.get('attack_type', 'clean') + '_' + entry['library'] + '_' + entry['task_id'] + '.png'
                        (screenshot_dir / name).write_bytes(pixels)
                    cache[entry['page']] = pixels
                    return pixels
            finally:
                context.close()
        for attack in representatives(manifest, all_pages):
            record = {'attack_id': attack['attack_id'], 'library': attack['library'], 'attack_type': attack['attack_type']}
            try:
                baseline_pixels = render(baselines[attack['baseline_id']])
                attack_pixels = render(attack)
                identical = attack['attack_type'].startswith(('tm_', 'cognitive_'))
                if identical and baseline_pixels != attack_pixels:
                    raise ValueError('Visually hidden attack changed screenshot')
                record.update(status='passed', screenshot_identical=baseline_pixels == attack_pixels)
            except Exception as exc:
                record.update(status='failed', error=str(exc))
            records.append(record)
        browser.close()
    return {'manifest_sha256': hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest(),
            'scope': 'all_attack_pages' if all_pages else 'one_per_library_and_attack_type',
            'checked_attacks': len(records), 'rendered_pages': len(cache),
            'passed': all(r['status'] == 'passed' for r in records), 'records': records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path('generated_corpus'))
    parser.add_argument('--all', action='store_true', help='Render every attack instead of representatives')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    report = validate(args.corpus, args.all, args.screenshots)
    path = args.report or args.corpus / 'validation-report.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
