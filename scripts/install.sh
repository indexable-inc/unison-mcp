#!/bin/bash
# Install the server: scripts/install.sh [--codebase DIR] [--migrate-old]
# Loads the repo into the codebase (default ~/.local/share/uni/codebase, project main), compiles
# Server.main and installs the launcher as ~/.local/share/uni/unison-mcp (+ unison-mcp.uc, ucm.pin).
# Refuses while any ucm holds the codebase. --migrate-old first deletes the pre-repo Mcp/Superhuman
# definitions (the older in-codebase client), which clash with the new ones.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cb="$HOME/.local/share/uni/codebase"; migrate=0
while [ $# -gt 0 ]; do case "$1" in
  --codebase) cb="$2"; shift 2;;
  --migrate-old) migrate=1; shift;;
  *) echo "usage: install.sh [--codebase DIR] [--migrate-old]" >&2; exit 2;; esac; done
if ps -eo args= | grep -F -- "-C $cb" | grep -v grep | grep -q .; then
  echo "install: a ucm still holds $cb (stop the running unison MCP server first)" >&2; exit 1; fi
dest="$HOME/.local/share/uni"
tmpuc="$(mktemp "${TMPDIR:-/tmp}/unison-mcp.XXXXXX")"
if [ "$migrate" = 1 ]; then
  export UNISON_MCP_PRE=$'delete.namespace.force Superhuman\ndelete.namespace.force Mcp\ndelete.type.force Mcp'
fi
"$here/scripts/build.sh" "$cb" "$tmpuc"
install -m 755 "$here/bin/unison-mcp" "$dest/unison-mcp"
install -m 644 "$tmpuc" "$dest/unison-mcp.uc"
install -m 644 "$here/ucm.pin" "$dest/ucm.pin"
rm -f "$tmpuc"
echo "install: done. Claude Code config: claude mcp add unison -- $dest/unison-mcp"
