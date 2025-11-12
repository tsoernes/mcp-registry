"""Docker MCP registry source integration via git cloning."""

import asyncio
import logging
from pathlib import Path

import httpx
import yaml
from git import Repo
from git.exc import GitCommandError

from ..models import LaunchMethod, RegistryEntry, SourceType
from .github_utils import fetch_github_stars

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
            await asyncio.get_event_loop().run_in_executor(None, lambda: origin.pull())
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


def _parse_docker_registry_entry(entry_data: dict, entry_id: str) -> RegistryEntry | None:
    """Parse a single Docker registry YAML entry to RegistryEntry format.

    Args:
        entry_data: Raw entry data from Docker registry server.yaml
        entry_id: Entry identifier/key (directory name)

    Returns:
        Normalized RegistryEntry or None if parsing fails
    """
    try:
        # Docker registry YAML schema:
        # name: string
        # image: string (e.g., "mcp/github")
        # type: "server"
        # meta:
        #   category: string
        #   tags: list[string]
        # about:
        #   title: string
        #   description: string
        #   icon: string (URL)
        # source:
        #   project: string (GitHub URL)
        #   branch: string
        #   commit: string
        #   dockerfile: string
        # config:
        #   secrets: list[{name, env, example}]
        #   parameters: object (JSON schema)

        name = entry_data.get("name") or entry_id

        # Get description from about section
        about = entry_data.get("about", {})
        title = about.get("title", name)
        description = about.get("description", "")

        # Container image reference
        container_image = entry_data.get("image")
        if container_image and not container_image.startswith("docker.io/"):
            # Prepend docker.io/ if not present
            container_image = f"docker.io/{container_image}"

        # Get source repository
        source = entry_data.get("source", {})
        repo_url = source.get("project")

        # Categories and tags from meta
        meta = entry_data.get("meta", {})
        category = meta.get("category")
        categories = [category] if category else []

        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]

        # Docker-built images are official
        official = bool(container_image and container_image.startswith("docker.io/mcp/"))

        # Featured flag (not in YAML schema currently)
        featured = entry_data.get("featured", False)

        # Check for API key requirements from config.secrets
        requires_api_key = False
        config = entry_data.get("config", {})
        secrets = config.get("secrets", [])
        if secrets:
            requires_api_key = True

        # Tools (will be discovered on activation)
        tools = []

        # Launch method
        launch_method = LaunchMethod.PODMAN if container_image else LaunchMethod.UNKNOWN

        return RegistryEntry(
            id=f"docker/{entry_id}",
            name=title or name,
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
        logger.warning(f"Failed to parse Docker registry entry {entry_id}: {e}", exc_info=True)
        return None


async def scrape_docker_registry(
    sources_dir: Path,
    fetch_github_stars_flag: bool = True,
) -> list[RegistryEntry]:
    """Scrape the Docker MCP registry for entries.

    Args:
        sources_dir: Directory containing cloned sources
        fetch_github_stars_flag: Whether to fetch GitHub stars for popularity ranking

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

    # Docker MCP registry structure:
    # servers/
    #   <server-name>/
    #     server.yaml
    #     readme.md (optional)

    servers_dir = repo_dir / "servers"
    if not servers_dir.exists() or not servers_dir.is_dir():
        logger.warning(f"No servers/ directory found in {repo_dir}")
        return []

    # Iterate through server directories
    for server_dir in servers_dir.iterdir():
        if not server_dir.is_dir():
            continue

        # Look for server.yaml file
        yaml_file = server_dir / "server.yaml"
        if not yaml_file.exists():
            logger.debug(f"No server.yaml found in {server_dir.name}, skipping")
            continue

        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                entry_data = yaml.safe_load(f)

            if not entry_data:
                logger.warning(f"Empty YAML in {server_dir.name}/server.yaml")
                continue

            # Use directory name as entry_id
            entry_id = server_dir.name
            entry = _parse_docker_registry_entry(entry_data, entry_id)
            if entry:
                entries.append(entry)
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML {server_dir.name}/server.yaml: {e}")
        except Exception as e:
            logger.warning(f"Failed to process {server_dir.name}: {e}", exc_info=True)

    # Fetch GitHub stars for all entries with repo URLs
    if fetch_github_stars_flag and entries:
        logger.info(f"Fetching GitHub stars for {len(entries)} Docker registry entries")
        async with httpx.AsyncClient(timeout=5.0) as client:
            for entry in entries:
                if entry.repo_url:
                    stars = await fetch_github_stars(entry.repo_url, client)
                    if stars is not None:
                        entry.raw_metadata["github_stars"] = stars

    logger.info(
        f"Scraped {len(entries)} entries from Docker MCP registry "
        f"(official={sum(1 for e in entries if e.official)})"
    )
    return entries
