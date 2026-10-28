#!/usr/bin/env python3
"""Stop hook: Codex (or GitHub Copilot) acts as navigator and reviews what Claude (the driver) just wrote.

The navigator CLI is chosen with PAIR_NAVIGATOR: `codex` (default) or `copilot`.

Inactive unless `.pair/session.md` exists in the project (created by /pair).
Each review covers what changed since the last LGTM checkpoint (a git tree
snapshot of the working tree), so approved steps are not re-reviewed.

On CHANGES it blocks the stop and hands the review back to Claude. On LGTM it
lets Claude stop — or, in autopilot (`.pair/autopilot` exists), tells Claude to
continue with the next step until the driver ends a message with `PAIR: KLART`
(goal reached) or `PAIR: FRÅGA` (needs the user). Caps on review rounds per step
and steps per autopilot run keep the pair from looping forever.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_ROUNDS = int(os.environ.get("PAIR_MAX_ROUNDS", "3"))
MAX_STEPS = int(os.environ.get("PAIR_MAX_STEPS", "8"))
NAVIGATOR = os.environ.get("PAIR_NAVIGATOR", "codex").strip().lower()
CODEX_BIN = os.environ.get("PAIR_CODEX_BIN", "codex")
COPILOT_BIN = os.environ.get("PAIR_COPILOT_BIN", "copilot")
NAVIGATOR_NAMES = {"codex": "Codex", "copilot": "Copilot"}
NAVIGATOR_NAME = NAVIGATOR_NAMES.get(NAVIGATOR, NAVIGATOR)
MAX_DIFF_CHARS = 150_000
NAVIGATOR_TIMEOUT = 540  # keep below the hook timeout in settings.json (600)
HERE = Path(__file__).resolve().parent
SCHEMA_FILE = HERE / "navigator-schema.json"
MARKER = re.compile(r"PAIR:\s*(KLART|FRÅGA)\s*$", re.MULTILINE)
SCOPE = [
    "--", ".",
    ":(exclude).pair",
    ":(exclude).claude/hooks/codex-navigator.py",
    ":(exclude).claude/hooks/navigator-*",
    ":(exclude).claude/skills/pair",
]


def git(root, *args, env=None):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)


def snapshot_tree(root):
    """Write the working tree (tracked + untracked, minus ignored and the pair's own files)
    as a git tree object via a throwaway index, leaving the real index untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        has_head = git(root, "rev-parse", "--verify", "-q", "HEAD").returncode == 0
        git(root, "read-tree", "HEAD" if has_head else "--empty", env=env)
        git(root, "add", "-A", *SCOPE, env=env)
        return git(root, "write-tree", env=env).stdout.strip()


def base_tree(root, state):
    """Last LGTM checkpoint if it still exists, else HEAD (or the empty tree)."""
    lgtm = state.get("lgtm_tree")
    if lgtm and git(root, "cat-file", "-e", lgtm).returncode == 0:
        return lgtm
    if git(root, "rev-parse", "--verify", "-q", "HEAD").returncode == 0:
        return git(root, "rev-parse", "HEAD^{tree}").stdout.strip()
    return git(root, "hash-object", "-t", "tree", "/dev/null").stdout.strip()


def tree_diff(root, base, tree):
    diff = git(root, "diff", base, tree, *SCOPE).stdout
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


def driver_marker(msg):
    found = MARKER.findall(msg or "")
    return found[-1] if found else None


def format_comments(comments):
    return "\n".join(
        f"{i}. [{c['severity']}] {c['location']} — {c['comment']}" for i, c in enumerate(comments, 1)
    )


def run_codex(root, prompt):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "review.json"
        cmd = [
            CODEX_BIN, "exec",
            "--sandbox", "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C", str(root),
            "--output-schema", str(SCHEMA_FILE),
            "-o", str(out),
            "-",
        ]
        if os.environ.get("PAIR_CODEX_MODEL"):
            cmd[2:2] = ["-m", os.environ["PAIR_CODEX_MODEL"]]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=NAVIGATOR_TIMEOUT)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
        return json.loads(out.read_text(encoding="utf-8"))


COPILOT_OUTPUT = """
## Output format
Your final reply must be exactly one JSON object that matches this JSON Schema, with no code fences and no text before or after it:
```json
{schema}
```
"""


def run_copilot(root, prompt):
    """Copilot CLI has no output schema or read-only sandbox: the schema goes into the prompt,
    the reply is parsed and validated, and file writes, shell and network are denied."""
    with tempfile.TemporaryDirectory() as tmp:
        # The prompt goes in a file: the diff alone can exceed Linux's 128 KiB limit for one argv string
        brief = Path(tmp) / "navigator-brief.md"
        brief.write_text(prompt + COPILOT_OUTPUT.format(schema=SCHEMA_FILE.read_text(encoding="utf-8").strip()),
                         encoding="utf-8")
        cmd = [
            COPILOT_BIN,
            "-p", f"Read the file {brief} and follow its instructions exactly. Do not modify any files.",
            "-s", "--no-color",
            "--allow-all-tools",  # needed in non-interactive mode; the deny rules below take precedence
            "--deny-tool", "write",
            "--deny-tool", "shell",
            "--deny-tool", "url",
            "--disable-builtin-mcps",
            "--no-ask-user",
            "--add-dir", tmp,
            "-C", str(root),
        ]
        if os.environ.get("PAIR_COPILOT_MODEL"):
            cmd += ["--model", os.environ["PAIR_COPILOT_MODEL"]]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=NAVIGATOR_TIMEOUT,
                              stdin=subprocess.DEVNULL)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip()[-800:])
        return parse_review(proc.stdout)


def parse_review(text):
    """Pull the JSON object out of a free-text reply (tolerates code fences or stray prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in the navigator's reply: {text.strip()[:300]}")
    return json.loads(text[start:end + 1])


def validate_review(review):
    """Check the shape the rest of the hook relies on; Codex enforces it, Copilot does not."""
    severities = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))[
        "properties"]["comments"]["items"]["properties"]["severity"]["enum"]
    if not isinstance(review, dict) or not isinstance(review.get("summary"), str) \
            or not isinstance(review.get("comments"), list):
        raise ValueError("the navigator's reply lacks summary/comments")
    for c in review["comments"]:
        if not isinstance(c, dict) or c.get("severity") not in severities \
                or not all(isinstance(c.get(k), str) for k in ("location", "comment")):
            raise ValueError(f"malformed navigator comment: {json.dumps(c, ensure_ascii=False)[:300]}")
    return review


NAVIGATORS = {"codex": run_codex, "copilot": run_copilot}


def run_navigator(root, prompt):
    if NAVIGATOR not in NAVIGATORS:
        raise ValueError(f"unknown PAIR_NAVIGATOR {NAVIGATOR!r} (use: {', '.join(NAVIGATORS)})")
    return validate_review(NAVIGATORS[NAVIGATOR](root, prompt))


def log(pair_dir, heading, body):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(pair_dir / "log.md", "a", encoding="utf-8") as fh:
        fh.write(f"\n## {stamp} — {heading}\n\n{body.strip()}\n")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(0)


AUTOPILOT_CONTINUE = (
    "Autopilot: fortsätt med nästa steg mot målet. Håll steget fokuserat och avsluta med vad du "
    "gjorde och varför. När hela målet är nått och verifierat: avsluta meddelandet med raden "
    "`PAIR: KLART`. Behöver du ett beslut av användaren: ställ frågan och avsluta med `PAIR: FRÅGA`."
)


def main():
    inp = json.load(sys.stdin)
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or inp.get("cwd") or ".")
    pair_dir = root / ".pair"
    session = pair_dir / "session.md"
    if not session.exists():
        sys.exit(0)
    autopilot = (pair_dir / "autopilot").exists()

    state_file = pair_dir / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    continuing = bool(inp.get("stop_hook_active"))
    if not continuing:
        # a fresh user turn starts a fresh review cycle and a fresh autopilot run
        state["rounds"] = 0
        state["steps"] = 0

    def save():
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    driver_msg = last_driver_message(inp)
    marker = driver_marker(driver_msg)
    tree = snapshot_tree(root)
    diff = tree_diff(root, base_tree(root, state), tree)

    if not diff.strip() or tree == state.get("last_tree"):
        # Nothing new to review since the last review (or since the last LGTM)
        if continuing and state.get("last_verdict") == "CHANGES":
            log(pair_dir, "Föraren invände utan att ändra koden", driver_msg)
            state["last_verdict"] = "DISPUTED"
            save()
            emit({"systemMessage": "🧭 Föraren (Claude) höll inte med navigatören och lät koden stå kvar — du får avgöra. Se .pair/log.md."})
        save()
        if autopilot and continuing:
            if marker == "KLART":
                log(pair_dir, "Autopilot: föraren anser målet nått", driver_msg)
                emit({"systemMessage": "🧭 Autopilot klar — föraren anser målet nått och navigatören har godkänt allt."})
            if marker is None:
                log(pair_dir, "Autopilot pausad: föraren stannade utan ny kod", driver_msg)
                emit({"systemMessage": "🧭 Autopilot pausad — föraren stannade utan ny kod och utan att säga klart. Se .pair/log.md."})
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
        review = run_navigator(root, prompt)
    except Exception as exc:  # a broken navigator must never trap the driver
        log(pair_dir, "Navigatören kunde inte köras", str(exc))
        emit({"systemMessage": f"🧭 {NAVIGATOR_NAME}-granskningen misslyckades och hoppades över: {str(exc)[:300]}"})

    comments = review.get("comments", [])
    # Decide the verdict from severities rather than trusting the model's own label
    must_fix = [c for c in comments if c["severity"] in ("blocker", "major")]
    verdict = "CHANGES" if must_fix else "LGTM"
    state["rounds"] = state.get("rounds", 0) + 1
    summary = review.get("summary", "").strip()
    rendered = f"{summary}\n\n{format_comments(comments)}".strip()

    log(pair_dir, "Föraren", driver_msg or "(inget meddelande)")
    log(pair_dir, f"Navigatören, runda {state['rounds']} — {verdict}", rendered)
    state.update(last_tree=tree, last_verdict=verdict, last_review=rendered)

    if verdict == "CHANGES":
        save()
        emit({
            "decision": "block",
            "reason": (
                f"🧭 Navigatören ({NAVIGATOR_NAME}), runda {state['rounds']}/{MAX_ROUNDS}:\n\n{rendered}\n\n"
                "Som förare: ta ställning till varje punkt. Åtgärda den, eller invänd med ett konkret skäl "
                "om du tror att navigatören har fel — lyd inte blint och avfärda inte lättvindigt. "
                "Avsluta med en kort lista: punktnummer → fixat / invänder (varför)."
            ),
        })

    # LGTM: this state becomes the new checkpoint, and the next step starts fresh
    state.update(lgtm_tree=tree, rounds=0, steps=state.get("steps", 0) + 1)
    save()
    notes = f"\n{format_comments(comments)}" if comments else ""

    if not autopilot:
        emit({"systemMessage": f"🧭 Navigator: LGTM — {summary}{notes}"})
    if marker == "KLART":
        emit({"systemMessage": f"🧭 Autopilot klar efter {state['steps']} steg — navigatören: LGTM. {summary}{notes}"})
    if marker == "FRÅGA":
        emit({"systemMessage": f"🧭 Autopilot pausad: föraren har en fråga till dig. Navigatören: LGTM. {summary}"})
    if state["steps"] >= MAX_STEPS:
        log(pair_dir, f"Autopilot: taket på {MAX_STEPS} steg nått", "")
        emit({"systemMessage": f"🧭 Autopilot pausad efter {MAX_STEPS} godkända steg — säg till om paret ska fortsätta."})
    emit({
        "decision": "block",
        "reason": f"🧭 Navigatören ({NAVIGATOR_NAME}): LGTM, steg {state['steps']}/{MAX_STEPS}. {summary}{notes}\n\n{AUTOPILOT_CONTINUE}",
    })


if __name__ == "__main__":
    main()
