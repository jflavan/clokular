"""clokular command line.

  clokular clokular:<text>     what Okular's menu runs: open the answer window
  clokular ask "<text>"        same, from a terminal
  clokular check               check that everything clokular needs is present
  clokular install|uninstall   add/remove the "Claude" entry in Okular
  clokular status              show what's installed and what Okular reports
  clokular index FILE OUT      internal: extract a book's text (offscreen Qt)
  clokular dry-run "<text>"    print what Claude would be sent, without asking it
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd != "index":
        from . import log

        log.write(f"start: {cmd[:120]!r} ({len(' '.join(argv))} chars)")
    if cmd.lower().startswith("clokular:"):
        from .urls import selection_from_url

        try:
            text = selection_from_url(cmd)
        except ValueError as e:
            from .window import show_error

            return show_error(str(e))
        from .window import show

        return show(text)
    if cmd == "ask" and len(argv) > 1:
        from .window import show

        return show(" ".join(argv[1:]))
    if cmd == "index" and len(argv) == 3:
        from .book import index_to_file

        index_to_file(argv[1], argv[2])
        return 0
    if cmd == "dry-run" and len(argv) > 1:
        from .session import prepare

        p = prepare(" ".join(argv[1:]))
        print(f"workdir: {p.workdir}\ntitle: {p.title}\npage: {p.page}/{p.pages}\nlocated: {p.located}")
        for w in p.warnings:
            print("warning:", w)
        print("\n--- prompt ---\n" + p.prompt)
        return 0
    if cmd in ("check", "install", "uninstall", "status"):
        from . import install

        return getattr(install, cmd)()
    print(f"unknown command: {cmd}\n\n{__doc__.strip()}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
