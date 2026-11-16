"""Command-line entry point for the paired-trap pipeline.

Two subcommands:

* ``python -m pipeline.cli generate --config <file> --out <dir>`` -- run
  :func:`pipeline.generate.generate_all` over the config and write the dataset as
  ``specs.jsonl`` (full specs, one :func:`pipeline.specs.to_jsonl_line` per spec)
  plus ``grader.jsonl`` (the matching on-disk evaluator sidecar per spec).
* ``python -m pipeline.cli render --specs <specs.jsonl> --out <dir>`` -- rebuild
  every instance directory, run the validation gate, and write ``manifest.json``
  (:func:`pipeline.render.render_from_jsonl`).

``generate`` performs LLM calls through :func:`pipeline.generate.generate_all`
(cached per spec hash); ``render`` is pure local materialization + validation and
never calls a model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline import generate, render
from pipeline.specs import to_jsonl_line
from pipeline.validate import ValidationFailed


def _load_config(path) -> generate.Config:
    """Build a :class:`pipeline.generate.Config` from a JSON file.

    Only the JSON-expressible fields are read here; ``client`` (a live model
    client) stays ``None`` and must be wired in programmatically for a real run.
    """
    data = json.loads(Path(path).read_text())
    known = {f for f in generate.Config.__dataclass_fields__}
    kwargs = {k: v for k, v in data.items() if k in known and k != "client"}
    return generate.Config(**kwargs)


def _cmd_generate(args) -> int:
    config = _load_config(args.config)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    specs_lines = []
    grader_lines = []
    for spec in generate.generate_all(config):
        specs_lines.append(to_jsonl_line(spec))
        grader_lines.append(
            json.dumps(render._grader_json(spec), ensure_ascii=False, sort_keys=True)
        )

    (out / "specs.jsonl").write_text("\n".join(specs_lines) + ("\n" if specs_lines else ""))
    (out / "grader.jsonl").write_text("\n".join(grader_lines) + ("\n" if grader_lines else ""))
    print(f"wrote {len(specs_lines)} specs to {out/'specs.jsonl'}")
    return 0


def _cmd_render(args) -> int:
    try:
        manifest = render.render_from_jsonl(args.specs, args.out)
    except ValidationFailed as exc:
        print("validation failed:")
        for failure in exc.failures:
            print(f"  - {failure}")
        return 1
    print(f"rendered {len(manifest)} files; manifest at {Path(args.out)/'manifest.json'}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="run the generator and write the dataset JSONL")
    gen.add_argument("--config", required=True, help="path to the JSON config")
    gen.add_argument("--out", default=".", help="output directory for the JSONL files")
    gen.set_defaults(func=_cmd_generate)

    ren = sub.add_parser("render", help="render + validate instances and write the manifest")
    ren.add_argument("--specs", required=True, help="path to specs.jsonl")
    ren.add_argument("--out", required=True, help="output directory for instances/ + manifest")
    ren.set_defaults(func=_cmd_render)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
