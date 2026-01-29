"""
End-to-end test for the pr_number input fallback path.

Simulates a workflow_dispatch scenario: creates a PR in the test repo,
merges it, then runs main.py with a workflow_dispatch-style event file
(no pull_request key) and the pr_number argument. Verifies the backport
PR is created successfully.

Requires TEST_GITHUB_TOKEN environment variable.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid

# Add project root to path so we can import integration_helpers
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
from tests.integration_helpers import GitHubAPIHelper, TEST_REPO, API_URL


def main():
    token = os.environ.get("TEST_GITHUB_TOKEN")
    if not token:
        print("TEST_GITHUB_TOKEN not set, skipping")
        return

    test_id = uuid.uuid4().hex[:8]
    api = GitHubAPIHelper(token)

    feature_branch = f"test-dispatch-{test_id}"
    target_branch = f"test-dispatch-target-{test_id}"
    test_file = f"test-dispatch-{test_id}.txt"

    try:
        # 1. Create target branch (where we'll backport to)
        print(f"Creating target branch: {target_branch}")
        api.create_branch(target_branch, from_branch="main")

        # 2. Create feature branch with a commit
        print(f"Creating feature branch: {feature_branch}")
        api.create_branch(feature_branch, from_branch="main")
        api.create_commit(feature_branch, test_file, f"content {test_id}", f"Test commit {test_id}")

        # 3. Create and merge a PR
        print("Creating PR...")
        pr = api.create_pull_request(
            title=f"Dispatch test PR {test_id}",
            head=feature_branch,
            base="main",
            body="Automated dispatch test",
        )
        pr_number = pr["number"]
        print(f"Created PR #{pr_number}")

        print("Merging PR...")
        merge_resp = requests.put(
            f"{API_URL}/repos/{TEST_REPO}/pulls/{pr_number}/merge",
            headers=api.headers,
            json={"merge_method": "squash"},
        )
        merge_resp.raise_for_status()
        print("PR merged.")

        # 4. Write a workflow_dispatch-style event file (NO pull_request key)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"action": "completed"}, f)
            event_file = f.name

        # 5. Clone the test repo
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_dir = os.path.join(tmp_dir, "repo")
            print(f"Cloning {TEST_REPO}...")
            subprocess.run(
                ["git", "clone", f"https://x-access-token:{token}@github.com/{TEST_REPO}.git", repo_dir],
                check=True,
                capture_output=True,
            )

            # 6. Run main.py with the 5th pr_number argument
            env = os.environ.copy()
            env["GITHUB_EVENT_PATH"] = event_file
            env["GITHUB_REPOSITORY"] = TEST_REPO
            env["GITHUB_API_URL"] = API_URL
            env["GITHUB_ACTOR"] = "test-actor"

            main_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")

            print(f"Running main.py with pr_number={pr_number}...")
            result = subprocess.run(
                [
                    sys.executable,
                    main_py,
                    target_branch,
                    "Backport #{pr_number} ({original_title}) to {pr_branch}",
                    "Automated backport of #{pr_number}",
                    token,
                    str(pr_number),
                ],
                cwd=repo_dir,
                env=env,
                capture_output=True,
                text=True,
            )

            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")

            if result.returncode != 0:
                print("FAILED: main.py exited with non-zero status")
                sys.exit(1)

        # 7. Verify the backport PR was created
        print("Verifying backport PR...")
        prs = api.get_pull_requests(state="open", base=target_branch)
        backport_prs = [p for p in prs if "backport" in p["head"]["ref"].lower()]

        if len(backport_prs) != 1:
            print(f"FAILED: Expected 1 backport PR, found {len(backport_prs)}")
            sys.exit(1)

        backport_pr = backport_prs[0]
        api.created_prs.append(backport_pr["number"])
        api.created_branches.append(backport_pr["head"]["ref"])

        assert f"#{pr_number}" in backport_pr["title"], f"PR title missing #{pr_number}: {backport_pr['title']}"
        assert target_branch in backport_pr["title"], f"PR title missing {target_branch}: {backport_pr['title']}"

        print(f"SUCCESS: Backport PR #{backport_pr['number']} created: {backport_pr['title']}")

        # Clean up event file
        os.unlink(event_file)

    finally:
        api.cleanup()


if __name__ == "__main__":
    main()
