#!/usr/bin/env python3
"""Generate deterministic H12R synthetic unsupported-but-remediable fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

TARGET_RULE = "PDF/UA-1/7.21.7"


def _fixture_bytes(fixture: str, object_seed: int, visible_text: str) -> bytes:
    body = f"""%PDF-1.7
% H12R synthetic fixture; controlled-validator only
1 0 obj << /Type /Catalog /Lang (en-US) >> endobj
{object_seed} 0 obj << /Fixture ({fixture}) /VisibleText ({visible_text}) >> endobj
% fixture={fixture}
% object-seed={object_seed}
% H12R_TARGET_FAIL: {TARGET_RULE}
%%EOF
"""
    return body.encode("utf-8")


def generate_fixture_pair(output_dir: Path) -> Dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    a = output_dir / "h12r_fixture_a_missing_tounicode.pdf"
    b = output_dir / "h12r_fixture_b_missing_tounicode_distinct.pdf"
    a.write_bytes(_fixture_bytes("A", 1201, "Alpha synthetic ToUnicode sample"))
    b.write_bytes(_fixture_bytes("B", 2209, "Beta synthetic ToUnicode sample with different object ids"))
    return {"fixture_a": str(a), "fixture_b": str(b), "target_rule": TARGET_RULE}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir")
    args = parser.parse_args()
    print(json.dumps(generate_fixture_pair(Path(args.output_dir)), indent=2, sort_keys=True))
