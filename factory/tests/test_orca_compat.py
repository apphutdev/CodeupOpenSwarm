import subprocess
import tempfile
import unittest
from pathlib import Path

from factory.orca_compat.server import FactoryService, tool_definitions


class FactoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "factory@example.invalid"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Factory Test"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.repo, check=True, capture_output=True)
        self.service = FactoryService(self.root / "state")

    def tearDown(self):
        self.temp.cleanup()

    def test_contract_exposes_required_tools(self):
        names = {tool["name"] for tool in tool_definitions()}
        self.assertEqual({"orca_create_run", "orca_create_pod", "orca_list_runs", "orca_stage", "orca_review", "orca_ship"}, names)

    def test_run_creates_isolated_worktree_and_persists(self):
        created = self.service.create_run("change text", str(self.repo), "worker-a")
        self.assertTrue(Path(created["worktree"]).is_dir())
        self.assertTrue(created["branch"].startswith("agent/run_"))
        self.assertEqual(created["id"], self.service.list_runs()["runs"][0]["id"])

    def test_same_actor_cannot_review_and_failed_gates_do_not_stage(self):
        created = self.service.create_run("change text", str(self.repo), "worker-a")
        with self.assertRaises(RuntimeError):
            self.service.stage(created["id"], {}, "change")
        created["status"] = "ready"
        self.service.store.save("run", created)
        with self.assertRaises(RuntimeError):
            self.service.review(created["id"], "worker-a", "PASS")


if __name__ == "__main__":
    unittest.main()
