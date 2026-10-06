# http-json: HTTP and JSON from a cell

Run these with `action:'run'`.

## HTTP
- `URI.parse "https://..."` (capital URI, throws Exception). `Http.get uri`. Run with `Threads.run do Http.run do ...`.
- `HttpResponse.bodyText resp : Text`; `Status.code (HttpResponse.status resp) : Nat`; `Body.toBytes (HttpResponse.body r) : Bytes`; `Bytes.size`.
- GET: `Threads.run do Http.run do HttpResponse.bodyText (Http.get (URI.parse "https://example.com"))`.
- POST: `HttpRequest.post uri (Body.fromText t)`, `HttpRequest.setHeader k [v] req`, PUT: `Http.request (HttpRequest.put uri (Body Bytes.empty))`. Read headers with `Headers.getValues "name" (HttpResponse.headers resp)` (case-insensitive).
- The client does not throw on 4xx or 5xx: check `Status.code`.
- `Threads.run` allows only {IO, Exception}: a handler run inside it cannot be ability-polymorphic.

## JSON (@unison/json)
- `Json.fromText : Text ->{Exception} Json`; `Json.toText`.
- Constructors: `Json.Text t`, `Json.Object [(Text, Json)]`, `Json.Array [Json]`, `Json.Boolean b`, `Json.Number`, `Json.Null`. A bare `String` constructor does not exist and `Text` alone clashes: qualify with `Json.`.
- Field lookup: `List.find (cases (k, _) -> k == "name") kvs`.
- Optional equality needs `===`.

## Servers
A WebSocket echo server: `HandlerWebSocket cases req | Routes.get (Path ["echo"]) req -> WebSocketHandler (ws -> forever do WebSockets.send ws (WebSockets.receive ws)); _ -> abort`, then `Threads.run do Config.serve (Routes.default <<< handler) (server.Config.default |> server.Config.port.set (Port "9101"))`. Run servers with a timeout; a blocking call holds the tool until the timeout.
