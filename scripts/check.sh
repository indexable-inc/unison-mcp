#!/bin/bash
# Prove the repo equals a codebase: scripts/check.sh CODEBASE_DIR
# Builds a fresh codebase from the repo in a temp dir, then compares (name, hash) of every
# definition under our namespaces (Jx Stdio Mcp Cdp Server Superhuman) with CODEBASE_DIR.
# Run it with no ucm holding CODEBASE_DIR (use a copy of a live codebase).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cb="${1:?usage: check.sh CODEBASE_DIR}"
ucm="${UNISON_MCP_UCM_DIR:-$HOME/.local/share/uni/ucm/release-1.5.0}/ucm"
work="$(mktemp -d "${TMPDIR:-/tmp}/unison-mcp-check.XXXXXX")"
trap 'rm -rf "$work"' EXIT
"$here/scripts/build.sh" "$work/fresh" >/dev/null
dump() { # codebase out
  local t="$work/dump.$$.md"
  { echo '```ucm'; echo 'scratch/main> switch main/main'; echo '```'
    for ns in Jx Stdio Mcp Cdp Server Superhuman; do echo '```ucm'; echo "main/main> find.verbose $ns"; echo '```'; done; } > "$t"
  "$ucm" -c "$1" transcript.in-place "$t" >/dev/null 2>&1 || true
  python3 -I - "${t%.md}.output.md" > "$2" <<'PY'
import re, sys
lines = open(sys.argv[1], encoding="utf8").read().splitlines()
out = set()
for i, l in enumerate(lines):
    m = re.match(r"\s+\d+\.\s+-- (#\S+)", l)
    if m and i + 1 < len(lines):
        name = lines[i + 1].strip().split(" : ")[0]
        if re.match(r"(Jx|Stdio|Mcp|Cdp|Server|Superhuman)\.", name):
            out.add(f"{name} {m.group(1)}")
print("\n".join(sorted(out)))
PY
}
dump "$work/fresh" "$work/repo.txt"
dump "$cb" "$work/live.txt"
n=$(wc -l < "$work/repo.txt")
if [ "$n" -lt 50 ]; then echo "check: suspiciously few definitions in the repo build ($n)" >&2; exit 2; fi
if diff "$work/repo.txt" "$work/live.txt" > "$work/diff.txt"; then echo "check: repo == codebase ($n definitions)"; else cat "$work/diff.txt" | head -40; echo "check: DIFFERENT" >&2; exit 1; fi
