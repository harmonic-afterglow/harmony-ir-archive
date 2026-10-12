# Harmony IR archive — Logitech's raw device data

Everything Logitech's Harmony service knew about **276,236 devices**: each device's
resolved profile, its features, its commands, and all **684** of Logitech's IR protocol
definitions. These are the service's own responses, exactly as they came off the wire on
**2026-09-02**, before anyone reshaped them.

This is a mirror, kept by [Afterglow](https://github.com/harmonic-afterglow/afterglow) so the
data cannot disappear with one account. It was captured and first published by
**pickysysadmin** as the
[`raw-2026-09-02` release](https://github.com/pickysysadmin/logitech-harmony-ir-archive/releases/tag/raw-2026-09-02)
of [logitech-harmony-ir-archive](https://github.com/pickysysadmin/logitech-harmony-ir-archive),
which also publishes a curated, easier-to-use tree built from the same captures. The
capture is dedicated to the public domain (CC0, see `LICENSE`), and so is this copy.

## What is here

| file | what |
|---|---|
| `device_features/device_features_raw.part-NN.jsonl.gz` | `SimpleRestSaveDeviceAndFeatures` for every device, one JSON object a line, in the capture's order, split into parts |
| `device_features/parts.json` | each part's lines, first and last device id, and the checksum of its contents |
| `catalog_raw.jsonl.gz` | `GetGlobalDevices`: one catalogue row per device |
| `AllProtocols.json.gz` | all 684 IR protocol definitions |
| `RAW-SCHEMA.md` | what every field is, and what is already known about them (pickysysadmin's) |
| `SHA256SUMS.original` | the checksums of the three files as first published |
| `reassemble.py` | checks the parts, and rebuilds the single file if you want it |
| `split.py` | how the parts were made from the published file |

The device features file is 329 MB compressed, more than git hosting takes as one file, so
it is split - at line boundaries, so each part is valid JSON lines on its own. Read the
parts in order and you have read the capture; nothing needs joining first:

```sh
zcat device_features/*.jsonl.gz | head -1 | python3 -m json.tool
python3 reassemble.py                                    # check every part
python3 reassemble.py device_features_raw.jsonl.gz       # one file, as first published
```

The rebuilt file's *contents* are byte for byte the original's (`parts.json` records the
checksum of the whole uncompressed capture); its gzip wrapper differs, so compare
uncompressed: `zcat device_features_raw.jsonl.gz | sha256sum`.

Read `RAW-SCHEMA.md` before parsing. Two things worth knowing up front:

- An action list's `Order` field is authoritative, not its position in the array.
- An input's `IsOnline` marks the inputs a device can only switch to once its apps are up -
  in practice Netflix, on 8,328 of the 8,329 devices that have one - and `PowerFeature`'s
  `ConnectedAppPowerOnDelay` is how long after power-on that takes.

This repository is archived: it is a record of one capture, and does not change.
