#!/usr/bin/env python3 -I
"""Tests of the self-evolving codebase (scripts/evolve.py + the post-update hook in the server).

  python3 -I tests/evolve.py

Every test works on a throwaway copy of the test codebase (made with the sqlite backup API) and a throwaway git repo
under the scratch dir; it never touches the live codebase or any real repo. UNISON_MCP_CONFIG=/dev/null keeps the
installed config out. Builds the test codebase once like tests/integration.py (network the first time).
"""
import os, shutil, sqlite3, subprocess, sys, tempfile, threading, time, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import integration as I

EVOLVE = os.path.join(I.REPO, "scripts", "evolve.py")
GITCFG = os.path.join(I.TEST_DIR, "gitconfig")


def backup(src_cb, dst_cb):
    shutil.rmtree(dst_cb, ignore_errors=True)
    os.makedirs(os.path.join(dst_cb, ".unison", "v2"))
    s = sqlite3.connect(f"file:{src_cb}/.unison/v2/unison.sqlite3?mode=ro", uri=True)
    d = sqlite3.connect(os.path.join(dst_cb, ".unison", "v2", "unison.sqlite3"))
    s.backup(d)
    d.close()
    s.close()


def sh(*args, cwd=None, env=None):
    return subprocess.run(args, capture_output=True, text=True, cwd=cwd, env=dict(os.environ, **(env or {})))


class Evolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        I.ensure_build()
        with open(GITCFG, "w") as f:
            f.write("[user]\n\tname = evolve test\n\temail = evolve@test.invalid\n[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="evolve-", dir=I.TEST_DIR)
        self.addCleanup(shutil.rmtree, self.work, True)
        self.cb = os.path.join(self.work, "codebase")
        backup(I.CB, self.cb)
        self.repo = os.path.join(self.work, "repo")
        self.env = {"GIT_CONFIG_GLOBAL": GITCFG, "UNISON_MCP_CONFIG": "/dev/null", "UNISON_MCP_EVOLVE_SIGN": "0",
                    "UNISON_MCP_EVOLVE_REPO": self.repo, "UNISON_MCP_EVOLVE_SCRIPT": EVOLVE, "UNISON_MCP_CODEBASE": self.cb,
                    "UNISON_MCP_EVOLVE_UCM": f"{I.UCM_DIR}/unison/unison"}
        os.environ.update({k: v for k, v in self.env.items() if k.startswith("GIT_")})
        sh("git", "init", "-q", self.repo)
        self.clients = []

    def tearDown(self):
        for c in self.clients:
            c.close()

    def client(self, **extra):
        c = I.Client(dict(self.env, **extra))
        self.clients.append(c)
        return c

    def commits(self, repo=None):
        r = sh("git", "-C", repo or self.repo, "rev-list", "--count", "HEAD")
        return int(r.stdout) if r.returncode == 0 else 0

    def wait_commits(self, n, repo=None, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if self.commits(repo) >= n:
                return
            time.sleep(0.3)
        log = open(os.path.join(repo or self.repo, ".git", "unison-evolve.log")).read() if os.path.exists(os.path.join(repo or self.repo, ".git", "unison-evolve.log")) else "(no log)"
        self.fail(f"expected {n} commits, have {self.commits(repo)}; log:\n{log}")

    def subjects(self, repo=None):
        return sh("git", "-C", repo or self.repo, "log", "--format=%s").stdout.splitlines()

    def evolve(self, *args):
        return sh(EVOLVE, *args, env=self.env)

    def idle(self):
        for c in self.clients:
            c.close()
        self.clients = []
        end = time.time() + 30
        while time.time() < end and self.holders():
            time.sleep(0.5)

    def holders(self):
        return [r for r in I.ps() if self.cb in r[2] and "unison" in r[2]]

    def test_update_makes_exactly_one_commit_naming_the_definition(self):
        c = self.client(UNISON_MCP_LANE="lane-7")
        err, text = c.tool(action="update", code="Evo.one : Nat\nEvo.one = 1\n")
        self.assertIn("ok: true", text)
        self.wait_commits(1)
        time.sleep(3)  # a second commit would show up by now
        self.assertEqual(self.commits(), 1)
        msg = sh("git", "-C", self.repo, "log", "-1", "--format=%B").stdout
        self.assertTrue(msg.startswith("update: Evo.one"), msg)
        self.assertIn("lane: lane-7", msg)
        self.assertIn("session: ", msg)
        self.assertTrue(os.path.exists(os.path.join(self.repo, "export", "defs", "Evo.one.u")))
        self.assertIn("term Evo.one #", open(os.path.join(self.repo, "export", "INDEX.txt")).read())
        self.assertIn("-- #", open(os.path.join(self.repo, "export", "defs", "Evo.one.u")).read())
        # the snapshot is a consistent store and the export matches it
        self.idle()
        v = self.evolve("verify", "--repo", self.repo, "--codebase", self.cb, "--live")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertNotIn("/mcp/", sh("git", "-C", self.repo, "ls-files").stdout)

    def test_two_sessions_concurrently_give_two_commits_and_a_consistent_store(self):
        a, b = self.client(), self.client()
        out = {}

        def go(name, c, code):
            out[name] = c.tool(action="update", code=code)[1]

        ts = [threading.Thread(target=go, args=("a", a, "Evo.alpha : Nat\nEvo.alpha = 1\n")),
              threading.Thread(target=go, args=("b", b, "Evo.beta : Nat\nEvo.beta = 2\n"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertIn("ok: true", out["a"])
        self.assertIn("ok: true", out["b"])
        self.wait_commits(2)
        time.sleep(2)
        self.assertEqual(self.commits(), 2)
        subj = " ".join(self.subjects())
        self.assertIn("Evo.alpha", subj)
        self.assertIn("Evo.beta", subj)
        self.idle()
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".git", "unison-evolve.lock")), "the lock is released")
        v = self.evolve("verify", "--repo", self.repo, "--codebase", self.cb, "--live")
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        index = open(os.path.join(self.repo, "export", "INDEX.txt")).read()
        self.assertIn("Evo.alpha", index)
        self.assertIn("Evo.beta", index)

    def test_failing_update_makes_no_commit(self):
        c = self.client()
        err, text = c.tool(action="update", code='Evo.bad : Nat\nEvo.bad = "x"\n')
        self.assertIn("ok: false", text)
        # positive control: the corrected definition commits, and it is the only commit
        err, text = c.tool(action="update", code="Evo.bad : Nat\nEvo.bad = 1\n")
        self.assertIn("ok: true", text)
        self.wait_commits(1)
        time.sleep(3)
        self.assertEqual(self.commits(), 1)
        self.assertEqual(len(self.subjects()), 1)
        # a check (not an update) never commits either
        c.tool(action="check", code="Evo.fine : Nat\nEvo.fine = 3\n")
        time.sleep(3)
        self.assertEqual(self.commits(), 1)

    def test_rollback_restores_the_previous_definition(self):
        c = self.client()
        c.tool(action="update", code="Evo.val : Nat\nEvo.val = 1\n")
        self.wait_commits(1)
        c.tool(action="update", code="Evo.val : Nat\nEvo.val = 2\n")
        self.wait_commits(2)
        self.idle()
        self.assertIn("2", self.client().tool(action="run", code="Evo.val")[1].split("\n\n", 1)[1])
        self.idle()
        r = self.evolve("restore", "--codebase", self.cb, "--repo", self.repo, "HEAD~1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.commits(), 4)  # the state before and after the restore are commits too
        c2 = self.client()
        err, text = c2.tool(action="run", code="Evo.val")
        self.assertTrue(text.rstrip().endswith("1"), text)
        # restore refuses while a ucm holds the codebase
        c2.tool(action="search", name="Evo.val")
        refused = self.evolve("restore", "--codebase", self.cb, "--repo", self.repo, "HEAD~1")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("refused", refused.stdout)

    def test_sync_pushes_after_a_secrets_scan_and_pulls_into_a_clean_clone(self):
        remote = os.path.join(self.work, "remote.git")
        sh("git", "init", "-q", "--bare", remote)
        c = self.client()
        c.tool(action="update", code="Evo.s : Nat\nEvo.s = 1\n")
        self.wait_commits(1)
        sh("git", "-C", self.repo, "remote", "add", "origin", remote)
        sh("git", "-C", self.repo, "push", "-q", "-u", "origin", "HEAD")
        self.idle()
        # the scan reports what a library carries inside the sqlite (an embedded test key); accepting it is an explicit step
        scan = self.evolve("scan", "--repo", self.repo)
        self.assertEqual(scan.returncode, 1, scan.stdout)
        self.assertIn("private key", scan.stdout)
        self.evolve("scan", "--repo", self.repo, "--accept")
        self.assertEqual(self.evolve("scan", "--repo", self.repo).returncode, 0)
        sh("git", "-C", self.repo, "add", ".secrets-allow")
        sh("git", "-C", self.repo, "commit", "-q", "-m", "accept library test key")
        # clone B with its own copy of the codebase as it was at that commit
        repo_b, cb_b = os.path.join(self.work, "repo-b"), os.path.join(self.work, "codebase-b")
        sh("git", "clone", "-q", remote, repo_b)
        backup(self.cb, cb_b)
        # A makes another commit; plain sync on A pushes it (scan clean)
        c = self.client()
        c.tool(action="update", code="Evo.s : Nat\nEvo.s = 2\n")
        self.wait_commits(3)
        self.idle()
        out = self.evolve("sync", "--codebase", self.cb, "--repo", self.repo)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("pushed (secrets scan clean)", out.stdout, out.stdout)
        # B pulls and gets the snapshot because its live codebase had nothing the repo lacked
        out = sh(EVOLVE, "sync", "--codebase", cb_b, "--repo", repo_b, env=self.env)
        self.assertIn("pulled 2 commits", out.stdout, out.stdout + out.stderr)
        self.assertIn("replaced", out.stdout)
        cb_env = dict(self.env, UNISON_MCP_CODEBASE=cb_b)
        cb = I.Client(cb_env)
        self.clients.append(cb)
        err, text = cb.tool(action="run", code="Evo.s")
        self.assertTrue(text.rstrip().endswith("2"), text)
        self.idle()
        # secrets scan blocks the push of a planted token (positive control above pushed fine)
        with open(os.path.join(self.repo, "note.txt"), "w") as f:
            f.write('{"access_token": "abcdefghijklmnopqrstuv0123456789"}\n')
        sh("git", "-C", self.repo, "add", "note.txt")
        sh("git", "-C", self.repo, "commit", "-q", "-m", "plant")
        out = self.evolve("sync", "--codebase", self.cb, "--repo", self.repo)
        self.assertIn("not pushed: secrets scan found", out.stdout)
        self.assertEqual(sh("git", "-C", remote, "rev-list", "--count", "HEAD").stdout.strip(), "3")

    def test_no_repo_configured_is_a_no_op(self):
        env = dict(self.env)
        for k in ("UNISON_MCP_EVOLVE_REPO", "UNISON_MCP_EVOLVE_SCRIPT"):
            env.pop(k)
        c = I.Client(env)
        self.clients.append(c)
        err, text = c.tool(action="update", code="Evo.noop : Nat\nEvo.noop = 1\n")
        self.assertIn("ok: true", text)
        self.assertIn("sync is off", c.tool(action="sync")[1])
        time.sleep(1)
        self.assertEqual(self.commits(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
