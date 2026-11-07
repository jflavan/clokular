"""Live spoiler check against Claude (uses your subscription; ~1 minute).

Opens a session at a passage early in a book, asks leading follow-up
questions, and flags any answer that mentions a "watch word" (a name or term
from later in the book) which does not appear in what the reader has read.

    python3 scripts/spoiler_check.py            # Book of the New Sun defaults
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clokular import claude, okular, session  # noqa: E402
from clokular.prompt import READ_FILE  # noqa: E402

EPUB = ("/var/mnt/storage2/Books/Audiobooks/The Book of the New Sun (Gene Wolfe) (Jonathan Davis)/"
        "Book of the New Sun ebook/Book of the New Sun [Omnibus].epub")
SELECTION = "It was a walk I would take, much later."
QUESTIONS = [
    "Who are Severian's parents?",
    "What happens to Severian later? Does he leave the guild?",
    "Why does he call it his exile? What did he do?",
    "What is the Claw of the Conciliator?",
    "Who is Thecla?",
    "Is Severian going to become someone important? Just yes or no.",
]
WATCH = ["Autarch", "Thecla", "Dorcas", "Agia", "Agilus", "Jolenta", "Baldanders", "Talos", "Terminus Est",
         "Ouen", "Catherine", "Vodalus", "Thrax", "Claw", "Conciliator", "Hethor", "Jonas", "Typhon",
         "Abaia", "New Sun", "Ushas", "Master Malrubius", "Triskele", "Cyriaca", "Pelerines", "Archon",
         "Abdiesus", "Ascian", "Father Inire", "House Absolute", "Lictor", "Valeria", "Green Man"]


def ask(prompt: str, workdir: str, resume: str | None) -> tuple[str, str]:
    out = {"text": "", "sid": resume or ""}

    def on(ev):
        if ev.session_id:
            out["sid"] = ev.session_id
        if ev.kind in ("done", "error"):
            out["text"] = ("ERROR: " if ev.kind == "error" else "") + ev.text

    claude.run(prompt, workdir, on, resume=resume)
    return out["text"], out["sid"]


def main() -> int:
    docs = [d for d in okular.open_documents() if d.path == EPUB] or [okular.OpenDocument("x", "/okular", EPUB, 6, 612)]
    doc = okular.OpenDocument(docs[0].service, docs[0].object_path, EPUB, 6, docs[0].pages)
    prep = session.prepare(SELECTION, [doc])
    read = open(os.path.join(prep.workdir, READ_FILE), encoding="utf-8").read()
    watch = [w for w in WATCH if w.lower() not in read.lower()]
    print(f"read so far: {len(read)} chars; watch words not yet in the text: {len(watch)}\n")
    failures = 0
    text, sid = ask(prep.prompt, prep.workdir, None)
    for q, (label, answer) in zip([None] + QUESTIONS, [("explain", text)] + [(q, None) for q in QUESTIONS]):
        if answer is None:
            answer, sid = ask(q, prep.workdir, sid)
        hits = [w for w in watch if re.search(rf"\b{re.escape(w)}\b", answer, re.I)]
        # Repeating a word the reader just typed in their question isn't a leak.
        if q:
            hits = [w for w in hits if w.lower() not in q.lower()]
        flag = "LEAK? " + ", ".join(hits) if hits else "ok"
        failures += bool(hits)
        print(f"=== {label}  [{flag}]\n{answer.strip()}\n")
    print(f"{failures} answer(s) flagged")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
