#!/usr/bin/env python3
"""Stand-in for `codex exec`: writes FAKE_REVIEW (JSON) to the -o file and saves the prompt to FAKE_PROMPT_OUT."""
import os
import sys

args = sys.argv[1:]
if os.environ.get("FAKE_FAIL"):
    print("simulated codex failure", file=sys.stderr)
    sys.exit(1)
with open(os.environ["FAKE_PROMPT_OUT"], "w", encoding="utf-8") as fh:
    fh.write(sys.stdin.read())
with open(args[args.index("-o") + 1], "w", encoding="utf-8") as fh:
    fh.write(os.environ["FAKE_REVIEW"])
