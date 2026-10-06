# process-ffi: processes, files and FFI

## Processes
- `(i, o, e, p) = Process.start "git" ["status", "-s"]` gives (stdin, stdout, stderr, process). Then `getText o`; `Process.wait p : Nat` is the exit code; `Process.kill p`. There is no `Process.run`. `Process.start` needs IO in the cell's abilities.
- Handles: `Handle.getText`, `getLine h`, `putText h t`. Stdin pipes are buffered: `setBuffering hin NoBuffering` before writing or a read from the child hangs forever. Wrap child work in a timeout.
- `Process.kill` sends SIGTERM, which a busy ucm child ignores until its computation ends: start children as `sh -c 'echo $$ >&2; exec cmd "$@"'`, read the pid from stderr and stop with `/bin/kill -9 PID`.
- Never kill a process group from a cell: MCP children share the parent's group. Kill by pid.

## Stdio MCP client in 14 lines
```
rpc : Handle -> Handle -> Nat -> Text -> Text ->{IO, Exception} Text
rpc hin hout n method params =
  putText hin ("{\"jsonrpc\":\"2.0\",\"id\":" ++ Nat.toText n ++ ",\"method\":\"" ++ method ++ "\",\"params\":" ++ params ++ "}\n")
  getLine hout
```
then `initialize`, a `notifications/initialized` line, `tools/list`.

## Files
`readFileUtf8 (FilePath "/abs/path")`, `writeFileUtf8`, `FilePath.exists`. Make directories with `Process.start "mkdir" ["-p", dir]`.

## FFI
`DLL.openByName "c"`, `DLL.getSymbol dll "getpid" (Spec.fn0 FFI.Type.int32)`; `FFI.Type.int32` is already Int.

## Clock
`Clock.monotonic() |> Duration.countMillisecondsInt |> Int.truncate0`. A forked `getLine` thread polled with `Promise.tryRead` and `sleepMicroseconds` ticks works under `ucm run.compiled`.
