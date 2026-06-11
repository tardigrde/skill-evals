from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from rich.console import Console

console = Console()


class WorkspaceManager:
    def __init__(self, base_dir: Path | None = None, source_repo: str | None = None):
        self.base_dir = base_dir or Path(tempfile.gettempdir())
        self.source_repo = source_repo
        self.workspaces: list[Path] = []

    def create_workspace(self, name: str, fixture_files: dict[str, Path] | None = None) -> Path:
        workspace = self.base_dir / f"agent-skill-eval-{name}"
        if workspace.exists():
            shutil.rmtree(workspace)

        if self.source_repo:
            self._clone_repo(workspace)
        else:
            workspace.mkdir(parents=True, exist_ok=True)
            self._init_git_repo(workspace)

        if fixture_files:
            for rel_path, src_path in fixture_files.items():
                dest = workspace / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src_path.is_dir():
                    shutil.copytree(src_path, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_path, dest)

        self.workspaces.append(workspace)
        return workspace

    def _clone_repo(self, workspace: Path) -> None:
        subprocess.run(
            ["git", "clone", self.source_repo, str(workspace)],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "eval@agent-skill-eval.local"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Skill Eval"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )

    def _init_git_repo(self, workspace: Path) -> None:
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "eval@agent-skill-eval.local"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Skill Eval"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial commit", "--allow-empty"],
            cwd=workspace,
            capture_output=True,
            check=True,
        )

    def cleanup(self, workspace: Path) -> None:
        if workspace.exists():
            shutil.rmtree(workspace)
        if workspace in self.workspaces:
            self.workspaces.remove(workspace)

    def cleanup_all(self) -> None:
        for ws in self.workspaces[:]:
            self.cleanup(ws)
