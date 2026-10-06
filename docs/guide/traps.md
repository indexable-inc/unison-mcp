# traps: what causes most failures

1. Look names up first (`action:'search'`). Guessed names are the top error; `class: wrong-name` means look again, not guess again.
2. No infix for named functions: `Nat.mod a b`, never `a Nat.mod b`. Only symbolic operators are infix.
3. Function first: `List.foreach printLine xs`, `List.map f xs`.
4. Compile errors are data and exit codes lie. ucm exits 0 on compile errors and uncaught exceptions; read `ok:` and `class:` in the reply.
5. Unique name per run: `run` with `name` can execute an older committed definition. Cleanup of a scratch cell is skipped after a timeout.
6. IO needs `action:'run'`, not `check`; `check` only evaluates pure `> expr` lines. A program has type `'{IO, Exception} a`.
7. `==` is per type; lists and Optionals need `===`. `-` on Nat yields Int.
8. After a timeout the ucm child is killed and restarts on the next call; do not issue another call on a busy child. Never group-kill: the child shares your process group; kill by pid.
9. Libraries: install `@unison/base` as well as http and json, or names become ambiguous (`URI.parse`, `Text.lines`).
10. `transcript` plumbing (when scripting ucm yourself): `ucm -c DIR transcript.in-place file.md` writes `file.output.md`, not stdout; `-C DIR` creates a codebase and ignores an existing one; every ucm command needs its own fenced block; a stanza with no results aborts the transcript. Only one ucm may hold a codebase.
11. Large results: anything over about 12,000 characters is truncated (head, tail, file path of the full text).
