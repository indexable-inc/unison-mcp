#!/usr/bin/env python3 -I
"""Integration tests: drive bin/unison-mcp over stdio with scripted JSON-RPC.

  python3 -I tests/integration.py            # builds the test codebase once (needs network the first time)

Environment:
  UNISON_MCP_UCM_DIR   pinned ucm release dir (default ~/.local/share/uni/ucm/release-1.5.0)
  UNISON_MCP_TEST_DIR  scratch dir (default <tmp>/unison-mcp-test); holds the codebase, server.uc, chrome profile
  CHROME               Chrome binary for the Cdp test (default macOS Google Chrome); the test is skipped if missing

Tests never touch the browser on :9222 or any codebase that is not theirs.
"""
import hashlib, json, os, signal, socket, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")
UCM_DIR = os.environ.get("UNISON_MCP_UCM_DIR", f"{HOME}/.local/share/uni/ucm/release-1.5.0")
TEST_DIR = os.environ.get("UNISON_MCP_TEST_DIR", os.path.join(tempfile.gettempdir(), "unison-mcp-test"))
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CB = os.path.join(TEST_DIR, "codebase")
PROG = os.path.join(TEST_DIR, "server.uc")
STAMP = os.path.join(TEST_DIR, "stamp")


def source_hash():
    h = hashlib.sha256()
    for rel in open(os.path.join(REPO, "ORDER")).read().split() + ["scripts/build.sh"]:
        h.update(open(os.path.join(REPO, rel), "rb").read())
    return h.hexdigest()


def ensure_build():
    os.makedirs(TEST_DIR, exist_ok=True)
    want = source_hash()
    if os.path.exists(STAMP) and open(STAMP).read() == want and os.path.exists(PROG):
        return
    subprocess.run(["rm", "-rf", CB], check=True)
    r = subprocess.run([os.path.join(REPO, "scripts/build.sh"), CB, PROG], capture_output=True, text=True,
                       env=dict(os.environ, UNISON_MCP_UCM_DIR=UCM_DIR))
    if r.returncode != 0:
        raise RuntimeError("build failed:\n" + r.stdout[-3000:] + r.stderr[-1000:])
    open(STAMP, "w").write(want)


def ps():
    out = subprocess.run(["ps", "-eo", "pid=,pgid=,args="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), int(parts[1]), parts[2]))
    return rows


def ours():
    """processes that mention our test codebase (the ucm mcp children and the server)."""
    return [r for r in ps() if CB in r[2] or PROG in r[2]]


class Client:
    def __init__(self, env=None):
        e = dict(os.environ, UNISON_MCP_CODEBASE=CB, UNISON_MCP_PROGRAM=PROG, UNISON_MCP_UCM_DIR=UCM_DIR)
        e.update(env or {})
        self.p = subprocess.Popen([os.path.join(REPO, "bin/unison-mcp")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, env=e)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        assert line, "server closed stdout: " + self.p.stderr.read()
        msg = json.loads(line)
        assert msg["id"] == self.n, msg
        return msg

    def tool(self, **args):
        r = self.rpc("tools/call", {"name": "unison", "arguments": args})["result"]
        return r["isError"], r["content"][0]["text"]

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(15)
        except Exception:
            self.p.kill()


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_build()

    def setUp(self):
        self.c = Client()
        self.addCleanup(self.c.close)


class Protocol(Base):
    def test_tools_list_is_one_tool(self):
        tools = self.c.rpc("tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["unison"])
        self.assertIn("action", tools[0]["inputSchema"]["properties"])
        d = tools[0]["description"]
        for needle in ("MCP client", "Cdp.connect", "OAuth", "look up library names first", "Mcp.toolNames", "guide"):
            self.assertIn(needle, d)
        self.assertIn("infix", d)
        self.assertLess(len(d), 1800, "the description is paid in every session")

    def test_unknown_tool_and_method(self):
        r = self.c.rpc("tools/call", {"name": "typecheck-code", "arguments": {}})
        self.assertEqual(r["error"]["code"], -32602)
        self.assertEqual(self.c.rpc("nope")["error"]["code"], -32601)
        self.assertEqual(self.c.rpc("ping")["result"], {})


class Unison(Base):
    def test_typecheck_error_is_data(self):
        err, text = self.c.tool(code='foo : Nat\nfoo = "a"')
        self.assertFalse(err)  # a compile error is a result, not a tool failure
        self.assertIn("ok: false", text)
        self.assertIn("class: type-mismatch", text)
        # positive control: the corrected cell passes
        err, text = self.c.tool(code="foo : Nat\nfoo = 1")
        self.assertIn("ok: true", text)

    def test_error_classes(self):
        self.assertIn("class: wrong-name", self.c.tool(code="x = nopeNotAFunction 1")[1])
        self.assertIn("class: unhandled-ability", self.c.tool(code='y = printLine "x"\n> y')[1] if False else self.c.tool(code='y = do printLine "x"\n> y()')[1])
        self.assertIn("class: parse-error", self.c.tool(code="z = (1 +")[1])

    def test_expression_cell(self):
        err, text = self.c.tool(code="> 1 + 2")
        self.assertFalse(err)
        self.assertIn("ok: true", text)
        self.assertIn("3", text.split("\n\n", 1)[1])

    def test_run_body_and_named(self):
        err, text = self.c.tool(action="run", code="1 + 1")
        self.assertIn("ok: true", text)
        self.assertTrue(text.rstrip().endswith("2"), text)
        err, text = self.c.tool(action="update", code='testMain : \'{IO, Exception} Text\ntestMain = do "hello " ++ "named"')
        self.assertIn("ok: true", text)
        err, text = self.c.tool(action="run", name="testMain")
        self.assertIn("hello named", text)

    def test_search_view_tests_guide(self):
        self.assertIn("Text.lines", self.c.tool(action="search", name="Text.lines")[1])
        self.assertIn("Cdp.eval", self.c.tool(action="view", name="Cdp.eval")[1])
        self.assertIn("passing", self.c.tool(action="tests", name="Mcp")[1])
        self.assertIn("passing", self.c.tool(action="tests", name="Cdp")[1])
        self.assertGreater(len(self.c.tool(action="guide")[1]), 3000)
        self.assertIn("typecheck-code", self.c.tool(action="tools")[1])

    def test_guide_topics(self):
        topics = ["unison-basics", "http-json", "mcp-client", "oauth", "cdp", "process-ffi", "traps"]
        listed = self.c.rpc("tools/list")["result"]["tools"][0]["description"]
        for t in topics:
            self.assertIn(t, listed)
            err, text = self.c.tool(action="guide", topic=t)
            self.assertFalse(err)
            self.assertIn("ok: true", text, t)
            self.assertIn("# " + t + ":", text)
            self.assertGreater(len(text), 500)
            self.assertNotIn("/Users/", text)
        # the default guide is the index plus the basics and the traps
        err, text = self.c.tool(action="guide")
        self.assertIn("Topics (call action", text)
        # unknown topic is an error class, not a crash; positive control above
        err, text = self.c.tool(action="guide", topic="nope")
        self.assertIn("ok: false", text)
        self.assertIn("class: usage", text)
        self.assertIn("unknown topic 'nope'", text)

    def test_repo_names_are_searchable_and_callable(self):
        # bug: Cdp.* was in the compiled server but not in the codebase cells see
        for name in ("Cdp.connect", "Cdp.targets", "Mcp.toolNames", "Mcp.run", "Superhuman.listThreads"):
            self.assertIn(name, self.c.tool(action="search", name=name)[1], name)
        code = 'f : \'{IO, Exception} [Cdp.Target]\nf = do Cdp.targets "http://127.0.0.1:1"\n'
        err, text = self.c.tool(action="check", code=code)
        self.assertIn("ok: true", text, text)

    def test_run_cell_with_definitions_and_trailing_expression(self):
        for last in ("> double 21", "double 21"):
            code = "double : Nat -> Nat\ndouble n = n * 2\n\n" + last
            err, text = self.c.tool(action="run", code=code)
            self.assertIn("ok: true", text, text)
            self.assertTrue(text.rstrip().endswith("42"), text)
        # positive control: a plain body with bindings still runs as a body
        err, text = self.c.tool(action="run", code="x = 20\nx + 1")
        self.assertTrue(text.rstrip().endswith("21"), text)
        # definitions without a final expression are a usage error, not a parse error
        err, text = self.c.tool(action="run", code="g : Nat\ng = 1")
        self.assertIn("ok: false", text)

    def test_big_result_is_cut_and_spilled_to_a_file(self):
        err, small = self.c.tool(action="run", code='Text.join "" (List.replicate 100 do "ab")')
        self.assertNotIn("cut,", small)
        err, text = self.c.tool(action="run", code='Text.join "" (List.replicate 30000 do "ab")')
        self.assertFalse(err)
        self.assertLess(len(text), 13000)
        self.assertIn("ok: true", text)
        self.assertIn("cut, full text (", text)
        path = text.split("in file: ", 1)[1].split(" ...]", 1)[0].strip()
        self.assertTrue(path.endswith(".txt") and "/spill/" in path, path)
        full = open(path).read()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self.assertGreaterEqual(len(full), 60000)
        self.assertIn("ababab", full)

    def test_mcp_tool_names(self):
        self.assertIn("passing", self.c.tool(action="tests", name="Mcp")[1])
        code = 'Exception.catch do Mcp.fake (n t x -> "{\\"tools\\":[{\\"name\\":\\"a\\"},{\\"name\\":\\"b\\"}]}") do Mcp.toolNames "s"'
        err, text = self.c.tool(action="run", code=code)
        self.assertIn("ok: true", text, text)
        self.assertIn('"a"', text)

    def test_superhuman_example_fake(self):
        self.assertIn("passing", self.c.tool(action="tests", name="Superhuman")[1])


class Install(unittest.TestCase):
    def test_install_puts_repo_definitions_in_the_codebase(self):
        """install.sh into a throwaway codebase and dest; it verifies Cdp.connect etc. in main/main itself."""
        d = os.path.join(TEST_DIR, "install")
        subprocess.run(["rm", "-rf", d], check=True)
        r = subprocess.run([os.path.join(REPO, "scripts/install.sh"), "--codebase", os.path.join(d, "cb"), "--dest", os.path.join(d, "dest")],
                           capture_output=True, text=True, env=dict(os.environ, UNISON_MCP_UCM_DIR=UCM_DIR))
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertIn("verified Cdp.connect", r.stdout)
        for f in ("unison-mcp", "unison-mcp.uc", "ucm.pin"):
            self.assertTrue(os.path.exists(os.path.join(d, "dest", f)), f)
        # negative control: a codebase without the repo must make the same check fail
        empty = os.path.join(d, "empty")
        t = os.path.join(d, "v.md")
        open(t, "w").write("```ucm\nscratch/main> project.create-empty main\n```\n")
        subprocess.run([os.path.join(UCM_DIR, "ucm"), "-C", empty, "transcript.in-place", t], capture_output=True)
        r2 = subprocess.run([os.path.join(REPO, "scripts/verify-install.sh"), empty], capture_output=True, text=True,
                            env=dict(os.environ, UNISON_MCP_UCM_DIR=UCM_DIR))
        self.assertNotEqual(r2.returncode, 0, r2.stdout + r2.stderr)


class Supervision(Base):
    def test_timeout_kills_child_and_server_recovers(self):
        self.assertIn("ok: true", self.c.tool(code="> 1")[1])  # child is up
        before = [r for r in ours() if "mcp -C" in r[2]]
        self.assertTrue(before)
        t = time.time()
        err, text = self.c.tool(action="run", code="sleepMicroseconds 20000000", timeout_ms=1500)
        took = time.time() - t
        self.assertTrue(err)
        self.assertIn("class: timeout", text)
        self.assertLess(took, 8, "timeout must be near timeout_ms")
        time.sleep(0.5)
        after = [r for r in ours() if "mcp -C" in r[2]]
        self.assertFalse(set(r[0] for r in before) & set(r[0] for r in after), "old ucm child must be dead")
        # restart on the next call
        self.assertIn("ok: true", self.c.tool(code="> 2 + 2")[1])

    def test_restart_after_child_death(self):
        self.assertIn("ok: true", self.c.tool(code="> 1")[1])
        kids = [r for r in ours() if "mcp -C" in r[2]]
        self.assertTrue(kids)
        for pid, _, _ in kids:
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
        err, text = self.c.tool(code="> 5 + 5")
        self.assertIn("ok: true", text)
        self.assertIn("10", text)

    def test_launcher_kills_group_on_stdin_close_and_sigterm(self):
        self.assertIn("ok: true", self.c.tool(code="> 1")[1])
        self.c.close()
        time.sleep(1.0)
        self.assertEqual(ours(), [], "stdin close must leave no process behind")
        c2 = Client()
        self.assertIn("ok: true", c2.tool(code="> 1")[1])
        c2.p.send_signal(signal.SIGTERM)
        c2.p.wait(10)
        time.sleep(1.0)
        self.assertEqual(ours(), [], "SIGTERM on the launcher must kill the whole group")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(os.path.exists(CHROME), "no Chrome binary")
class CdpHeadless(Base):
    def test_navigate_eval_read_click(self):
        port = free_port()
        self.assertNotEqual(port, 9222)
        profile = os.path.join(TEST_DIR, "chrome-profile")
        chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                                   "--no-first-run", "--no-default-browser-check", "about:blank"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(lambda: (os.killpg(chrome.pid, signal.SIGKILL), chrome.wait()))
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        base = f"http://127.0.0.1:{port}"
        page = "data:text/html,<title>t</title><p id=p>start</p><button id=b>go</button><input id=i>"
        wire = "document.getElementById('b').onclick = () => { document.getElementById('p').textContent = 'clicked' }; 1"
        code = "\n".join([
            f'Cdp.connect "{base}" "about:blank" do',
            f'  _ = Cdp.navigate "{page}"',
            f'  _ = Cdp.eval "{wire}"',
            '  two = Cdp.evalText "String(1 + 1)"',
            '  before = !Cdp.readPage',
            '  hit = Cdp.click "#b"',
            '  typed = Cdp.typeText "#i" "abc"',
            '  value = Cdp.evalText "document.getElementById(\'i\').value"',
            '  _ = Cdp.waitFor (Cdp.Wait.Contains "clicked") 3000',
            '  after = !Cdp.readPage',
            '  shot = Cdp.screenshot "' + os.path.join(TEST_DIR, "shot.png") + '"',
            '  Text.join "|" [two, before, after, value, Boolean.toText hit, Boolean.toText typed, Nat.toText shot]'])
        err, text = self.c.tool(action="run", code=code, timeout_ms=60000)
        self.assertIn("ok: true", text, text)
        body = text.split("\n\n", 1)[1]
        self.assertIn("2|start", body)
        self.assertIn("go|clicked", body)
        self.assertIn("go|abc|true|true|", body)
        self.assertGreater(os.path.getsize(os.path.join(TEST_DIR, "shot.png")), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
