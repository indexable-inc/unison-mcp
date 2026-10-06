# cdp: drive Chrome over the DevTools Protocol

Start Chrome with `--remote-debugging-port=9222` (a throwaway `--user-data-dir` for tests). The default endpoint is `Cdp.endpoint` = `http://127.0.0.1:9222`. All run with `action:'run'`.

```
Cdp.connect Cdp.endpoint "github.com" do !Cdp.readPage
```
`Cdp.connect base urlSubstring thunk` finds a tab whose URL contains the substring, or opens one (`http`, `data:` and `about:` URLs).

| function | |
|---|---|
| `Cdp.targets base`, `Cdp.pageFor base substr` | list targets; find or open a page |
| `Cdp.navigate url` | Page.navigate, waits for readyState complete |
| `Cdp.eval js`, `Cdp.evalText`, `Cdp.evalBool` | Runtime.evaluate (returnByValue, awaitPromise) |
| `!Cdp.readPage` | document.body.innerText |
| `Cdp.waitFor (Cdp.Wait.Selector "#id") 5000` | also `Cdp.Wait.Load`, `Cdp.Wait.Contains t`; false on timeout |
| `Cdp.click sel`, `Cdp.typeText sel text` | click; focus and Input.insertText |
| `Cdp.screenshot path` | PNG to a file, returns byte count |
| `Cdp.call "Page.reload" "{}"` | any command; raises on a protocol error |

Traps
- CDP is not JSON-RPC 2.0: a `"jsonrpc"` member makes Chrome drop the message silently and the call hangs. Send only id, method, params.
- Replies are interleaved with events: loop until the text contains the call's `"id":N`.
- Raw WebSocket client: `handle webSocket (HttpRequest.get (URI.parse "http://127.0.0.1:9222/devtools/page/ID")) with HttpWebSocket.ioHandler` (the scheme must be http; `ws:` throws), then `WebSockets.runLocal do WebSockets.send ws (Message.text t)` and `WebSockets.receive ws` (Message = TextMessage Text | BinaryMessage Bytes).
- HTTP endpoints: `/json/new?URL` needs PUT; close a tab with GET `/json/close/ID`.
