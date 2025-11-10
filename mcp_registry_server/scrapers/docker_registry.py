"""Docker MCP registry source integration via git cloning."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from git import Repo
from git.exc import GitCommandError

from ..models import LaunchMethod, RegistryEntry, SourceType

logger = logging.getLogger(__name__)

DOCKER_REGISTRY_REPO = "https://github.com/docker/mcp-registry.git"


async def clone_or_update_docker_registry(sources_dir: Path) -> Path | None:
    """Clone or update the Docker MCP registry repository.

    Args:
        sources_dir: Directory to store cloned repositories

    Returns:
        Path to the cloned repository or None on error
    """
    repo_dir = sources_dir / "docker-mcp-registry"

    try:
        if repo_dir.exists():
            logger.info(f"Updating Docker MCP registry at {repo_dir}")
            repo = Repo(repo_dir)
            origin = repo.remotes.origin
            # Run git pull in executor to avoid blocking
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: origin.pull("--ff-only")
            )
            logger.info("Successfully updated Docker MCP registry")
        else:
            logger.info(f"Cloning Docker MCP registry to {repo_dir}")
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: Repo.clone_from(DOCKER_REGISTRY_REPO, repo_dir)
            )
            logger.info("Successfully cloned Docker MCP registry")

        return repo_dir
    except GitCommandError as e:
        logger.error(f"Git operation failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to clone/update Docker registry: {e}")
        return None


def _parse_docker_registry_entry(
    entry_data: dict, entry_id: str
) -> RegistryEntry | None:
    """Parse a single Docker registry entry to RegistryEntry format.

    Args:
        entry_data: Raw entry data from Docker registry JSON
        entry_id: Entry identifier/key

    Returns:
        Normalized RegistryEntry or None if parsing fails
    """
    try:
        # Docker registry schema (based on CONTRIBUTING.md and examples)
        # Expected fields: name, description, image (or sourceRepository), category, tags, etc.

        name = entry_data.get("name") or entry_data.get("title") or entry_id
        description = entry_data.get("description", "")

        # Container image reference
        container_image = entry_data.get("image")
        repo_url = entry_data.get("sourceRepository") or entry_data.get("repository")

        # Categories and tags
        categories = []
        if "category" in entry_data:
            cat = entry_data["category"]
            categories = [cat] if isinstance(cat, str) else cat

        tags = entry_data.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        # Official/featured flags (Docker-built images are official)
        official = entry_data.get("official", False)
        if container_image and container_image.startswith("docker.io/mcp/"):
            official = True

        featured = entry_data.get("featured", False)

        # API key requirement
        requires_api_key = entry_data.get("requiresApiKey", False)

        # Tools (if pre-listed)
        tools = entry_data.get("tools", [])
        if isinstance(tools, str):
            tools = [tools]

        # Launch method
        launch_method = LaunchMethod.PODMAN if container_image else LaunchMethod.UNKNOWN

        return RegistryEntry(
            id=f"docker/{entry_id}",
            name=name,
            description=description,
            source=SourceType.DOCKER,
            repo_url=repo_url,
            container_image=container_image,
            categories=categories,
            tags=tags,
            official=official,
            featured=featured,
            requires_api_key=requires_api_key,
            tools=tools,
            launch_method=launch_method,
            raw_metadata=entry_data,
        )
    except Exception as e:
        logger.warning(f"Failed to parse Docker registry entry {entry_id}: {e}")
        return None


async def scrape_docker_registry(sources_dir: Path) -> list[RegistryEntry]:
    """Scrape the Docker MCP registry for entries.

    Args:
        sources_dir: Directory containing cloned sources

    Returns:
        List of normalized RegistryEntry objects
    """
    logger.info("Scraping Docker MCP registry")

    # Clone or update repository
    repo_dir = await clone_or_update_docker_registry(sources_dir)
    if not repo_dir:
        logger.error("Failed to clone/update Docker registry, returning empty list")
        return []

    entries = []

    # Look for JSON files or structured data in the repository
    # Docker registry structure may vary, so we check multiple patterns

    # Pattern 1: Single registry.json file
    registry_json = repo_dir / "registry.json"
    if registry_json.exists():
        try:
            with open(registry_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle different JSON structures
            servers = data
            if isinstance(data, dict):
                servers = data.get("servers") or data.get("mcpServers") or data

            if isinstance(servers, dict):
                # Key-value mapping
                for entry_id, entry_data in servers.items():
                    entry = _parse_docker_registry_entry(entry_data, entry_id)
                    if entry:
                        entries.append(entry)
            elif isinstance(servers, list):
                # List of entries
                for i, entry_data in enumerate(servers):
                    entry_id = (
                        entry_data.get("id") or entry_data.get("name") or f"entry-{i}"
                    )
                    entry = _parse_docker_registry_entry(entry_data, entry_id)
                    if entry:
                        entries.append(entry)
        except Exception as e:
            logger.error(f"Failed to parse registry.json: {e}")

    # Pattern 2: Multiple JSON files in a servers/ directory
    servers_dir = repo_dir / "servers"
    if servers_dir.exists() and servers_dir.is_dir():
        for json_file in servers_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    entry_data = json.load(f)

                entry_id = json_file.stem
                entry = _parse_docker_registry_entry(entry_data, entry_id)
                if entry:
                    entries.append(entry)
            except Exception as e:
                logger.warning(f"Failed to parse {json_file.name}: {e}")

    # Pattern 3: YAML files (if present, convert to dict)
    # TODO: Add YAML support if Docker registry uses it

    logger.info(f"Scraped {len(entries)} entries from Docker MCP registry")
    return entries
