#!/usr/bin/env python3
"""
Scan openrgb-headless/Controllers/**/*Detect*.cpp for REGISTER_*_DETECTOR(...)
macros and emit a JSON catalog of every supported device.

Output rows: {name, vid, pid, controller, kind}
- name        : first quoted string in the macro (display name)
- vid/pid     : resolved from #define / hex literal in the same file (best-effort)
- controller  : the parent Controllers/<X>/ folder
- kind        : "hid" | "i2c" | "smbus" | "dynamic" | "remote" | "generic"

Only factual data is extracted (device labels + USB IDs). No GPL source is copied.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "openrgb-headless" / "Controllers"
OUT = Path(__file__).resolve().parents[2] / "qos-service" / "data" / "openrgb-supported-devices.json"

# Match REGISTER_*_DETECTOR( "name" , identifier , ... ) including multi-line
MACRO_RE = re.compile(
    r"REGISTER_(?P<flavor>[A-Z_0-9]*?)DETECTOR(?:_[A-Z]+)?\s*\(\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<rest>[^;]*?)\)\s*;",
    re.DOTALL,
)

DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z0-9_]+)\s+(0x[0-9A-Fa-f]+|[0-9]+)", re.MULTILINE)
HEX_RE = re.compile(r"^(0x[0-9A-Fa-f]+|[0-9]+)$")


def classify(flavor: str) -> str:
    f = flavor.upper()
    if "HID" in f:
        return "hid"
    if "I2C" in f or "SMBUS" in f:
        return "i2c"
    if "DYNAMIC" in f:
        return "dynamic"
    if "REMOTE" in f:
        return "remote"
    if "PID" in f:
        return "hid"
    return "generic"


def resolve(token: str, defines: dict[str, str]) -> str | None:
    token = token.strip()
    if not token:
        return None
    if HEX_RE.match(token):
        return token
    if token in defines:
        v = defines[token]
        if HEX_RE.match(v):
            return v
    return None


def extract_from_file(path: Path) -> list[dict]:
    text = path.read_text(errors="replace")
    defines = dict(DEFINE_RE.findall(text))
    controller = path.relative_to(ROOT).parts[0]

    rows = []
    for m in MACRO_RE.finditer(text):
        name = m.group("name").strip()
        if not name:
            continue
        flavor = m.group("flavor") or ""
        kind = classify(flavor)
        rest = m.group("rest")
        # Drop comments inside arglist
        rest = re.sub(r"/\*.*?\*/", "", rest, flags=re.DOTALL)
        rest = re.sub(r"//[^\n]*", "", rest)
        args = [a.strip() for a in rest.split(",")]

        vid = pid = None
        if kind == "hid" and len(args) >= 3:
            # signature: function, vid, pid, ...
            vid = resolve(args[1], defines)
            pid = resolve(args[2], defines)

        rows.append(
            {
                "name": name,
                "vid": vid,
                "pid": pid,
                "controller": controller,
                "kind": kind,
            }
        )
    return rows


def main() -> int:
    if not ROOT.is_dir():
        print(f"error: not found: {ROOT}", file=sys.stderr)
        return 1

    all_rows: list[dict] = []
    files = sorted(ROOT.rglob("*Detect*.cpp")) + sorted(ROOT.rglob("*Detector*.cpp"))
    seen_files: set[Path] = set()
    for f in files:
        if f in seen_files:
            continue
        seen_files.add(f)
        try:
            all_rows.extend(extract_from_file(f))
        except Exception as ex:
            print(f"warn: {f}: {ex}", file=sys.stderr)

    # Stable de-dupe on (name, vid, pid)
    dedup: dict[tuple, dict] = {}
    for r in all_rows:
        key = (r["name"], r["vid"], r["pid"])
        if key not in dedup:
            dedup[key] = r
    out_rows = sorted(dedup.values(), key=lambda r: (r["controller"], r["name"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"count": len(out_rows), "devices": out_rows}, indent=2) + "\n")

    by_kind: dict[str, int] = {}
    for r in out_rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    print(f"wrote {len(out_rows)} devices to {OUT}")
    for k, n in sorted(by_kind.items()):
        print(f"  {k:8s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
