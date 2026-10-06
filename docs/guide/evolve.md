# evolve: add definitions, keep history, roll back

Every definition you add or change is kept. When the user has a private codebase repo configured, each successful `update` (also `install`, `run` with `name` and `code`, and the raw tools update-definitions, delete-definitions, delete-namespace, rename-definition, move-definition, move-to, lib-install) becomes one git commit there, made in the background after the reply. Nothing in this public server names a repo: it is switched on by `UNISON_MCP_EVOLVE_REPO` in `~/.local/share/uni/unison-mcp.env` (or the environment).

Adding a capability:
1. Look first: `action:'search'` for the name; reuse before writing.
2. `action:'check'` the code, then `action:'update'` with the final code. Give it a real namespace (`Foo.bar`), not a scratch name; scratch cells from `run` are deleted and never committed.
3. A short doc comment (`-- ...`) above each definition says what it is for. Add a `test>` line when the behaviour is checkable.
4. The reply stays `ok: true` whether or not the commit works: the commit runs detached, serialised by a lock, and logs to `<repo>/.git/unison-evolve.log`. Look there when `git log` has no new commit after a few seconds.

What a commit holds (private repo): `codebase/unison.sqlite3` (a consistent online backup of the codebase: git is the source of truth), `export/defs/*.u` (one file per definition, first line `-- #hash`), `export/INDEX.txt` (kind, name, hash of every definition outside lib and scratch) and `export/head.txt` (namespace hash of the branch). The message names the added or changed definitions, the session (server pid) and the lane (`UNISON_MCP_LANE`).

History and rollback:
- `git -C REPO log --stat` is the history; `git log -p -- export/defs/Foo.bar.u` is one definition's history; the text export is the diff and merge surface.
- Restore an older state of the whole codebase: stop every ucm on it (the lazy child exits about 4 s after idle), then `unison-evolve restore --codebase CB --repo REPO REV`. It refuses while a ucm holds the codebase, and copies the snapshot of REV into place.
- The reflog tool: `action:'tool', name:'reflog'` lists the earlier roots of the branch (every update and delete, with hashes), `action:'tool', name:'history'` the namespace history. It is read-only here; to go back use the git restore above (the repo keeps the snapshot of every update, the reflog only what ucm still holds).
- `action:'sync'` fast-forwards the repo from its remote, swaps in the pulled snapshot when the live codebase has no changes the repo lacks and no other ucm holds it, runs a secrets scan, then pushes. Commits are never pushed automatically unless `UNISON_MCP_EVOLVE_PUSH=1`.

Traps:
- Concurrent sessions: each commit takes a snapshot of the whole codebase at that moment, so a commit can contain a sibling session's definition; every update still gets its own commit (empty diff allowed).
- The export is for reading and merging, the sqlite is the truth: rebuild with `unison-evolve verify --repo REPO` (loads the export into a throwaway copy and compares hashes).
- Never copy a live codebase file by hand while a ucm runs (WAL): the commit step uses the sqlite backup API.
