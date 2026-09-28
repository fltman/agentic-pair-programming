#!/usr/bin/env python3
"""Stop hook: Codex acts as navigator and reviews what Claude (the driver) just wrote.

Inactive unless `.pair/session.md` exists in the project (created by /pair).
On CHANGES it blocks the stop and hands the review back to Claude; on LGTM,
after MAX_ROUNDS, or when the driver disputes without changing code, it lets
Claude stop and tells the user why.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_ROUNDS = int(os.environ.get("PAIR_MAX_ROUNDS", "3"))
MAX_DIFF_CHARS = 150_000
CODEX_TIMEOUT = 540  # keep below the hook timeout in settings.json (600)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HERE = Path(__file__).resolve().parent


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def collect_diff(root):
    """Uncommitted changes (staged, unstaged and untracked) under root, minus the pair's own files."""
    base = "HEAD" if git(root, "rev-parse", "--verify", "-q", "HEAD").returncode == 0 else EMPTY_TREE
    scope = [
        "--", ".",
        ":(exclude).pair",
        ":(exclude).claude/hooks/codex-navigator.py",
        ":(exclude).claude/hooks/navigator-*",
        ":(exclude).claude/skills/pair",
    ]
    parts = [git(root, "diff", base, *scope).stdout]
    untracked = git(root, "ls-files", "--others", "--exclude-standard", *scope).stdout.splitlines()
    for f in untracked:
        # --no-index exits 1 when files differ, which is the normal case here
        parts.append(git(root, "diff", "--no-index", "--", "/dev/null", f).stdout)
    diff = "".join(parts)
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n[... diff truncated — read the files directly for the rest ...]\n"
    return diff


def last_driver_message(inp):
    if inp.get("last_assistant_message"):
        return inp["last_assistant_message"]
    path = inp.get("transcript_path")
    if not path or not os.path.exists(path):
        return ""
    last = ""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            content = entry.get("message", {}).get("content", [])
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            if any(t.strip() for t in texts):
                last = "\n".join(texts)
    return last


def format_comments(comments):
    return "\n".join(
        f"{i}. [{c['severity']}] {c['location']} — {c['comment']}" for i, c in enumerate(comments, 1)
    )


def run_codex(root, prompt):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "review.json"
        cmd = [
            "codex", "exec",
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C", str(root),
            "--output-schema", str(HERE / "navigator-schema.json"),
            "-o", str(out),
            "-",
        ]
        if os.environ.get("PAIR_CODEX_MODEL"):
            cmd[2:2] = ["-m", os.environ["PAIR_CODEX_MODEL"]]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=CODEX_TIMEOUT)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
        return json.loads(out.read_text(encoding="utf-8"))


def log(pair_dir, heading, body):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(pair_dir / "log.md", "a", encoding="utf-8") as fh:
        fh.write(f"\n## {stamp} — {heading}\n\n{body.strip()}\n")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


def main():
    inp = json.load(sys.stdin)
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or inp.get("cwd") or ".")
    pair_dir = root / ".pair"
    session = pair_dir / "session.md"
    if not session.exists():
        sys.exit(0)

    state_file = pair_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    continuing = bool(inp.get("stop_hook_active"))
    if not continuing:
        state["rounds"] = 0  # a fresh user turn starts a fresh review cycle

    def save():
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    diff = collect_diff(root)
    if not diff.strip():
        save()
        sys.exit(0)

    driver_msg = last_driver_message(inp)
    digest = hashlib.sha256(diff.encode()).hexdigest()
    if digest == state.get("last_hash"):
        if continuing and state.get("last_verdict") == "CHANGES":
            log(pair_dir, "Föraren invände utan att ändra koden", driver_msg)
            state["last_verdict"] = "DISPUTED"
            save()
            emit({"systemMessage": "🧭 Föraren (Claude) höll inte med navigatören och lät koden stå kvar — du får avgöra. Se .pair/log.md."})
        save()
        sys.exit(0)

    if state.get("rounds", 0) >= MAX_ROUNDS:
        log(pair_dir, f"Taket på {MAX_ROUNDS} rundor nått", driver_msg)
        state["rounds"] = 0
        save()
        emit({"systemMessage": f"🧭 Navigatören har gått {MAX_ROUNDS} rundor utan att bli nöjd — ta en titt själv. Se .pair/log.md."})

    prompt = (
        (HERE / "navigator-prompt.md").read_text(encoding="utf-8")
        .replace("{{GOAL}}", session.read_text(encoding="utf-8").strip())
        .replace("{{PREVIOUS_REVIEW}}", state.get("last_review", "") or "(none)")
        .replace("{{DRIVER_MESSAGE}}", driver_msg or "(none)")
        .replace("{{DIFF}}", diff)
    )
    try:
        review = run_codex(root, prompt)
    except Exception as exc:  # a broken navigator must never trap the driver
        log(pair_dir, "Navigatören kunde inte köras", str(exc))
        emit({"systemMessage": f"🧭 Codex-granskningen misslyckades och hoppades över: {str(exc)[:300]}"})

    comments = review.get("comments", [])
    # Decide the verdict from severities rather than trusting the model's own label
    must_fix = [c for c in comments if c["severity"] in ("blocker", "major")]
    verdict = "CHANGES" if must_fix else "LGTM"
    state["rounds"] = state.get("rounds", 0) + 1
    rendered = f"{review.get('summary', '').strip()}\n\n{format_comments(comments)}".strip()

    log(pair_dir, "Föraren", driver_msg or "(inget meddelande)")
    log(pair_dir, f"Navigatören, runda {state['rounds']} — {verdict}", rendered)
    state.update(last_hash=digest, last_verdict=verdict, last_review=rendered)
    save()

    if verdict == "LGTM":
        notes = f"\n{format_comments(comments)}" if comments else ""
        emit({"systemMessage": f"🧭 Navigator: LGTM — {review.get('summary', '').strip()}{notes}"})

    emit({
        "decision": "block",
        "reason": (
            f"🧭 Navigatören (Codex), runda {state['rounds']}/{MAX_ROUNDS}:\n\n{rendered}\n\n"
            "Som förare: ta ställning till varje punkt. Åtgärda den, eller invänd med ett konkret skäl "
            "om du tror att navigatören har fel — lyd inte blint och avfärda inte lättvindigt. "
            "Avsluta med en kort lista: punktnummer → fixat / invänder (varför)."
        ),
    })


if __name__ == "__main__":
    main()
