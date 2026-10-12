"""Split device_features_raw.jsonl.gz into gzip parts under GitHub's 100 MB limit, whole
lines each, and record each part's id range, line count and checksums."""
import gzip
import hashlib
import json
import subprocess
import sys

SOURCE = sys.argv[1]
LIMIT = 1_150_000_000          # uncompressed bytes a part; ~16:1 keeps it near 70 MB
parts, whole = [], hashlib.sha256()


def open_part(number):
    name = f"device_features/device_features_raw.part-{number:02d}.jsonl.gz"
    proc = subprocess.Popen(["gzip", "-9", "-n"], stdin=subprocess.PIPE,
                            stdout=open(name, "wb"))
    return name, proc


number, size, lines, first = 1, 0, 0, None
name, proc = open_part(number)
part_hash = hashlib.sha256()
with gzip.open(SOURCE, "rb") as f:
    for line in f:
        if size + len(line) > LIMIT and lines:
            proc.stdin.close(); proc.wait()
            parts.append({"file": name, "lines": lines, "first_id": first, "last_id": last,
                          "uncompressed_sha256": part_hash.hexdigest(), "uncompressed_bytes": size})
            number += 1; size = lines = 0; first = None
            name, proc = open_part(number); part_hash = hashlib.sha256()
        record_id = json.loads(line)["id"]
        first = record_id if first is None else first
        last = record_id
        proc.stdin.write(line); part_hash.update(line); whole.update(line)
        size += len(line); lines += 1
proc.stdin.close(); proc.wait()
parts.append({"file": name, "lines": lines, "first_id": first, "last_id": last,
              "uncompressed_sha256": part_hash.hexdigest(), "uncompressed_bytes": size})
json.dump({"source": "device_features_raw.jsonl.gz", "uncompressed_sha256": whole.hexdigest(),
           "lines": sum(p["lines"] for p in parts), "parts": parts},
          open("device_features/parts.json", "w"), indent=2)
print(json.dumps(parts, indent=1))
