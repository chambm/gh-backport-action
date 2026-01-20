"""
Shared utilities for integration testing.

This module provides helpers for tests that can run in both mock and integration modes.
"""

import os
import requests

TEST_REPO = "chambm/gh-backport-action-test"
API_URL = "https://api.github.com"


def is_integration_mode():
    """Check if we're running in integration mode with real GitHub API."""
    return bool(os.environ.get("TEST_GITHUB_TOKEN"))


class GitHubAPIHelper:
    """Helper for real GitHub API calls in integration tests."""

    def __init__(self, token):
        self.token = token
        self.api_base = f"{API_URL}/repos/{TEST_REPO}"
        self.headers = {
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "accept": "application/vnd.github.v3+json",
        }
        self.created_branches = []
        self.created_prs = []

    def create_branch(self, branch_name, from_branch="main"):
        """Create a new branch from an existing branch."""
        resp = requests.get(f"{self.api_base}/git/ref/heads/{from_branch}", headers=self.headers)
        resp.raise_for_status()
        sha = resp.json()["object"]["sha"]

        resp = requests.post(
            f"{self.api_base}/git/refs",
            headers=self.headers,
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        resp.raise_for_status()
        self.created_branches.append(branch_name)
        return sha

    def create_commit(self, branch_name, filename, content, message):
        """Create a file commit on a branch."""
        resp = requests.post(
            f"{self.api_base}/git/blobs",
            headers=self.headers,
            json={"content": content, "encoding": "utf-8"},
        )
        resp.raise_for_status()
        blob_sha = resp.json()["sha"]

        resp = requests.get(f"{self.api_base}/git/ref/heads/{branch_name}", headers=self.headers)
        resp.raise_for_status()
        current_commit_sha = resp.json()["object"]["sha"]

        resp = requests.get(f"{self.api_base}/git/commits/{current_commit_sha}", headers=self.headers)
        resp.raise_for_status()
        base_tree_sha = resp.json()["tree"]["sha"]

        resp = requests.post(
            f"{self.api_base}/git/trees",
            headers=self.headers,
            json={
                "base_tree": base_tree_sha,
                "tree": [{"path": filename, "mode": "100644", "type": "blob", "sha": blob_sha}],
            },
        )
        resp.raise_for_status()
        new_tree_sha = resp.json()["sha"]

        resp = requests.post(
            f"{self.api_base}/git/commits",
            headers=self.headers,
            json={"message": message, "tree": new_tree_sha, "parents": [current_commit_sha]},
        )
        resp.raise_for_status()
        new_commit_sha = resp.json()["sha"]

        resp = requests.patch(
            f"{self.api_base}/git/refs/heads/{branch_name}",
            headers=self.headers,
            json={"sha": new_commit_sha},
        )
        resp.raise_for_status()
        return new_commit_sha

    def merge_branch(self, target_branch, source_branch, message="Merge branch"):
        """Merge source_branch into target_branch, creating a merge commit with two parents."""
        # Get the SHA of both branches
        resp = requests.get(f"{self.api_base}/git/ref/heads/{target_branch}", headers=self.headers)
        resp.raise_for_status()
        target_sha = resp.json()["object"]["sha"]

        resp = requests.get(f"{self.api_base}/git/ref/heads/{source_branch}", headers=self.headers)
        resp.raise_for_status()
        source_sha = resp.json()["object"]["sha"]

        # Get the tree from source branch (simulating merge taking source's tree)
        resp = requests.get(f"{self.api_base}/git/commits/{source_sha}", headers=self.headers)
        resp.raise_for_status()
        source_tree_sha = resp.json()["tree"]["sha"]

        # Create a merge commit with two parents
        resp = requests.post(
            f"{self.api_base}/git/commits",
            headers=self.headers,
            json={
                "message": message,
                "tree": source_tree_sha,
                "parents": [target_sha, source_sha],
            },
        )
        resp.raise_for_status()
        merge_commit_sha = resp.json()["sha"]

        # Update the target branch to point to the merge commit
        resp = requests.patch(
            f"{self.api_base}/git/refs/heads/{target_branch}",
            headers=self.headers,
            json={"sha": merge_commit_sha},
        )
        resp.raise_for_status()
        return merge_commit_sha

    def create_pull_request(self, title, head, base, body=""):
        """Create a pull request."""
        resp = requests.post(
            f"{self.api_base}/pulls",
            headers=self.headers,
            json={"title": title, "head": head, "base": base, "body": body},
        )
        resp.raise_for_status()
        pr = resp.json()
        self.created_prs.append(pr["number"])
        return pr

    def get_pull_requests(self, state="open", base=None):
        """Get pull requests."""
        params = {"state": state}
        if base:
            params["base"] = base
        resp = requests.get(f"{self.api_base}/pulls", headers=self.headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def close_pull_request(self, pr_number):
        """Close a pull request."""
        requests.patch(
            f"{self.api_base}/pulls/{pr_number}",
            headers=self.headers,
            json={"state": "closed"},
        )

    def delete_branch(self, branch_name):
        """Delete a branch."""
        requests.delete(f"{self.api_base}/git/refs/heads/{branch_name}", headers=self.headers)

    def cleanup(self):
        """Clean up all created resources."""
        for pr_number in self.created_prs:
            try:
                self.close_pull_request(pr_number)
            except Exception:
                pass

        for branch in self.created_branches:
            try:
                self.delete_branch(branch)
            except Exception:
                pass
