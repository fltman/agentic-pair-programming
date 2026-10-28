#!/usr/bin/env bash
# Installera navigatören (Codex eller Copilot) i ett projekt: ./install.sh /sökväg/till/projekt
set -euo pipefail

src="$(cd "$(dirname "$0")" && pwd)/.claude"
target="${1:?Användning: ./install.sh <projektkatalog>}"
target="$(cd "$target" && pwd)"

mkdir -p "$target/.claude/hooks" "$target/.claude/skills/pair"
cp "$src/hooks/codex-navigator.py" "$src/hooks/navigator-prompt.md" "$src/hooks/navigator-schema.json" "$target/.claude/hooks/"
chmod +x "$target/.claude/hooks/codex-navigator.py"
cp "$src/skills/pair/SKILL.md" "$target/.claude/skills/pair/"

# Lägg till Stop-hooken i settings.json utan att röra övriga inställningar (idempotent)
python3 - "$target/.claude/settings.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
settings = json.loads(path.read_text()) if path.exists() else {}
command = 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/codex-navigator.py"'
stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
if not any(h.get("command") == command for group in stop for h in group.get("hooks", [])):
    stop.append({"hooks": [{"type": "command", "command": command, "timeout": 600}]})
path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
PY

echo "Installerat i $target. Starta om Claude Code där och kör: /pair <mål>"
