"""Skill evaluation framework."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-skill-eval")
except PackageNotFoundError:
    __version__ = "0.4.0"
