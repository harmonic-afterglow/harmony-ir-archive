# The raw capture — schema

These are the **verbatim responses** from Logitech's Harmony cloud service, exactly as
they came off the wire, before any projection. The curated archive in this repository
is built from them.

They exist so that no judgment made while building the archive is permanent. If a
field was dropped that you need, or a schema decision turns out to be wrong, the
answer is in here — the fix is a rebuild, not a re-crawl of a service that may stop
answering.

## The assets

| file | uncompressed | compressed | lines | what |
|---|---|---|---|---|
| `device_features_raw.jsonl.gz` | 5,489 MB | 329 MB | 276,236 | verbatim `SimpleRestSaveDeviceAndFeatures` — the resolved device profile, its features, and its commands |
| `catalog_raw.jsonl.gz` | 372 MB | 13 MB | 276,236 | verbatim `GetGlobalDevices` — one catalogue row per device |
| `AllProtocols.json.gz` | 2.3 MB | 66 KB | — | all 684 of Logitech's IR protocol definitions |
| `SHA256SUMS` | — | — | — | checksums of the three files above, as uploaded |

Plain gzip, so nothing beyond the standard tools is needed:

```sh
gzip -d device_features_raw.jsonl.gz           # or stream it:
zcat device_features_raw.jsonl.gz | head -1 | python3 -m json.tool
```

Both `.jsonl` files are **one JSON object per line**, so they stream — you never need
5.4 GB of memory or 5.4 GB of disk, and `zcat … | while read` works fine.

## `device_features_raw.jsonl`

```json
{"id": 154, "ok": true, "instance": 83589239, "device": {…}, "features": […], "commands": […]}
```

| key | meaning |
|---|---|
| `id` | Logitech's **global device id** — the catalogue identity, and the join key to `catalog_raw.jsonl` and to `globalDeviceId` in the archive |
| `ok` | whether the capture completed. A record with `ok: false` may still carry a usable `device` and `features` and simply have failed at the command fetch |
| `instance` | an **ephemeral artifact of our own capture**: the per-account device instance id minted when we attached the device to fetch it. It means nothing outside that session and should be ignored |
| `device` | the resolved device profile — 56 fields |
| `features` | the `DeviceFeatures` objects — 42 distinct fields across five types |
| `commands` | the device's commands — 12 fields each |

This capture holds **exactly one line per device**, 276,236 lines with 276,236
distinct ids. The crawler appends and can retry, so a consumer written against it
should still prefer the last `ok: true` record for an id, but no deduplication is
needed for this file.

### `device` — 56 fields

Timing lives here: `InterKeyDelay`, `InterDeviceDelay`, `HoldInterKeyDelay`,
`HoldInterDeviceDelay`, `PressMinRepeats`, `HoldMinRepeats`, `IsInterKeyDelayOptimized`
and the four `Default*` twins. Identity lives here too — `Manufacturer`, `Model`,
`Name`, `DeviceType`, `DeviceTypeDisplayName`, `Transport`, `DeviceClassification`.

Twelve fields are null on every device sampled: `ActivityIds`, `AutoDetectedDevice`,
`BTAddress`, `DecodedEdid`, `EncodedEdid`, `GroupName`, `ParentDeviceId`, `PictureId`,
`RegionalCharset`, `RegisterSection`, `RenewSection`, `Tokens`. `DeviceAddedDate` is
the timestamp of **our** attach, not anything about the device.

### `features` — five types

Each entry is identified by the part of `__type` before the colon.

| type | present on | carries |
|---|---|---|
| `PowerFeature` | every device | `PowerTypeId` (1 discrete, 2 toggle, 3 none, 0 unknown), the on/off/toggle/reset action lists, `PowerOnDelay`, `ConnectedAppPowerOnDelay` |
| `InputFeature` | every device | `Inputs[]` (name, actions, `PortTypes`, `InputOrder`), `NextActions`, `PreviousActions`, `InputType`, `InputDelay` |
| `ChannelTuningFeature` | every device | `FixedDigits`, `StartActions`, `FinishActions`, `GreaterTenActions`, `GreaterHundredActions` |
| `InternalStateFeature` | 15,689 devices | `StateName` and `StateValues[]` — the **declarations** behind every `IRDevAction`: which states exist, their legal values, and the actions that reach each one. 947 distinct state names |
| `OutputFeature` | 11,185 devices | `Outputs[]` — physical output jacks, named and typed. **No output on any device carries an action**, so there is nothing to send |

### Action lists

Every actionable field is an array of action objects, typed by `__type`. Four kinds
cover the entire catalogue:

| `__type` | count | fields |
|---|---|---|
| `IRPressAction` | 1,327,422 | `IRCommandName`, `Duration` (null on all but 18,093) |
| `IRDevAction` | 212,173 | `StateName`, `StateValue` — a state transition, not a transmission |
| `IRDelayAction` | 79,886 | `Delay` — **note the field is `Delay`, not `Duration`** |
| `IRHoldAction` | 45 | `IRCommandName`; its `Duration` is always null |

**`Order` is authoritative, not array position.** About 0.4% of action lists arrive
with their entries out of order — most often a two-press `PowerToggleActions` that
serialises as `[2, 1]`. Sort by `Order` before executing, or you will send the
sequence backwards. (`InputOrder` on `Inputs[]`, by contrast, never disagrees with
array position.)

## Work already done — don't redo it

These were checked device by device across all 276,236 devices. They are recorded
here so nobody has to re-derive them.

**Constant across the entire catalogue:**

- `HoldInterKeyDelay` — 100 on every device
- `HoldMinRepeats` — 0 on every device
- `PressDuration` on every input — 0 on all 1,089,512
- `IsPowerAlwaysOn` — true on 0 devices

**Exact duplicates of another field:**

- `DefaultInterKeyDelay` = `InterKeyDelay`
- `DefaultInterDeviceDelay` = `InterDeviceDelay`
- `DefaultPressMinRepeats` = `PressMinRepeats`
- `DefaultInputDelay` = `InputDelay`
- `DefaultPowerOnDelay` = `PowerOnDelay`, with absent read as 0

**Undecoded, and left as opaque integers:** `InputType` (0–6) and the `Attributes`
array on each input's `PortTypes` (`[1]`, `[2]`, `[3]`, `[1,8]`). Their meaning is
not known; the archive passes the first through unchanged and drops the second rather
than guess.

**There is no `preSilence` field in the service at all.** Harmony hub firmware has a
runtime `preSilence` fed from its compiled configuration; it is not per-device data
and must not be relabelled as such.

## What the archive projects from this

The curated archive publishes 9 of the 16 timing fields (the seven above are the ones
dropped), and projects `PowerFeature`, `InputFeature`, `ChannelTuningFeature` and
`InternalStateFeature` into its `power`, `inputs`, `channelTuning` and `states`
blocks. `OutputFeature`, the port `Attributes`, `ActionId` / `Id` / `State` and
similar service plumbing, and the capture's own account artifacts are not projected.
Everything else in the archive — commands, keycodes, Pronto, protocols — comes from
these same captures.

## Privacy

These files were scanned before publication for the capturing account's id and email
address, and for `AUTHTOKEN`, `HarmonyAuth`, `Bearer`, `refresh_token`, `sessionToken`
and `identityToken`: **zero hits** for every one.

Two patterns do match, and both are Logitech's own data rather than anything of ours:

- `cookie` — 734 lines, every one the literal template placeholder
  `"Header": "{\"cookie\":\"{cookie}\"}"` in the IP-control command definitions of
  Sony smart TVs. A placeholder a client would fill in at runtime; no value;
- `password` — the same 734 lines, carrying the literal placeholder
  `password={renewpin}` in an access-control URL, plus a handful of set-top boxes
  with an IR command *named* `Password`.

The only capture-linked artifacts are the ephemeral `instance` ids described above
and `DeviceAddedDate` timestamps recording when we attached each device.
