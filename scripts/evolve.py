#!/usr/bin/env python3
"""unison-evolve: keep a Unison codebase versioned in a (private) git repo.

  unison-evolve commit  --codebase CB --repo REPO [--session S] [--lane L] [--action A] < update-output
      Detaches at once, then (under a lock) takes a consistent snapshot of CB, regenerates the text export and
      makes one git commit naming the definitions in the update output. Never fails the caller: errors go to
      REPO/.git/unison-evolve.log.
  unison-evolve sync    --codebase CB --repo REPO    fast-forward from the remote, swap in the pulled snapshot when safe, scan, push
  unison-evolve restore --codebase CB --repo REPO REV   put the snapshot of git revision REV back (no ucm may hold CB)
  unison-evolve scan    --repo REPO [--accept]   secrets scan of the tracked files (sync runs it before every push)
  unison-evolve export  --snapshot FILE.sqlite3 --out DIR   the text export of one snapshot
  unison-evolve verify  --repo REPO [--live --codebase CB] [--roundtrip]   consistency of the committed snapshot and export

Repo layout: codebase/unison.sqlite3 (online backup, the source of truth), export/defs/<name>.u (first line `-- #hash`),
export/INDEX.txt (`term|type|ctor NAME #hash`), export/head.txt (namespace hash of the branch), export/libs.txt.

Environment: UNISON_MCP_EVOLVE_UCM (the `unison` binary used on snapshot copies; default UNISON_MCP_UCM, else the
pinned release), UNISON_MCP_EVOLVE_PUSH=1 (push after each commit, after the secrets scan),
UNISON_MCP_EVOLVE_SIGN=0 (never sign; default: whatever git config says, falling back to unsigned when signing fails).
"""
import argparse, errno, os, re, shutil, sqlite3, subprocess, sys, tempfile, time

if sys.path and os.path.abspath(sys.path[0] or ".") == os.path.dirname(os.path.abspath(__file__)):
    sys.path.pop(0)  # never import from the install directory

HOME = os.path.expanduser("~")
SNAP = "codebase/unison.sqlite3"
TRANSCRIPT_TIMEOUT = 180


# ---------- small helpers ----------

class Log:
    path = None

    @classmethod
    def w(cls, msg):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} pid={os.getpid()} {msg}\n"
        try:
            if cls.path:
                with open(cls.path, "a") as f:
                    f.write(line)
            else:
                sys.stderr.write(line)
        except OSError:
            pass


def git(repo, *args, check=True, env=None, timeout=120, input=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check, env=e, timeout=timeout, input=input)


def ucm_bin():
    for k in ("UNISON_MCP_EVOLVE_UCM", "UNISON_MCP_UCM"):
        if os.environ.get(k):
            return os.environ[k]
    return f"{HOME}/.local/share/uni/ucm/release-1.5.0/unison/unison"


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM


def ucm_holders(codebase):
    """pids of unison processes whose command line names this codebase (a `ucm mcp -C CB` child or a CLI `-c CB`)."""
    out = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True).stdout
    cb = os.path.realpath(codebase)
    pids = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2 or int(parts[0]) == os.getpid():
            continue
        args = parts[1]
        if "unison" in args and ("run.compiled" not in args) and (f" {codebase}" in args or f" {cb}" in args) and re.search(r"\s-[cC]\s", args):
            pids.append(int(parts[0]))
    return pids


class Lock:
    """mkdir lock built under a temp name and renamed into place (rename onto a non-empty directory fails, so it is atomic
    and the lock never exists without its owner file)."""

    def __init__(self, repo, wait=300):
        self.path = os.path.join(repo, ".git", "unison-evolve.lock")
        self.wait = wait

    def __enter__(self):
        deadline = time.time() + self.wait
        while True:
            tmp = f"{self.path}.{os.getpid()}.{os.urandom(3).hex()}"
            os.mkdir(tmp)
            with open(os.path.join(tmp, "owner"), "w") as f:
                f.write(f"{os.getpid()}\n{int(time.time())}\n")
            try:
                os.rename(tmp, self.path)
                return self
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
            try:
                pid, started = open(os.path.join(self.path, "owner")).read().split()[:2]
                stale = not alive(int(pid)) or time.time() - int(started) > 900
            except (OSError, ValueError):
                stale = False
            if stale:
                dead = f"{self.path}.dead.{os.urandom(3).hex()}"
                try:
                    os.rename(self.path, dead)
                    shutil.rmtree(dead, ignore_errors=True)
                    Log.w("broke a stale lock")
                except OSError:
                    pass
                continue
            if time.time() > deadline:
                raise TimeoutError("lock wait exceeded")
            time.sleep(0.2)

    def __exit__(self, *a):
        shutil.rmtree(self.path, ignore_errors=True)


# ---------- snapshot ----------

def codebase_file(codebase):
    return os.path.join(codebase, ".unison", "v2", "unison.sqlite3")


def snapshot(codebase, dest):
    """Consistent online backup of the codebase sqlite (works while a ucm writes; the backup API restarts on change)."""
    tmp = dest + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    last = None
    for attempt in range(8):
        try:
            src = sqlite3.connect(f"file:{codebase_file(codebase)}?mode=ro", uri=True, timeout=30)
            dst = sqlite3.connect(tmp)
            with dst:
                src.backup(dst)
            dst.execute("pragma journal_mode = delete")  # a plain file: no -wal/-shm beside the snapshot
            dst.close()
            src.close()
            os.replace(tmp, dest)
            return
        except sqlite3.Error as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"snapshot failed: {last}")


def head_hash(sqlite_file, project="main", branch="main"):
    c = sqlite3.connect(f"file:{sqlite_file}?mode=ro", uri=True)
    try:
        row = c.execute(
            "select h.base32 from project p join project_branch pb on pb.project_id = p.id "
            "join causal c on c.self_hash_id = pb.causal_hash_id join hash h on h.id = c.value_hash_id "
            "where p.name = ? and pb.name = ?", (project, branch)).fetchone()
        return row[0] if row else ""
    finally:
        c.close()


# ---------- text export ----------

def run_transcript(codebase_copy, stanzas, work):
    t = os.path.join(work, "t.md")
    with open(t, "w") as f:
        for s in stanzas:
            f.write("```ucm\n" + s + "\n```\n")
    p = subprocess.Popen([ucm_bin(), "-c", codebase_copy, "transcript.in-place", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        p.wait(TRANSCRIPT_TIMEOUT)
    except subprocess.TimeoutExpired:
        p.kill()  # this pid only
        p.wait()
        raise RuntimeError("ucm transcript timed out")
    out = os.path.join(work, "t.output.md")
    if not os.path.exists(out):
        raise RuntimeError("ucm produced no transcript output")
    return open(out, encoding="utf8").read()


def stanza_outputs(text):
    """{command: output text} from a transcript output file (every stanza is one command)."""
    res = {}
    for m in re.finditer(r"``` ucm\n(.*?)\n```", text, re.S):
        body = m.group(1)
        cmd, _, rest = body.partition("\n")
        res.setdefault(cmd.split("> ", 1)[-1].strip(), []).append(rest)
    return res


def parse_find(text, tops):
    out = {}
    lines = text.splitlines()
    for i, l in enumerate(lines):
        m = re.match(r"\s+\d+\.\s+-- (#\S+)", l)
        if not m or i + 1 >= len(lines):
            continue
        h = m.group(1)
        decl = lines[i + 1].strip()
        tm = re.match(r"(?:unique |structural )?(type|ability) (\S+)", decl)
        if h.count("#") > 1:  # a constructor (#hash#N): kept in the index, its source is the type's
            kind, name = "ctor", decl.split(" : ")[0].strip()
        elif tm:
            kind, name = "type", tm.group(2)
        else:
            kind, name = "term", decl.split(" : ")[0].strip()
        for name in [n.strip() for n in name.split(", ")]:  # aliases are listed together
            if name.split(".")[0] in tops and name.split(".")[0] not in ("lib", "scratch"):
                out[(kind, name)] = h
    return out


def split_chunks(text):
    """definitions from `unison :added-by-ucm scratch.u` blocks: {(kind, name): source}."""
    res = {}
    for m in re.finditer(r"``` unison :added-by-ucm scratch\.u\n(.*?)\n```", text, re.S):
        for chunk in re.split(r"\n\n(?=\S)", m.group(1).strip("\n")):
            first = chunk.split("\n", 1)[0]
            tm = re.match(r"(?:unique |structural )?(type|ability) (\S+)", first)
            if tm:
                key = ("type", tm.group(2))
            elif first.startswith("test> "):
                key = ("term", first.split()[1])
            else:
                key = ("term", re.split(r"[ :]", first, maxsplit=1)[0])
            res[key] = chunk.rstrip("\n") + "\n"
    return res


def fname(kind, name):
    s = re.sub(r"[^A-Za-z0-9_.-]", lambda m: "%%%02X" % ord(m.group(0)), name)
    return s + (".type.u" if kind == "type" else ".u")


def export(snapshot_file, out_dir, project="main", branch="main"):
    """Write the text export of a snapshot into out_dir (replaced as a whole)."""
    work = tempfile.mkdtemp(prefix="unison-evolve-")
    try:
        cbdir = os.path.join(work, "cb")
        os.makedirs(os.path.join(cbdir, ".unison", "v2"))
        shutil.copy(snapshot_file, codebase_file(cbdir))
        sw = f"{project}/{branch}"
        t1 = run_transcript(cbdir, [f"scratch/main> switch {sw}", f"{sw}> ls", f"{sw}> ls lib"], work)
        ls = stanza_outputs(t1)
        entries = []
        for l in ls.get("ls", [""])[0].splitlines():
            m = re.match(r"\s+\d+\.\s+(\S+)", l)
            if m:
                entries.append(m.group(1))
        libs = [m.group(1) for l in ls.get("ls lib", [""])[0].splitlines() for m in [re.match(r"\s+\d+\.\s+(\S+)", l)] if m]
        namespaces = sorted({e.rstrip(".") for e in entries if e.endswith(".") and e.rstrip(".") not in ("lib", "scratch")})
        loose = sorted({e for e in entries if not e.endswith(".") and e not in ("lib", "scratch")})
        tops = set(namespaces) | set(loose)
        stanzas = [f"scratch/main> switch {sw}"]
        stanzas += [f"{sw}> find.verbose {n}" for n in sorted(tops)]
        stanzas += [f"{sw}> edit.namespace {n}" for n in namespaces]
        if loose:
            stanzas += [f"{sw}> edit {n}" for n in loose]
        t2 = run_transcript(cbdir, stanzas, work)
        index = {}
        for n in sorted(tops):
            for chunk in stanza_outputs(t2).get(f"find.verbose {n}", []):
                index.update(parse_find(chunk, tops))
        chunks = split_chunks(t2)
        new = out_dir + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.makedirs(os.path.join(new, "defs"))
        missing = []
        for (kind, name), h in sorted(index.items()):
            if kind == "ctor":
                continue
            src = chunks.get((kind, name))
            if src is None:
                twin = next((n for (k, n), hh in index.items() if hh == h and k == kind and (kind, n) in chunks), None)
                parent = next((p for p in (name.rsplit(".", 1)[0], name.rsplit(".", 2)[0]) if ("type", p) in chunks), None)
                if twin:
                    src = f"-- alias of {twin} (same hash)\n"
                elif parent:
                    src = f"-- generated by the record type {parent}\n"
                else:
                    missing.append(name)
                    src = "-- (source not produced by ucm edit)\n"
            with open(os.path.join(new, "defs", fname(kind, name)), "w", encoding="utf8") as f:
                f.write(f"-- {h}\n{src}")
        with open(os.path.join(new, "INDEX.txt"), "w") as f:
            f.write("".join(f"{k} {n} {h}\n" for (k, n), h in sorted(index.items())))
        with open(os.path.join(new, "head.txt"), "w") as f:
            f.write(head_hash(snapshot_file, project, branch) + "\n")
        with open(os.path.join(new, "libs.txt"), "w") as f:
            f.write("".join(l + "\n" for l in sorted(libs)))
        if len(index) < 1:
            raise RuntimeError("export found no definitions")
        if missing:
            Log.w(f"export: no source for {len(missing)} definitions: {missing[:5]}")
        shutil.rmtree(out_dir, ignore_errors=True)
        os.rename(new, out_dir)
        return len(index)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------- commit ----------

def names_from(output):
    names = []
    for l in output.splitlines():
        m = re.match(r"\s*[+~-]\s+(?:unique |structural )?(?:type |ability )?([^\s:]+)", l)
        if m and m.group(1) not in names and not l.strip().startswith("~ (") and not l.strip().startswith("- ("):
            names.append(m.group(1))
        m = re.match(r"\s+\d+\.\s+(\S+)\s*$", l)  # "I deleted these terms: 1. Foo.two"
        if m and m.group(1) not in names:
            names.append(m.group(1))
        m = re.search(r"[Ii]nstalled (?:the )?\S* ?(lib\.\S+|\S+)", l)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def message(action, names, session, lane, output, head, note=""):
    if names:
        shown = ", ".join(names[:6]) + (f" (+{len(names) - 6} more)" if len(names) > 6 else "")
        subject = f"{action}: {shown}"
    else:
        subject = f"{action}: codebase changed"
    body = [f"session: {session}", f"lane: {lane or '-'}", f"action: {action}", f"head: {head[:12]}"]
    if note:
        body.append(note)
    out = output.strip()
    if out:
        body += ["", out[:3000]]
    return subject[:200] + "\n\n" + "\n".join(body) + "\n"


def git_commit(repo, msg):
    gp = ["-c", "commit.gpgsign=false"] if os.environ.get("UNISON_MCP_EVOLVE_SIGN") == "0" else []
    r = git(repo, *gp, "commit", "--allow-empty", "-q", "-F", "-", input=msg, check=False)
    if r.returncode != 0 and not gp:
        Log.w("signed commit failed, retrying unsigned: " + r.stderr.strip()[:300])
        r = git(repo, "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-q", "-F", "-", input=msg + "signed: no (signing failed)\n", check=False)
    if r.returncode != 0:
        raise RuntimeError("git commit failed: " + r.stderr.strip()[:400])


def commit_locked(codebase, repo, action, names, session, lane, output, project, branch, note=""):
    os.makedirs(os.path.join(repo, "codebase"), exist_ok=True)
    snapshot(codebase, os.path.join(repo, SNAP))
    head = head_hash(os.path.join(repo, SNAP), project, branch)
    try:
        n = export(os.path.join(repo, SNAP), os.path.join(repo, "export"), project, branch)
        Log.w(f"export: {n} definitions")
    except Exception as e:  # keep the snapshot commit even when the text export fails
        Log.w(f"export failed: {e}")
        note = (note + "\n" if note else "") + "export: failed (see .git/unison-evolve.log)"
    git(repo, "add", "-A", "codebase", "export")
    git_commit(repo, message(action, names, session, lane, output, head, note))
    Log.w(f"committed: {action} {names[:6]}")
    repack_if_loose(repo)
    if os.environ.get("UNISON_MCP_EVOLVE_PUSH") == "1":
        try:
            push_checked(repo)
        except Exception as e:
            Log.w(f"push skipped: {e}")


def repack_if_loose(repo, limit_mib=40):
    """Loose objects are whole zlib copies of the sqlite (about half its size each); a repack turns the sequence of snapshots
    into deltas (a few KB per update, because the online backup keeps the page layout; VACUUM INTO would not)."""
    try:
        kv = dict(l.split(": ", 1) for l in git(repo, "count-objects", "-v").stdout.splitlines())
        if int(kv.get("size", "0")) > limit_mib * 1024:  # KiB
            git(repo, "repack", "-a", "-d", "-q", timeout=300)
            Log.w("repacked")
    except Exception as e:
        Log.w(f"repack skipped: {e}")


def daemonize():
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    fd = os.open(os.devnull, os.O_RDWR)
    for n in (0, 1, 2):
        os.dup2(fd, n)


def cmd_commit(a):
    output = sys.stdin.read() if not sys.stdin.isatty() else ""
    daemonize()
    try:
        with Lock(a.repo):
            commit_locked(a.codebase, a.repo, a.action, names_from(output), a.session, a.lane, output, a.project, a.branch)
    except Exception as e:
        Log.w(f"commit failed: {type(e).__name__}: {e}")
    os._exit(0)


# ---------- secrets scan and push ----------

SECRET_PATTERNS = [
    (rb'"(?:access_token|refresh_token|id_token)"\s*:\s*"[A-Za-z0-9._~+/=-]{16,}"', "token value"),
    (rb'"client_secret"\s*:\s*"[^"]{8,}"', "client secret"),
    (rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JWT"),
    (rb"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}", "GitHub token"),
    (rb"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{30,}", "API key"),
    (rb"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])", "AWS access key id"),
    (rb"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\r\n]{40,}", "private key"),
    (rb"Bearer [A-Za-z0-9._~+/-]{24,}", "bearer token"),
]


def secrets_scan(repo):
    """Findings in everything tracked at HEAD: (file, what, sha256-of-match). /Users/ paths in definitions are allowed; state
    files are never. A match whose sha256 is listed in REPO/.secrets-allow (written by `scan --accept`, e.g. the test key that a
    library carries inside the sqlite) is not a finding."""
    import hashlib
    allow = set()
    try:
        allow = {l.split()[0] for l in open(os.path.join(repo, ".secrets-allow")) if l.strip() and not l.startswith("#")}
    except OSError:
        pass
    hits = []
    files = git(repo, "ls-files", "-z").stdout.split("\0")
    for f in files:
        if not f:
            continue
        if re.search(r"(^|/)mcp/[^/]+\.json$", f) or re.search(r"(^|/)(servers|superhuman)\.json$", f):
            hits.append((f, "state file tracked (only *.template or *.example are allowed)", ""))
            continue
        try:
            data = open(os.path.join(repo, f), "rb").read()
        except OSError:
            continue
        for pat, what in SECRET_PATTERNS:
            for m in re.finditer(pat, data):
                h = hashlib.sha256(m.group(0)).hexdigest()
                if h not in allow:
                    hits.append((f, what, h))
    return hits


def cmd_scan(a):
    hits = secrets_scan(a.repo)
    if a.accept:
        with open(os.path.join(a.repo, ".secrets-allow"), "a") as f:
            for file, what, h in hits:
                if h:
                    f.write(f"{h} {what} in {file}\n")
        print(f"accepted {sum(1 for x in hits if x[2])} findings into .secrets-allow (review it, then commit it)")
        return 0
    for file, what, h in hits:
        print(f"{file}: {what} {h}")
    print(f"scan: {len(hits)} findings")
    return 1 if hits else 0


def push_checked(repo):
    hits = secrets_scan(repo)
    if hits:
        raise RuntimeError("secrets scan found: " + "; ".join(f"{f}: {w}" for f, w, _ in hits[:5]) + " (see `unison-evolve scan`)")
    vis = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True)
    if vis.returncode != 0:
        raise RuntimeError("no remote 'origin'")
    r = git(repo, "push", "-q", "origin", "HEAD", check=False, timeout=180)
    if r.returncode != 0:
        raise RuntimeError("git push failed: " + r.stderr.strip()[:300])


# ---------- sync / restore ----------

def install_snapshot(codebase, snapshot_file):
    live = codebase_file(codebase)
    tmp = live + ".evolve.tmp"
    shutil.copyfile(snapshot_file, tmp)
    for ext in ("-wal", "-shm"):
        if os.path.exists(live + ext):
            os.remove(live + ext)
    os.replace(tmp, live)


def cmd_sync(a):
    msgs = []
    with Lock(a.repo):
        has_remote = git(a.repo, "remote", check=False).stdout.strip() != ""
        if not has_remote:
            print("no remote configured; nothing to pull or push")
            return 0
        old_head = ""
        r = git(a.repo, "show", "HEAD:export/head.txt", check=False)
        if r.returncode == 0:
            old_head = r.stdout.strip()
        f = git(a.repo, "fetch", "-q", "origin", check=False, timeout=180)
        if f.returncode != 0:
            print("fetch failed: " + f.stderr.strip()[:300])
            return 1
        target = "@{u}" if git(a.repo, "rev-parse", "--abbrev-ref", "@{u}", check=False).returncode == 0 else None
        if target:
            behind = int(git(a.repo, "rev-list", "--count", "HEAD.." + target).stdout)
            ahead = int(git(a.repo, "rev-list", "--count", target + "..HEAD").stdout)
            if behind and ahead:
                print(f"diverged: {ahead} local and {behind} remote commits; resolve with git, nothing changed")
                return 1
            if behind:
                m = git(a.repo, "merge", "--ff-only", "-q", target, check=False)
                if m.returncode != 0:
                    print("fast-forward failed: " + m.stderr.strip()[:300])
                    return 1
                msgs.append(f"pulled {behind} commits")
                holders = ucm_holders(a.codebase)
                try:
                    live_snap = tempfile.mkdtemp(prefix="unison-evolve-")
                    snapshot(a.codebase, os.path.join(live_snap, "live.sqlite3"))
                    live_head = head_hash(os.path.join(live_snap, "live.sqlite3"), a.project, a.branch)
                finally:
                    shutil.rmtree(live_snap, ignore_errors=True)
                if holders:
                    msgs.append(f"snapshot NOT applied: ucm pids {holders} hold the codebase (retry sync when idle)")
                elif old_head and live_head != old_head:
                    msgs.append(f"snapshot NOT applied: the live codebase has changes the repo does not (live head {live_head[:10]}, repo head {old_head[:10]}); make an update to commit them, then merge by hand")
                else:
                    install_snapshot(a.codebase, os.path.join(a.repo, SNAP))
                    msgs.append("live codebase replaced by the pulled snapshot")
            else:
                msgs.append("already up to date with the remote")
        else:
            msgs.append("no upstream branch; skipped pull")
        try:
            push_checked(a.repo)
            msgs.append("pushed (secrets scan clean)")
        except Exception as e:
            msgs.append(f"not pushed: {e}")
    print("\n".join(msgs))
    return 0


def cmd_restore(a):
    holders = ucm_holders(a.codebase)
    if holders:
        print(f"refused: ucm pids {holders} hold {a.codebase}; wait until they exit (the lazy child leaves about 4 s after idle)")
        return 1
    with Lock(a.repo):
        p = subprocess.run(["git", "-C", a.repo, "show", f"{a.rev}:{SNAP}"], capture_output=True)
        if p.returncode != 0:
            print("unknown revision or no snapshot there: " + p.stderr.decode()[:200])
            return 1
        commit_locked(a.codebase, a.repo, "pre-restore", [], "-", "", "", a.project, a.branch, note=f"state before restoring {a.rev}")
        tmp = tempfile.mktemp(prefix="unison-evolve-")
        open(tmp, "wb").write(p.stdout)
        try:
            install_snapshot(a.codebase, tmp)
        finally:
            os.remove(tmp)
        commit_locked(a.codebase, a.repo, "restore", [], "-", "", "", a.project, a.branch, note=f"restored the snapshot of {a.rev}")
    print(f"restored {a.rev}")
    return 0


# ---------- verify (rebuild from the export, compare hashes) ----------

def cmd_verify(a):
    """The committed repo is self-consistent: the sqlite passes integrity_check, the committed export equals a fresh
    export of that sqlite (INDEX and head), and, when --codebase is given and no ucm holds it, its head equals the repo's.
    With --roundtrip also reload the exported terms into a throwaway copy and report how many keep their hash (informative:
    the text carries no unique-type GUIDs and some terms pretty-print to a different resolution, so it is not expected to be all)."""
    exp = os.path.join(a.repo, "export")
    snap = os.path.join(a.repo, SNAP)
    problems = []
    c = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
    ic = c.execute("pragma integrity_check").fetchone()[0]
    c.close()
    if ic != "ok":
        problems.append(f"integrity_check: {ic}")
    work = tempfile.mkdtemp(prefix="unison-evolve-verify-")
    try:
        n = export(snap, os.path.join(work, "export"), a.project, a.branch)
        for f in ("INDEX.txt", "head.txt"):
            if open(os.path.join(exp, f)).read() != open(os.path.join(work, "export", f)).read():
                problems.append(f"export/{f} differs from a fresh export of the snapshot")
        index = [l.split(" ", 2) for l in open(os.path.join(exp, "INDEX.txt")).read().splitlines() if l]
        if a.codebase and os.path.exists(codebase_file(a.codebase)) and not ucm_holders(a.codebase) and a.live:
            snapshot(a.codebase, os.path.join(work, "live.sqlite3"))
            if head_hash(os.path.join(work, "live.sqlite3"), a.project, a.branch) != head_hash(snap, a.project, a.branch):
                problems.append("the live codebase head differs from the repo snapshot")
        if a.roundtrip:
            r = roundtrip(a, index, exp, work)
            print(f"roundtrip: {r}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if problems:
        print("verify: PROBLEMS: " + "; ".join(problems))
        return 1
    print(f"verify: ok ({n} definitions; sqlite integrity ok; export == fresh export of the snapshot)")
    return 0


def roundtrip(a, index, exp, work):
    cb = os.path.join(work, "cb")
    os.makedirs(os.path.join(cb, ".unison", "v2"))
    shutil.copy(os.path.join(a.repo, SNAP), codebase_file(cb))
    sw = f"{a.project}/{a.branch}"
    tops = sorted({n.split(".")[0] for _, n, _ in index})
    allu = os.path.join(work, "all.u")
    st = [f"scratch/main> switch {sw}"]
    rebuilt = []
    with open(allu, "w", encoding="utf8") as out:
        for kind, name, _ in index:
            if kind != "term":
                continue
            body = open(os.path.join(exp, "defs", fname(kind, name)), encoding="utf8").read().split("\n", 1)[1]
            if body.startswith("-- alias of") or body.startswith("-- generated by"):
                continue
            st.append(f"{sw}> delete.term.force {name}")
            rebuilt.append(name)
            out.write(body + "\n")
    st += [f"{sw}> load {allu}", f"{sw}> update"] + [f"{sw}> find.verbose {n}" for n in tops]
    t = run_transcript(cb, st, work)
    if "\U0001F6D1" in t:
        return "ucm stopped at an error: " + t[t.index("\U0001F6D1"):][:300].replace("\n", " ")
    got = {}
    for cmd, chunks in stanza_outputs(t).items():
        if cmd.startswith("find.verbose"):
            for c in chunks:
                got.update(parse_find(c, set(tops)))
    want = {(k, n): h for k, n, h in index}
    same = sum(1 for n in rebuilt if got.get(("term", n)) == want[("term", n)])
    return f"{same} of {len(rebuilt)} rebuilt terms keep their hash"


def main():
    ap = argparse.ArgumentParser(prog="unison-evolve")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("commit", "sync", "restore", "export", "verify", "scan"):
        p = sub.add_parser(name)
        p.add_argument("--codebase", default=os.environ.get("UNISON_MCP_CODEBASE", f"{HOME}/.local/share/uni/codebase"))
        p.add_argument("--repo", default=os.environ.get("UNISON_MCP_EVOLVE_REPO"))
        p.add_argument("--project", default="main")
        p.add_argument("--branch", default="main")
        p.add_argument("--session", default="-")
        p.add_argument("--lane", default=os.environ.get("UNISON_MCP_LANE", ""))
        p.add_argument("--action", default="update")
        p.add_argument("--snapshot")
        p.add_argument("--live", action="store_true", help="verify: also compare with the live codebase head")
        p.add_argument("--roundtrip", action="store_true")
        p.add_argument("--accept", action="store_true", help="scan: record the current findings in .secrets-allow")
        p.add_argument("--out")
        if name == "restore":
            p.add_argument("rev")
    a = ap.parse_args()
    if a.cmd == "export":
        print(export(a.snapshot, a.out, a.project, a.branch), "definitions")
        return 0
    if not a.repo:
        print("no repo: pass --repo or set UNISON_MCP_EVOLVE_REPO", file=sys.stderr)
        return 2
    Log.path = os.path.join(a.repo, ".git", "unison-evolve.log")
    return {"commit": cmd_commit, "sync": cmd_sync, "restore": cmd_restore, "verify": cmd_verify, "scan": cmd_scan}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
