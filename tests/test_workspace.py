from __future__ import annotations

import subprocess

import pytest

from skill_eval.workspace import WorkspaceManager


@pytest.fixture
def manager(tmp_path):
    return WorkspaceManager(base_dir=tmp_path)


class TestCreateWorkspace:
    def test_creates_directory(self, manager, tmp_path):
        ws = manager.create_workspace("test-ws")
        assert ws.exists()
        assert ws.is_dir()

    def test_initializes_git_repo(self, manager):
        ws = manager.create_workspace("test-ws")
        assert (ws / ".git").exists()

    def test_creates_initial_commit(self, manager):
        ws = manager.create_workspace("test-ws")
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=ws,
            capture_output=True,
            text=True,
        )
        assert "Initial commit" in result.stdout

    def test_copies_fixture_files(self, manager, tmp_path):
        fixture = tmp_path / "fixture.txt"
        fixture.write_text("test content")
        ws = manager.create_workspace("test-ws", {"fixture.txt": fixture})
        assert (ws / "fixture.txt").exists()
        assert (ws / "fixture.txt").read_text() == "test content"

    def test_replaces_existing_workspace(self, manager):
        ws1 = manager.create_workspace("test-ws")
        (ws1 / "marker.txt").write_text("old")
        ws2 = manager.create_workspace("test-ws")
        assert not (ws2 / "marker.txt").exists()

    def test_tracks_workspaces(self, manager):
        ws = manager.create_workspace("test-ws")
        assert ws in manager.workspaces


class TestCleanup:
    def test_removes_workspace_directory(self, manager):
        ws = manager.create_workspace("test-ws")
        assert ws.exists()
        manager.cleanup(ws)
        assert not ws.exists()

    def test_removes_from_tracking(self, manager):
        ws = manager.create_workspace("test-ws")
        manager.cleanup(ws)
        assert ws not in manager.workspaces

    def test_cleanup_all(self, manager):
        ws1 = manager.create_workspace("test-ws-1")
        ws2 = manager.create_workspace("test-ws-2")
        manager.cleanup_all()
        assert not ws1.exists()
        assert not ws2.exists()
        assert len(manager.workspaces) == 0
