"""Run the claude CLI headless, on the user's own Claude login.

We use `claude -p` rather than the API so the user's Claude subscription
pays for it (no API key). The session is locked down:
  --restricted        no shell or code-running tools; ignores user/project
                      settings, so the user's own hooks and plugins stay out
  --tools Read,Grep   it can only read and search ...
  cwd = a work dir    ... and file tools are confined to that directory,
                      which holds nothing but read-so-far.txt
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Iterable

from . import config
from .prompt import SYSTEM_PROMPT


@dataclass
class Event:
    kind: str  # "text" (partial answer so far), "tool", "done", "error"
    text: str = ""
    session_id: str = ""


def find_claude(cfg: dict | None = None) -> str | None:
    cfg = cfg or config.load()
    if cfg.get("claude_path"):
        return cfg["claude_path"]
    found = shutil.which("claude")
    if found:
        return found
    import os

    for p in ("~/.local/bin/claude", "~/.claude/local/claude", "~/.npm-global/bin/claude"):
        p = os.path.expanduser(p)
        if os.access(p, os.X_OK):
            return p
    return None


def command(claude: str, model: str, resume: str | None = None) -> list[str]:
    cmd = [
        claude, "-p",
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--restricted", "--tools", "Read,Grep", "--strict-mcp-config", "--disable-slash-commands",
        "--model", model,
        "--system-prompt", SYSTEM_PROMPT,
    ]
    if resume:
        cmd += ["--resume", resume]
    return cmd


def parse_stream(lines: Iterable[str]) -> Iterable[Event]:
    """Turn stream-json lines into Events. Text resets when a tool call starts,
    because what Claude writes before searching is narration, not the answer."""
    answer = ""
    session = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = d.get("type")
        session = d.get("session_id") or session
        if t == "stream_event":
            ev = d.get("event", {})
            et = ev.get("type")
            if et == "content_block_start":
                block = ev.get("content_block", {})
                if block.get("type") == "tool_use":
                    answer = ""
                    yield Event("tool", block.get("name", ""), session)
                elif block.get("type") == "text" and answer:
                    answer += "\n\n"
            elif et == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    answer += delta.get("text", "")
                    yield Event("text", answer, session)
        elif t == "result":
            if d.get("is_error") or d.get("subtype") not in (None, "success"):
                msg = d.get("result") or "; ".join(d.get("errors", []) or []) or d.get("subtype", "error")
                yield Event("error", str(msg), session)
            else:
                yield Event("done", d.get("result") or answer, session)
            return


def run(prompt: str, workdir: str, on_event: Callable[[Event], None], resume: str | None = None,
        proc_holder: list | None = None) -> None:
    cfg = config.load()
    claude = find_claude(cfg)
    if not claude:
        on_event(Event("error", "Couldn't find the `claude` command. Install Claude Code and sign in, "
                                "or set \"claude_path\" in ~/.config/clokular/config.json."))
        return
    proc = subprocess.Popen(
        command(claude, cfg["model"], resume), cwd=workdir, text=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1,
    )
    if proc_holder is not None:
        proc_holder.append(proc)
    proc.stdin.write(prompt)
    proc.stdin.close()
    finished = False
    for ev in parse_stream(proc.stdout):
        on_event(ev)
        if ev.kind in ("done", "error"):
            finished = True
    proc.wait()
    if not finished:
        err = proc.stderr.read().strip() if proc.stderr else ""
        if proc.returncode and proc.returncode < 0:
            return  # we killed it (window closed)
        on_event(Event("error", err.splitlines()[-1] if err else f"claude exited with code {proc.returncode}"))
