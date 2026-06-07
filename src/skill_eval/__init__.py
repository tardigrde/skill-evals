"""Skill evaluation framework."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("skill-eval")
except PackageNotFoundError:
    __version__ = "0.1.0"
