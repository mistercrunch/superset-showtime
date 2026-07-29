"""
🚩 Tests for the `showtime flags` CLI command and label-set resolution.

Covers conflicting labels, non-canonical label casing, and the empty-state hint.
"""

from typing import Any, List
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from showtime.cli import app
from showtime.core.feature_flags import extract_feature_flags_from_labels

runner = CliRunner()


@pytest.fixture
def github(monkeypatch: Any) -> Any:
    """Patch the GitHub interface, seeded with a PR's labels."""

    def _seed(labels: List[str]) -> Mock:
        mock = Mock()
        mock.get_labels.return_value = list(labels)
        monkeypatch.setattr("showtime.core.pull_request.get_github", lambda: mock)
        return mock

    return _seed


class TestConflictingLabelsAreDeterministic:
    """Both FLAG=true and FLAG=false on one PR must not flip between runs"""

    def test_conflicting_labels_resolve_identically_across_hash_seeds(self) -> None:
        """Set iteration order varies per process; the answer must not.

        This is the flapping bug: two CI runs of the same PR reaching opposite
        conclusions and restarting the container back and forth.
        """
        import os
        import subprocess
        import sys

        script = (
            "from showtime.core.feature_flags import extract_feature_flags_from_labels;"
            "print(extract_feature_flags_from_labels("
            "{'🎪 🚩 EMBEDDED_SUPERSET=true', '🎪 🚩 EMBEDDED_SUPERSET=false'}))"
        )
        outcomes = {
            subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONHASHSEED": str(seed)},
            ).stdout.strip()
            for seed in range(8)
        }

        assert len(outcomes) == 1, f"resolution varies by hash seed: {outcomes}"

    def test_an_enabling_label_wins_a_conflict(self) -> None:
        result = extract_feature_flags_from_labels(
            {"🎪 🚩 EMBEDDED_SUPERSET=true", "🎪 🚩 EMBEDDED_SUPERSET=false"}
        )

        assert result == {"EMBEDDED_SUPERSET": True}


class TestAddClearsTheOppositeLabel:
    """--add must not leave a contradictory label behind"""

    def test_add_false_removes_an_existing_true_label(self, github: Any) -> None:
        mock = github(["🎪 🚩 EMBEDDED_SUPERSET=true"])

        result = runner.invoke(app, ["flags", "1234", "--add", "EMBEDDED_SUPERSET=false"])

        assert result.exit_code == 0
        mock.remove_label.assert_called_once_with(1234, "🎪 🚩 EMBEDDED_SUPERSET=true")
        mock.add_label.assert_called_once_with(1234, "🎪 🚩 EMBEDDED_SUPERSET=false")

    def test_add_true_removes_an_existing_false_label(self, github: Any) -> None:
        mock = github(["🎪 🚩 EMBEDDED_SUPERSET=false"])

        result = runner.invoke(app, ["flags", "1234", "--add", "EMBEDDED_SUPERSET=true"])

        assert result.exit_code == 0
        mock.remove_label.assert_called_once_with(1234, "🎪 🚩 EMBEDDED_SUPERSET=false")

    def test_add_without_a_conflict_removes_nothing(self, github: Any) -> None:
        mock = github(["🎪 🚩 THUMBNAILS=true"])

        result = runner.invoke(app, ["flags", "1234", "--add", "EMBEDDED_SUPERSET=true"])

        assert result.exit_code == 0
        mock.remove_label.assert_not_called()


class TestRemoveMatchesWhatTheParserAccepts:
    """--remove must clear any label `showtime flags` lists"""

    def test_removes_label_with_non_canonical_casing(self, github: Any) -> None:
        mock = github(["🎪 🚩 EMBEDDED_SUPERSET=True"])

        result = runner.invoke(app, ["flags", "1234", "--remove", "EMBEDDED_SUPERSET"])

        assert result.exit_code == 0
        mock.remove_label.assert_called_once_with(1234, "🎪 🚩 EMBEDDED_SUPERSET=True")
        assert "No feature flag label found" not in result.output

    def test_removes_canonical_label(self, github: Any) -> None:
        mock = github(["🎪 🚩 EMBEDDED_SUPERSET=true"])

        result = runner.invoke(app, ["flags", "1234", "--remove", "EMBEDDED_SUPERSET"])

        assert result.exit_code == 0
        mock.remove_label.assert_called_once_with(1234, "🎪 🚩 EMBEDDED_SUPERSET=true")

    def test_reports_when_the_flag_is_absent(self, github: Any) -> None:
        mock = github(["🎪 🚩 THUMBNAILS=true"])

        result = runner.invoke(app, ["flags", "1234", "--remove", "EMBEDDED_SUPERSET"])

        assert result.exit_code == 0
        mock.remove_label.assert_not_called()
        assert "No feature flag label found" in result.output


class TestEmptyStateHint:
    """The copy-pasteable hint must contain the real PR number"""

    def test_hint_interpolates_the_pr_number(self, github: Any) -> None:
        github([])

        result = runner.invoke(app, ["flags", "1234"])

        assert result.exit_code == 0
        assert "{pr}" not in result.output
        assert "showtime flags 1234 --add" in result.output


class TestDryRunReconcileReporting:
    """--dry-run-aws must not claim an update when there is nothing to apply"""

    def test_no_flags_reports_no_change(self) -> None:
        from showtime.core.show import Show

        show = Show(pr_number=1234, sha="abc123f", status="running")

        result = show.update_feature_flags({}, dry_run=True)

        assert result.success is True
        assert result.changed is False

    def test_flags_to_apply_report_a_change(self) -> None:
        from showtime.core.show import Show

        show = Show(pr_number=1234, sha="abc123f", status="running")

        result = show.update_feature_flags({"SUPERSET_FEATURE_THUMBNAILS": True}, dry_run=True)

        assert result.changed is True

    def test_sync_dry_run_without_flags_reports_no_action(self) -> None:
        from showtime.core.pull_request import PullRequest

        labels = ["🎪 abc123f 🚦 running", "🎪 🎯 abc123f"]
        pr = PullRequest(1234, labels)

        with patch.object(pr, "_determine_action", return_value="no_action"):
            with patch.object(pr, "refresh_labels"):
                result = pr.sync(
                    "abc123f", dry_run_aws=True, dry_run_github=True, dry_run_docker=True
                )

        assert result.success is True
        assert result.action_taken == "no_action"
