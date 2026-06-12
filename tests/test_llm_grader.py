from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from openai import OpenAIError

from agent_skill_eval.graders import LLMGrader


class TestLLMGraderClient:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        grader = LLMGrader()
        with pytest.raises(OpenAIError, match="OPENROUTER_API_KEY or OPENAI_API_KEY not set"):
            _ = grader.client

    def test_uses_openrouter_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        grader = LLMGrader()
        assert grader.client.api_key == "or-key"

    def test_falls_back_to_openai_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "oa-key")

        grader = LLMGrader()
        assert grader.client.api_key == "oa-key"

    def test_custom_base_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        grader = LLMGrader(base_url="https://custom.api/v1")
        assert "custom.api" in str(grader.client.base_url)

    def test_default_base_url_is_openrouter(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        grader = LLMGrader()
        assert "openrouter.ai" in str(grader.client.base_url)

    def test_env_base_url_override(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env-base.api/v1")
        grader = LLMGrader()
        assert "env-base.api" in str(grader.client.base_url)

    def test_client_is_cached(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        grader = LLMGrader()
        client1 = grader.client
        client2 = grader.client
        assert client1 is client2


class TestLLMGraderGrade:
    def test_prompt_shape_and_success_parsing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "file1.py").write_text("print('hello')")
        (workspace / "file2.py").write_text("print('world')")

        output_dir = workspace / "with_skill" / "test_case"
        output_dir.mkdir(parents=True)

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {
                            "results": [
                                {"text": "The output contains hello", "passed": True, "evidence": "Found in file1.py"},
                                {"text": "A new file was created", "passed": False, "evidence": "No new file created"},
                            ]
                        }
                    )
                )
            )
        ]

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        grader._client = mock_client

        assertions = ["The output contains hello", "A new file was created"]
        results = grader.grade(
            assertions=assertions,
            agent_output="Finished successfully",
            output_dir=output_dir,
            expected_output="hello",
        )

        assert len(results) == 2
        assert results[0].text == "The output contains hello"
        assert results[0].passed is True
        assert results[0].evidence == "Found in file1.py"
        assert results[1].text == "A new file was created"
        assert results[1].passed is False
        assert results[1].evidence == "No new file created"

    def test_prompt_includes_expected_output_and_agent_output(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        output_dir = tmp_path / "with_skill" / "test"
        output_dir.mkdir(parents=True)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps({"results": []})))]

        grader = LLMGrader()
        captured_messages = []

        def capture_create(**kwargs):
            captured_messages.append(kwargs["messages"])
            return mock_response

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = capture_create
        grader._client = mock_client

        grader.grade(
            assertions=["assertion 1"],
            agent_output="agent said hello",
            output_dir=output_dir,
            expected_output="expected world",
        )

        prompt = captured_messages[0][0]["content"]
        assert "expected world" in prompt
        assert "agent said hello" in prompt
        assert "1. assertion 1" in prompt

    def test_empty_assertions_returns_empty(self, tmp_path):
        grader = LLMGrader()
        results = grader.grade(assertions=[], agent_output="out", output_dir=tmp_path, expected_output="exp")
        assert results == []

    def test_malformed_json_response(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="This is not JSON!"))]

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        grader._client = mock_client

        assertions = ["Assert 1", "Assert 2"]
        results = grader.grade(
            assertions=assertions,
            agent_output="output",
            output_dir=tmp_path / "output_dir",
            expected_output="expected",
        )

        assert len(results) == 2
        for i, r in enumerate(results):
            assert r.text == assertions[i]
            assert r.passed is False
            assert "LLM grading error" in r.evidence

    def test_api_error_returns_fail_for_all_assertions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = OpenAIError("Rate limit exceeded")
        grader._client = mock_client

        results = grader.grade(
            assertions=["A", "B", "C"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert len(results) == 3
        for r in results:
            assert r.passed is False
            assert "Rate limit exceeded" in r.evidence

    def test_partial_results_returns_fail_for_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {
                            "results": [
                                {"text": "Assert 1", "passed": True, "evidence": "ok"},
                            ]
                        }
                    )
                )
            )
        ]

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        grader._client = mock_client

        results = grader.grade(
            assertions=["Assert 1", "Assert 2", "Assert 3"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert len(results) == 3
        assert results[0].text == "Assert 1"
        assert results[0].passed is True
        assert results[1].text == "Assert 2"
        assert results[1].passed is False
        assert "did not return" in results[1].evidence
        assert results[2].text == "Assert 3"
        assert results[2].passed is False
        assert "did not return" in results[2].evidence

    def test_dropped_assertion_recovered_by_retry(self, tmp_path, monkeypatch):
        """One retry with only the dropped assertions turns a would-be skip
        into a real verdict."""
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        def response_with(results):
            return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps({"results": results})))])

        first = response_with([{"text": "Assert 1", "passed": True, "evidence": "ok"}])
        retry = response_with([{"text": "Assert 2", "passed": False, "evidence": "not found"}])

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [first, retry]
        grader._client = mock_client

        results = grader.grade(
            assertions=["Assert 1", "Assert 2"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert mock_client.chat.completions.create.call_count == 2
        # The retry prompt only contains the dropped assertion.
        retry_prompt = mock_client.chat.completions.create.call_args_list[1].kwargs["messages"][0]["content"]
        assert "Assert 2" in retry_prompt
        assert "1. Assert 1" not in retry_prompt
        assert len(results) == 2
        by_text = {r.text: r for r in results}
        assert by_text["Assert 1"].passed is True
        assert by_text["Assert 2"].passed is False
        assert not any(r.skipped for r in results)

    def test_retry_does_not_duplicate_already_answered_assertions(self, tmp_path, monkeypatch):
        """A retry that re-answers an already-graded assertion (or returns
        unrelated rows) must not add duplicate results."""
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        # Same response both times: answers Assert 1, never Assert 2.
        mock_response = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps({"results": [{"text": "Assert 1", "passed": True, "evidence": "ok"}]})
                    )
                )
            ]
        )

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        grader._client = mock_client

        results = grader.grade(
            assertions=["Assert 1", "Assert 2"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert mock_client.chat.completions.create.call_count == 2
        assert len(results) == 2
        assert [r.text for r in results] == ["Assert 1", "Assert 2"]
        assert results[1].skipped is True

    def test_retry_api_error_falls_back_to_skip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        first = MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        content=json.dumps({"results": [{"text": "Assert 1", "passed": True, "evidence": "ok"}]})
                    )
                )
            ]
        )

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [first, OpenAIError("boom")]
        grader._client = mock_client

        results = grader.grade(
            assertions=["Assert 1", "Assert 2"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].skipped is True
        assert "did not return" in results[1].evidence

    def test_missing_text_field_in_result(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps(
                        {
                            "results": [
                                {"passed": True, "evidence": "ok"},
                            ]
                        }
                    )
                )
            )
        ]

        grader = LLMGrader()
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        grader._client = mock_client

        results = grader.grade(
            assertions=["Assert 1"],
            agent_output="out",
            output_dir=tmp_path,
            expected_output="exp",
        )

        assert len(results) == 1
        assert results[0].passed is False
        assert "LLM grading error" in results[0].evidence


class TestLLMGraderFileListing:
    def test_file_listing_bounded_at_50(self, tmp_path):
        grader = LLMGrader()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        for i in range(60):
            (workspace / f"file_{i:02d}.txt").write_text(f"content {i}")

        file_listing = grader._list_workspace_files(workspace)
        lines = file_listing.strip().split("\n")
        assert len(lines) == 50

    def test_file_listing_excludes_git(self, tmp_path):
        grader = LLMGrader()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "real.txt").write_text("content")
        git_dir = workspace / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("config")

        file_listing = grader._list_workspace_files(workspace)
        assert "real.txt" in file_listing
        assert ".git" not in file_listing

    def test_file_listing_shows_sizes(self, tmp_path):
        grader = LLMGrader()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "data.txt").write_text("hello")

        file_listing = grader._list_workspace_files(workspace)
        assert "data.txt" in file_listing
        assert "bytes" in file_listing

    def test_empty_workspace_returns_placeholder(self, tmp_path):
        grader = LLMGrader()
        workspace = tmp_path / "empty"
        workspace.mkdir()

        file_listing = grader._list_workspace_files(workspace)
        assert file_listing == "(empty workspace)"
