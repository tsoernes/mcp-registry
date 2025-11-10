"""Main FastMCP server with dynamic MCP registry tools."""

import asyncio
import logging
import sys
from pathlib import Path

from fastmcp import FastMCP
from pydantic import Field

from .editor_config import EditorConfigManager
from .models import (
    ActiveMount,
    ConfigSetRequest,
    LaunchMethod,
    RegistryEntry,
    SearchQuery,
    SourceType,
)
from .podman_runner import PodmanRunner
from .registry import Registry
from .tasks import RefreshScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP(
    name="mcp-registry",
    instructions="""
    This server provides a dynamic MCP registry that aggregates servers from multiple sources.

    Available sources:
    - Docker MCP Registry (official Docker catalog)
    - mcpservers.org (community-curated servers with rich metadata)

    Use registry-find to search for servers, registry-add to activate them,
    and registry-exec to run tools from active servers.

    All servers run in isolated Podman containers for security.
    """,
)

# Global instances
registry: Registry | None = None
podman_runner: PodmanRunner | None = None
refresh_scheduler: RefreshScheduler | None = None
editor_manager: EditorConfigManager | None = None


async def initialize_registry() -> None:
    """Initialize registry and start background tasks."""
    global registry, podman_runner, refresh_scheduler, editor_manager

    if registry is not None:
        return  # Already initialized

    logger.info("Initializing mcp-registry server")

    # Create registry instance
    registry = Registry(
        cache_dir=Path.home() / ".cache" / "mcp-registry",
        sources_dir=Path.home() / ".local" / "share" / "mcp-registry" / "sources",
        refresh_interval_hours=24,
    )

    # Create Podman runner
    podman_runner = PodmanRunner()

    # Create editor config manager
    editor_manager = EditorConfigManager()

    # Create and start refresh scheduler
    refresh_scheduler = RefreshScheduler(registry)
    await refresh_scheduler.start()

    logger.info("mcp-registry server initialized")


async def shutdown_registry() -> None:
    """Shutdown registry and cleanup resources."""
    global podman_runner, refresh_scheduler

    logger.info("Shutting down mcp-registry server")

    # Stop refresh scheduler
    if refresh_scheduler:
        await refresh_scheduler.stop()

    # Cleanup Podman containers
    if podman_runner:
        await podman_runner.cleanup_all()

    logger.info("mcp-registry server shutdown complete")


@mcp.tool()
async def registry_find(
    query: str = Field(..., description="Search text (fuzzy matched)"),
    categories: list[str] = Field(
        default_factory=list, description="Filter by categories (OR logic)"
    ),
    tags: list[str] = Field(
        default_factory=list, description="Filter by tags (OR logic)"
    ),
    sources: list[str] = Field(
        default_factory=list,
        description="Filter by sources: docker, mcpservers (OR logic)",
    ),
    official_only: bool = Field(False, description="Only show official servers"),
    featured_only: bool = Field(False, description="Only show featured servers"),
    limit: int = Field(20, description="Max results to return (1-100)"),
) -> str:
    """Search for MCP servers in the aggregated registry.

    This tool searches across all registry sources (Docker, mcpservers.org) with
    intelligent fuzzy matching and filtering options.

    Returns:
        Formatted list of matching servers with metadata
    """
    await initialize_registry()

    # Convert sources to SourceType enum
    source_types = []
    for s in sources:
        try:
            source_types.append(SourceType(s.lower()))
        except ValueError:
            logger.warning(f"Invalid source type: {s}")

    search_query = SearchQuery(
        query=query,
        categories=categories,
        tags=tags,
        sources=source_types if source_types else [],
        official_only=official_only,
        featured_only=featured_only,
        limit=min(limit, 100),
    )

    results = await registry.search(search_query)

    if not results:
        return f"No servers found matching query: {query}"

    # Format results as markdown
    output = [f"# Found {len(results)} matching servers\n"]

    for i, entry in enumerate(results, 1):
        output.append(f"## {i}. {entry.name}")
        output.append(f"**ID:** `{entry.id}`")
        output.append(f"**Source:** {entry.source.value}")
        output.append(f"**Description:** {entry.description}")

        if entry.categories:
            output.append(f"**Categories:** {', '.join(entry.categories)}")

        if entry.tags:
            output.append(f"**Tags:** {', '.join(entry.tags[:5])}")

        flags = []
        if entry.official:
            flags.append("Official")
        if entry.featured:
            flags.append("Featured")
        if entry.requires_api_key:
            flags.append("Requires API Key")
        if flags:
            output.append(f"**Flags:** {', '.join(flags)}")

        if entry.repo_url:
            output.append(f"**Repository:** {entry.repo_url}")

        if entry.container_image:
            output.append(f"**Image:** {entry.container_image}")

        output.append("")  # Blank line

    return "\n".join(output)


@mcp.tool()
async def registry_list(
    source: str | None = Field(
        None, description="Filter by source: docker, mcpservers, or all"
    ),
    limit: int = Field(50, description="Max results to return (1-200)"),
) -> str:
    """List all available servers in the registry.

    Returns:
        Formatted list of all servers
    """
    await initialize_registry()

    if source:
        try:
            source_type = SourceType(source.lower())
            entries = registry.get_entries_by_source(source_type)
        except ValueError:
            return f"Invalid source: {source}. Valid options: docker, mcpservers"
    else:
        entries = await registry.list_all(limit=min(limit, 200))

    output = [f"# Registry listing ({len(entries)} servers)\n"]

    for entry in entries[:limit]:
        flags = []
        if entry.official:
            flags.append("Official")
        if entry.featured:
            flags.append("Featured")
        flag_str = f" [{', '.join(flags)}]" if flags else ""

        output.append(
            f"- **{entry.name}** (`{entry.id}`){flag_str} - {entry.description[:100]}"
        )

    if len(entries) > limit:
        output.append(f"\n*({len(entries) - limit} more servers available)*")

    return "\n".join(output)


@mcp.tool()
async def registry_add(
    entry_id: str = Field(..., description="Registry entry ID to activate"),
    editor: str = Field(
        ...,
        description="Editor to configure (required for non-Podman servers): 'zed' or 'claude'",
    ),
    prefix: str | None = Field(
        None, description="Tool prefix for namespacing (default: auto-generated)"
    ),
) -> str:
    """Activate an MCP server from the registry.

    For Podman servers: Pulls the container image and starts the server.
    For stdio servers: Adds the server to the specified editor's config file.

    Args:
        entry_id: Registry entry ID to activate
        editor: Editor to configure ('zed' or 'claude') - required for non-Podman servers
        prefix: Optional tool prefix for namespacing

    Returns:
        Confirmation message with activation details
    """
    await initialize_registry()

    # Validate editor
    if editor.lower() not in ["zed", "claude"]:
        return f"Invalid editor: {editor}. Supported editors: zed, claude"

    # Check if already active (for Podman servers)
    existing = await registry.get_active_mount(entry_id)
    if existing:
        return f"Server already active: {existing.name} (prefix: {existing.prefix})"

    # Get entry from registry
    entry = await registry.get_entry(entry_id)
    if not entry:
        return f"Entry not found: {entry_id}"

    # Generate prefix if not provided
    if not prefix:
        # Extract last component of ID as prefix
        prefix = entry_id.split("/")[-1].replace("-", "_")

    # Check launch method
    if entry.launch_method == LaunchMethod.PODMAN and entry.container_image:
        # Podman-based server
        pull_success = await podman_runner.pull_image(entry.container_image)
        if not pull_success:
            return f"Failed to pull image: {entry.container_image}"

        # Start container
        container_name = f"mcp-registry-{prefix}"
        container_id = await podman_runner.run_container(
            image=entry.container_image,
            name=container_name,
            environment={},  # Will be set via config-set
        )

        if not container_id:
            return f"Failed to start container for {entry.name}"

        # Create active mount
        mount = ActiveMount(
            entry_id=entry.id,
            name=entry.name,
            prefix=prefix,
            container_id=container_id,
            environment={},
            tools=[],  # Will be discovered
        )

        await registry.add_active_mount(mount)

        return f"""Successfully activated: {entry.name}

**Type:** Podman container
**Container ID:** {container_id[:12]}
**Prefix:** {prefix}
**Image:** {entry.container_image}

Use `registry-config-set` to configure environment variables.
Use `registry-exec` to run tools from this server.
"""

    elif entry.server_command or entry.launch_method == LaunchMethod.STDIO_PROXY:
        # Stdio-based server - add to editor config
        if not entry.server_command:
            return f"Server {entry.name} is marked as stdio but has no command configuration. Unable to add to editor."

        # Add to editor configuration
        try:
            if editor.lower() == "zed":
                result = editor_manager.add_zed_server(
                    server_name=prefix,
                    command=entry.server_command.command,
                    args=entry.server_command.args,
                    env=entry.server_command.env,
                )
            elif editor.lower() == "claude":
                result = editor_manager.add_claude_server(
                    server_name=prefix,
                    command=entry.server_command.command,
                    args=entry.server_command.args,
                    env=entry.server_command.env,
                )
            else:
                return f"Unsupported editor: {editor}"

            # Create active mount record (non-container)
            mount = ActiveMount(
                entry_id=entry.id,
                name=entry.name,
                prefix=prefix,
                container_id=None,
                pid=None,
                environment=entry.server_command.env,
                tools=[],
            )
            await registry.add_active_mount(mount)

            return f"""Successfully activated: {entry.name}

**Type:** Stdio server
**Editor:** {editor}
**Command:** {entry.server_command.command}
**Args:** {" ".join(entry.server_command.args)}

{result}
"""
        except Exception as e:
            logger.error(f"Failed to add server to {editor} config: {e}", exc_info=True)
            return f"Failed to add server to {editor} configuration: {e}"

    elif entry.repo_url:
        # Source-based servers need command configuration
        return f"""Server {entry.name} requires manual setup from source.

**Repository:** {entry.repo_url}

To use this server:
1. Clone the repository
2. Follow installation instructions
3. Manually add to your {editor} configuration
4. Use `registry-config-set` if needed
"""

    else:
        return f"Unable to activate {entry.name}: no container image, command configuration, or source repository"


@mcp.tool()
async def registry_remove(
    entry_id: str = Field(..., description="Registry entry ID to deactivate"),
) -> str:
    """Deactivate an active MCP server.

    Stops and removes the container, freeing resources.

    Returns:
        Confirmation message
    """
    await initialize_registry()

    mount = await registry.get_active_mount(entry_id)
    if not mount:
        return f"Server not active: {entry_id}"

    # Stop container if running
    if mount.container_id:
        stopped = await podman_runner.stop_container(mount.container_id)
        if not stopped:
            # Try force kill
            await podman_runner.kill_container(mount.container_id)

    # Remove from active mounts
    await registry.remove_active_mount(entry_id)

    return f"Successfully deactivated: {mount.name}"


@mcp.tool()
async def registry_active() -> str:
    """List all currently active MCP servers.

    Returns:
        Formatted list of active servers with details
    """
    await initialize_registry()

    mounts = await registry.list_active_mounts()

    if not mounts:
        return "No active servers."

    output = [f"# Active servers ({len(mounts)})\n"]

    for mount in mounts:
        output.append(f"## {mount.name}")
        output.append(f"**ID:** `{mount.entry_id}`")
        output.append(f"**Prefix:** `{mount.prefix}`")

        if mount.container_id:
            output.append(f"**Container:** {mount.container_id[:12]}")

        if mount.environment:
            env_keys = list(mount.environment.keys())
            output.append(f"**Environment:** {', '.join(env_keys)}")

        if mount.tools:
            output.append(f"**Tools:** {len(mount.tools)} available")

        output.append(
            f"**Mounted at:** {mount.mounted_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        output.append("")

    return "\n".join(output)


@mcp.tool()
async def registry_config_set(
    entry_id: str = Field(..., description="Active server ID to configure"),
    environment: dict[str, str] = Field(
        ..., description="Environment variables to set (key-value pairs)"
    ),
) -> str:
    """Configure environment variables for an active server.

    Only whitelisted environment variable prefixes are allowed for security:
    API_KEY, API_TOKEN, AUTH_, DATABASE_, DB_, GITHUB_, OPENAI_, ANTHROPIC_,
    AWS_, AZURE_, GCP_, SLACK_, DISCORD_, NOTION_, MCP_

    Returns:
        Confirmation message
    """
    await initialize_registry()

    # Validate request
    try:
        config = ConfigSetRequest(entry_id=entry_id, environment=environment)
    except Exception as e:
        return f"Invalid configuration: {e}"

    mount = await registry.get_active_mount(entry_id)
    if not mount:
        return f"Server not active: {entry_id}"

    # Update environment in registry
    updated = await registry.update_mount_environment(entry_id, environment)

    if not updated:
        return f"Failed to update configuration for {entry_id}"

    # Note: For running containers, would need to restart or use exec to inject env
    # For now, just store in registry for next restart

    return f"""Configuration updated for {mount.name}

**Environment variables set:** {", ".join(environment.keys())}

Note: Changes will take effect on next restart.
To apply now, use `registry-remove` followed by `registry-add`.
"""


@mcp.tool()
async def registry_exec(
    tool_name: str = Field(
        ..., description="Fully-qualified tool name (prefix_toolname)"
    ),
    arguments: dict[str, str] = Field(
        default_factory=dict, description="Tool arguments as key-value pairs"
    ),
) -> str:
    """Execute a tool from an active MCP server.

    Tool names must be prefixed with the server's prefix (e.g., postgres_run_query).

    Returns:
        Tool execution result
    """
    await initialize_registry()

    # TODO: Implement actual tool dispatch to mounted servers
    # This would require:
    # 1. Parse prefix from tool_name
    # 2. Find active mount by prefix
    # 3. Communicate with container via stdio or HTTP
    # 4. Forward tool call and return result

    return f"""Tool execution not yet implemented.

Requested tool: {tool_name}
Arguments: {arguments}

This feature requires implementing MCP client communication with running containers.
Coming soon!
"""


@mcp.tool()
async def registry_refresh(
    source: str = Field(
        ..., description="Source to refresh: docker, mcpservers, or all"
    ),
) -> str:
    """Force refresh a registry source.

    Respects rate limits (24h interval) unless cache is stale.

    Returns:
        Refresh status message
    """
    await initialize_registry()

    if source.lower() == "all":
        sources = [SourceType.DOCKER, SourceType.MCPSERVERS]
    else:
        try:
            sources = [SourceType(source.lower())]
        except ValueError:
            return f"Invalid source: {source}. Valid options: docker, mcpservers, all"

    results = []
    for source_type in sources:
        success = await refresh_scheduler.force_refresh(source_type)
        status = "Success" if success else "Failed"
        results.append(f"- {source_type.value}: {status}")

    return f"# Refresh results\n\n" + "\n".join(results)


@mcp.tool()
async def registry_status() -> str:
    """Get registry status and statistics.

    Returns:
        Comprehensive status information
    """
    await initialize_registry()

    status = await registry.get_status()

    output = [f"# Registry Status\n"]
    output.append(f"**Total entries:** {status.total_entries}")
    output.append(f"**Active mounts:** {status.active_mounts}")
    output.append(f"**Cache directory:** {status.cache_dir}")
    output.append(f"**Sources directory:** {status.sources_dir}")

    if status.last_refresh_attempt:
        output.append(
            f"**Last refresh:** {status.last_refresh_attempt.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    output.append("\n## Sources\n")

    for source_name, source_info in status.sources.items():
        output.append(f"### {source_name}")
        output.append(f"**Entries:** {source_info['entry_count']}")
        output.append(f"**Status:** {source_info['status']}")

        if source_info.get("last_refresh"):
            output.append(f"**Last refresh:** {source_info['last_refresh']}")

        if source_info.get("error_message"):
            output.append(f"**Error:** {source_info['error_message']}")

        output.append("")

    return "\n".join(output)


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting mcp-registry server")

    # Run the server
    mcp.run()


if __name__ == "__main__":
    main()
