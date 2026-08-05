"""
Tests for Showtime PR comment cleanup: superseded comments are deleted
when new lifecycle comments are posted.
"""

from unittest.mock import Mock, patch

import pytest

from showtime.core.constants import SHOWTIME_COMMENT_MARKER
from showtime.core.github import GitHubInterface, is_showtime_comment
from showtime.core.pull_request import PullRequest


@pytest.fixture
def github():
    """Create a GitHubInterface with a fake token"""
    return GitHubInterface(token="fake-token", org="test-org", repo="test-repo")


class TestIsShowtimeComment:
    """Tests for the is_showtime_comment helper function"""

    def test_marker_comment(self) -> None:
        body = f"🎪 Showtime deployed environment\n\n{SHOWTIME_COMMENT_MARKER}"
        assert is_showtime_comment(body) is True

    def test_marker_alone(self) -> None:
        assert is_showtime_comment(SHOWTIME_COMMENT_MARKER) is True

    def test_legacy_building_comment(self) -> None:
        body = (
            "🎪 [Showtime](https://github.com/mistercrunch/superset-showtime) "
            "is building environment on [GHA](https://github.com/apache/superset/"
            "actions/runs/123) for [abc123f](https://github.com/apache/superset/commit/abc123f)"
        )
        assert is_showtime_comment(body) is True

    def test_legacy_success_comment(self) -> None:
        body = (
            "🎪 [Showtime](https://github.com/mistercrunch/superset-showtime) "
            "deployed environment on [GHA](url) for [abc123f](url)\n\n"
            "• **Environment:** http://1.2.3.4:8080 (admin/admin)\n"
            "• **Lifetime:** 48h auto-cleanup"
        )
        assert is_showtime_comment(body) is True

    def test_user_comment(self) -> None:
        assert is_showtime_comment("LGTM, thanks for the fix!") is False

    def test_user_comment_mentioning_showtime(self) -> None:
        """A human discussing superset-showtime mid-comment is not a bot comment"""
        body = "I think superset-showtime should handle this differently"
        assert is_showtime_comment(body) is False

    def test_empty_body(self) -> None:
        assert is_showtime_comment("") is False


class TestDeleteShowtimeComments:
    """Tests for GitHubInterface.delete_showtime_comments"""

    def test_deletes_only_showtime_comments(self, github: GitHubInterface) -> None:
        comments = [
            {"id": 1, "body": f"🎪 Showtime is building\n\n{SHOWTIME_COMMENT_MARKER}"},
            {"id": 2, "body": "Great work on this PR!"},
            {
                "id": 3,
                "body": "🎪 [Showtime](https://github.com/mistercrunch/superset-showtime) "
                "deployed environment",
            },
            {"id": 4, "body": None},
        ]

        with patch.object(github, "get_comments", return_value=comments):
            with patch.object(github, "delete_comment") as mock_delete:
                deleted = github.delete_showtime_comments(1234)

        assert deleted == 2
        assert [call.args[0] for call in mock_delete.call_args_list] == [1, 3]

    def test_no_showtime_comments(self, github: GitHubInterface) -> None:
        comments = [{"id": 1, "body": "Just a regular comment"}]

        with patch.object(github, "get_comments", return_value=comments):
            with patch.object(github, "delete_comment") as mock_delete:
                deleted = github.delete_showtime_comments(1234)

        assert deleted == 0
        mock_delete.assert_not_called()


class TestPostShowtimeComment:
    """Tests for PullRequest._post_showtime_comment"""

    @patch("showtime.core.pull_request.get_github")
    def test_deletes_old_comments_before_posting(self, mock_get_github: Mock) -> None:
        mock_github = Mock()
        mock_github.delete_showtime_comments.return_value = 2
        mock_get_github.return_value = mock_github

        pr = PullRequest(1234, [])
        pr._post_showtime_comment("🎪 Showtime deployed environment")

        mock_github.delete_showtime_comments.assert_called_once_with(1234)
        mock_github.post_comment.assert_called_once()
        posted_body = mock_github.post_comment.call_args.args[1]
        assert posted_body.startswith("🎪 Showtime deployed environment")
        assert SHOWTIME_COMMENT_MARKER in posted_body

    @patch("showtime.core.pull_request.get_github")
    def test_cleanup_failure_still_posts(self, mock_get_github: Mock) -> None:
        """A failed cleanup should never block the new comment"""
        mock_github = Mock()
        mock_github.delete_showtime_comments.side_effect = Exception("API error")
        mock_get_github.return_value = mock_github

        pr = PullRequest(1234, [])
        pr._post_showtime_comment("🎪 Showtime deployed environment")

        mock_github.post_comment.assert_called_once()

    @patch("showtime.core.pull_request.get_github")
    def test_dry_run_does_nothing(self, mock_get_github: Mock) -> None:
        mock_github = Mock()
        mock_get_github.return_value = mock_github

        pr = PullRequest(1234, [])
        pr._post_showtime_comment("🎪 Showtime deployed environment", dry_run=True)

        mock_github.delete_showtime_comments.assert_not_called()
        mock_github.post_comment.assert_not_called()
