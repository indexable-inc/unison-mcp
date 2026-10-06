#!/bin/bash
# Check that the repo definitions are searchable in project main of a codebase: scripts/verify-install.sh CODEBASE_DIR
# Cells see only the codebase, never the compiled .uc, so a build that was not updated into it hides Cdp.*, Mcp.*.
set -uo pipefail
cb="${1:?usage: verify-install.sh CODEBASE_DIR}"
ucm="${UNISON_MCP_UCM_DIR:-$HOME/.local/share/uni/ucm/release-1.5.0}/ucm"
dir="$(mktemp -d "${TMPDIR:-/tmp}/unison-mcp-verify.XXXXXX")"
trap 'rm -rf "$dir"' EXIT
{ echo '```ucm'; echo 'scratch/main> switch main/main'; echo '```'
  for n in Cdp.connect Mcp.toolNames Server.main Jx.get; do echo '```ucm'; echo "main/main> find.verbose $n"; echo '```'; done; } > "$dir/v.md"
"$ucm" -c "$cb" transcript.in-place "$dir/v.md" >/dev/null 2>&1 || true
if grep -q '🛑' "$dir/v.output.md" 2>/dev/null || [ "$(grep -c '^ *1\. -- #' "$dir/v.output.md" 2>/dev/null)" -lt 4 ]; then
  echo "verify-install: FAILED, the repo definitions are not in main/main of $cb" >&2; exit 1; fi
echo "install: verified Cdp.connect, Mcp.toolNames, Server.main, Jx.get in main/main of $cb"
