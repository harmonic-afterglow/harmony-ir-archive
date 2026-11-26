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
the same key as Logitech's rendering of it. A frame that is not a header, two bit shapes and
a trailer - Samsung's 36-bit, RC6, XMP - is keyed by its pairs instead, "g36-37-0101...":
the "g" keeps every key an earlier build gave as it was, so an Afterglow that predates it
reads this index as before. Afterglow computes it with the same rules
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
    frames = _frames(list(pulses))
    for frame in frames:
        layout = _layout(frame)
        if layout is None:
            continue
        value = _payload(frame, layout)
        if value is None:
            continue
        header = abs(layout["header"][0]) if layout["header"] else 0
        return f"{round(header / HEADER_CLASS_US)}-{layout['bits']}-{value:x}"
    for frame in frames:
        key = _symbols_key(frame)
        if key:
            return key
    return None


# How many kinds of pair, and how few pairs, a frame keyed by its pairs may have.
MOST_SYMBOLS, FEWEST_PAIRS = 8, 8


def _symbols_key(frame):
    """A frame the key above cannot read - bits split by a longer space (Samsung's
    36-bit, the Flirc's), bi-phase (RC5, RC6), spaces of four lengths (XMP) - keyed by
    its (mark, space) pairs: a header when its mark is longer than any other, then each
    pair as the rank of its kind, the kinds ordered by length: ``"g<header class>-<pairs>-
    <ranks>"``. The "g" keeps it from ever being a key the rules above give, so an index
    built before it reads the same. None for a frame of too few pairs or too many kinds."""
    body = frame[:-1] if frame and frame[-1] < 0 and -frame[-1] >= FRAME_GAP_US else frame
    if not body or body[0] < 0:
        return None
    if len(body) % 2:                      # the last mark, its space the frame's gap
        body = body + [-1]
    pairs = [(body[i], body[i + 1]) for i in range(0, len(body), 2)]
    if any(mark < 0 or space > 0 for mark, space in pairs):
        return None
    header = 0
    if len(pairs) > 1 and all(pairs[0][0] > 1.5 * mark for mark, _space in pairs[1:]):
        header = pairs[0][0]
        pairs = pairs[1:]
    if len(pairs) < FEWEST_PAIRS:
        return None
    kinds = []
    of = []
    for pair in pairs:
        for number, kind in enumerate(kinds):
            if _close(pair[0], kind[0][0]) and _close(pair[1], kind[0][1]):
                kind.append(pair)
                of.append(number)
                break
        else:
            kinds.append([pair])
            of.append(len(kinds) - 1)
    if len(kinds) > MOST_SYMBOLS:
        return None
    means = [(sum(m for m, _s in kind) / len(kind), sum(-s for _m, s in kind) / len(kind))
             for kind in kinds]
    order = sorted(range(len(kinds)), key=lambda k: (means[k][0] + means[k][1], means[k][0]))
    rank = {kind: place for place, kind in enumerate(order)}
    ranks = "".join(str(rank[number]) for number in of)
    return f"g{round(header / HEADER_CLASS_US)}-{len(pairs)}-{ranks}"
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
