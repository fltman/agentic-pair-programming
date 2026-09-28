"""Tests for the navigator Stop hook, using a fake codex. Run: python3 -m unittest discover tests"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / ".claude" / "hooks" / "codex-navigator.py"
FAKE = Path(__file__).resolve().parent / "fake_codex.py"

LGTM = {"verdict": "LGTM", "summary": "Ser bra ut.", "comments": []}
CHANGES = {
    "verdict": "CHANGES",
    "summary": "Fel vid jämnt antal.",
    "comments": [{"severity": "major", "location": "stats.py:3", "comment": "fel median"}],
}


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        (self.root / "stats.py").write_text("def mean(xs):\n    return sum(xs) / len(xs)\n")
        self.git("add", ".")
        self.git("commit", "-qm", "init")
        self.prompt_file = self.root.parent / f"{self.root.name}-prompt.txt"

    def tearDown(self):
        self.tmp.cleanup()
        self.prompt_file.unlink(missing_ok=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def start(self, goal="Lägg till median", autopilot=False):
        pair = self.root / ".pair"
        pair.mkdir(exist_ok=True)
        (pair / ".gitignore").write_text("*\n")
        (pair / "session.md").write_text(goal)
        if autopilot:
            (pair / "autopilot").touch()

    def write(self, name, text):
        (self.root / name).write_text(text)

    def run_hook(self, review=LGTM, continuing=False, message="", fail=False, **env):
        self.prompt_file.unlink(missing_ok=True)
        environ = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(self.root),
            "PAIR_CODEX_BIN": str(FAKE),
            "FAKE_REVIEW": json.dumps(review),
            "FAKE_PROMPT_OUT": str(self.prompt_file),
            **env,
        }
        if fail:
            environ["FAKE_FAIL"] = "1"
        payload = json.dumps({"stop_hook_active": continuing, "last_assistant_message": message})
        proc = subprocess.run(["python3", str(HOOK)], input=payload, capture_output=True, text=True, env=environ)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def reviewed(self):
        return self.prompt_file.exists()

    def prompt(self):
        return self.prompt_file.read_text()

    def state(self):
        return json.loads((self.root / ".pair" / "state.json").read_text())

    # --- basic pairing ---

    def test_inactive_without_session(self):
        self.write("stats.py", "changed\n")
        self.assertIsNone(self.run_hook())
        self.assertFalse(self.reviewed())

    def test_no_changes_means_no_review(self):
        self.start()
        self.assertIsNone(self.run_hook())
        self.assertFalse(self.reviewed())

    def test_changes_block_then_fix_gives_lgtm(self):
        self.start()
        self.write("stats.py", "bug\n")
        out = self.run_hook(CHANGES)
        self.assertEqual(out["decision"], "block")
        self.assertIn("fel median", out["reason"])
        self.write("stats.py", "fixed\n")
        out = self.run_hook(LGTM, continuing=True)
        self.assertIn("LGTM", out["systemMessage"])
        self.assertNotIn("decision", out)

    def test_verdict_comes_from_severity_not_label(self):
        self.start()
        self.write("stats.py", "bug\n")
        out = self.run_hook({**CHANGES, "verdict": "LGTM"})
        self.assertEqual(out["decision"], "block")

    def test_untracked_files_are_reviewed_and_real_index_untouched(self):
        self.start()
        self.write("new.py", "print('hej')\n")
        self.run_hook()
        self.assertIn("new.py", self.prompt())
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertIn("?? new.py", self.git("status", "--short"))

    def test_pair_files_are_not_reviewed(self):
        self.start()
        self.write("stats.py", "changed\n")
        self.run_hook()
        self.assertNotIn("session.md", self.prompt())

    def test_dispute_without_code_change_releases_to_user(self):
        self.start()
        self.write("stats.py", "bug\n")
        self.run_hook(CHANGES)
        out = self.run_hook(CHANGES, continuing=True, message="1 → invänder")
        self.assertFalse(self.reviewed())
        self.assertIn("höll inte med", out["systemMessage"])
        self.assertEqual(self.state()["last_verdict"], "DISPUTED")

    def test_max_rounds(self):
        self.start()
        for i in range(3):
            self.write("stats.py", f"bug {i}\n")
            self.assertEqual(self.run_hook(CHANGES, continuing=i > 0)["decision"], "block")
        self.write("stats.py", "bug 3\n")
        out = self.run_hook(CHANGES, continuing=True)
        self.assertFalse(self.reviewed())
        self.assertIn("3 rundor", out["systemMessage"])

    def test_codex_failure_never_traps_driver(self):
        self.start()
        self.write("stats.py", "changed\n")
        out = self.run_hook(fail=True)
        self.assertIn("misslyckades", out["systemMessage"])

    def test_repo_without_commits(self):
        subprocess.run(["rm", "-rf", str(self.root / ".git")], check=True)
        self.git("init", "-q")
        self.start()
        out = self.run_hook()
        self.assertIn("stats.py", self.prompt())
        self.assertIn("LGTM", out["systemMessage"])

    # --- checkpoints ---

    def test_review_is_incremental_after_lgtm(self):
        self.start()
        self.write("stats.py", "step one\n")
        self.run_hook(LGTM)
        self.write("other.py", "step two\n")
        self.run_hook(LGTM)
        self.assertIn("step two", self.prompt())
        self.assertNotIn("step one", self.prompt())

    def test_changes_step_keeps_whole_step_in_diff(self):
        self.start()
        self.write("stats.py", "step one\n")
        self.run_hook(CHANGES)
        self.write("other.py", "the fix\n")
        self.run_hook(LGTM, continuing=True)
        self.assertIn("step one", self.prompt())
        self.assertIn("the fix", self.prompt())

    # --- autopilot ---

    def test_autopilot_continues_after_lgtm(self):
        self.start(autopilot=True)
        self.write("stats.py", "step one\n")
        out = self.run_hook(LGTM)
        self.assertEqual(out["decision"], "block")
        self.assertIn("PAIR: KLART", out["reason"])
        self.assertIn("steg 1/", out["reason"])

    def test_autopilot_stops_when_driver_says_done(self):
        self.start(autopilot=True)
        self.write("stats.py", "last step\n")
        out = self.run_hook(LGTM, continuing=True, message="Allt klart.\nPAIR: KLART")
        self.assertIn("Autopilot klar", out["systemMessage"])

    def test_done_marker_does_not_override_changes(self):
        self.start(autopilot=True)
        self.write("stats.py", "bug\n")
        out = self.run_hook(CHANGES, continuing=True, message="PAIR: KLART")
        self.assertEqual(out["decision"], "block")

    def test_autopilot_question_hands_back_to_user(self):
        self.start(autopilot=True)
        self.write("stats.py", "step\n")
        out = self.run_hook(LGTM, continuing=True, message="Postgres eller SQLite?\nPAIR: FRÅGA")
        self.assertIn("fråga", out["systemMessage"])

    def test_autopilot_done_without_new_code(self):
        self.start(autopilot=True)
        self.write("stats.py", "step\n")
        self.run_hook(LGTM)
        out = self.run_hook(LGTM, continuing=True, message="Verifierat.\nPAIR: KLART")
        self.assertFalse(self.reviewed())
        self.assertIn("Autopilot klar", out["systemMessage"])

    def test_autopilot_pauses_when_driver_stalls(self):
        self.start(autopilot=True)
        self.write("stats.py", "step\n")
        self.run_hook(LGTM)
        out = self.run_hook(LGTM, continuing=True, message="Hmm.")
        self.assertIn("pausad", out["systemMessage"])

    def test_autopilot_step_cap(self):
        self.start(autopilot=True)
        for i in range(2):
            self.write("stats.py", f"step {i}\n")
            out = self.run_hook(LGTM, continuing=i > 0, PAIR_MAX_STEPS="2")
        self.assertIn("2 godkända steg", out["systemMessage"])

    def test_fresh_user_turn_resets_step_count(self):
        self.start(autopilot=True)
        self.write("stats.py", "step 0\n")
        self.run_hook(LGTM, PAIR_MAX_STEPS="2")
        self.write("stats.py", "step 1\n")
        out = self.run_hook(LGTM, continuing=False, PAIR_MAX_STEPS="2")
        self.assertEqual(out["decision"], "block")


if __name__ == "__main__":
    unittest.main()
