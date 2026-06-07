from __future__ import annotations

import shutil
from pathlib import Path

from skill_eval.models import AgentType

SKILL_PATHS = {
    AgentType.OPENCODE: [".opencode/skills"],
    AgentType.CLAUDE_CODE: [".claude/skills"],
    AgentType.CODEX: [".codex/skills"],
}


class SkillInstaller:
    def __init__(self, skill_path: Path):
        self.skill_path = skill_path
        self.skill_name = skill_path.name
        self.skill_md = skill_path / "SKILL.md"
        if not self.skill_md.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_path}")

    def install(self, workspace: Path, agent_type: AgentType) -> Path:
        target_dirs = SKILL_PATHS[agent_type]
        installed_to = None

        for target_dir in target_dirs:
            dest_base = workspace / target_dir / self.skill_name
            dest_base.mkdir(parents=True, exist_ok=True)

            shutil.copy2(self.skill_md, dest_base / "SKILL.md")

            for item in self.skill_path.iterdir():
                if item.name == "SKILL.md":
                    continue
                if item.is_file():
                    shutil.copy2(item, dest_base / item.name)
                elif item.is_dir() and item.name not in ("evals", "__pycache__", ".git"):
                    shutil.copytree(item, dest_base / item.name, dirs_exist_ok=True)

            installed_to = dest_base

        if installed_to is None:
            raise ValueError(f"No skill paths configured for {agent_type}")

        return installed_to

    def uninstall(self, workspace: Path, agent_type: AgentType) -> None:
        for target_dir in SKILL_PATHS[agent_type]:
            dest_base = workspace / target_dir / self.skill_name
            if dest_base.exists():
                shutil.rmtree(dest_base)

            parent = dest_base.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
