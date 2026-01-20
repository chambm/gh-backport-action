# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

gh-backport-action is a GitHub Action that automatically backports (cherry-picks) merged pull requests to a target branch. It supports all three GitHub merge strategies: "Merge Commit", "Rebase and Merge", and "Squash and Merge". On success, it opens a new PR; on failure, it opens an Issue with error details.

## Commands

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run unit tests (mocked, fast)
pytest

# Run integration tests against real GitHub API (uses chambm/gh-backport-action-test repo)
TEST_GITHUB_TOKEN=<your-pat> pytest -v

# Run a single test file
pytest tests/test_helpers.py

# Run a single test
pytest tests/test_helpers.py::TestEventExtraction::test_get_base_branch

# Format code (line-length: 140)
black .

# Lint code (max-line-length: 140, max-complexity: 10)
flake8 .

# Run all pre-commit hooks
pre-commit run --all-files
```

## Testing

Tests support two modes:
- **Unit tests (default)**: Use mocked GitHub API and git commands. Fast, no external dependencies.
- **Integration tests**: Use real GitHub API against `chambm/gh-backport-action-test` repo. Set `TEST_GITHUB_TOKEN` env var to enable.

CI runs unit tests on all PRs. Integration tests run when the `TEST_GITHUB_TOKEN` secret is available.

## Architecture

**Entry Point**: `entrypoint.sh` → `main.py`

**Core Files**:
- `main.py` - Primary orchestrator with `entrypoint()` function that handles the complete backport workflow
- `helpers.py` - Utility functions organized by responsibility:
  - Git operations: `git()` wrapper, `git_setup()`, `GitException`
  - GitHub event extraction: `_get_base_branch()`, `_get_target_branch()`, `_get_pr_number()`, `_get_pr_title()`
  - GitHub API: `github_get_commits_in_pr()`, `github_open_pull_request()`, `github_open_issue()`

**Workflow**:
1. Parse CLI arguments (pr_branch, pr_title, pr_body, github_token)
2. Load GitHub event data from `GITHUB_EVENT_PATH`
3. Fetch commits from GitHub API (filters out merge commits)
4. Create backport branch, cherry-pick commits, push to origin
5. Create PR or Issue depending on success/failure

**Key Patterns**:
- Template variables in PR title/body: `{pr_branch}`, `{pr_number}`, `{base_branch}`, `{original_title}`
- Cascading error handlers that gracefully degrade
- Git operations wrapped with custom `git()` function and `GitException`

**Environment Variables Used**:
- `GITHUB_EVENT_PATH` - JSON event data
- `GITHUB_REPOSITORY` - Repo in org/name format
- `GITHUB_ACTOR` - Actor creating the commit
- `GITHUB_API_URL` - API base URL

## Runtime

Python 3.8 in Docker (Alpine Linux). Single dependency: `requests==2.26.0`.
