"""
MCP Official Registry Scraper

Fetches server metadata from the official MCP Registry at registry.modelcontextprotocol.io
"""

import asyncio
import logging
import re
from typing import Any

import httpx

from ..models import LaunchMethod, RegistryEntry, SourceType

logger = logging.getLogger(__name__)

# Official MCP Registry API endpoint
REGISTRY_API_URL = "https://registry.modelcontextprotocol.io/v0/servers"

# GitHub API endpoint for repository info
GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}"


async def _fetch_github_stars(
    repo_url: str,
    client: httpx.AsyncClient,
) -> int | None:
    """
    Fetch GitHub stars for a repository.

    Args:
        repo_url: GitHub repository URL
        client: HTTP client to use

    Returns:
        Number of stars, or None if unavailable
    """
    # Extract owner/repo from URL
    # Format: https://github.com/owner/repo or https://github.com/owner/repo.git
    match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", repo_url)
    if not match:
        return None

    owner, repo = match.groups()

    try:
        url = GITHUB_API_URL.format(owner=owner, repo=repo)
        response = await client.get(url, timeout=5.0)

        if response.status_code == 200:
            data = response.json()
            stars = data.get("stargazers_count", 0)
            logger.debug(f"Fetched {stars} stars for {owner}/{repo}")
            return stars
        else:
            logger.debug(f"GitHub API returned {response.status_code} for {owner}/{repo}")
            return None
    except Exception as e:
        logger.debug(f"Failed to fetch GitHub stars for {owner}/{repo}: {e}")
        return None


async def scrape_mcp_official_registry(
    limit: int | None = None,
    timeout: float = 30.0,
    fetch_github_stars: bool = True,
) -> list[RegistryEntry]:
    """
    Scrape server metadata from the official MCP Registry API.

    The API is stable (v0.1 freeze) and provides comprehensive metadata about
    published MCP servers.

    Args:
        limit: Maximum number of servers to fetch (None = all servers)
        timeout: Request timeout in seconds
        fetch_github_stars: Whether to fetch GitHub stars for popularity ranking

    Returns:
        List of normalized RegistryEntry objects
    """
    logger.info("Starting MCP Official Registry scrape")
    entries: list[RegistryEntry] = []

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Fetch all servers (API supports pagination)
            url = REGISTRY_API_URL
            if limit:
                url = f"{url}?limit={limit}"

            logger.debug(f"Fetching from {url}")
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()
            servers = data.get("servers", [])

            logger.info(f"Retrieved {len(servers)} servers from MCP Official Registry")

            for server_data in servers:
                try:
                    entry = _normalize_server(server_data)
                    if entry:
                        # Fetch GitHub stars if enabled and repo URL exists
                        if fetch_github_stars and entry.repo_url:
                            stars = await _fetch_github_stars(entry.repo_url, client)
                            if stars is not None:
                                entry.raw_metadata["github_stars"] = stars
                        entries.append(entry)
                except Exception as e:
                    server_name = server_data.get("server", {}).get("name", "unknown")
                    logger.warning(
                        f"Failed to normalize server {server_name}: {e}",
                        exc_info=True,
                    )

    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching MCP Official Registry: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Error scraping MCP Official Registry: {e}", exc_info=True)
        raise

    logger.info(f"Successfully scraped {len(entries)} entries from MCP Official Registry")
    return entries


def _normalize_server(server_data: dict[str, Any]) -> RegistryEntry | None:
    """
    Normalize a server entry from the MCP Official Registry API.

    Server data structure:
    {
        "server": {
            "$schema": "...",
            "name": "io.github.user/server-name",
            "description": "...",
            "repository": {"url": "...", "source": "github"},
            "version": "1.0.0",
            "packages": [...],  # OCI containers, NPM, PyPI
            "remotes": [...],   # HTTP/SSE endpoints
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "publishedAt": "...",
                "updatedAt": "...",
                "isLatest": true,
                "serverId": "...",
                "versionId": "..."
            }
        }
    }
    """
    server = server_data.get("server", {})
    meta = server_data.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})

    # Skip inactive servers
    if meta.get("status") != "active":
        return None

    # Only include latest versions to avoid duplicates
    if not meta.get("isLatest", False):
        return None

    name = server.get("name", "")
    if not name:
        logger.warning("Server missing name, skipping")
        return None

    # Extract basic info
    description = server.get("description", "")
    version = server.get("version", "")

    # Repository info
    repo_data = server.get("repository", {})
    repo_url = repo_data.get("url", "")

    # Determine launch method and container image
    launch_method = LaunchMethod.UNKNOWN
    container_image = None

    # Check for packages (OCI containers, NPM, PyPI)
    packages = server.get("packages", [])
    if packages:
        for package in packages:
            registry_type = package.get("registryType", "")
            if registry_type == "oci":
                launch_method = LaunchMethod.PODMAN
                container_image = package.get("identifier", "")
                break
            elif registry_type == "npm":
                launch_method = LaunchMethod.STDIO_PROXY
                break
            elif registry_type == "pypi":
                launch_method = LaunchMethod.STDIO_PROXY
                break

    # Check for remote endpoints (HTTP/SSE)
    remotes = server.get("remotes", [])
    if remotes and launch_method == LaunchMethod.UNKNOWN:
        for remote in remotes:
            remote_type = remote.get("type", "")
            if remote_type in ("streamable-http", "sse"):
                launch_method = LaunchMethod.REMOTE_HTTP
                break

    # Extract categories from name prefix (e.g., "io.github" -> "github")
    categories = []
    if "." in name:
        parts = name.split(".")
        # Add source as category (github, gitlab, etc.)
        if len(parts) >= 2:
            categories.append(parts[1])  # e.g., "github" from "io.github.user/server"

    # Extract tags from description (simple keyword extraction)
    tags = _extract_tags_from_description(description)

    # Check if requires API key
    requires_api_key = False
    for package in packages:
        env_vars = package.get("environmentVariables", [])
        for var in env_vars:
            var_name = var.get("name", "").upper()
            if "API" in var_name or "KEY" in var_name or "TOKEN" in var_name:
                requires_api_key = True
                break
        if requires_api_key:
            break

    # Create slug from name (use full name as ID for official registry)
    # Format: "io.github.user/server-name" -> "mcp-official-io-github-user-server-name"
    entry_id = f"mcp-official-{name.replace('.', '-').replace('/', '-')}"

    # Track official and featured status
    official = True  # All entries from official registry are official
    featured = False  # Could be determined from metadata if available

    return RegistryEntry(
        id=entry_id,
        name=name,
        description=description,
        source=SourceType.MCP_OFFICIAL,
        repo_url=repo_url,
        container_image=container_image,
        categories=categories,
        tags=tags,
        official=official,
        featured=featured,
        requires_api_key=requires_api_key,
        launch_method=launch_method,
        server_command=None,  # Will be determined at launch time
        raw_metadata={
            "version": version,
            "published_at": meta.get("publishedAt"),
            "updated_at": meta.get("updatedAt"),
            "server_id": meta.get("serverId"),
            "version_id": meta.get("versionId"),
            "schema": server.get("$schema"),
        },
    )


def _extract_tags_from_description(description: str) -> list[str]:
    """
    Extract tags from description using simple keyword matching.

    This is a heuristic approach - we look for common technology keywords.
    """
    tags = []

    # Common technology keywords to look for
    keywords = [
        "github",
        "gitlab",
        "database",
        "sql",
        "api",
        "web",
        "search",
        "file",
        "cloud",
        "aws",
        "azure",
        "gcp",
        "docker",
        "kubernetes",
        "ai",
        "ml",
        "data",
        "analytics",
        "security",
        "auth",
        "slack",
        "discord",
        "notion",
        "openai",
        "anthropic",
    ]

    description_lower = description.lower()
    for keyword in keywords:
        if keyword in description_lower:
            tags.append(keyword)

    return tags[:10]  # Limit to 10 tags
