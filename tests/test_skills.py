from __future__ import annotations

import pytest

from skill_eval.models import AgentType
from skill_eval.skills import SkillInstaller


@pytest.fixture
def skill_dir(tmp_path):
    skill = tmp_path / "my-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Test skill\nlicense: MIT\ncompatibility: opencode\n---\n\n# My Skill\n"
    )
    (skill / "helper.py").write_text("print('helper')")
    return skill


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


class TestSkillInstaller:
    def test_init_reads_skill_name(self, skill_dir):
        installer = SkillInstaller(skill_dir)
        assert installer.skill_name == "my-skill"

    def test_init_raises_if_no_skill_md(self, tmp_path):
        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            SkillInstaller(empty_dir)


class TestInstall:
    def test_installs_to_opencode(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        result = installer.install(workspace, AgentType.OPENCODE)
        assert result == workspace / ".opencode" / "skills" / "my-skill"
        assert (workspace / ".opencode" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_installs_to_claude_code(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        result = installer.install(workspace, AgentType.CLAUDE_CODE)
        assert result == workspace / ".claude" / "skills" / "my-skill"
        assert (workspace / ".claude" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_installs_to_codex(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        result = installer.install(workspace, AgentType.CODEX)
        assert result == workspace / ".codex" / "skills" / "my-skill"
        assert (workspace / ".codex" / "skills" / "my-skill" / "SKILL.md").exists()

    def test_copies_extra_files(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        installer.install(workspace, AgentType.OPENCODE)
        assert (workspace / ".opencode" / "skills" / "my-skill" / "helper.py").exists()

    def test_skips_evals_dir(self, skill_dir, workspace):
        (skill_dir / "evals").mkdir()
        (skill_dir / "evals" / "evals.json").write_text("{}")
        installer = SkillInstaller(skill_dir)
        installer.install(workspace, AgentType.OPENCODE)
        assert not (workspace / ".opencode" / "skills" / "my-skill" / "evals").exists()


class TestUninstall:
    def test_removes_installed_skill(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        installer.install(workspace, AgentType.OPENCODE)
        assert (workspace / ".opencode" / "skills" / "my-skill").exists()
        installer.uninstall(workspace, AgentType.OPENCODE)
        assert not (workspace / ".opencode" / "skills" / "my-skill").exists()

    def test_no_error_if_not_installed(self, skill_dir, workspace):
        installer = SkillInstaller(skill_dir)
        installer.uninstall(workspace, AgentType.OPENCODE)
