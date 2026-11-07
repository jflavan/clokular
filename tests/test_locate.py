import unittest

from clokular.locate import BookText, locate, normalize, okular_to_book_page, read_so_far, context_before


def make_book(pages: list[str], exact=True) -> BookText:
    starts, pos = [], 0
    for p in pages:
        starts.append(pos)
        pos += len(p)
    return BookText("".join(pages), starts, exact_pages=exact)


class NormalizeTest(unittest.TestCase):
    def test_folds_typography_and_whitespace(self):
        n, _ = normalize("“Someone’s  coming,”\nRoche ﬁnally — whispered.")
        self.assertEqual(n, "\"someone's coming,\" roche finally - whispered.")

    def test_index_map_points_back_into_original(self):
        src = "a  ’b’\n\nc"
        n, idx = normalize(src)
        self.assertEqual(len(n), len(idx))
        self.assertEqual(src[idx[n.index("c")]], "c")


class PageMappingTest(unittest.TestCase):
    def test_exact_pages_are_used_directly(self):
        b = make_book(["a\n"] * 10)
        self.assertEqual(okular_to_book_page(b, 1, 10), 0)
        self.assertEqual(okular_to_book_page(b, 10, 10), 9)

    def test_scaled_when_counts_differ(self):
        b = make_book(["a\n"] * 588, exact=False)
        self.assertEqual(okular_to_book_page(b, 6, 612), 5)
        self.assertEqual(okular_to_book_page(b, 612, 612), 587)


class LocateTest(unittest.TestCase):
    def setUp(self):
        self.pages = [f"Page {i} filler text. " * 20 + "\n" for i in range(40)]
        self.pages[3] += "Drotte rattled the gate.\n"
        self.pages[30] += "Drotte rattled the gate.\n"  # same words, much later
        self.pages[30] += "THE SECRET ENDING.\n"
        self.book = make_book(self.pages)

    def test_picks_occurrence_on_current_page(self):
        loc = locate(self.book, "Drotte rattled the gate.", 4, 40)
        self.assertEqual(loc.method, "near-page")
        self.assertEqual(loc.page, 3)
        self.assertNotIn("SECRET", read_so_far(self.book, loc))

    def test_never_reads_past_the_selections_page(self):
        loc = locate(self.book, "Drotte rattled the gate.", 4, 40)
        self.assertLessEqual(loc.cutoff, self.book.page_end(3))
        self.assertTrue(read_so_far(self.book, loc).endswith("Drotte rattled the gate.\n"))

    def test_later_occurrence_when_reader_is_there(self):
        loc = locate(self.book, "Drotte rattled the gate.", 31, 40)
        self.assertEqual(loc.page, 30)

    def test_wrong_page_falls_back_to_latest_earlier_occurrence(self):
        # Okular says page 20; the text only appears on pages 4 and 31.
        loc = locate(self.book, "Drotte rattled the gate.", 20, 40)
        self.assertEqual(loc.method, "before-page")
        self.assertEqual(loc.page, 3)

    def test_reader_before_any_occurrence_uses_earliest(self):
        loc = locate(self.book, "THE SECRET ENDING", 2, 40)
        self.assertEqual(loc.method, "first-occurrence")

    def test_matches_despite_line_breaks_and_quotes(self):
        pages = ["intro\n", "“The guard has\ngone.” Thus my friend\n", "after\n"]
        b = make_book(pages)
        loc = locate(b, '"The guard has gone." Thus my friend', 2, 3)
        self.assertIsNotNone(loc)
        self.assertEqual(loc.page, 1)
        self.assertNotIn("after", read_so_far(b, loc))

    def test_partial_match_when_selection_has_extra_text(self):
        words = " ".join(f"w{i}" for i in range(30))
        b = make_book(["start\n", words + "\n", "later\n"])
        sel = words.replace("w15", "w15 [footnote 3]")
        loc = locate(b, sel, 2, 3)
        self.assertIsNotNone(loc)
        self.assertIn("matched part of the selection", loc.notes)

    def test_not_found(self):
        self.assertIsNone(locate(self.book, "nowhere in this book", 3, 40))

    def test_estimated_pages_prefer_earlier_on_drift(self):
        # Replica layout (exact=False): occurrences 3 pages before and 3 after.
        pages = [f"p{i} " * 50 + "\n" for i in range(100)]
        pages[47] += "Thecla smiled.\n"
        pages[53] += "Thecla smiled.\n"
        b = make_book(pages, exact=False)
        loc = locate(b, "Thecla smiled.", 51, 100)  # maps to index 50
        self.assertEqual(loc.page, 47)

    def test_context_ends_at_cutoff(self):
        loc = locate(self.book, "Drotte rattled the gate.", 4, 40)
        ctx = context_before(self.book, loc)
        self.assertTrue(ctx.endswith("Drotte rattled the gate.\n"))
        self.assertLessEqual(len(ctx), 9000 + 100)


if __name__ == "__main__":
    unittest.main()
