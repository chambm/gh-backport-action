"""
Pytest configuration and shared fixtures.

Tests can run in two modes:
1. Mock mode (default): Uses mocked GitHub API and git commands for fast local testing
2. Integration mode: Uses real GitHub API when TEST_GITHUB_TOKEN is set

Set TEST_GITHUB_TOKEN environment variable to run against real GitHub API.
"""

import os
import pytest

from tests.integration_helpers import is_integration_mode, GitHubAPIHelper, TEST_REPO, API_URL


@pytest.fixture
def integration_mode():
    """Returns True if running in integration mode."""
    return is_integration_mode()


@pytest.fixture
def github_token():
    """Get the GitHub token (real or fake depending on mode)."""
    if is_integration_mode():
        return os.environ["TEST_GITHUB_TOKEN"]
    return "fake-token-for-testing"


@pytest.fixture
def sample_event():
    """Sample GitHub pull_request event data."""
    return {
        "pull_request": {
            "number": 42,
            "title": "Fix critical bug in login",
            "base": {"ref": "main"},
            "head": {"ref": "feature/fix-login"},
        }
    }


@pytest.fixture
def github_env(monkeypatch):
    """Set up GitHub environment variables."""
    if is_integration_mode():
        monkeypatch.setenv("GITHUB_REPOSITORY", TEST_REPO)
    else:
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_API_URL", API_URL)
    monkeypatch.setenv("GITHUB_ACTOR", "test-actor")


@pytest.fixture
def github_api(github_token):
    """Provides a GitHub API helper for integration tests."""
    if not is_integration_mode():
        pytest.skip("Integration mode not enabled (set TEST_GITHUB_TOKEN)")
    helper = GitHubAPIHelper(github_token)
    yield helper
    helper.cleanup()
