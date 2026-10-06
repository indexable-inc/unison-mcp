# mcp-client: call any MCP server from a cell

The tool ships an MCP client written in Unison (`Mcp.*`). Servers are configured in `~/.local/share/uni/mcp/servers.json`:

```json
{"mail": {"url": "https://example.com/mcp", "auth": "oauth"},
 "fs": {"command": "npx", "args": ["-y", "some-mcp-server"], "auth": "none"},
 "x": {"url": "https://example.com/mcp", "auth": "bearer-env:X_TOKEN"}}
```

Transports: `url` (streamable HTTP, JSON or SSE replies) or `command`+`args` (stdio). Auth: `none`, `bearer-env:VAR`, `oauth` (see topic oauth).

## Calls (action:'run')
- Sign in (oauth only, once): `Mcp.login "mail"`.
- Tool names, cheap: `Mcp.run do Mcp.toolNames "mail"`.
- Full tool list (large, can be tens of thousands of characters): `Mcp.run do Mcp.tools "mail"`.
- Call: `Mcp.run do Mcp.call "mail" "tool_name" "{\"limit\":3}"` (arguments are a JSON object as Text; the result is the text content).
- Test double: `Mcp.fake (server tool args -> "...") do Mcp.call "mail" "t" "{}"`.

## Typed wrappers
`examples/superhuman.u` shows how to wrap tools of one server (`Superhuman.listThreads 3`). It is an example module, not part of the core: load it with `action:'update'` if you want it.

## Output size
Any tool result longer than about 12,000 characters is cut: you get the head, the tail and the path of a file holding the full text (under `~/.local/share/uni/spill/`). Read it with `readFileUtf8` or your own file tool, or ask for less (`Mcp.toolNames`, a `limit` argument).

## Notes
`Mcp.run` returns plain values. The ability is named `Mcp`; an older codebase with an `Mcp` namespace must be migrated (`scripts/install.sh --migrate-old`).
