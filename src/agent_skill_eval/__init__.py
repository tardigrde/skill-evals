"""Skill evaluation framework."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-skill-eval")
except PackageNotFoundError:
    # Not installed (e.g. running from a source checkout): version is unknown.
    # pyproject.toml is the single source of truth for the real version.
    __version__ = "0.0.0"
