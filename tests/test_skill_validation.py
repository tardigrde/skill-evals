from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"
REQUIRED_FIELDS = {"name", "description", "license", "compatibility"}
VALID_AGENTS = {"opencode", "claude-code", "codex"}


def get_skill_dirs() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    return [d for d in SKILLS_DIR.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]


@pytest.fixture(params=get_skill_dirs(), ids=lambda p: p.name)
def skill_dir(request):
    return request.param


class TestSkillFrontmatter:
    def test_skill_md_exists(self, skill_dir):
        assert (skill_dir / "SKILL.md").exists()

    def test_has_frontmatter(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"

    def test_frontmatter_parses(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing ---"
        frontmatter = yaml.safe_load(parts[1])
        assert isinstance(frontmatter, dict)

    def test_has_required_fields(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        frontmatter = yaml.safe_load(parts[1])
        missing = REQUIRED_FIELDS - set(frontmatter.keys())
        assert not missing, f"Missing required fields: {missing}"

    def test_name_matches_directory(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        frontmatter = yaml.safe_load(parts[1])
        assert frontmatter["name"] == skill_dir.name, (
            f"Frontmatter name '{frontmatter['name']}' must match directory name '{skill_dir.name}'"
        )

    def test_compatibility_valid(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        frontmatter = yaml.safe_load(parts[1])
        compat = frontmatter.get("compatibility", "")
        if isinstance(compat, str):
            agents = {a.strip() for a in compat.split(",")}
        else:
            agents = set(compat)
        invalid = agents - VALID_AGENTS
        assert not invalid, f"Invalid agent(s) in compatibility: {invalid}"

    def test_description_not_empty(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        frontmatter = yaml.safe_load(parts[1])
        assert frontmatter.get("description", "").strip(), "Description must not be empty"

    def test_has_body_content(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        parts = content.split("---", 2)
        body = parts[2].strip() if len(parts) > 2 else ""
        assert body, "SKILL.md must have content after frontmatter"
