"""
Tests for helpers.py functions.

These tests run in mock mode by default, or integration mode when TEST_GITHUB_TOKEN is set.
"""

import pytest
from unittest.mock import patch, MagicMock
from subprocess import CalledProcessError

from helpers import (
    git,
    GitException,
    _get_base_branch,
    _get_target_branch,
    _get_pr_number,
    _get_pr_title,
    git_setup,
    github_api_headers,
    github_get_commits_in_pr,
    github_open_pull_request,
    github_open_issue,
)

from tests.integration_helpers import is_integration_mode


class TestEventExtraction:
    """Tests for extracting data from GitHub event dictionaries."""

    def test_get_base_branch(self, sample_event):
        assert _get_base_branch(sample_event) == "main"

    def test_get_base_branch_missing_raises(self):
        with pytest.raises(RuntimeError, match="pull_request.base.ref not found"):
            _get_base_branch({})

    def test_get_target_branch(self, sample_event):
        assert _get_target_branch(sample_event) == "feature/fix-login"

    def test_get_target_branch_missing_raises(self):
        with pytest.raises(RuntimeError, match="pull_request.head.ref not found"):
            _get_target_branch({})

    def test_get_pr_number(self, sample_event):
        assert _get_pr_number(sample_event) == 42

    def test_get_pr_number_missing_raises(self):
        with pytest.raises(RuntimeError, match="pull_request.number not found"):
            _get_pr_number({})

    def test_get_pr_title(self, sample_event):
        assert _get_pr_title(sample_event) == "Fix critical bug in login"

    def test_get_pr_title_missing_raises(self):
        with pytest.raises(RuntimeError, match="pull_request.title not found"):
            _get_pr_title({})


class TestGitCommand:
    """Tests for the git command wrapper."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.subprocess.run")
    def test_git_success(self, mock_run):
        mock_run.return_value = MagicMock(stdout=b"output from git\n")
        result = git("status")
        mock_run.assert_called_once_with(
            ["git", "status"], stdout=-1, stderr=-1, check=True
        )
        assert result == "output from git\n"

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.subprocess.run")
    def test_git_with_multiple_args(self, mock_run):
        mock_run.return_value = MagicMock(stdout=b"")
        git("commit", "-m", "test message")
        mock_run.assert_called_once_with(
            ["git", "commit", "-m", "test message"], stdout=-1, stderr=-1, check=True
        )

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.subprocess.run")
    def test_git_failure_raises_git_exception(self, mock_run):
        error = CalledProcessError(1, "git")
        error.stderr = b"fatal: not a git repository"
        mock_run.side_effect = error

        with pytest.raises(GitException, match="fatal: not a git repository"):
            git("status")

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.subprocess.run")
    def test_git_failure_with_non_decodable_stderr(self, mock_run):
        error = CalledProcessError(1, "git")
        error.stderr = b"\xff\xfe"  # Invalid UTF-8
        mock_run.side_effect = error

        with pytest.raises(GitException):
            git("status")


class TestGitSetup:
    """Tests for git setup configuration."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.git")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_ACTOR": "testuser"})
    def test_git_setup_configures_correctly(self, mock_git):
        git_setup("test-token")

        assert mock_git.call_count == 4
        mock_git.assert_any_call("config", "--global", "--add", "safe.directory", "/github/workspace")
        mock_git.assert_any_call(
            "remote", "set-url", "--push", "origin",
            "https://testuser:test-token@github.com/owner/repo.git"
        )
        mock_git.assert_any_call("config", "user.email", "action@github.com")
        mock_git.assert_any_call("config", "user.name", "github action")


class TestGitHubApiHeaders:
    """Tests for GitHub API header generation."""

    def test_headers_format(self):
        headers = github_api_headers("my-token")
        assert headers == {
            "authorization": "Bearer my-token",
            "content-type": "application/json",
            "accept": "application/vnd.github.v3+json",
        }


class TestGitHubGetCommitsInPr:
    """Tests for fetching commits from a PR."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.requests.get")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_API_URL": "https://api.github.com"})
    def test_returns_commit_shas(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"sha": "abc123", "parents": [{"sha": "parent1"}]},
            {"sha": "def456", "parents": [{"sha": "parent2"}]},
        ]
        mock_get.return_value = mock_response

        commits = github_get_commits_in_pr(42, "token")

        assert commits == ["abc123", "def456"]
        mock_get.assert_called_once()
        mock_response.raise_for_status.assert_called_once()

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.requests.get")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_API_URL": "https://api.github.com"})
    def test_filters_out_merge_commits(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"sha": "abc123", "parents": [{"sha": "parent1"}]},  # Regular commit
            {"sha": "merge123", "parents": [{"sha": "p1"}, {"sha": "p2"}]},  # Merge commit
            {"sha": "def456", "parents": [{"sha": "parent2"}]},  # Regular commit
        ]
        mock_get.return_value = mock_response

        commits = github_get_commits_in_pr(42, "token")

        assert commits == ["abc123", "def456"]
        assert "merge123" not in commits

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.requests.get")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_API_URL": "https://api.github.com"})
    def test_calls_correct_api_url(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_get.return_value = mock_response

        github_get_commits_in_pr(123, "my-token")

        mock_get.assert_called_once_with(
            url="https://api.github.com/repos/owner/repo/pulls/123/commits",
            headers=github_api_headers("my-token"),
        )


class TestGitHubOpenPullRequest:
    """Tests for creating pull requests."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.requests.post")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_API_URL": "https://api.github.com"})
    def test_creates_pull_request(self, mock_post):
        mock_response = MagicMock()
        mock_post.return_value = mock_response

        github_open_pull_request(
            title="Test PR",
            body="PR body",
            head="feature-branch",
            base="main",
            gh_token="token",
        )

        mock_post.assert_called_once_with(
            url="https://api.github.com/repos/owner/repo/pulls",
            json={
                "head": "feature-branch",
                "base": "main",
                "title": "Test PR",
                "body": "PR body",
            },
            headers=github_api_headers("token"),
        )
        mock_response.raise_for_status.assert_called_once()


class TestGitHubOpenIssue:
    """Tests for creating issues."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("helpers.requests.post")
    @patch.dict("os.environ", {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_API_URL": "https://api.github.com"})
    def test_creates_issue(self, mock_post):
        mock_response = MagicMock()
        mock_post.return_value = mock_response

        github_open_issue(
            title="Error occurred",
            body="Something went wrong",
            gh_token="token",
        )

        mock_post.assert_called_once_with(
            url="https://api.github.com/repos/owner/repo/issues",
            json={
                "title": "Error occurred",
                "body": "Something went wrong",
            },
            headers=github_api_headers("token"),
        )
        mock_response.raise_for_status.assert_called_once()


# Integration tests - only run when TEST_GITHUB_TOKEN is set
class TestGitHubAPIIntegration:
    """Integration tests that call the real GitHub API."""

    @pytest.mark.skipif(not is_integration_mode(), reason="Integration test requires TEST_GITHUB_TOKEN")
    def test_get_commits_from_real_pr(self, github_env, github_token, github_api):
        """Test fetching commits from a real PR."""
        import uuid
        test_id = uuid.uuid4().hex[:8]
        branch_name = f"test-commits-{test_id}"

        # Create a branch with a commit
        github_api.create_branch(branch_name, from_branch="main")
        github_api.create_commit(branch_name, f"test-{test_id}.txt", "content", "Test commit")

        # Create a PR
        pr = github_api.create_pull_request(
            title=f"Test PR {test_id}",
            head=branch_name,
            base="main",
        )

        # Fetch commits using our function
        commits = github_get_commits_in_pr(pr["number"], github_token)

        assert len(commits) >= 1
        assert all(isinstance(c, str) and len(c) == 40 for c in commits)

    @pytest.mark.skipif(not is_integration_mode(), reason="Integration test requires TEST_GITHUB_TOKEN")
    def test_open_and_verify_pull_request(self, github_env, github_token, github_api):
        """Test creating a real PR via the API."""
        import uuid
        test_id = uuid.uuid4().hex[:8]
        branch_name = f"test-pr-{test_id}"

        # Create a branch with a commit
        github_api.create_branch(branch_name, from_branch="main")
        github_api.create_commit(branch_name, f"test-{test_id}.txt", "content", "Test commit")

        # Create PR using our function
        github_open_pull_request(
            title=f"Integration Test PR {test_id}",
            body="This is an automated test PR",
            head=branch_name,
            base="main",
            gh_token=github_token,
        )

        # Verify PR was created
        prs = github_api.get_pull_requests(state="open")
        matching_prs = [p for p in prs if p["head"]["ref"] == branch_name]

        assert len(matching_prs) == 1
        assert matching_prs[0]["title"] == f"Integration Test PR {test_id}"

        # Track for cleanup
        github_api.created_prs.append(matching_prs[0]["number"])
