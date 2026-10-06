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
3. `scripts/install.sh` loads the repo into the codebase (`--codebase DIR` for another one, `--migrate-old` to replace the earlier in-codebase `Mcp`/`Superhuman` definitions), compiles `Server.main` and installs the launcher as `~/.local/share/uni/unison-mcp` next to `unison-mcp.uc` and `ucm.pin`. It refuses while another ucm holds the codebase.
4. Claude Code: `claude mcp add unison -- ~/.local/share/uni/unison-mcp`

The launcher checks `unison/unison` against `ucm.pin` on every start (`UNISON_MCP_SKIP_PIN_CHECK=1` skips), runs the server in its own process group, and kills that whole group when stdin closes or on SIGTERM/SIGHUP/SIGINT.

Environment: `UNISON_MCP_CODEBASE` (default `~/.local/share/uni/codebase`), `UNISON_MCP_UCM_DIR`, `UNISON_MCP_PROGRAM`, `UNISON_MCP_PROJECT` / `UNISON_MCP_BRANCH` (default `main`/`main`), `UNISON_MCP_TIMEOUT_MS` (default 120000).

## The tool

`unison` takes:

| field | meaning |
|---|---|
| `code` | Unison source (check, update, diff, type-search), or the body of a `do` block (`run` without `name`) |
| `action` | `check` (default), `run`, `update`, `view`, `search`, `type-search`, `install`, `docs`, `tests`, `diff`, `guide`, `tools`, `tool` |
| `name` | definition(s), search query, library project, tests subnamespace or raw ucm tool name, by action |
| `args` | arguments of the run main function, or `[branch]` for `install` |
| `json` | raw JSON arguments for `action: "tool"` (any ucm tool; `projectContext` is added when missing) |
| `timeout_ms` | per call, default 120000; on timeout the ucm child is killed and restarts on the next call |
| `project`, `branch` | default `main`, `main` |

The reply is text that starts with three header lines, then the messages:

```
stage: typecheck        # typecheck | run | update | view | search | ... | unison (transport failure)
ok: false
class: type-mismatch    # none | wrong-name | ambiguous-name | type-mismatch | unhandled-ability | parse-error | timeout | child-died | rpc-error | usage | error
```

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

## Design

- `src/jx.u` JSON helpers. `src/stdio.u` supervised JSON-RPC client over a child process (health check by exit code, per-call deadline on a monotonic clock, kill -9 on stop). `src/mcp.u` generic MCP client. `src/cdp.u` CDP. `src/server.u` the one-tool server. `examples/` vendor-specific modules. `ORDER` is the load order.
- Why `kill -9` and a reader thread: `ucm` only reacts to SIGTERM after the running computation ends, so a timed-out `run` would otherwise hold the call for its full length; the child is started through `sh -c 'echo $$ >&2; exec ...'` to learn its pid. Reads happen on a forked thread that the caller polls against the deadline.
- Supervision: before each call the child is started if missing or dead; a timeout or broken pipe stops it and returns `class: timeout` / `child-died`; the next call restarts it. A call is never retried automatically (an `update` might have run).
- A `run` with only `code` is wrapped as `scratch.mcpCell = do ...`, updated, run, and deleted again (not after a timeout).
- Considered and not used: existing Unison Share MCP and OAuth libraries (none covers streamable HTTP, dynamic client registration or discovery, or has a usable licence): `docs/upstream/unison-share-mcp-oauth/SOURCE.md`.

## Build, check, test

- `scripts/build.sh CODEBASE [OUT.uc]` loads `ORDER` into a (new or existing) codebase and compiles `Server.main`. `UNISON_MCP_PRE` holds ucm commands to run first (migrations).
- `scripts/check.sh CODEBASE` rebuilds the repo into a temp codebase and compares (name, hash) of every definition in our namespaces with `CODEBASE`: repo == codebase. Run it with no ucm holding `CODEBASE`.
- `python3 -I tests/integration.py` scripted JSON-RPC over stdio against the real launcher and ucm: `tools/list` is one tool, a type error is data, `> 1 + 2`, the error classes, `run`, the timeout kills the child and the server recovers, restart after the child is killed, process-group cleanup on stdin close and SIGTERM, and a headless Chrome on a throwaway profile and a random port (navigate to a `data:` URL, eval, read text, click, type, screenshot; never the browser on :9222).

## Licence

MIT, see `LICENSE`. Runtime dependencies are `@unison/base`, `@unison/http`, `@unison/json` (MIT) and ucm 1.5.0 (MIT).
