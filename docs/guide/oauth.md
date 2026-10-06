# oauth: signing in to MCP servers with a browser pop-up

`Mcp.login "name"` for a server whose `servers.json` entry has `"auth":"oauth"`:
1. Discovery: `/.well-known/oauth-protected-resource` of the MCP URL, then the authorization-server metadata.
2. Dynamic client registration (public client, auth method none) when the server supports it.
3. Authorization code with PKCE (S256). The redirect is a loopback listener at `http://127.0.0.1:8976/callback`; the client opens your default browser with macOS `open <url>` and receives the code.
4. If no authorization endpoint is advertised, the RFC 8628 device flow is used instead (the call returns after polling; the device code lives a few minutes).
5. Tokens are stored per server in `~/.local/share/uni/mcp/<name>.json` with mode 0600 and are never printed. A 401 triggers a refresh.

Practical notes
- Calls block until the cell ends, so a sign-in must finish inside `timeout_ms` (default 120 s; raise it for a slow human).
- Some servers accept dynamic registration and device flow endpoints but refuse activation for a registered client ("Activation denied"); prefer PKCE with the loopback redirect, which worked there.
- Port 8976 must be free. There is no close for the listening socket: it lives until the ucm process ends (a timeout restarts the child).
- PKCE building blocks if you write your own: `crypto.hashBytes Sha2_256 bytes`, `Bytes.toBase64UrlUnpadded`, `IO.randomBytes n`, `Socket.listen (Socket.server (Some (HostName "127.0.0.1")) (Port "8976"))`, `Socket.accept`, `Socket.receive`, `Socket.send conn bytes`, `Socket.close conn`.
- Secret file with mode 0600: `Process.start "install" ["-m","600","/dev/null",path]`, then `writeFileUtf8 (FilePath path)` keeps the mode.
