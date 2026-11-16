#!/usr/bin/env python3
"""Build the reverse indexes in docs/api/v1 from the API build_api.py wrote.

    python3 build_index.py

The API finds a device by its manufacturer and model. An application holding only what a
remote sends - a configuration read off a Harmony One, which keeps neither - needs the way
back: which command sets send this code, and which models use those sets.

    codes/<sha1(key)[:2]>.json.gz        {key: [[codeset, command name], ...]}
    codeset_devices/<codeset[:3]>.json.gz {codeset: [[id, manufacturer, model, type], ...]}

A key is a command's first frame read from its Pronto: its header's first mark in classes
of 250 us, how many bits it carries and their value - "36-32-20df10ef". It is protocol-free
on purpose: a code someone recorded off a remote, which says nothing of its protocol, gives
the same key as Logitech's rendering of it. Afterglow computes it with the same rules
(src/afterglow/ir_recognise.py, `fingerprint`); the functions below are a copy and must
stay one. `code_key` in the manifest is their version.

Run after build_api.py; it re-stamps the manifest's build.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from build_api import OUT, canonical, stamp

CODE_KEY = 1
CODE_SHARD = 2

# ---- the key, as Afterglow's ir_recognise.fingerprint computes it (keep them one) ----
TOLERANCE, TOLERANCE_US = 0.10, 80
FRAME_GAP_US = 10000
HEADER_CLASS_US = 250


def _close(actual, expected):
    if (actual < 0) != (expected < 0):
        return False
    return abs(abs(actual) - abs(expected)) <= max(TOLERANCE_US, abs(expected) * TOLERANCE)


def _frames(pulses):
    out, current = [], []
    for pulse in pulses:
        current.append(pulse)
        if pulse < 0 and -pulse >= FRAME_GAP_US:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def _group(pairs):
    groups = []
    for pair in pairs:
        for group in groups:
            if _close(pair[0], group[0][0]) and _close(pair[1], group[0][1]):
                group.append(pair)
                break
        else:
            groups.append([pair])
    if len(groups) != 2:
        return None
    shapes = [tuple(round(sum(item[i] for item in group) / len(group)) for i in (0, 1))
              for group in groups]
    return sorted(shapes, key=lambda shape: abs(shape[0]) + abs(shape[1]))


def _layout(frame):
    body = frame[:-1] if frame and frame[-1] < 0 and -frame[-1] >= FRAME_GAP_US else frame
    for header, trailer in ((2, 1), (1, 0)):
        bits = body[header:len(body) - trailer]
        if len(bits) < 8 or len(bits) % 2:
            continue
        shapes = _group([(bits[i], bits[i + 1]) for i in range(0, len(bits), 2)])
        if shapes is None:
            continue
        return {"header": body[:header], "trailer": body[len(body) - trailer:],
                "symbols": shapes, "bits": len(bits) // 2}
    return None


def _take(frame, at, durations):
    if at + len(durations) > len(frame):
        return None
    if not all(_close(frame[at + i], d) for i, d in enumerate(durations)):
        return None
    return at + len(durations)


def _payload(frame, layout):
    at = _take(frame, 0, list(layout["header"]))
    if at is None:
        return None
    value = 0
    for _ in range(layout["bits"]):
        for bit, shape in enumerate(layout["symbols"]):
            moved = _take(frame, at, list(shape))
            if moved is not None:
                at, value = moved, value << 1 | bit
                break
        else:
            return None
    return value if _take(frame, at, list(layout["trailer"])) is not None else None


def fingerprint(pulses):
    for frame in _frames(list(pulses)):
        layout = _layout(frame)
        if layout is None:
            continue
        value = _payload(frame, layout)
        if value is None:
            continue
        header = abs(layout["header"][0]) if layout["header"] else 0
        return f"{round(header / HEADER_CLASS_US)}-{layout['bits']}-{value:x}"
    return None
# ---- end of the copy ----


def pronto_pulses(text):
    """Raw Pronto `0000` as signed microseconds: its once part, else its repeat part."""
    words = text.split()
    if len(words) < 4 or words[0].upper() != "0000":
        return None
    divisor, once, again = (int(word, 16) for word in words[1:4])
    if not divisor or len(words) != 4 + 2 * (once + again):
        return None
    period = divisor * 0.241246
    durations = [int(word, 16) for word in words[4:]][:2 * once] or \
        [int(word, 16) for word in words[4:]]
    return [round(d * period) if i % 2 == 0 else -round(d * period)
            for i, d in enumerate(durations)]


def shard(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:CODE_SHARD]


def write_gz(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(canonical(value), mtime=0))


def main():
    codes = defaultdict(lambda: defaultdict(list))
    commands = keyed = 0
    for bucket in sorted((OUT / "codesets").glob("*.json.gz")):
        for codeset, entries in json.loads(gzip.decompress(bucket.read_bytes())).items():
            for command in entries:
                commands += 1
                pulses = pronto_pulses(command.get("pronto") or "")
                key = fingerprint(pulses) if pulses else None
                if key is None:
                    continue
                keyed += 1
                codes[shard(key)][key].append([codeset, command.get("Name")])
    for name, table in codes.items():
        write_gz(OUT / "codes" / f"{name}.json.gz", dict(sorted(table.items())))

    users = defaultdict(lambda: defaultdict(list))
    for bucket in sorted((OUT / "devices").glob("*.json.gz")):
        for device_id, record in json.loads(gzip.decompress(bucket.read_bytes())).items():
            codeset = record.get("codeset")
            if not codeset:
                continue
            device = record.get("device") or {}
            users[codeset[:3]][codeset].append([
                int(device_id), device.get("Manufacturer"), device.get("Model"),
                device.get("DeviceTypeDisplayName")])
    for prefix, table in users.items():
        write_gz(OUT / "codeset_devices" / f"{prefix}.json.gz",
                 {codeset: sorted(rows) for codeset, rows in sorted(table.items())})

    manifest = json.loads((OUT / "manifest.json").read_text())
    manifest["layout"]["code"] = "codes/{sha1(key)[:2]}.json.gz"
    manifest["layout"]["codeset_devices"] = "codeset_devices/{codeset[:3]}.json.gz"
    manifest["code_key"] = CODE_KEY
    manifest["counts"]["keyed_commands"] = keyed
    manifest["counts"]["code_keys"] = sum(len(table) for table in codes.values())
    (OUT / "manifest.json").write_bytes(canonical(manifest))
    print(f"{keyed} of {commands} commands keyed, "
          f"{manifest['counts']['code_keys']} keys; build {stamp()}")


if __name__ == "__main__":
    main()
