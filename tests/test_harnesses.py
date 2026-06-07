from __future__ import annotations

import json

from skill_eval.harnesses import ClaudeCodeHarness, CodexHarness, FakeHarness, OpenCodeHarness


class TestOpenCodeHarnessParseOutput:
    def test_extracts_text_messages(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps({"type": "text", "part": {"text": "Hello world"}})
        output, timing = harness.parse_output(stdout, "")
        assert "Hello world" in output

    def test_extracts_token_usage(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = json.dumps(
            {
                "type": "step_finish",
                "part": {"tokens": {"input": 100, "output": 50, "cache": {"read": 20}}},
            }
        )
        output, timing = harness.parse_output(stdout, "")
        assert timing.input_tokens == 100
        assert timing.output_tokens == 50
        assert timing.cached_tokens == 20
        assert timing.total_tokens == 150

    def test_handles_multiple_events(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        events = [
            json.dumps({"type": "text", "part": {"text": "First"}}),
            json.dumps({"type": "text", "part": {"text": "Second"}}),
        ]
        stdout = "\n".join(events)
        output, timing = harness.parse_output(stdout, "")
        assert "First" in output
        assert "Second" in output

    def test_handles_empty_output(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        output, timing = harness.parse_output("", "")
        assert output == ""
        assert timing.total_tokens == 0

    def test_skips_invalid_json(self, tmp_path):
        harness = OpenCodeHarness(tmp_path)
        stdout = "not json\n" + json.dumps({"type": "text", "part": {"text": "valid"}})
        output, timing = harness.parse_output(stdout, "")
        assert "valid" in output


class TestClaudeCodeHarnessParseOutput:
    def test_extracts_result(self, tmp_path):
        harness = ClaudeCodeHarness(tmp_path)
        stdout = json.dumps({"result": "Task completed", "usage": {"input_tokens": 200, "output_tokens": 100}})
        output, timing = harness.parse_output(stdout, "")
        assert output == "Task completed"
        assert timing.input_tokens == 200
        assert timing.output_tokens == 100

    def test_extracts_cached_tokens(self, tmp_path):
        harness = ClaudeCodeHarness(tmp_path)
        stdout = json.dumps(
            {
                "result": "done",
                "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 30},
            }
        )
        output, timing = harness.parse_output(stdout, "")
        assert timing.cached_tokens == 30

    def test_handles_invalid_json(self, tmp_path):
        harness = ClaudeCodeHarness(tmp_path)
        output, timing = harness.parse_output("plain text output", "")
        assert output == "plain text output"


class TestCodexHarnessParseOutput:
    def test_extracts_messages(self, tmp_path):
        harness = CodexHarness(tmp_path)
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Codex response"},
            }
        )
        output, timing = harness.parse_output(stdout, "")
        assert "Codex response" in output

    def test_extracts_usage(self, tmp_path):
        harness = CodexHarness(tmp_path)
        stdout = json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 300, "output_tokens": 150, "cached_input_tokens": 50},
            }
        )
        output, timing = harness.parse_output(stdout, "")
        assert timing.input_tokens == 300
        assert timing.output_tokens == 150
        assert timing.cached_tokens == 50

    def test_handles_empty_output(self, tmp_path):
        harness = CodexHarness(tmp_path)
        output, timing = harness.parse_output("", "")
        assert output == ""
        assert timing.total_tokens == 0


class TestFakeHarness:
    def test_run_formats_when_fake_skill_is_installed(self, tmp_path):
        skill_dir = tmp_path / ".fake" / "skills" / "format-json"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Format JSON")

        harness = FakeHarness(tmp_path)
        output, timing, stdout, stderr = harness.run("Format JSON", tmp_path / "outputs")

        assert "formatted-json-ok" in output
        assert stdout == output
        assert stderr == ""
        assert timing.total_tokens == 1

    def test_run_baseline_does_not_format_without_skill(self, tmp_path):
        harness = FakeHarness(tmp_path)
        output, timing, stdout, stderr = harness.run("Format JSON", tmp_path / "outputs")

        assert "formatted-json-ok" not in output
        assert stdout == output
        assert stderr == ""
        assert timing.total_tokens == 1
