# Unison multiplayer research (fetched 2026-10-06 UTC)
Question: can a local ucm codebase sync with a Cloudflare Durable Object SQLite store; Share vs git vs custom.
Licences: unison repo and share-api are MIT (unison-LICENSE.txt read; share-api README states MIT, reported). Cloudflare/unison.cloud pages are vendor docs, saved as research excerpts only (do not redistribute).
Files (URL, all fetched 2026-10-06):
- unison-schema-create.sql: github.com/unisonweb/unison trunk codebase2/codebase-sqlite/sql/create.sql (tables hash, object, hash_object, causal, causal_parent, namespace_root, watch, indexes)
- unison-LICENSE.txt: trunk/LICENSE (MIT)
- unison-development.markdown: trunk/development.markdown (stack build, GHC via stack.yaml/nix/versions.nix)
- share-api-README.md: unisoncomputing/share-api README (MIT, OAuth2 PKCE, Postgres+Redis, no sync protocol docs)
- cf-do-pricing.html, cf-do-limits.html, cf-do-websockets.html: developers.cloudflare.com durable-objects
- unison-cloud-pricing.html: www.unison.cloud/pricing/
- unison-discussion-5516.html: github.com/unisonweb/unison/discussions/5516 (WASM backend; maintainers cite abilities/continuations and WASM GC; a July 2026 comment reports "Warp" compiling Unison to WASM, unverified)
