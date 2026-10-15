#!/usr/bin/env python3
"""
Scan openrgb-headless/Controllers/**/*Detect*.cpp for REGISTER_*_DETECTOR(...)
macros and emit a JSON catalog of every supported device.

Output rows: {name, vid, pid, controller, kind}
- name        : first quoted string in the macro (display name)
- vid/pid     : hex literal, or a #define resolved from the detector file, the headers
                it includes, and the headers in its controller folder (best-effort).
                A wildcard such as HID_PID_ANY stays null.
- controller  : the parent Controllers/<X>/ folder
- kind        : "hid" | "i2c" | "smbus" | "dynamic" | "remote" | "generic"

Usage: extract-supported-devices.py [<Controllers dir> [<output json>]]
The defaults assume nexus-rgb/ and nexus-service/ sit side by side.

Only factual data is extracted (device labels + USB IDs). No GPL source is copied.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "openrgb-headless" / "Controllers"
OUT = Path(__file__).resolve().parents[2] / "nexus-service" / "data" / "openrgb-supported-devices.json"
INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)

# Match REGISTER_*_DETECTOR( "name" , identifier , ... ) including multi-line
MACRO_RE = re.compile(
    r"REGISTER_(?P<flavor>[A-Z_0-9]*?)DETECTOR(?:_[A-Z]+)?\s*\(\s*"
    r'"(?P<name>[^"]*)"\s*,\s*'
    r"(?P<rest>[^;]*?)\)\s*;",
    re.DOTALL,
)

# Value is a literal (optionally parenthesized, with an integer suffix) or another identifier.
DEFINE_RE = re.compile(
    r"^\s*#\s*define\s+([A-Za-z0-9_]+)[ \t]+\(?[ \t]*((?:0x[0-9A-Fa-f]+|[0-9]+)(?:[uUlL]*)|[A-Za-z_][A-Za-z0-9_]*)[ \t]*\)?[ \t]*(?://.*|/\*.*)?$",
    re.MULTILINE,
)
HEX_RE = re.compile(r"^(0x[0-9A-Fa-f]+|[0-9]+)[uUlL]*$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_SUFFIXES = {".h", ".hpp"}


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
    if "WOOTING" in f:
        return "hid"
    return "generic"


class Defines:
    """Looks up #define constants for a detector file: its own text, the quoted
    includes it pulls in (transitively), then every header in its controller folder."""

    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[Path, dict[str, str]] = {}
        self.text: dict[Path, str] = {}
        self.by_name: dict[str, list[Path]] = {}
        for h in root.parent.rglob("*"):
            if h.suffix in HEADER_SUFFIXES:
                self.by_name.setdefault(h.name, []).append(h)

    def read(self, path: Path) -> str:
        if path not in self.text:
            self.text[path] = path.read_text(errors="replace")
        return self.text[path]

    def own(self, path: Path) -> dict[str, str]:
        if path not in self.cache:
            self.cache[path] = dict(DEFINE_RE.findall(self.read(path)))
        return self.cache[path]

    def include_closure(self, path: Path) -> list[Path]:
        seen: list[Path] = []
        todo = [path]
        while todo:
            cur = todo.pop(0)
            if cur in seen:
                continue
            seen.append(cur)
            for inc in INCLUDE_RE.findall(self.read(cur)):
                local = (cur.parent / inc).resolve()
                if local.is_file():
                    todo.append(local)
                    continue
                # Quoted includes are also found through the project include path.
                todo.extend(self.by_name.get(Path(inc).name, []))
        return seen

    def scope(self, path: Path) -> dict[str, str]:
        merged: dict[str, str] = {}
        controller_dir = self.root / path.relative_to(self.root).parts[0]
        # Lowest priority first: controller folder headers, then includes, then the file itself.
        for h in sorted(h for h in controller_dir.rglob("*") if h.suffix in HEADER_SUFFIXES):
            merged.update(self.own(h))
        for src in reversed(self.include_closure(path)):
            merged.update(self.own(src))
        return merged


def resolve(token: str, defines: dict[str, str]) -> str | None:
    token = token.strip()
    seen: set[str] = set()
    while token:
        if HEX_RE.match(token):
            return re.sub(r"[uUlL]+$", "", token)
        if not IDENT_RE.match(token) or token in seen:
            return None
        seen.add(token)
        token = defines.get(token, "").strip()
    return None


def extract_from_file(path: Path, scopes: Defines) -> list[dict]:
    text = path.read_text(errors="replace")
    defines = scopes.scope(path.resolve())
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
        if kind == "hid":
            # signature: function, vid, pid, ...; the Wooting wrapper macro is (name, vid, pid)
            first = 0 if "WOOTING" in flavor else 1
            if len(args) >= first + 2:
                vid = resolve(args[first], defines)
                pid = resolve(args[first + 1], defines)

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
    global ROOT, OUT
    # Optional overrides for checkouts that do not sit in the default workspace layout:
    #   extract-supported-devices.py [<Controllers dir> [<output json>]]
    if len(sys.argv) > 1:
        ROOT = Path(sys.argv[1])
    if len(sys.argv) > 2:
        OUT = Path(sys.argv[2])
    ROOT = ROOT.resolve()
    if not ROOT.is_dir():
        print(f"error: not found: {ROOT}", file=sys.stderr)
        return 1
    scopes = Defines(ROOT)

    all_rows: list[dict] = []
    files = sorted(ROOT.rglob("*Detect*.cpp")) + sorted(ROOT.rglob("*Detector*.cpp"))
    seen_files: set[Path] = set()
    for f in files:
        if f in seen_files:
            continue
        seen_files.add(f)
        try:
            all_rows.extend(extract_from_file(f, scopes))
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
