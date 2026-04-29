from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

BEGIN_RE = re.compile(r"^BEGIN\s+LAUNDERING\s+ATTEMPT\s*-\s*(.+?)\s*$", re.IGNORECASE)
END_RE = re.compile(r"^END\s+LAUNDERING\s+ATTEMPT", re.IGNORECASE)

HEADER = [
    "pattern_group",
    "pattern_type",
    "timestamp",
    "from_bank",
    "from_account",
    "to_bank",
    "to_account",
    "amount_received",
    "receiving_currency",
    "amount_paid",
    "payment_currency",
    "payment_format",
    "is_laundering",
]


def parse(input_path: Path, output_path: Path) -> tuple[int, int]:
    n_groups = 0
    n_rows = 0
    current_type: str | None = None
    current_group: int = 0

    with input_path.open("r", encoding="utf-8", errors="replace") as fin, \
         output_path.open("w", encoding="utf-8", newline="") as fout:
        writer = csv.writer(fout)
        writer.writerow(HEADER)

        for raw in fin:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            m = BEGIN_RE.match(line)
            if m:
                current_type = m.group(1).strip().upper()
                current_group += 1
                n_groups += 1
                continue

            if END_RE.match(line):
                current_type = None
                continue

            if current_type is None:
                continue
            
            fields = line.split(",")
            if len(fields) != 11:
                # Malformed row; warn but keep going.
                print(
                    f"WARN: unexpected field count ({len(fields)}) in "
                    f"{input_path.name} group {current_group}: {line[:80]}...",
                    file=sys.stderr,
                )
                continue

            writer.writerow([current_group, current_type, *fields])
            n_rows += 1

    return n_groups, n_rows


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.txt> <output.csv>", file=sys.stderr)
        return 1

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])

    if not in_path.is_file():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        return 1

    n_groups, n_rows = parse(in_path, out_path)
    print(f"parse_patterns: wrote {n_rows} rows across {n_groups} pattern groups → {out_path}")
    return 0


if __name__ == "__main__":
    main()