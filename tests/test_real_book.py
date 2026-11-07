"""Checks against real books on this machine. Skipped when the file is absent.

Set CLOKULAR_TEST_EPUB / CLOKULAR_TEST_PDF to point at other books.
"""

import os
import subprocess
import tempfile
import unittest

from clokular import book as booklib
from clokular.locate import locate, read_so_far

EPUB = os.environ.get(
    "CLOKULAR_TEST_EPUB",
    "/var/mnt/storage2/Books/Audiobooks/The Book of the New Sun (Gene Wolfe) (Jonathan Davis)/"
    "Book of the New Sun ebook/Book of the New Sun [Omnibus].epub",
)
OKULAR_PAGES = int(os.environ.get("CLOKULAR_TEST_EPUB_PAGES", "612"))


@unittest.skipUnless(os.path.exists(EPUB), "test EPUB not present")
class RealEpubTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = booklib.load(EPUB)

    def test_layout_is_close_to_okulars_page_count(self):
        self.assertLess(abs(self.book.page_count - OKULAR_PAGES) / OKULAR_PAGES, 0.08)

    def test_opening_passage_is_on_okulars_page_6(self):
        loc = locate(self.book, "It is possible I already had some presentiment of my future.", 6, OKULAR_PAGES)
        self.assertIsNotNone(loc)
        self.assertEqual(loc.method, "near-page")

    def test_read_so_far_stops_in_chapter_one(self):
        loc = locate(self.book, "“Someone’s coming,” Roche whispered. Drotte jerked Eata out.", 6, OKULAR_PAGES)
        so_far = read_so_far(self.book, loc)
        self.assertIn("presentiment", so_far)
        self.assertLess(len(so_far), len(self.book.text) * 0.02)
        # Nothing from the end of the omnibus.
        tail = self.book.text.strip()[-400:]
        self.assertNotIn(tail, so_far)

    def test_common_word_resolves_near_the_reader(self):
        loc = locate(self.book, "Drotte", 6, OKULAR_PAGES)
        self.assertIn(loc.method, ("near-page", "nearby"))
        self.assertLessEqual(loc.page, 8)

    def test_title_and_author(self):
        self.assertIn("New Sun", self.book.title)
        self.assertIn("Wolfe", self.book.author)


@unittest.skipUnless(subprocess.run(["which", "pdftotext"], capture_output=True).returncode == 0
                     and os.path.exists(EPUB), "needs pdftotext and a source for a test PDF")
class GeneratedPdfTest(unittest.TestCase):
    """Builds a 3-page PDF with Qt so PDF extraction is tested end to end."""

    def test_pdf_pages_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.pdf")
            script = (
                "import sys,os; os.environ['QT_QPA_PLATFORM']='offscreen';"
                "from PySide6.QtGui import QGuiApplication,QPdfWriter,QPainter,QPageSize;"
                "from PySide6.QtCore import QRect;"
                "a=QGuiApplication([]); w=QPdfWriter(sys.argv[1]); w.setPageSize(QPageSize(QPageSize.A5));"
                "p=QPainter(w);"
                "[ (p.drawText(QRect(100,100,4000,400), 0, t), (w.newPage() if i<2 else None)) "
                "for i,t in enumerate(['First page text.','The guard has gone.','Hidden ending here.'])];"
                "p.end()"
            )
            subprocess.run(["python3", "-c", script, path], check=True, capture_output=True)
            from unittest import mock
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": tmp}):
                b = booklib.load(path)
            self.assertEqual(b.page_count, 3)
            loc = locate(b, "The guard has gone.", 2, 3)
            self.assertEqual(loc.page, 1)
            self.assertNotIn("Hidden ending", read_so_far(b, loc))


if __name__ == "__main__":
    unittest.main()
