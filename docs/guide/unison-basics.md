# unison-basics: writing Unison for this tool (ucm 1.5.0, @unison/base 7.19.2, @unison/http 16.1.0, @unison/json 1.4.2)

## Loop
1. Look up every library name first: `action:'search', name:'Text.lines'` or `action:'type-search', name:'[a] -> Nat'`. Guessing names was the top error class.
2. Typecheck with `action:'check'` (code with optional `> expr` lines and `test> name = check (..)` lines; nothing is saved). Run IO with `action:'run'` (code is the BODY of a do block).
3. Read the reply header: `stage:`, `ok:`, `class:`. Compile errors are data (isError false, `ok: false`); ucm exits 0 even when the code does not compile, so the exit status never tells you anything.
4. Retry only after reading the error class: wrong-name, ambiguous-name, type-mismatch, unhandled-ability, parse-error.
5. `action:'update'` writes the code into the codebase (nothing is written on error). `action:'view'` shows source, `action:'tests'` runs tests.

## run mode
- `code` only: the code is the body of `do` of type `'{IO, Exception} a`. The result is printed and the cell discarded.
- `code` that has definitions followed by one final bare expression or `> expr` line: the definitions are loaded as given and the last expression runs.
- `name` only: runs that committed definition (`'{IO, Exception} a`); `args` are its Text arguments. `code` plus `name`: code is updated first, then `name` runs.
- Give each program a unique name: run can pick an older committed definition with the same name.

## Rules
- No infix for named functions: write `Nat.mod a b`, never `a Nat.mod b`. Only symbolic operators (`+ == ++ |>`) are infix.
- Higher-order functions take the function first: `List.foreach printLine xs`.
- `==` is per type (Nat, Text, Int); lists and Optionals need `===` (Universal) or `List.equals`. `-` on Nat gives Int; use `Nat.decrement` or `Nat.drop`-style helpers after looking them up.
- Programs: `main : '{IO, Exception} ()` then `main = do ...`.
- Tests: `test> ns.tests.name = check (expr == value)`; results print on load.
- Abilities: `Threads.run do ...` handles Threads (needed by Http.run). `handle expr with handlerFn` applies a handler; do not pass a thunk as an argument to it. Handler template: `go acc = cases { a } -> ..; { Ability.op x -> resume } -> handle resume () with go (..)` then `handle !thunk with go []`.
- `namespace X` works, `namespace X where` does not. `handle` and `type` are reserved words (no `Foo.handle`, `Cdp.type`).
- Records: `unique type X = { a : Text }` has constructor `X.X`. `List.exists` does not exist: use `List.find` and match. Destructuring `(a, b) = f x` works.
- A multi-line lambda in parentheses can give "expecting binding" with no position: use a named local function.
- `concurrent.fork_` must be written in full (`fork_` is ambiguous). `sleepMicroseconds` needs Exception. Write `a / b`, not `Nat./ a b`.
- Bare capitalised builtin types (Process) are not found by name search; never conclude they are missing.

## Names that exist
- Text: `Text.size`, `Text.lines`, `Text.contains`, `Text.toLowercase`, `Text.reverse`, `Text.filter`, `Text.split ?, line` (Char first), `Text.join sep list`, `isLetter`, `Nat.toText`, `Int.toText`.
- Files: `readFileUtf8 (FilePath "/abs/path") : Text`, `writeFileUtf8 (FilePath p) text`, `FilePath.exists`. `readFile` returns Bytes.
- Exceptions: `Exception.catch : '{g, Exception} a ->{g} Either Failure a`; rethrow `Exception.raise f`; `Exception.raiseGeneric "msg" value`. Refs: `IO.ref 0`, `IO.ref.modify r f`, `Ref.read r`. `IO.getEnv "HOME"` is `Text ->{IO, Exception} Text`.

## Libraries
Install once per codebase with `action:'install', name:'@unison/base'` (and `@unison/http`, `@unison/json`; `args:['releases/7.19.2']` style branches pin a version). Install @unison/base too, or `URI.parse` and `Text.lines` become ambiguous because http and json each nest a different base. `find` does not see `lib`; use `search` or the `tool` action with `debug.find.global`-style tools. A transcript aborts at the first stanza with no results.

## Hygiene
Docs: a `{{ doc }}` comment on X generates `X.doc`. `view` drops unique-type GUIDs; pin `unique[uGUID]` (it must start with a letter) when a hash must be stable.
