#!/bin/bash
# Build the codebase from the repo: scripts/build.sh CODEBASE_DIR [OUT.uc]
# Creates CODEBASE_DIR if missing, installs the pinned libraries, loads src/*.u
# in order, updates, and compiles `Server.main` to OUT.uc when given.
# Needs network on the first run (lib.install from Unison Share).
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cb="${1:?usage: build.sh CODEBASE_DIR [OUT.uc]}"
out="${2:-}"
ucm="${UNISON_MCP_UCM_DIR:-$HOME/.local/share/uni/ucm/release-1.5.0}/ucm"
work="$(mktemp -d "${TMPDIR:-/tmp}/unison-mcp-build.XXXXXX")"
trap 'rm -rf "$work"' EXIT
t="$work/build.md"
{
  if [ -e "$cb/.unison" ]; then
    echo '```ucm'; echo 'scratch/main> switch main/main'; echo '```'
  else
    echo '```ucm'; echo 'scratch/main> project.create-empty main'; echo '```'
  fi
  if [ ! -e "$cb/.unison" ] || [ "${UNISON_MCP_INSTALL_LIBS:-0}" = 1 ]; then
    echo '```ucm'; echo 'main/main> lib.install @unison/base/releases/7.19.2'; echo '```'
    echo '```ucm'; echo 'main/main> lib.install @unison/http/releases/16.1.0'; echo '```'
    echo '```ucm'; echo 'main/main> lib.install @unison/json/releases/1.4.2'; echo '```'
  fi
  # UNISON_MCP_PRE: ucm commands run first (one per line), e.g. to migrate an older codebase
  while IFS= read -r cmd; do
    [ -z "$cmd" ] || { echo '```ucm'; echo "main/main> $cmd"; echo '```'; }
  done <<< "${UNISON_MCP_PRE:-}"
  for f in $(cat "$here/ORDER"); do
    cp "$here/${f}" "$work/$(basename $f)"
    echo '```ucm'; echo "main/main> load $work/$(basename $f)"; echo '```'
    echo '```ucm'; echo 'main/main> update'; echo '```'
  done
  if [ -n "$out" ]; then
    echo '```ucm'; echo "main/main> compile Server.main $work/server"; echo '```'
  fi
} > "$t"
if [ -e "$cb/.unison" ]; then sub=transcript.in-place; flag=-c; else sub=transcript.in-place; flag=-C; fi
"$ucm" "$flag" "$cb" "$sub" "$t" >"$work/stdout.txt" 2>&1 || true
cp "$work/build.output.md" "$work/out.txt" 2>/dev/null || cp "$work/stdout.txt" "$work/out.txt"
if grep -q "🛑" "$work/out.txt"; then grep -n -B3 -A25 "🛑" "$work/out.txt" | head -80; else tail -n 15 "$work/out.txt"; fi
nfiles=$(wc -w < "$here/ORDER")
ndone=$(grep -c '^  Done\.' "$work/out.txt" || true)
[ -n "${UNISON_MCP_DEBUG:-}" ] && cp "$work/out.txt" "$UNISON_MCP_DEBUG"
# warnings from the UNISON_MCP_PRE stanzas (deleting old definitions) are expected; judge only from the first load on
sed -n '/> load /,$p' "$work/out.txt" > "$work/judge.txt"
if grep -qE '⚠️|❗️|I got confused|I couldn.t|Type mismatch|type mismatch|There was an error|not found|ambiguous' "$work/judge.txt" || [ "$ndone" -lt "$nfiles" ]; then echo "BUILD FAILED (updates done: $ndone of $nfiles)" >&2; exit 1; fi
[ -z "$out" ] || cp "$work/server.uc" "$out"
