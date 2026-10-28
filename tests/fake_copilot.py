#!/usr/bin/env python3
"""Stand-in for `copilot -p`: prints FAKE_REVIEW as the reply, saves the brief file to FAKE_PROMPT_OUT and argv to FAKE_ARGS_OUT."""
import json
import os
import re
import sys

args = sys.argv[1:]
if os.environ.get("FAKE_FAIL"):
    print("simulated copilot failure", file=sys.stderr)
    sys.exit(1)
brief = re.search(r"Read the file (\S+)", args[args.index("-p") + 1]).group(1)
with open(brief, encoding="utf-8") as src, open(os.environ["FAKE_PROMPT_OUT"], "w", encoding="utf-8") as dst:
    dst.write(src.read())
if os.environ.get("FAKE_ARGS_OUT"):
    with open(os.environ["FAKE_ARGS_OUT"], "w", encoding="utf-8") as fh:
        json.dump(args, fh)
print(os.environ.get("FAKE_REPLY") or os.environ["FAKE_REVIEW"])
