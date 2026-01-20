"""
Tests for main.py functions.

These tests run in mock mode by default, or integration mode when TEST_GITHUB_TOKEN is set.
"""

import json
import os
import subprocess
import uuid
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from main import backport_commits, entrypoint
from tests.integration_helpers import is_integration_mode, TEST_REPO, API_URL


class TestBackportCommits:
    """Tests for the backport_commits function."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.git")
    @patch("main.datetime")
    def test_creates_branch_and_cherry_picks(self, mock_datetime, mock_git):
        mock_datetime.utcnow.return_value = datetime(2024, 3, 15)

        result = backport_commits(
            commits=["abc123", "def456"],
            initial_name="main",
            to_branch="release",
        )

        assert result == "backport-main-031524-release"
        mock_git.assert_any_call("switch", "-c", "backport-main-031524-release", "origin/release")
        mock_git.assert_any_call("cherry-pick", "abc123")
        mock_git.assert_any_call("cherry-pick", "def456")
        mock_git.assert_any_call("push", "-u", "origin", "backport-main-031524-release")

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.git")
    @patch("main.datetime")
    def test_truncates_long_branch_names(self, mock_datetime, mock_git):
        mock_datetime.utcnow.return_value = datetime(2024, 3, 15)

        result = backport_commits(
            commits=["abc123"],
            initial_name="very-long-branch-name-that-exceeds-limit",
            to_branch="release",
        )

        # initial_name is truncated to 15 chars
        assert result == "backport-very-long-branc-031524-release"

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.git")
    @patch("main.datetime")
    def test_raises_on_cherry_pick_failure(self, mock_datetime, mock_git):
        mock_datetime.utcnow.return_value = datetime(2024, 3, 15)

        def git_side_effect(*args):
            if args[0] == "cherry-pick":
                raise Exception("Conflict")

        mock_git.side_effect = git_side_effect

        with pytest.raises(RuntimeError, match="Could not cherry pick"):
            backport_commits(
                commits=["abc123"],
                initial_name="main",
                to_branch="release",
            )


class TestEntrypoint:
    """Tests for the entrypoint function."""

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.github_open_pull_request")
    @patch("main.backport_commits")
    @patch("main.github_get_commits_in_pr")
    def test_successful_backport(self, mock_get_commits, mock_backport, mock_open_pr, sample_event):
        mock_get_commits.return_value = ["abc123", "def456"]
        mock_backport.return_value = "backport-main-031524-release"

        entrypoint(
            event_dict=sample_event,
            pr_branch="release",
            pr_title="Cherry pick of #{pr_number} ({original_title}) from {base_branch} to {pr_branch}",
            pr_body="Backport of #{pr_number}",
            gh_token="test-token",
        )

        mock_get_commits.assert_called_once_with(pr_number=42, gh_token="test-token")
        mock_backport.assert_called_once_with(["abc123", "def456"], "main", "release")
        mock_open_pr.assert_called_once_with(
            title="Cherry pick of #42 (Fix critical bug in login) from main to release",
            head="backport-main-031524-release",
            base="release",
            body="Backport of #42",
            gh_token="test-token",
        )

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.github_open_pull_request")
    @patch("main.backport_commits")
    @patch("main.github_get_commits_in_pr")
    def test_template_variables_substituted(self, mock_get_commits, mock_backport, mock_open_pr, sample_event):
        mock_get_commits.return_value = ["abc123"]
        mock_backport.return_value = "new-branch"

        entrypoint(
            event_dict=sample_event,
            pr_branch="release",
            pr_title="{base_branch} -> {pr_branch}: {original_title} (#{pr_number})",
            pr_body="From {base_branch}, PR #{pr_number}: {original_title}",
            gh_token="token",
        )

        mock_open_pr.assert_called_once()
        call_kwargs = mock_open_pr.call_args[1]
        assert call_kwargs["title"] == "main -> release: Fix critical bug in login (#42)"
        assert call_kwargs["body"] == "From main, PR #42: Fix critical bug in login"

    @pytest.mark.skipif(is_integration_mode(), reason="Unit test only")
    @patch("main.github_open_pull_request")
    @patch("main.backport_commits")
    @patch("main.github_get_commits_in_pr")
    def test_handles_empty_commits_list(self, mock_get_commits, mock_backport, mock_open_pr, sample_event):
        mock_get_commits.return_value = []
        mock_backport.return_value = "new-branch"

        entrypoint(
            event_dict=sample_event,
            pr_branch="release",
            pr_title="Backport #{pr_number}",
            pr_body="Body",
            gh_token="token",
        )

        mock_backport.assert_called_once_with([], "main", "release")


# Integration tests - only run when TEST_GITHUB_TOKEN is set
class TestBackportIntegration:
    """Integration tests for the full backport workflow."""

    @pytest.mark.skipif(not is_integration_mode(), reason="Integration test requires TEST_GITHUB_TOKEN")
    def test_full_backport_workflow(self, github_env, github_token, github_api, tmp_path):
        """Test the complete backport workflow end-to-end."""
        test_id = uuid.uuid4().hex[:8]

        # Create unique branch names
        feature_branch = f"test-feature-{test_id}"
        target_branch = f"test-target-{test_id}"
        test_file = f"test-file-{test_id}.txt"

        # 1. Create target branch (where we'll backport to)
        github_api.create_branch(target_branch, from_branch="main")

        # 2. Create feature branch with a commit
        github_api.create_branch(feature_branch, from_branch="main")
        github_api.create_commit(
            feature_branch,
            test_file,
            f"Test content {test_id}",
            f"Test commit for backport {test_id}"
        )

        # 3. Create and merge a PR (using squash to get a single commit)
        pr = github_api.create_pull_request(
            title=f"Test PR for backport {test_id}",
            head=feature_branch,
            base="main",
            body="Integration test PR",
        )
        pr_number = pr["number"]

        # Merge the PR
        import requests
        merge_resp = requests.put(
            f"{API_URL}/repos/{TEST_REPO}/pulls/{pr_number}/merge",
            headers=github_api.headers,
            json={"merge_method": "squash"},
        )
        merge_resp.raise_for_status()

        # 4. Create event file
        event_data = {
            "pull_request": {
                "number": pr_number,
                "title": f"Test PR for backport {test_id}",
                "base": {"ref": "main"},
                "head": {"ref": feature_branch},
            }
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event_data))

        # 5. Clone the test repo
        repo_dir = tmp_path / "repo"
        subprocess.run(
            ["git", "clone", f"https://x-access-token:{github_token}@github.com/{TEST_REPO}.git", str(repo_dir)],
            check=True,
            capture_output=True,
        )

        # 6. Set up environment and run main.py
        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = str(event_file)
        env["GITHUB_REPOSITORY"] = TEST_REPO
        env["GITHUB_API_URL"] = API_URL
        env["GITHUB_ACTOR"] = "test-actor"

        # Get the path to main.py in the actual project
        main_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")

        result = subprocess.run(
            [
                "python",
                main_py_path,
                target_branch,
                "Backport #{pr_number} ({original_title}) to {pr_branch}",
                "Automated backport of #{pr_number}",
                github_token,
            ],
            cwd=str(repo_dir),
            env=env,
            capture_output=True,
            text=True,
        )

        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")

        # 7. Verify success
        assert result.returncode == 0, f"Backport failed: {result.stderr}"

        # 8. Find and verify the backport PR
        prs = github_api.get_pull_requests(state="open", base=target_branch)
        backport_prs = [p for p in prs if "backport" in p["head"]["ref"].lower()]

        assert len(backport_prs) == 1, f"Expected 1 backport PR, found {len(backport_prs)}"
        backport_pr = backport_prs[0]

        # Track for cleanup
        github_api.created_prs.append(backport_pr["number"])
        github_api.created_branches.append(backport_pr["head"]["ref"])

        # Verify PR title
        assert f"#{pr_number}" in backport_pr["title"]
        assert target_branch in backport_pr["title"]
        assert f"Test PR for backport {test_id}" in backport_pr["title"]

    @pytest.mark.skipif(not is_integration_mode(), reason="Integration test requires TEST_GITHUB_TOKEN")
    def test_backport_with_merge_commit(self, github_env, github_token, github_api, tmp_path):
        """Test backport workflow when PR contains a merge commit from updating the feature branch.

        This tests the scenario where a developer merges main into their feature branch
        to get the latest changes. The merge commit should be skipped during cherry-pick.
        """
        import requests
        test_id = uuid.uuid4().hex[:8]

        feature_branch = f"test-merge-bp-{test_id}"
        target_branch = f"test-target-bp-{test_id}"

        # 1. Create target branch (where we'll backport to)
        github_api.create_branch(target_branch, from_branch="main")

        # 2. Create feature branch from main
        github_api.create_branch(feature_branch, from_branch="main")

        # 3. Make a commit on main (simulating main advancing)
        github_api.create_commit("main", f"main-{test_id}.txt", "main content", f"Main commit {test_id}")

        # 4. Make a commit on feature branch
        github_api.create_commit(
            feature_branch, f"feature1-{test_id}.txt", "feature content 1", f"Feature commit 1 {test_id}"
        )

        # 5. Merge main into feature branch (creates merge commit with 2 parents)
        github_api.merge_branch(
            target_branch=feature_branch,
            source_branch="main",
            message=f"Merge main into {feature_branch}",
        )

        # 6. Make another commit on feature branch after merge
        github_api.create_commit(
            feature_branch, f"feature2-{test_id}.txt", "feature content 2", f"Feature commit 2 {test_id}"
        )

        # 7. Create and merge PR (using merge commit method to preserve history)
        pr = github_api.create_pull_request(
            title=f"Test PR with merge commit {test_id}",
            head=feature_branch,
            base="main",
            body="Integration test PR with merge commit",
        )
        pr_number = pr["number"]

        merge_resp = requests.put(
            f"{API_URL}/repos/{TEST_REPO}/pulls/{pr_number}/merge",
            headers=github_api.headers,
            json={"merge_method": "merge"},  # Use merge to preserve commits
        )
        merge_resp.raise_for_status()

        # 8. Create event file
        event_data = {
            "pull_request": {
                "number": pr_number,
                "title": f"Test PR with merge commit {test_id}",
                "base": {"ref": "main"},
                "head": {"ref": feature_branch},
            }
        }
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(event_data))

        # 9. Clone the test repo
        repo_dir = tmp_path / "repo"
        subprocess.run(
            ["git", "clone", f"https://x-access-token:{github_token}@github.com/{TEST_REPO}.git", str(repo_dir)],
            check=True,
            capture_output=True,
        )

        # 10. Run the backport
        env = os.environ.copy()
        env["GITHUB_EVENT_PATH"] = str(event_file)
        env["GITHUB_REPOSITORY"] = TEST_REPO
        env["GITHUB_API_URL"] = API_URL
        env["GITHUB_ACTOR"] = "test-actor"

        main_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")

        result = subprocess.run(
            [
                "python",
                main_py_path,
                target_branch,
                "Backport #{pr_number} ({original_title}) to {pr_branch}",
                "Automated backport of #{pr_number}",
                github_token,
            ],
            cwd=str(repo_dir),
            env=env,
            capture_output=True,
            text=True,
        )

        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")

        # 11. Verify success - merge commit should have been skipped
        assert result.returncode == 0, f"Backport failed (merge commit may not have been skipped): {result.stderr}"

        # 12. Find and verify the backport PR
        prs = github_api.get_pull_requests(state="open", base=target_branch)
        backport_prs = [p for p in prs if "backport" in p["head"]["ref"].lower()]

        assert len(backport_prs) == 1, f"Expected 1 backport PR, found {len(backport_prs)}"
        backport_pr = backport_prs[0]

        # Track for cleanup
        github_api.created_prs.append(backport_pr["number"])
        github_api.created_branches.append(backport_pr["head"]["ref"])

        # Verify PR title includes the original title
        assert f"#{pr_number}" in backport_pr["title"]
        assert f"Test PR with merge commit {test_id}" in backport_pr["title"]
