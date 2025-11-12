"""Shared utilities for fetching GitHub metadata."""

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# GitHub API endpoint for repository info
GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}"


def extract_github_owner_repo(url: str) -> tuple[str, str] | None:
    """
    Extract owner and repo name from a GitHub URL.

    Supports various GitHub URL formats:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo.git
    - github.com/owner/repo

    Args:
        url: GitHub URL to parse

    Returns:
        Tuple of (owner, repo) or None if not a valid GitHub URL
    """
    if not url:
        return None

    # Match various GitHub URL formats
    # https://github.com/owner/repo or https://github.com/owner/repo.git
    # git@github.com:owner/repo.git
    match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", url)
    if match:
        owner, repo = match.groups()
        return (owner, repo)

    return None


async def fetch_github_stars(
    repo_url: str,
    client: httpx.AsyncClient,
    timeout: float = 5.0,
) -> int | None:
    """
    Fetch GitHub stars for a repository.

    Args:
        repo_url: GitHub repository URL
        client: HTTP client to use (should be async)
        timeout: Request timeout in seconds

    Returns:
        Number of stars, or None if unavailable
    """
    parsed = extract_github_owner_repo(repo_url)
    if not parsed:
        return None

    owner, repo = parsed

    try:
        url = GITHUB_API_URL.format(owner=owner, repo=repo)
        response = await client.get(url, timeout=timeout)

        if response.status_code == 200:
            data = response.json()
            stars = data.get("stargazers_count", 0)
            logger.debug(f"Fetched {stars} stars for {owner}/{repo}")
            return stars
        elif response.status_code == 404:
            logger.debug(f"Repository not found: {owner}/{repo}")
            return None
        elif response.status_code == 403:
            logger.warning(f"GitHub API rate limit hit for {owner}/{repo}")
            return None
        else:
            logger.debug(f"GitHub API returned {response.status_code} for {owner}/{repo}")
            return None
    except httpx.TimeoutException:
        logger.debug(f"Timeout fetching GitHub stars for {owner}/{repo}")
        return None
    except Exception as e:
        logger.debug(f"Failed to fetch GitHub stars for {owner}/{repo}: {e}")
        return None


async def fetch_github_metadata(
    repo_url: str,
    client: httpx.AsyncClient,
    timeout: float = 5.0,
) -> dict[str, Any] | None:
    """
    Fetch comprehensive GitHub metadata for a repository.

    Args:
        repo_url: GitHub repository URL
        client: HTTP client to use (should be async)
        timeout: Request timeout in seconds

    Returns:
        Dictionary with metadata:
        - stars: Number of stars
        - forks: Number of forks
        - watchers: Number of watchers
        - open_issues: Number of open issues
        - updated_at: Last update timestamp
        - created_at: Creation timestamp
        - language: Primary language
        - topics: List of topics/tags
    """
    parsed = extract_github_owner_repo(repo_url)
    if not parsed:
        return None

    owner, repo = parsed

    try:
        url = GITHUB_API_URL.format(owner=owner, repo=repo)
        response = await client.get(url, timeout=timeout)

        if response.status_code == 200:
            data = response.json()
            metadata = {
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "watchers": data.get("watchers_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "updated_at": data.get("updated_at"),
                "created_at": data.get("created_at"),
                "language": data.get("language"),
                "topics": data.get("topics", []),
                "description": data.get("description"),
                "homepage": data.get("homepage"),
            }
            logger.debug(f"Fetched metadata for {owner}/{repo}: {metadata['stars']} stars")
            return metadata
        else:
            logger.debug(f"GitHub API returned {response.status_code} for {owner}/{repo}")
            return None
    except Exception as e:
        logger.debug(f"Failed to fetch GitHub metadata for {owner}/{repo}: {e}")
        return None
