#!/usr/bin/env python3
"""Rebuild device_features_raw.jsonl - or its .gz - from the parts, and check it.

    python3 reassemble.py                 # check the parts against parts.json
    python3 reassemble.py out.jsonl.gz    # write the whole capture, gzipped, and check it

The parts hold the capture's lines in order, whole lines each, so reading them one after
another *is* the capture: nothing needs writing to stream it.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "device_features" / "parts.json").read_text())
whole = hashlib.sha256()
out = gzip.open(sys.argv[1], "wb") if len(sys.argv) > 1 else None
for part in manifest["parts"]:
    digest, lines = hashlib.sha256(), 0
    with gzip.open(HERE / part["file"], "rb") as f:
        for line in f:
            digest.update(line); whole.update(line); lines += 1
            if out:
                out.write(line)
    ok = digest.hexdigest() == part["uncompressed_sha256"] and lines == part["lines"]
    print(f"{part['file']}: {lines} lines {'OK' if ok else 'MISMATCH'}")
    if not ok:
        sys.exit(1)
if out:
    out.close()
ok = whole.hexdigest() == manifest["uncompressed_sha256"]
print(f"whole capture: {'OK' if ok else 'MISMATCH'} ({manifest['lines']} lines)")
sys.exit(0 if ok else 1)
