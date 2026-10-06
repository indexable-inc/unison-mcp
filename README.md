# unison-mcp

One MCP tool, `unison`, that is the user's REPL and general MCP client, written in Unison.

It is not only a helper for writing Unison. A cell you run with `action: "run"` can:

- act as an **MCP client** for any server, over stdio or streamable HTTP, with OAuth sign-in (browser pop-up, PKCE, device flow fallback, dynamic client registration, token refresh), for example Superhuman Mail;
- **drive Chrome over CDP** (find or open a tab, navigate, eval, read text, click, type, screenshot);
- run **processes**, read and write **files**, make **HTTP** calls;
- **write, typecheck, update, search and test Unison code** in a local codebase.

Claude Code sees one tool instead of the 29 tools of `ucm mcp`; the server proxies to them internally.

```
Claude Code --stdio--> bin/unison-mcp (launcher, own process group)
                         `-- ucm run.compiled unison-mcp.uc   (this repo, Unison: src/server.u)
                               `-- ucm mcp -C <codebase>      (supervised child, restarted when it dies or times out)
```

## Install

1. ucm 1.5.0, pinned by sha256 (it is unsigned and not notarized, `ucm.pin` is the only integrity check):
   `scripts/install-ucm.sh` (downloads, checks the tarball and the two executed files, extracts to `~/.local/share/uni/ucm/release-1.5.0`).
2. A codebase with project `main`, branch `main`, and the libraries `@unison/base` 7.19.2, `@unison/http` 16.1.0, `@unison/json` 1.4.2:
   `scripts/build.sh ~/.local/share/uni/codebase` creates it on first use (needs network once).
3. `scripts/install.sh` loads the repo into the codebase (`--codebase DIR` for another one, `--migrate-old` to replace the earlier in-codebase `Mcp`/`Superhuman` definitions), compiles `Server.main` and installs the launcher as `~/.local/share/uni/unison-mcp` next to `unison-mcp.uc` and `ucm.pin`. It refuses while another ucm holds the codebase, and afterwards runs `scripts/verify-install.sh` (Cdp.connect, Mcp.toolNames, Server.main and Jx.get must be searchable in main/main: cells see the codebase, not the compiled `.uc`). `--dest DIR` installs the launcher elsewhere.
4. Claude Code: `claude mcp add unison -- ~/.local/share/uni/unison-mcp`

The launcher checks `unison/unison` against `ucm.pin` on every start (`UNISON_MCP_SKIP_PIN_CHECK=1` skips), runs the server in its own process group, and kills that whole group when stdin closes or on SIGTERM/SIGHUP/SIGINT.

**Lazy, short-lived ucm child.** The server spawns `ucm mcp` on the first call that needs it (`initialize`, `tools/list` and `ping` never do), and stops it after `UNISON_MCP_IDLE_MS` (default 4000) without a call, so an idle server holds nothing. Several launchers (several Claude sessions) can run at once and interleave calls; each names its scratch cells with its own pid (`scratch.mcpCell_<pid>`, `scratch.mcpRun_<pid>`), so sessions never run each other's cells. A CLI `ucm` (an install, a transcript) waits for the codebase lock while any `ucm mcp` child is alive; with idle children it gets the lock a few seconds after the last call. If ucm will not start (for example because something holds the lock), the server retries with backoff (250 ms doubling to 2 s) for `UNISON_MCP_START_WAIT_MS` (default 20000) and then replies `class: timeout` with a message about the codebase lock.

Environment: `UNISON_MCP_CODEBASE` (default `~/.local/share/uni/codebase`), `UNISON_MCP_UCM_DIR`, `UNISON_MCP_PROGRAM`, `UNISON_MCP_PROJECT` / `UNISON_MCP_BRANCH` (default `main`/`main`), `UNISON_MCP_TIMEOUT_MS` (default 120000), `UNISON_MCP_IDLE_MS`, `UNISON_MCP_START_WAIT_MS`, `UNISON_MCP_CHILD_UCM` (ucm binary for the child only; tests use a fake).

## The tool

`unison` takes:

| field | meaning |
|---|---|
| `code` | Unison source (check, update, diff, type-search), or the body of a `do` block (`run` without `name`) |
| `action` | `check` (default), `run`, `update`, `view`, `search`, `type-search`, `install`, `docs`, `tests`, `diff`, `guide`, `tools`, `tool` |
| `name` | definition(s), search query, library project, tests subnamespace or raw ucm tool name, by action |
| `args` | arguments of the run main function, or `[branch]` for `install` |
| `topic` | for `guide`: unison-basics, http-json, mcp-client, oauth, cdp, process-ffi, traps (text in `docs/guide/*.md`, embedded into the build by `scripts/gen-guide.py` as `src/guide.u`) |
| `json` | raw JSON arguments for `action: "tool"` (any ucm tool; `projectContext` is added when missing) |
| `timeout_ms` | per call, default 120000; on timeout the ucm child is killed and restarts on the next call |
| `project`, `branch` | default `main`, `main` |

The reply is text that starts with three header lines, then the messages:

```
stage: typecheck        # typecheck | run | update | view | search | ... | unison (transport failure)
ok: false
class: type-mismatch    # none | wrong-name | ambiguous-name | type-mismatch | unhandled-ability | parse-error | timeout | child-died | rpc-error | usage | error
```

A reply longer than about 12,000 characters is cut to head and tail; the full text is written to `~/.local/share/uni/spill/<time>-<n>.txt` and its path is in the reply. `Mcp.toolNames server` lists tool names only.

A `run` cell whose code has definitions (a type signature or `type`/`ability` line) and ends with a `> expr` line or a bare expression is loaded under `scratch.mcpRun` and the expression is run.

Compile errors are data: `isError` is false and `ok: false` carries the verdict (ucm itself exits 0 on compile errors). `isError` is true only for infrastructure failures (timeout, dead child).

Examples (`code` of `action: "run"` unless noted):

```
> 1 + 2                                                    (action check, code "> 1 + 2")
Mcp.run do Mcp.call "superhuman" "list_threads" "{\"limit\":3}"
Mcp.run do Superhuman.listThreads 3                        (examples/superhuman.u)
Mcp.login "superhuman"                                     (opens the browser, stores the token 0600)
Cdp.connect Cdp.endpoint "github.com" do !Cdp.readPage
(i, o, e, p) = Process.start "git" ["status", "-s"]
getText o
```

## MCP client (`src/mcp.u`, generic)

`Mcp.Server = Server name transport auth`; transport `Remote url` (streamable HTTP, JSON or SSE replies) or `Local cmd args` (stdio); auth `NoAuth | Header | BearerEnv VAR | OAuth`. OAuth: discovery (`/.well-known/oauth-protected-resource`, then authorization-server metadata), dynamic client registration, PKCE with the loopback redirect `127.0.0.1:8976` (the client runs macOS `open` on the URL) when an authorization endpoint is advertised, otherwise the RFC 8628 device flow; refresh on 401. Tokens live in `~/.local/share/uni/mcp/<name>.json` (0600) and are never printed.

Servers are configured in `~/.local/share/uni/mcp/servers.json`:

```json
{"superhuman": {"url": "https://mcp.mail.superhuman.com/mcp", "auth": "oauth"},
 "fs": {"command": "npx", "args": ["-y", "some-mcp-server"], "auth": "none"},
 "x": {"url": "https://example.com/mcp", "auth": "bearer-env:X_TOKEN"}}
```

Use `Mcp.run do ...` for the real handler and `Mcp.fake f do ...` for a test double. Superhuman is only an example module (`examples/superhuman.u`), not part of the core.

## Chrome over CDP (`src/cdp.u`, independent of MCP)

`ability Cdp` (`send method paramsJson`, `drain` for buffered events) with a real handler over the `@unison/http` WebSocket client (`Cdp.run wsUrl`, `Cdp.connect base urlSubstring`) and a fake (`Cdp.fake f`). The endpoint defaults to `http://127.0.0.1:9222` (`Cdp.endpoint`).

| function | |
|---|---|
| `Cdp.targets base`, `Cdp.pageFor base substr` | list targets; find a page by URL substring or open a tab (`http`, `data:`, `about:` URLs) |
| `Cdp.call method paramsJson` | command; raises on a protocol error; events seen meanwhile are buffered |
| `Cdp.eval js`, `Cdp.evalText`, `Cdp.evalBool` | `Runtime.evaluate` with `returnByValue` and `awaitPromise` |
| `Cdp.navigate url` | `Page.navigate`, then waits for `readyState === 'complete'` |
| `Cdp.waitFor (Cdp.Wait.Load \| Selector s \| Contains t) ms` | polls every 50 ms; false on timeout |
| `!Cdp.readPage` | `document.body.innerText` |
| `Cdp.click sel`, `Cdp.typeText sel text` | click; focus and `Input.insertText` |
| `Cdp.screenshot path` | PNG to a file, returns the byte count |

CDP is not JSON-RPC 2.0: a `"jsonrpc"` member makes Chrome ignore the message, so `Cdp` sends only `id`, `method`, `params`.

## Self-evolving codebase (optional, off by default)

Agents add definitions to the codebase through `action: "update"`. To keep them, the server can commit every successful change to a **private** git repo; this public repo contains only the mechanism and no personal path, repo name or data.

```
Claude Code --update--> server (Server.evolve) --stdin: reply text--> unison-evolve commit   (detaches at once, never fails the call)
                                                   | lock (mkdir built under a temp name, renamed), then
                                                   | sqlite online backup of the codebase -> REPO/codebase/unison.sqlite3
                                                   | ucm on a copy of the snapshot -> REPO/export/{INDEX.txt,head.txt,libs.txt,defs/<name>.u}
                                                   `-- git commit "update: Foo.bar, ..." (session, lane, head), signed per git config
```

- Public (this repo): `scripts/evolve.py` (installed as `unison-evolve`), the hook and the `sync` action in `src/server.u`, guide topic `evolve`, `tests/evolve.py`.
- Private (the user's repo, for example `unison-codebase`): the snapshot, the export, personal modules (example Superhuman config, a `servers.json` template without tokens), `.secrets-allow`. Token state files under `~/.local/share/uni/mcp/*.json` are never committed (the scan refuses them).
- Switch on with `UNISON_MCP_EVOLVE_REPO=/path/to/private/repo` in the environment or in `~/.local/share/uni/unison-mcp.env` (sourced by the launcher; `UNISON_MCP_CONFIG` names another file). Optional: `UNISON_MCP_LANE` (named in the commit), `UNISON_MCP_EVOLVE_PUSH=1` (push after each commit, after the secrets scan; default is local commits only), `UNISON_MCP_EVOLVE_SIGN=0`.
- Triggers: `update`, `install`, `run` with `name` and `code`, and raw `tool` calls to update-definitions, delete-definitions, delete-namespace, rename-definition, move-definition, move-to, lib-install. Failed updates and scratch cells commit nothing. Every successful update gets its own commit (an empty diff is allowed when a concurrent session's snapshot already contained it). Errors only go to `REPO/.git/unison-evolve.log`.
- `action: "sync"` stops this session's ucm child, fast-forwards the repo from `origin`, replaces the live codebase by the pulled snapshot only when it has no changes the repo lacks and no other ucm holds it, runs the secrets scan and pushes.
- `unison-evolve restore --codebase CB --repo REPO REV` puts an older snapshot back (refuses while a ucm holds CB; the states before and after are commits). `verify` checks integrity, that the export equals a fresh export of the snapshot, and optionally the live head. `scan [--accept]` is the secrets scan.
- Why plain git and not LFS: the codebase is a 28 MB sqlite whose pages mostly do not move. The online backup API keeps the page layout, so a snapshot packs to a delta of a few KB; `VACUUM INTO` would reshuffle pages and defeat that. Loose commits are repacked (`git repack -a -d`) when they exceed 40 MiB.
- The text export is the diff and merge surface, the sqlite is the truth: the export does not carry the GUID of `unique type`s, so a rebuild from text alone gives such types (and what depends on them) new hashes.

## Design

- `src/jx.u` JSON helpers. `src/stdio.u` supervised JSON-RPC client over a child process (health check by exit code, per-call deadline on a monotonic clock, kill -9 on stop). `src/mcp.u` generic MCP client. `src/cdp.u` CDP. `src/server.u` the one-tool server. `examples/` vendor-specific modules. `ORDER` is the load order.
- Why `kill -9` and a reader thread: `ucm` only reacts to SIGTERM after the running computation ends, so a timed-out `run` would otherwise hold the call for its full length; the child is started through `sh -c 'echo $$ >&2; exec ...'` to learn its pid. Reads happen on a forked thread that the caller polls against the deadline.
- Supervision: before each call the child is started if missing or dead; a timeout or broken pipe stops it and returns `class: timeout` / `child-died`; the next call restarts it. A call is never retried automatically (an `update` might have run).
- A `run` with only `code` is wrapped as `scratch.mcpCell = do ...`, updated, run, and deleted again (not after a timeout).
- Considered and not used: existing Unison Share MCP and OAuth libraries (none covers streamable HTTP, dynamic client registration or discovery, or has a usable licence): `docs/upstream/unison-share-mcp-oauth/SOURCE.md`.

## Build, check, test

- `scripts/build.sh CODEBASE [OUT.uc]` loads `ORDER` into a (new or existing) codebase and compiles `Server.main`. `UNISON_MCP_PRE` holds ucm commands to run first (migrations).
- `scripts/check.sh CODEBASE` rebuilds the repo into a temp codebase and compares (name, hash) of every definition in our namespaces with `CODEBASE`: repo == codebase. Run it with no ucm holding `CODEBASE`.
- `python3 -I tests/evolve.py` the self-evolving codebase on throwaway copies: one commit per update naming the definition, two concurrent sessions give two commits and a consistent store, a failing update commits nothing, restore brings back the previous definition, sync pushes after the secrets scan and pulls into a clean clone.
- `python3 -I tests/integration.py` scripted JSON-RPC over stdio against the real launcher and ucm: `tools/list` is one tool, a type error is data, `> 1 + 2`, the error classes, `run`, the timeout kills the child and the server recovers, restart after the child is killed, process-group cleanup on stdin close and SIGTERM, and a headless Chrome on a throwaway profile and a random port (navigate to a `data:` URL, eval, read text, click, type, screenshot; never the browser on :9222).

## Licence

MIT, see `LICENSE`. Runtime dependencies are `@unison/base`, `@unison/http`, `@unison/json` (MIT) and ucm 1.5.0 (MIT).
