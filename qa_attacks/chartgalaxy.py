"""ChartGalaxy infographic QA: fetch a subset and build its attacked version.

The QA eval set lives in ``eval_data.zip`` (~830 MB) on Hugging Face as
``eval/test.jsonl`` (4,975 questions, ChartQAPro-style scoring) plus
``eval/test_images/``. ``fetch`` reads only the members it needs through HTTP
Range requests, so a stratified subset costs a few MB, not the whole archive.

    python -m qa_attacks.chartgalaxy fetch --out runs/qa_attacks/chartgalaxy/raw --per-subcategory 3
    python -m qa_attacks.chartgalaxy build --raw runs/qa_attacks/chartgalaxy/raw \\
        --out runs/qa_attacks/chartgalaxy/attacked

Rows keep ChartGalaxy's schema (``id``, ``conversation``, ``metadata``,
``images``) with an added ``attack`` field, so ChartGalaxy's own scorer reads
the attacked file directly; image paths are relative to the output directory.
"""
import argparse
from collections import defaultdict
import copy
import json
from pathlib import Path
import random
import zipfile

import requests

from qa_attacks.answers import choose_target
from qa_attacks.image_channels import CHANNELS
from qa_attacks.inject import Item, build
from qa_attacks.payloads import SUBTYPES

EVAL_ZIP_URL = "https://huggingface.co/datasets/ChartGalaxy/ChartGalaxy/resolve/main/eval_data.zip"
QA_MEMBER = "eval/test.jsonl"
IMAGE_PREFIX = "eval/"


class HttpRangeFile:
    """Minimal seekable read-only file over HTTP Range requests (for ``zipfile``)."""

    READ_AHEAD = 256 << 10

    def __init__(self, url, session=None):
        self._buf = (0, b"")
        self.session = session or requests.Session()
        head = self.session.head(url, allow_redirects=True, timeout=60)
        head.raise_for_status()
        self.url, self.size, self.pos = head.url, int(head.headers["Content-Length"]), 0

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def prefetch(self, offset, length):
        """Load ``[offset, offset + length)`` in one request (e.g. one zip member)."""
        end = min(offset + length, self.size) - 1
        resp = self.session.get(self.url, headers={"Range": f"bytes={offset}-{end}"}, timeout=120)
        resp.raise_for_status()
        self._buf = offset, resp.content

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        n = min(n, self.size - self.pos)
        if n <= 0:
            return b""
        start, buf = self._buf
        if not (start <= self.pos and self.pos + n <= start + len(buf)):
            # zipfile reads members in 4 KB chunks; read ahead so one request
            # covers many chunks instead of one request per chunk.
            end = min(self.pos + max(n, self.READ_AHEAD), self.size) - 1
            resp = self.session.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=120)
            resp.raise_for_status()
            self._buf = start, buf = self.pos, resp.content
        out = buf[self.pos - start:self.pos - start + n]
        self.pos += len(out)
        return out


def to_item(row):
    human, assistant = row["conversation"][0], row["conversation"][1]
    return Item(id=row["id"], prompt=human["content"], answer=assistant["content"],
                images=list(row["images"]), raw=row)


def to_row(item, row_id, prompt, images, attack):
    row = copy.deepcopy(item.raw)
    row["id"] = row_id
    row["conversation"][0]["content"] = prompt
    row["images"] = images
    row["attack"] = attack
    return row


def sample(rows, per_subcategory, seed=0):
    """Stratified sample by ``metadata.subcategory``, skipping untargetable
    (free-text) items. Deterministic for a given ``seed``."""
    groups = defaultdict(list)
    for row in rows:
        item = to_item(row)
        if choose_target(item.id, item.prompt, item.answer) is not None:
            groups[row["metadata"]["subcategory"]].append(row)
    rng = random.Random(seed)
    picked = []
    for key in sorted(groups):
        group = sorted(groups[key], key=lambda r: r["id"])
        picked.extend(rng.sample(group, min(per_subcategory, len(group))))
    return picked


def fetch(out_dir, per_subcategory=3, seed=0, url=EVAL_ZIP_URL):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    remote = HttpRangeFile(url)
    archive = zipfile.ZipFile(remote)
    qa_path = out_dir / "test_full.jsonl"
    if not qa_path.exists():
        qa_path.write_bytes(archive.read(QA_MEMBER))
    rows = [json.loads(line) for line in qa_path.read_text().splitlines() if line.strip()]
    picked = sample(rows, per_subcategory, seed)
    for row in picked:
        for rel in row["images"]:
            dst = out_dir / rel
            if not dst.exists():
                info = archive.getinfo(IMAGE_PREFIX + rel)
                # local header (30 B + name + extra, extra not in central dir) + data
                remote.prefetch(info.header_offset, 30 + 2 * len(info.orig_filename) + 1024 + info.compress_size)
                data = archive.read(info)
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(dst)
    with open(out_dir / "test.jsonl", "w") as fh:
        for row in picked:
            fh.write(json.dumps(row) + "\n")
    return picked


def load(raw_dir):
    path = Path(raw_dir) / "test.jsonl"
    return [to_item(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def _csv(value):
    return tuple(v.strip() for v in value.split(",") if v.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download a stratified QA subset and its images")
    f.add_argument("--out", required=True)
    f.add_argument("--per-subcategory", type=int, default=3)
    f.add_argument("--seed", type=int, default=0)

    b = sub.add_parser("build", help="write the attacked benchmark for a fetched subset")
    b.add_argument("--raw", required=True, help="directory written by fetch")
    b.add_argument("--out", required=True)
    b.add_argument("--subtypes", type=_csv, default=SUBTYPES)
    b.add_argument("--channels", type=_csv, default=CHANNELS)
    b.add_argument("--no-controls", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        picked = fetch(args.out, args.per_subcategory, args.seed)
        print(f"fetched {len(picked)} questions -> {args.out}")
    else:
        unknown = set(args.subtypes) - set(SUBTYPES) | set(args.channels) - set(CHANNELS)
        if unknown:
            parser.error(f"unknown subtype/channel: {sorted(unknown)}")
        manifest = build(load(args.raw), args.raw, args.out, to_row, subtypes=args.subtypes,
                         channels=args.channels, controls=not args.no_controls)
        print(json.dumps(manifest["rows"]), f"skipped={len(manifest['skipped_untargetable'])}")


if __name__ == "__main__":
    main()
