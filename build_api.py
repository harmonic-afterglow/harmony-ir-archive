#!/usr/bin/env python3
"""Build the static API in docs/api/v1 from the raw capture.

    python3 build_api.py

The capture is one stream of 276,236 records; an application looking up one device should
not have to fetch it all. This writes small JSON files any static host can serve - GitHub
Pages, raw.githubusercontent.com, jsDelivr - each found by its address alone:

    manifest.json                     counts, the capture's checksum, these paths
    manufacturers.json                [{"name", "slug", "devices"}]
    manufacturers/<slug>.json         [{"id", "model", "type", "name"}] - its devices
    devices/<id % 1024, 3 hex>.json.gz   {id: {"device", "features": {kind: [feature]},
                                                "codeset", "catalog"}} - a device's profile,
                                                features, and its catalogue row's extras
    codesets/<first 3 hex>.json.gz       {codeset: [command, ...]} - shared command sets
    protocols.json                    {protocol id: definition} - all 684, verbatim

A device names its command set by a hash of the set's contents, so the 276,236 devices
share 57,799 sets. The device and code-set buckets are gzipped: as plain JSON they come to
more than a gigabyte, more than GitHub Pages publishes. Records keep Logitech's own field names and values; what is left out is
only what says nothing about the device: nulls and empty lists, the service's bookkeeping
(record ids, dates, account state) and the fields RAW-SCHEMA.md finds duplicated or
constant. An action list's `Order`, not its position, is its order (RAW-SCHEMA.md).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "docs" / "api" / "v1"
DEVICE_BUCKETS, CODESET_PREFIX = 1024, 3

# Bookkeeping of the service and of the capture, constant or duplicated fields
# (RAW-SCHEMA.md, "Work already done"), anywhere in a record.
DROPPED = {
    "instance", "ok", "Id-", "DeviceId-", "GlobalDeviceVersionId-", "GlobalLanguageVersionId-",
    "ParentDevice-", "DateModified", "DeviceAddedDate", "SetupState", "State", "ActionId", "Id",
    "DefaultInterKeyDelay", "DefaultInterDeviceDelay", "DefaultPressMinRepeats",
    "DefaultInputDelay", "DefaultPowerOnDelay", "HoldInterKeyDelay", "HoldMinRepeats",
    "DeviceOrder", "DongleIndex", "DongleRFID", "DateTaught",
}
# What a command is: its name, how it is sent, and which function it is.
COMMAND_FIELDS = ("Name", "KeyCode", "ProtocolId", "CommandTypeId", "FunctionGroupId",
                  "TransportType", "Raw", "Parameters", "IsLearned")


def clean(value):
    """``value`` without the dropped fields, nulls or empty lists, anywhere in it."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in DROPPED:
                continue
            item = clean(item)
            if item is None or item == [] or item == {}:
                continue
            out[key] = item
        return out
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").casefold()).strip("-") or "unnamed"


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def _gather(staging: Path, kind: str, key: str, value: bytes, files: dict):
    """Append one entry to its bucket's staging file: `key<TAB>json`, a line each."""
    if kind not in files:
        files[kind] = open(staging / kind, "ab")
    files[kind].write(key.encode() + b"\t" + value + b"\n")


def _bucket(staging: Path, kind: str, out: Path):
    """A staged bucket as one JSON object, its entries in key order."""
    entries = {}
    with open(staging / kind, "rb") as f:
        for line in f:
            key, value = line.rstrip(b"\n").split(b"\t", 1)
            entries[key.decode()] = value
    body = b"{" + b",".join(json.dumps(key).encode() + b":" + entries[key]
                             for key in sorted(entries, key=_order)) + b"}"
    out.parent.mkdir(parents=True, exist_ok=True)
    # gzipped, and the same bytes on every build (no name, no time in the header)
    out.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))


def _order(key: str):
    return (0, int(key), "") if key.isdigit() else (1, 0, key)


class Pronto:
    """Pronto Hex for each command, from pickysysadmin's curated tree (CC0), which renders
    every infrared command from its key code and protocol. The capture has none: Logitech's
    service sent key codes, and its remotes rendered them. Found by device: the curated
    device names its code set, whose commands are matched by name and key code."""

    def __init__(self, tree: Path | None):
        self.tree = tree
        self.paths, self.cache = {}, {}
        self.missing = 0
        if tree is None:
            return
        for index in tree.glob("devices/*/index.json"):
            for entry in json.loads(index.read_text()):
                self.paths[entry["id"]] = index.parent / entry["f"]

    def commands(self, device_id: int) -> dict:
        """{(name, keycode): (pronto, prontoRepeat)} for one device's commands."""
        path = self.paths.get(device_id)
        if path is None:
            return {}
        codeset = json.loads(path.read_text()).get("codeset")
        if not codeset:
            return {}
        if codeset in self.cache:
            return self.cache[codeset]
        out = self.cache[codeset] = {}
        for command in json.loads((self.tree / codeset).read_text())["commands"]:
            if command.get("pronto"):
                out[(command.get("name"), command.get("keycode"))] = (
                    command["pronto"], command.get("prontoRepeat"))
        return out

    def add(self, device_id: int, commands: list[dict]):
        """Give each infrared command its Pronto, as `pronto` (and `prontoRepeat`): lower
        case, since they are not Logitech's fields."""
        if self.tree is None:
            return
        known = self.commands(device_id)
        for command in commands:
            found = known.get((command.get("Name"), command.get("KeyCode")))
            if found:
                command["pronto"] = found[0]
                if found[1]:
                    command["prontoRepeat"] = found[1]
            elif command.get("KeyCode"):
                self.missing += 1


# What the catalogue (GetGlobalDevices) says that the device record does not.
CATALOG_FIELDS = ("MinRepeats", "PrimaryBrandId", "PrimaryManufacturerAlias",
                  "PrimaryModelAlias", "GlobalLanguages", "DefaultGlobalLanguageVersionId")


def catalog() -> dict[int, dict]:
    """Each device's catalogue row, the fields the device record lacks."""
    out = {}
    with gzip.open(HERE / "catalog_raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            found = clean({key: row.get(key) for key in CATALOG_FIELDS})
            if found:
                out[row["Id"]] = found
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pronto-from", type=Path, metavar="CURATED_TREE",
                        help="a checkout of pickysysadmin/logitech-harmony-ir-archive")
    args = parser.parse_args()
    pronto = Pronto(args.pronto_from)
    rows = catalog()
    parts = json.loads((HERE / "device_features" / "parts.json").read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    staging = HERE / ".staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    files, seen, makers = {}, set(), defaultdict(list)
    commands = devices = 0
    for part in parts["parts"]:
        with gzip.open(HERE / part["file"], "rt", encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                device_id = record["id"]
                found = [{key: command[key] for key in COMMAND_FIELDS
                          if command.get(key) not in (None, False)}
                         for command in record.get("commands") or []]
                pronto.add(device_id, found)
                body = canonical(found)
                codeset = hashlib.sha256(body).hexdigest()[:16]
                if codeset not in seen:
                    seen.add(codeset)
                    commands += len(found)
                    _gather(staging, "c" + codeset[:CODESET_PREFIX], codeset, body, files)
                device = clean(record["device"])
                # a device can have several of a kind - a state each, an output each - so
                # every kind is a list
                features = defaultdict(list)
                for feature in clean(record.get("features") or []):
                    kind = feature.pop("__type").split(":")[0]
                    features[kind].append(feature)
                entry = {"device": device, "features": features, "codeset": codeset}
                if device_id in rows:
                    entry["catalog"] = rows[device_id]
                _gather(staging, f"d{device_id % DEVICE_BUCKETS:03x}", str(device_id),
                        canonical(entry), files)
                devices += 1
                makers[device.get("Manufacturer") or ""].append({
                    "id": device_id, "model": device.get("Model"),
                    "type": device.get("DeviceTypeDisplayName") or device.get("DeviceType"),
                    "name": device.get("Name")})
    for handle in files.values():
        handle.close()
    for kind in files:
        folder = "devices" if kind[0] == "d" else "codesets"
        _bucket(staging, kind, OUT / folder / f"{kind[1:]}.json.gz")
    shutil.rmtree(staging)
    taken, listing = set(), []
    for name in sorted(makers, key=str.casefold):
        base = candidate = slug(name)
        n = 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        taken.add(candidate)
        models = sorted(makers[name], key=lambda m: (str(m["model"]).casefold(), m["id"]))
        write(OUT / "manufacturers" / f"{candidate}.json", models)
        listing.append({"name": name, "slug": candidate, "devices": len(models)})
    write(OUT / "manufacturers.json", listing)
    with gzip.open(HERE / "AllProtocols.json.gz", "rt", encoding="utf-8") as f:
        source = json.load(f)
    protocols = {}
    for items in source.values():
        for protocol in items:
            protocols[str(protocol["Id-"])] = protocol
    write(OUT / "protocols.json", protocols)
    write(OUT / "manifest.json", {
        "api": 1,
        "captured": "2026-09-02",
        "source": "https://github.com/pickysysadmin/logitech-harmony-ir-archive/releases/tag/"
                  "raw-2026-09-02",
        "capture_sha256": parts["uncompressed_sha256"],
        "counts": {"devices": devices, "manufacturers": len(listing), "codesets": len(seen),
                   "commands_in_codesets": commands, "protocols": len(protocols)},
        "layout": {"device": "devices/{id % 1024:03x}.json.gz",
                   "codeset": "codesets/{codeset[:3]}.json.gz",
                   "manufacturer": "manufacturers/{slug}.json"},
        "device_buckets": DEVICE_BUCKETS, "codeset_prefix": CODESET_PREFIX,
    })
    print(json.dumps(json.loads((OUT / "manifest.json").read_text())["counts"]),
          "commands without Pronto:", pronto.missing)


if __name__ == "__main__":
    main()
