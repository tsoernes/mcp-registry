"""Wrapper for mcpservers.org scraper with normalization to RegistryEntry format."""

import asyncio
import logging
import sys
from pathlib import Path

# Add scripts directory to path to import existing scraper
scripts_dir = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from scrape_mcpservers import ServerInfo, scrape_all_servers

from ..models import LaunchMethod, RegistryEntry, ServerCommand, SourceType

logger = logging.getLogger(__name__)


def _normalize_server_info(server: ServerInfo) -> RegistryEntry:
    """Convert ServerInfo from scraper to RegistryEntry format.

    Args:
        server: ServerInfo from mcpservers.org scraper

    Returns:
        Normalized RegistryEntry
    """
    # Generate stable ID from URL
    entry_id = server.url.replace("https://mcpservers.org/servers/", "").rstrip("/")
    if not entry_id:
        # Fallback to name-based ID
        entry_id = server.name.lower().replace(" ", "-").replace("_", "-")

    # Determine launch method and command configuration
    launch_method = LaunchMethod.UNKNOWN
    container_image = None
    server_command = None

    # Check for npm package (npx-based servers)
    if server.npm_package:
        launch_method = LaunchMethod.STDIO_PROXY
        server_command = ServerCommand(
            command="npx",
            args=["-y", server.npm_package],
            env={},
        )
    # Check for Python package (python-based servers)
    elif server.pypi_package:
        launch_method = LaunchMethod.STDIO_PROXY
        server_command = ServerCommand(
            command="python",
            args=["-m", server.pypi_package],
            env={},
        )
    # Check for GitHub repo (might have container or be source-based)
    elif server.github_url:
        # Try to infer Docker Hub image from GitHub URL
        # Pattern: github.com/org/repo -> docker.io/mcp/repo
        try:
            parts = server.github_url.replace("https://github.com/", "").split("/")
            if len(parts) >= 2:
                org, repo = parts[0], parts[1]
                # Check if it might be in mcp/ namespace (official)
                if server.official:
                    container_image = f"docker.io/mcp/{repo}"
                    launch_method = LaunchMethod.PODMAN
                else:
                    # Assume stdio-proxy for non-official GitHub repos
                    launch_method = LaunchMethod.STDIO_PROXY
        except Exception:
            pass

    return RegistryEntry(
        id=f"mcpservers/{entry_id}",
        name=server.name,
        description=server.description or "",
        source=SourceType.MCPSERVERS,
        repo_url=server.github_url,
        container_image=container_image,
        categories=server.categories if server.categories else [],
        tags=server.categories if server.categories else [],  # Use categories as tags
        official=server.official or False,
        featured=server.featured or False,
        requires_api_key=server.requires_api_key or False,
        tools=[],  # Will be discovered on activation
        launch_method=launch_method,
        server_command=server_command,
        raw_metadata={
            "url": server.url,
            "npm_package": server.npm_package,
            "pypi_package": server.pypi_package,
            "author": server.author,
            "api_key_evidence": server.api_key_evidence,
            "api_env_vars": server.api_env_vars,
            "install_instructions": server.install_instructions,
        },
    )


async def scrape_mcpservers_org(
    concurrency: int = 50,
    limit: int | None = None,
    use_cache: bool = True,
    cache_dir: str | None = None,
) -> list[RegistryEntry]:
    """Scrape mcpservers.org and return normalized registry entries.

    Args:
        concurrency: Number of concurrent HTTP requests
        limit: Optional limit on number of servers to scrape
        use_cache: Whether to use cached HTML pages
        cache_dir: Cache directory for HTML pages

    Returns:
        List of normalized RegistryEntry objects
    """
    logger.info(f"Scraping mcpservers.org (concurrency={concurrency}, limit={limit})")

    # Call the existing scraper in executor to avoid blocking event loop
    loop = asyncio.get_event_loop()
    servers = await loop.run_in_executor(
        None,
        lambda: scrape_all_servers(
            limit=limit,
            concurrency=concurrency,
            cache_dir=cache_dir or ".cache/html",
            meta_cache_dir=cache_dir or ".cache/meta",
            resume=use_cache,
            force_refresh=not use_cache,
            use_categories=True,  # Always use categories for rich metadata
            use_sitemap=False,
            http2=False,
            max_connections=128,
            max_keepalive=32,
            strict_official=False,
        ),
    )

    logger.info(f"Scraped {len(servers)} servers from mcpservers.org")

    # Normalize to RegistryEntry format
    entries = []
    for server in servers:
        try:
            entry = _normalize_server_info(server)
            entries.append(entry)
        except Exception as e:
            logger.warning(
                f"Failed to normalize server {server.name}: {e}", exc_info=True
            )
            continue

    logger.info(
        f"Normalized {len(entries)} entries from mcpservers.org "
        f"(official={sum(1 for e in entries if e.official)}, "
        f"featured={sum(1 for e in entries if e.featured)})"
    )

    return entries
