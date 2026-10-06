#!/bin/bash
# Install the pinned ucm: scripts/install-ucm.sh [DEST_DIR]   (default ~/.local/share/uni/ucm/release-1.5.0)
# Downloads the release tarball, checks its sha256 against ucm.pin, extracts into a fresh directory,
# then checks the executed files (ucm wrapper, unison/unison). ucm is unsigned and not notarized,
# so the pin is the only integrity check.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:-$HOME/.local/share/uni/ucm/release-1.5.0}"
pin() { awk -v f="$1" '$2==f{print $1}' "$here/ucm.pin"; }
[ ! -e "$dest" ] || [ -z "$(ls -A "$dest")" ] || { echo "install-ucm: $dest exists and is not empty" >&2; exit 1; }
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ucm-dl.XXXXXX")"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/ucm.tar.gz" "https://github.com/unisonweb/unison/releases/download/release/1.5.0/ucm-macos-arm64.tar.gz"
[ "$(shasum -a 256 "$tmp/ucm.tar.gz" | awk '{print $1}')" = "$(pin ucm-macos-arm64.tar.gz)" ] || { echo "install-ucm: tarball sha256 mismatch" >&2; exit 1; }
mkdir -p "$dest"; tar -xzf "$tmp/ucm.tar.gz" -C "$dest"
for f in ucm unison/unison; do
  [ "$(shasum -a 256 "$dest/$f" | awk '{print $1}')" = "$(pin "$f")" ] || { echo "install-ucm: $f sha256 mismatch" >&2; exit 1; }
done
echo "install-ucm: ucm 1.5.0 verified in $dest"
