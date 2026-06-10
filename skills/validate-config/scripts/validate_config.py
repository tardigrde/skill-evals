#!/usr/bin/env python3
"""Structural validator for team service configs.

Checks required keys and value types only. Convention rules (naming,
ranges, allowed values) live in references/config-rules.md and are
checked by the agent, not by this script.

Usage: python validate_config.py <config.json>
Prints one "STRUCTURAL: ..." line per problem, or "STRUCTURAL: OK".
Exit code 0 if structure is valid, 1 otherwise.
"""

import json
import sys
from pathlib import Path

REQUIRED_KEYS = {
    "service_name": str,
    "port": int,
    "log_level": str,
    "max_retries": int,
    "environment": str,
}


def validate(config_path: Path) -> list[str]:
    problems: list[str] = []
    try:
        data = json.loads(config_path.read_text())
    except FileNotFoundError:
        return [f"STRUCTURAL: config file not found: {config_path}"]
    except json.JSONDecodeError as e:
        return [f"STRUCTURAL: config is not valid JSON: {e}"]

    if not isinstance(data, dict):
        return ["STRUCTURAL: top-level value must be a JSON object"]

    for key, expected_type in REQUIRED_KEYS.items():
        if key not in data:
            problems.append(f"STRUCTURAL: missing required key '{key}'")
        elif not isinstance(data[key], expected_type):
            problems.append(
                f"STRUCTURAL: key '{key}' must be {expected_type.__name__}, "
                f"got {type(data[key]).__name__}"
            )

    features = data.get("features")
    if features is not None and not isinstance(features, dict):
        problems.append("STRUCTURAL: key 'features' must be an object")

    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_config.py <config.json>", file=sys.stderr)
        return 2
    problems = validate(Path(sys.argv[1]))
    if not problems:
        print("STRUCTURAL: OK")
        return 0
    for line in problems:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
