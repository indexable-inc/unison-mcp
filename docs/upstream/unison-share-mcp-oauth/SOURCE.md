# Unison Share MCP and OAuth libraries: depend or keep our own?

Fetched 2026-10-06 (UTC). No bytes of any library are stored here (facts only).
Question: should the Unison MCP project (stdio server proxying to `ucm mcp`, plus a generic MCP client with
HTTP + OAuth PKCE / device flow / dynamic client registration) depend on existing Share libraries?
Method: Share project API (`https://api.unison-lang.org/users/<h>/projects/<p>[/branches/main/browse?namespace=..|/definitions/by-name/..|/find]`),
the unison MCP tools (share-project-info/readme/search), WebFetch of GitHub. Status tags: [read] seen in the primary text,
[reported] stated by a secondary source, [unverified] not found.

## Summary table

| Library | Latest release | Last update (branch/project) | Licence | Role | Deps (lib/) | Verdict |
|---|---|---|---|---|---|---|
| @kubukoz/mcp | none (branch main only) | 2026-03-27 | [unverified] none on Share, no source repo found | typed MCP schema 2025-11-25 + stdio server demo | unison_base 7.15.0, jsonrpc_main, baccata_schemas 0.2.0 | borrow ideas |
| @mizchi/mcp | none | 2025-06-27 ("dev") | MIT [read: README "## License MIT"] | hand-rolled JSON-RPC message builders, protocol 2024-11-05 | base 4.4.0, json 1.3.5 | keep ours |
| @nusentry/unison-mcp | 1.0.0 | 2026-05-08 (branch), project 2026-01-11 | [unverified] none on Share, no repo found | spawns `ucm mcp` over stdio, wraps each UCM tool | mizchi_mcp (branch main, not a release), json 1.3.5 | borrow ideas (closest to our proxy target) |
| @goenninger/tcmcp | none | 2026-03-19 | [unverified] repo goenninger-b-t/tc-mcp lists no LICENSE file (WebFetch of repo listing) | Siemens Teamcenter MCP server, 30+ tools, stdio JSON-RPC loop | nusentry_unison_mcp 0.5.1, http 15.2.0, json 1.3.5 | keep ours (domain-specific) |
| @kylegoetz/oauth2-client | none | 2025-06-01 (project 2025-05-28) | MIT [read: `metadata.license = License [copyrightHolders.kylegoetz] [Year 2025] mit` in the codebase, via definitions API] | OAuth2: auth-code, PKCE, device authorization, client credentials, jwt-bearer, password, refresh | http 3.8.1, json 1.3.4 | borrow ideas (best OAuth reference) |
| @alvaroc1/oauth2 | 0.0.6 | 2025-03-24 (branch 2024-09-29) | [unverified] no licence in codebase or README | basic OAuth2 + OIDC auth-code only; README TODO: "implement PKCE" | http 3.5.0, json 1.2.3, jwt, uri_parser 2.1.2, base 3.21.0 | keep ours |
| @kubukoz/jsonrpc (extra) | 0.0.9 | 2026-03-28 | [unverified] none on Share; README credits neandertech/jsonrpclib | JSON-RPC 2.0 Channel ability, stdio/socket binding (`bindChannel`), LSP framing; 14 open tickets | base 7.15.0, json 1.3.5, baccata schemas, ceedubs shell | borrow ideas (strongest JSON-RPC base, but pulls in schemas stack) |

Share project pages and the API expose no licence field for any project [read: API JSON has no licence key]. The only licences
found are the two MIT lines above. Anything marked [unverified] must not be depended on or copied until a licence text is read.
Search "stdio" returned nothing; "mcp" returned exactly the 4 MCP projects; "oauth" exactly the 2 OAuth projects; "json-rpc" only @kubukoz/jsonrpc.

## Coverage matrix (what each actually implements)

Client side: initialize, tools/list, tools/call, streamable HTTP, SSE, stdio, PKCE, device flow, DCR, refresh.

| Library | MCP client msgs | Streamable HTTP | SSE | Stdio | PKCE | Device RFC 8628 | DCR | Refresh | Server (tools) |
|---|---|---|---|---|---|---|---|---|---|
| kubukoz/mcp | typed schema only (2352 defs from MCP 2025-11-25); `McpClientApi` trait | no | no | server demo via `bindChannel stdIn stdOut` | n/a | n/a | n/a | n/a | yes: `McpServerApi`, `McpTool`, demoServer registers Initialize and ListTools endpoints |
| mizchi/mcp | build-only: initializeRequest, toolsListRequest, toolsCallRequest, stateful `client.create/simpleInit` (returns Json to send, no transport) | no | no | no transport | n/a | n/a | n/a | n/a | partial: handleInitialize, handleToolsList, hand-written dispatch |
| nusentry/unison-mcp | yes, via ucm: `ucm.Session.start ucmPath args` = `Process.start ucm [.. "mcp"]`, line-buffered stdio, wrappers per UCM tool, coverage check against tools/list | no | no | yes (client side, to ucm) | n/a | n/a | n/a | n/a | no |
| tcmcp | no | no | no | server stdio loop | n/a | n/a | n/a | n/a | yes, Teamcenter-specific, README says exceptions caught and serialized to JSON-RPC errors |
| kylegoetz/oauth2-client | n/a | n/a | n/a | n/a | yes (`pkce` ns: CodeVerifier, CodeChallenge, mkPkceParam; `HasPkceAuthorizeRequest`) | yes (`grants.deviceAuthorization`, `flows.deviceAuthorization`, README example with `pollDeviceTokenRequest`) | no (nothing named register/dynamic found; not checked exhaustively) | yes (`RefreshTokenRequest`, `OAuth2Http` auto-refresh wrapper) | n/a |
| alvaroc1/oauth2 | n/a | n/a | n/a | n/a | no (README TODO) | no | no | no refresh found in README (RefreshToken type exists) | n/a |

None of the six covers streamable HTTP, SSE, or dynamic client registration (RFC 7591), nor OAuth protected-resource/authorization-server
metadata discovery (RFC 9728 / 8414), which MCP HTTP auth requires. `@kylegoetz/oauth2-client` has a `metadata` namespace but it
holds only authors/copyrightHolders/license [read].

## Per-library notes

- @kubukoz/mcp. https://share.unison-lang.org/@kubukoz/mcp . Created 2026-03-13. No README, no release, depends on `jsonrpc_main`
  (a branch, not a pinned release) and on the schemas library (heavy, "black magic transforms" in the jsonrpc project). Value: generated
  types for the full 2025-11-25 MCP schema (CallToolRequest/Result, tasks, elicitation, PaginatedResult) to copy field names and the
  registerEndpoint-per-method structure. Server over stdio only. Verdict: borrow ideas; do not depend (unreleased, no licence, schemas stack).
- @mizchi/mcp. https://share.unison-lang.org/@mizchi/mcp . README says MIT [read]. Protocol "2024-11-05" (stale; spec has moved to 2025-11-25).
  Pure JSON builders, no I/O, no transport, no auth; project summary is "dev", untouched since 2025-06-27. Verdict: keep ours.
- @nusentry/unison-mcp. https://share.unison-lang.org/@nusentry/unison-mcp . 1.0.0 (4 download entries). Builds on mizchi/mcp via a lib copy
  of branch main. `UnisonMcp` ability with `callMcpTool : Text -> Json -> Result Json`, `runStdio`, `runStdioDefault`; wraps UCM tools
  (history, reflog, typecheck, run, searchByType, install, rename, move, share search/readme, createBranch). Release notes: multi-line message
  splitting fix, `ucm.share.projectInfo`, `ucm.project.createBranch`. It is a client OF `ucm mcp`, i.e. the opposite end of our proxy, and
  has no server; useful as evidence of how `ucm mcp` is spawned and which tools exist. No licence. Verdict: borrow ideas (and as a
  tool-coverage test pattern: compare tools/list to wrapped tools).
- @goenninger/tcmcp. https://share.unison-lang.org/@goenninger/tcmcp , https://github.com/goenninger-b-t/tc-mcp . Application, not a library
  (needs Siemens Teamcenter env vars). Useful as a worked example of a stdio JSON-RPC loop with abilities and error serialization. Verdict: keep ours.
- @kylegoetz/oauth2-client. https://share.unison-lang.org/@kylegoetz/oauth2-client . MIT [read]. Never released (no version to pin; depend by
  branch only). Uses "typeclasses as abilities" (`HasTokenRequest`, `HasPkceAuthorizeRequest`, `HasDeviceAuthorizationRequest`, ...). Has
  PKCE, device flow, refresh, a loopback redirect server (`simpleServer`), an `OAuth2Http` wrapper that adds tokens and refreshes. Pinned to
  old `unison_http_3_8_1` and json 1.3.4 (current http in tcmcp is 15.2.0), 2 open contributions, README examples are Google-specific, `TODO` term
  exists. Verdict: borrow ideas (MIT allows copying with the notice); not a dependency (no release, old http major, no DCR/discovery).
- @alvaroc1/oauth2. https://share.unison-lang.org/@alvaroc1/oauth2 . 0.0.6. Auth-code + OIDC (Google, Cognito constructors), no PKCE, no device
  flow, depends on very old base 3.21 / http 3.5. Licence unverified. Verdict: keep ours.
- @kubukoz/jsonrpc (found by search). https://share.unison-lang.org/@kubukoz/jsonrpc . 0.0.9, README read. Powers the LSP library
  @kubukoz/lsp. `Channel` ability, `runFull`, `bindChannel` (plain JSON-RPC), `bindLSPChannel`, can mix client stubs and server endpoints in one
  channel (server-to-client requests, needed for MCP sampling/elicitation). Pulls in baccata schemas, ceedubs shell. 14 open tickets. No licence.
  Verdict: borrow ideas; evaluate again only if a licence is published and we are willing to take the schemas dependency.

## Extracted facts that matter to us

- `ucm mcp` is spawned as `ucm <extraArgs> mcp` with line-buffered stdio (`Process.start`, `setBuffering stdinH LineBuffering`) [read, nusentry `ucm.Session.start`].
- Streamable HTTP, SSE, DCR, RFC 9728/8414 discovery: no Unison library exists; we must write them either way.
- Device flow and PKCE shapes worth copying (MIT, keep the notice): kylegoetz `grants.deviceAuthorization`, `pkce.mkPkceParam`, `OAuth2Http` refresh wrapper.
- All candidates are pinned to old `unison_http` majors (3.x, 15.2.0) and unreleased branches; none is a clean dependency.

## Recommendation

1. Keep our own MCP client/server and JSON-RPC code: no library covers streamable HTTP, SSE or DCR, and the stdio parts are small.
2. Do not depend on any Share project: all MCP and OAuth candidates are unreleased or stale, and 5 of 7 have no licence text at all.
3. Borrow shapes (not code) from @kubukoz/mcp (2025-11-25 schema, endpoint-per-method) and @nusentry/unison-mcp (how `ucm mcp` is spawned, tool-coverage check).
4. Borrow, with the MIT notice, PKCE and device-flow structure from @kylegoetz/oauth2-client; implement DCR and metadata discovery ourselves.
5. Re-check licences before reuse; if @kubukoz/jsonrpc gets a release and licence, reconsider it as the JSON-RPC layer.
