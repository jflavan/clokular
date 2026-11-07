import json
import tempfile
import unittest
from pathlib import Path

from clokular import install, session
from clokular.claude import command, parse_stream
from clokular.locate import BookText
from clokular.okular import OpenDocument
from clokular.pdf import split_pages
from clokular.prompt import READ_FILE
from clokular.urls import selection_from_url


class UrlTest(unittest.TestCase):
    def test_decodes(self):
        self.assertEqual(selection_from_url("clokular:It%20is%20%E2%80%9Cpossible%E2%80%9D"), "It is “possible”")

    def test_rejects_other_schemes(self):
        with self.assertRaises(ValueError):
            selection_from_url("https://example.com")


class PdfTest(unittest.TestCase):
    def test_split_pages(self):
        text, starts = split_pages("one\ntwo\n\fthree\n\f")
        self.assertEqual(starts, [0, 8])
        self.assertEqual(text[starts[1]:], "three\n")


class StreamTest(unittest.TestCase):
    def ev(self, **d):
        return json.dumps(d)

    def test_text_resets_after_tool_use_and_done(self):
        lines = [
            self.ev(type="system", subtype="init", session_id="s1"),
            self.ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Let me look."}}),
            self.ev(type="stream_event", event={"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Grep"}}),
            self.ev(type="stream_event", event={"type": "content_block_start", "content_block": {"type": "text"}}),
            self.ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Drotte is"}}),
            self.ev(type="stream_event", event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": " captain."}}),
            self.ev(type="result", subtype="success", result="Drotte is captain.", session_id="s1"),
        ]
        evs = list(parse_stream(lines))
        kinds = [e.kind for e in evs]
        self.assertEqual(kinds, ["text", "tool", "text", "text", "done"])
        self.assertEqual(evs[3].text, "Drotte is captain.")
        self.assertEqual(evs[-1].session_id, "s1")

    def test_error_result(self):
        evs = list(parse_stream([self.ev(type="result", subtype="error_during_execution", is_error=True, errors=["boom"])]))
        self.assertEqual(evs[-1].kind, "error")

    def test_command_is_locked_down(self):
        cmd = command("claude", "sonnet")
        for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Grep")
        self.assertNotIn("--bare", cmd)  # --bare can't use a subscription login


class PrepareTest(unittest.TestCase):
    def setUp(self):
        import os
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        pages = ["Chapter one. Severian swam.\n", "Drotte rattled the gate.\n", "SPOILER: the twist.\n"]
        starts, pos = [], 0
        for p in pages:
            starts.append(pos)
            pos += len(p)
        self.book = BookText("".join(pages), starts, True, "Shadow", "Wolfe")

    def tearDown(self):
        self.tmp.cleanup()

    def test_workdir_holds_only_what_was_read(self):
        doc = OpenDocument("svc", "/okular", "/books/x.pdf", 2, 3)
        p = session.prepare("Drotte rattled the gate.", [doc], loader=lambda path: self.book)
        files = list(Path(p.workdir).iterdir())
        self.assertEqual([f.name for f in files], [READ_FILE])
        text = files[0].read_text()
        self.assertIn("Severian swam", text)
        self.assertNotIn("SPOILER", text)
        self.assertNotIn("SPOILER", p.prompt)
        self.assertIn("page 2 of 3", p.prompt)
        self.assertTrue(p.located)

    def test_no_okular(self):
        p = session.prepare("some words", [], loader=lambda path: self.book)
        self.assertFalse(p.located)
        self.assertEqual(Path(p.workdir, READ_FILE).read_text(), "")
        self.assertTrue(p.warnings)

    def test_unmatched_text_uses_pages_before_current(self):
        doc = OpenDocument("svc", "/okular", "/books/x.pdf", 3, 3)
        p = session.prepare("not in the book at all", [doc], loader=lambda path: self.book)
        text = Path(p.workdir, READ_FILE).read_text()
        self.assertIn("Drotte", text)
        self.assertNotIn("SPOILER", text)

    def test_picks_the_tab_containing_the_selection(self):
        other = BookText("Something else entirely.\n", [0], True, "Other", "")
        docs = [OpenDocument("svc", "/okular", "/books/other.pdf", 1, 1),
                OpenDocument("svc", "/okular2", "/books/x.pdf", 2, 3)]
        p = session.prepare("Drotte rattled the gate.", docs,
                            loader=lambda path: other if "other" in path else self.book)
        self.assertEqual(p.title, "Shadow")


class InstallerTest(unittest.TestCase):
    def test_exec_arg_plain(self):
        self.assertEqual(install.exec_arg("/usr/bin/python3"), '"/usr/bin/python3"')

    def test_exec_arg_escapes_specials(self):
        # Spec: escape " ` $ \ inside quotes, then double every backslash; % -> %%.
        self.assertEqual(install.exec_arg('/a b/$x"y`z'), '"/a b/\\\\$x\\\\"y\\\\`z"')
        self.assertEqual(install.exec_arg("/r/100%"), '"/r/100%%"')
        self.assertEqual(install.exec_arg("/r\\s"), '"/r\\\\\\\\s"')

    def test_handler_has_no_python_flags(self):
        line = [l for l in install.handler_entry("/usr/bin/python3").splitlines() if l.startswith("Exec=")][0]
        self.assertTrue(line.startswith('Exec="/usr/bin/python3" "'))
        self.assertTrue(line.endswith('/bin/clokular" %u'))

    def test_install_stops_when_check_fails(self):
        from unittest import mock
        with mock.patch.object(install, "check", return_value=1), \
             mock.patch.object(install, "_install_icon") as icon, \
             mock.patch.object(install.subprocess, "run") as run:
            self.assertEqual(install.install(), 1)
        icon.assert_not_called()
        run.assert_not_called()


class KConfigEditTest(unittest.TestCase):
    def test_set_and_remove(self):
        lines = ["[General]", "EnableWebShortcuts=true", "", "[Other]", "x=1"]
        out = install._set(lines, "General", "PreferredWebShortcuts", "claude,google")
        self.assertEqual(install._get(out, "General", "PreferredWebShortcuts"), "claude,google")
        self.assertEqual(install._get(out, "Other", "x"), "1")
        out = install._set(out, "General", "PreferredWebShortcuts", None)
        self.assertIsNone(install._get(out, "General", "PreferredWebShortcuts"))

    def test_new_file(self):
        out = install._set([], "General", "PreferredWebShortcuts", "claude")
        self.assertEqual(out, ["[General]", "PreferredWebShortcuts=claude"])

    def test_provider_query_template(self):
        self.assertIn("Query=clokular:\\\\{@}", install.PROVIDER)
        self.assertIn("Icon=clokular-claude", install.PROVIDER)
        self.assertTrue(install.ICON_SRC.exists())


if __name__ == "__main__":
    unittest.main()
