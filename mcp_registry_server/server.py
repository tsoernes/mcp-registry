"""Main FastMCP server with dynamic MCP registry tools."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import Field

from .mcp_client import MCPClient, MCPClientManager
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
from .schema_converter import convert_tool_to_function, validate_tool_schema
from .stdio_runner import (
    StdioServerRunner,
    parse_server_command,
    validate_command_available,
)
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
stdio_runner: StdioServerRunner | None = None
refresh_scheduler: RefreshScheduler | None = None
mcp_client_manager: MCPClientManager | None = None

# Track dynamically registered tools for cleanup
_dynamic_tools: dict[str, list[str]] = {}  # container_id -> [tool_names]


async def initialize_registry() -> None:
    """Initialize registry and start background tasks."""
    global registry, podman_runner, stdio_runner, refresh_scheduler, mcp_client_manager

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

    # Create stdio runner
    stdio_runner = StdioServerRunner()

    # Create MCP client manager
    mcp_client_manager = MCPClientManager()

    # Create and start refresh scheduler
    refresh_scheduler = RefreshScheduler(registry)
    await refresh_scheduler.start()

    logger.info("mcp-registry server initialized")


async def shutdown_registry() -> None:
    """Shutdown registry and cleanup resources."""
    global podman_runner, stdio_runner, refresh_scheduler, mcp_client_manager

    logger.info("Shutting down mcp-registry server")

    # Stop refresh scheduler
    if refresh_scheduler:
        await refresh_scheduler.stop()

    # Close all MCP clients
    if mcp_client_manager:
        await mcp_client_manager.close_all()

    # Cleanup Podman containers
    if podman_runner:
        await podman_runner.cleanup_all()

    # Cleanup stdio servers
    if stdio_runner:
        await stdio_runner.cleanup_all()

    logger.info("mcp-registry server shutdown complete")


@mcp.tool(name="mcp_registry_find")
async def registry_find(
    query: str = Field(..., description="Search text (fuzzy matched)"),
    categories: list[str] = Field(
        default_factory=list, description="Filter by categories (OR logic)"
    ),
    tags: list[str] = Field(default_factory=list, description="Filter by tags (OR logic)"),
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


@mcp.tool(name="mcp_registry_list")
async def registry_list(
    source: str | None = Field(None, description="Filter by source: docker, mcpservers, or all"),
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

        output.append(f"- **{entry.name}** (`{entry.id}`){flag_str} - {entry.description[:100]}")

    if len(entries) > limit:
        output.append(f"\n*({len(entries) - limit} more servers available)*")

    return "\n".join(output)


@mcp.tool(name="mcp_registry_get_docs")
async def registry_get_docs(
    entry_id: str = Field(..., description="Registry entry ID to get documentation for"),
) -> str:
    """Get documentation and setup instructions for an MCP server.

    Returns:
        Formatted documentation including setup instructions, usage examples,
        and configuration requirements
    """
    await initialize_registry()

    entry = await registry.get_entry(entry_id)
    if not entry:
        return f"Entry not found: {entry_id}"

    return entry.get_documentation()


@mcp.tool(name="mcp_registry_launch_stdio")
async def registry_launch_stdio(
    command: str = Field(..., description="Command to execute (e.g., 'npx', 'python', 'node')"),
    prefix: str = Field(..., description="Tool prefix for namespacing (e.g., 'filesystem')"),
    args: list[str] | None = Field(None, description="Command arguments"),
    env: dict[str, str] | None = Field(
        None,
        description="Environment variables (e.g., {'API_KEY': 'your-key'})",
    ),
) -> str:
    """Launch a stdio-based MCP server with custom command, args, and environment.

    This allows you to start any stdio MCP server directly without needing a
    registry entry. Useful for:
    - Testing new MCP servers
    - Running local MCP servers
    - Using servers with custom configurations

    Examples:
        command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        command="python", args=["-m", "my_mcp_server"]
        command="node", args=["server.js", "--verbose"]

    Args:
        command: Base command to execute
        args: List of arguments to pass to the command
        env: Environment variables to set
        prefix: Tool prefix for namespacing the discovered tools

    Returns:
        Confirmation message with activation details
    """
    await initialize_registry()

    # Validate command is available
    is_available, message = await validate_command_available(command)
    if not is_available:
        return f"Command validation failed:\n{message}"

    # Generate unique server ID
    server_id = f"stdio-{prefix}"

    # Check if already active
    existing = await registry.get_active_mount(server_id)
    if existing:
        return f"Server already active with prefix '{prefix}'. Use a different prefix or remove the existing server first."

    try:
        # Spawn the stdio server
        args = args or []
        env = env or {}
        logger.info(f"Launching stdio server: {command} {' '.join(args)}")
        server_id, process = await stdio_runner.spawn_server(
            server_id=server_id,
            command=command,
            args=args,
            env=env,
        )

        # Create MCP client for this process
        client = MCPClient(process)

        # Initialize the MCP connection
        logger.info(f"Initializing MCP client for stdio server...")
        capabilities = await asyncio.wait_for(client.initialize(), timeout=30.0)
        logger.info(f"MCP client initialized: {capabilities}")

        # Discover tools
        logger.info(f"Discovering tools from stdio server...")
        tools = await asyncio.wait_for(client.list_tools(), timeout=30.0)
        tool_names = [tool.get("name", "unknown") for tool in tools]
        logger.info(f"Discovered {len(tool_names)} tools: {tool_names}")

        # Discover resources
        logger.info(f"Discovering resources from stdio server...")
        resources = await asyncio.wait_for(client.list_resources(), timeout=30.0)
        resource_uris = [res.get("uri", "unknown") for res in resources]
        logger.info(f"Discovered {len(resource_uris)} resources: {resource_uris}")

        # Discover prompts
        logger.info(f"Discovering prompts from stdio server...")
        prompts = await asyncio.wait_for(client.list_prompts(), timeout=30.0)
        prompt_names = [prompt.get("name", "unknown") for prompt in prompts]
        logger.info(f"Discovered {len(prompt_names)} prompts: {prompt_names}")

        # Register client with manager
        mcp_client_manager.register_client(server_id, client, process)

        # Dynamically register discovered tools with FastMCP using schema converter
        registered_tool_names = []

        # Create executor function that forwards to the MCP client
        async def tool_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            """Execute a tool via the MCP client."""
            client = mcp_client_manager.get_client(server_id)
            if not client:
                return f"Error: MCP client not found for server {server_id}"

            try:
                result = await client.call_tool(tool_name, arguments)
                return str(result)
            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                return f"Error executing {tool_name}: {str(e)}"

        for tool in tools:
            tool_name = tool.get("name", "")

            # Validate tool schema
            is_valid, error_msg = validate_tool_schema(tool)
            if not is_valid:
                logger.warning(f"Skipping tool {tool_name} due to invalid schema: {error_msg}")
                continue

            try:
                # Convert tool definition to Python function with explicit parameters
                full_tool_name, dynamic_function = convert_tool_to_function(
                    tool_definition=tool,
                    prefix=prefix,
                    executor=tool_executor,
                )

                # Register with FastMCP
                mcp.add_tool(dynamic_function)
                registered_tool_names.append(full_tool_name)
                logger.info(
                    f"Registered dynamic tool: {full_tool_name} "
                    f"(signature: {dynamic_function.__signature__})"
                )

            except Exception as e:
                logger.error(f"Failed to register tool {tool_name}: {e}", exc_info=True)
                # Continue with other tools even if one fails

        # Track registered tools for cleanup
        _dynamic_tools[server_id] = registered_tool_names

        logger.info(
            f"Successfully registered {len(registered_tool_names)} dynamic tools from stdio server"
        )

        # Create active mount record
        mount = ActiveMount(
            entry_id=server_id,
            name=f"Stdio Server ({prefix})",
            prefix=prefix,
            container_id=server_id,
            pid=process.pid,
            environment=env,
            tools=tool_names,
            resources=resource_uris,
            prompts=prompt_names,
        )

        await registry.add_active_mount(mount)

        return f"""Successfully launched stdio server!

**Type:** Stdio server (direct process)
**PID:** {process.pid}
**Prefix:** {prefix}
**Command:** {command} {" ".join(args)}
**Tools discovered:** {len(tool_names)}
**Resources discovered:** {len(resource_uris)}
**Prompts discovered:** {len(prompt_names)}

Available tools (callable via MCP):
{chr(10).join(f"  - mcp_{prefix}_{tool}" for tool in tool_names[:10])}
{f"  ... and {len(tool_names) - 10} more" if len(tool_names) > 10 else ""}

{f"Available resources: {', '.join(resource_uris[:5])}" if resource_uris else ""}
{f"  ... and {len(resource_uris) - 5} more" if len(resource_uris) > 5 else ""}

{f"Available prompts: {', '.join(prompt_names[:5])}" if prompt_names else ""}
{f"  ... and {len(prompt_names) - 5} more" if len(prompt_names) > 5 else ""}

These tools are now directly available through this MCP server!
You can call them by name (e.g., mcp_{prefix}_{tool_names[0] if tool_names else "toolname"})

Use `registry-config-set` to update environment variables if needed (requires restart).
Use `registry-remove` with entry_id="{server_id}" to stop this server.
"""

    except FileNotFoundError as e:
        return f"Failed to launch stdio server: {e}"
    except RuntimeError as e:
        return f"Failed to launch stdio server: {e}"
    except asyncio.TimeoutError:
        logger.error(f"Timeout initializing MCP client for stdio server")
        # Clean up
        if server_id in stdio_runner._processes:
            await stdio_runner.stop_server(server_id)
        return f"Failed to initialize MCP client for stdio server: timeout"
    except Exception as e:
        logger.error(f"Error launching stdio server: {e}", exc_info=True)
        # Clean up
        if server_id in stdio_runner._processes:
            await stdio_runner.stop_server(server_id)
        return f"Failed to launch stdio server: {str(e)}"


@mcp.tool(name="mcp_registry_add")
async def registry_add(
    entry_id: str = Field(..., description="Registry entry ID to activate"),
    prefix: str | None = Field(
        None, description="Tool prefix for namespacing (default: auto-generated)"
    ),
) -> str:
    """Activate an MCP server from the registry.

    Pulls the container image, starts the server, and dynamically registers
    discovered tools as callable MCP tools.

    Args:
        entry_id: Registry entry ID to activate
        prefix: Optional tool prefix for namespacing (default: auto-generated)

    Returns:
        Confirmation message with activation details
    """
    await initialize_registry()

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
        # Podman-based server - use interactive mode for MCP stdio communication
        pull_success = await podman_runner.pull_image(entry.container_image)
        if not pull_success:
            return f"Failed to pull image: {entry.container_image}"

        # Start container in interactive mode for stdio communication
        container_name = f"mcp-registry-{prefix}"
        container_id, process = await podman_runner.run_interactive_container(
            image=entry.container_image,
            name=container_name,
            environment={},  # Will be set via config-set
        )

        if not container_id or not process:
            return f"Failed to start interactive container for {entry.name}"

        # Create MCP client for this container
        try:
            client = MCPClient(process)

            # Initialize the MCP connection
            logger.info(f"Initializing MCP client for {entry.name}...")
            capabilities = await asyncio.wait_for(client.initialize(), timeout=30.0)
            logger.info(f"MCP client initialized: {capabilities}")

            # Discover tools
            logger.info(f"Discovering tools for {entry.name}...")
            tools = await asyncio.wait_for(client.list_tools(), timeout=30.0)
            tool_names = [tool.get("name", "unknown") for tool in tools]
            logger.info(f"Discovered {len(tool_names)} tools: {tool_names}")

            # Discover resources
            logger.info(f"Discovering resources for {entry.name}...")
            resources = await asyncio.wait_for(client.list_resources(), timeout=30.0)
            resource_uris = [res.get("uri", "unknown") for res in resources]
            logger.info(f"Discovered {len(resource_uris)} resources: {resource_uris}")

            # Discover prompts
            logger.info(f"Discovering prompts for {entry.name}...")
            prompts = await asyncio.wait_for(client.list_prompts(), timeout=30.0)
            prompt_names = [prompt.get("name", "unknown") for prompt in prompts]
            logger.info(f"Discovered {len(prompt_names)} prompts: {prompt_names}")

            # Register client with manager
            mcp_client_manager.register_client(container_id, client, process)

            # Dynamically register discovered tools with FastMCP using schema converter
            registered_tool_names = []

            # Create executor function that forwards to registry_exec
            async def tool_executor(tool_name: str, arguments: dict[str, Any]) -> str:
                """Execute a tool via the MCP client."""
                # Get the MCP client for this container
                client = mcp_client_manager.get_client(container_id)
                if not client:
                    return f"Error: MCP client not found for container {container_id}"

                try:
                    result = await client.call_tool(tool_name, arguments)
                    return str(result)
                except Exception as e:
                    logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
                    return f"Error executing {tool_name}: {str(e)}"

            for tool in tools:
                tool_name = tool.get("name", "")

                # Validate tool schema
                is_valid, error_msg = validate_tool_schema(tool)
                if not is_valid:
                    logger.warning(f"Skipping tool {tool_name} due to invalid schema: {error_msg}")
                    continue

                try:
                    # Convert tool definition to Python function with explicit parameters
                    full_tool_name, dynamic_function = convert_tool_to_function(
                        tool_definition=tool,
                        prefix=prefix,
                        executor=tool_executor,
                    )

                    # Register with FastMCP
                    mcp.add_tool(dynamic_function)
                    registered_tool_names.append(full_tool_name)
                    logger.info(
                        f"Registered dynamic tool: {full_tool_name} "
                        f"(signature: {dynamic_function.__signature__})"
                    )

                except Exception as e:
                    logger.error(f"Failed to register tool {tool_name}: {e}", exc_info=True)
                    # Continue with other tools even if one fails

            # Track registered tools for cleanup
            _dynamic_tools[container_id] = registered_tool_names

            logger.info(
                f"Successfully registered {len(registered_tool_names)} dynamic tools "
                f"for {entry.name}"
            )

        except asyncio.TimeoutError:
            logger.error(f"Timeout initializing MCP client for {entry.name}")
            # Clean up
            if process:
                try:
                    process.kill()
                    await process.wait()
                except Exception as e:
                    logger.warning(f"Error killing process: {e}")
            return f"Failed to initialize MCP client for {entry.name}: timeout"
        except Exception as e:
            logger.error(f"Error initializing MCP client for {entry.name}: {e}", exc_info=True)
            # Clean up
            if process:
                try:
                    process.kill()
                    await process.wait()
                except Exception as e:
                    logger.warning(f"Error killing process: {e}")
            return f"Failed to initialize MCP client for {entry.name}: {str(e)}"

        # Create active mount
        mount = ActiveMount(
            entry_id=entry.id,
            name=entry.name,
            prefix=prefix,
            container_id=container_id,
            environment={},
            tools=tool_names,  # Store discovered tools
            resources=resource_uris,
            prompts=prompt_names,
        )

        await registry.add_active_mount(mount)

        return f"""Successfully activated: {entry.name}

**Type:** Podman container (interactive/stdio mode)
**Container ID:** {container_id}
**Prefix:** {prefix}
**Image:** {entry.container_image}
**Tools discovered:** {len(tool_names)}
**Resources discovered:** {len(resource_uris)}
**Prompts discovered:** {len(prompt_names)}

Available tools (callable via MCP):
{chr(10).join(f"  - mcp_{prefix}_{tool}" for tool in tool_names[:10])}
{f"  ... and {len(tool_names) - 10} more" if len(tool_names) > 10 else ""}

{f"Available resources: {', '.join(resource_uris[:5])}" if resource_uris else ""}
{f"  ... and {len(resource_uris) - 5} more" if len(resource_uris) > 5 else ""}

{f"Available prompts: {', '.join(prompt_names[:5])}" if prompt_names else ""}
{f"  ... and {len(prompt_names) - 5} more" if len(prompt_names) > 5 else ""}

These tools are now directly available through this MCP server!
You can call them by name (e.g., mcp_{prefix}_{tool_names[0] if tool_names else "toolname"})

Use `registry-config-set` to configure environment variables (requires restart).
"""

    else:
        return f"""Unable to activate {entry.name}: Only Podman container-based servers are currently supported for dynamic tool exposure.

**Entry ID:** {entry_id}
**Launch Method:** {entry.launch_method.value if entry.launch_method else "unknown"}

Supported launch methods:
- PODMAN (with container image)

Note: Stdio-based servers and source-based servers are not yet supported for automatic activation.
You can manually configure them in your MCP client if needed.
"""


@mcp.tool(name="mcp_registry_remove")
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

    # Remove dynamically registered tools
    if mount.container_id and mount.container_id in _dynamic_tools:
        for tool_name in _dynamic_tools[mount.container_id]:
            try:
                mcp.remove_tool(tool_name)
                logger.info(f"Removed dynamic tool: {tool_name}")
            except Exception as e:
                logger.warning(f"Failed to remove tool {tool_name}: {e}")
        del _dynamic_tools[mount.container_id]

    # Clean up MCP client if present
    if mount.container_id:
        logger.info(f"Cleaning up MCP client for {mount.container_id}")
        await mcp_client_manager.remove_client(mount.container_id)

    # Stop container if running (for detached containers)
    # Interactive containers will stop when the MCP client is closed
    if mount.container_id and not mount.container_id.startswith("interactive-"):
        stopped = await podman_runner.stop_container(mount.container_id)
        if not stopped:
            # Try force kill
            await podman_runner.kill_container(mount.container_id)

    # Stop stdio server if running
    if mount.pid and not mount.container_id:
        # This is a stdio server (has PID but no container_id)
        logger.info(f"Stopping stdio server {mount.entry_id} (PID: {mount.pid})")
        await stdio_runner.stop_server(mount.entry_id)

    # Remove from active mounts
    await registry.remove_active_mount(entry_id)

    return f"Successfully deactivated: {mount.name}"


@mcp.tool(name="mcp_registry_active")
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

        if mount.resources:
            output.append(f"**Resources:** {len(mount.resources)} available")

        if mount.prompts:
            output.append(f"**Prompts:** {len(mount.prompts)} available")

        output.append(f"**Mounted at:** {mount.mounted_at.strftime('%Y-%m-%d %H:%M:%S')}")
        output.append("")

    return "\n".join(output)


@mcp.tool(name="mcp_registry_config_set")
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


@mcp.tool(name="mcp_registry_exec")
async def registry_exec(
    tool_name: str = Field(..., description="Fully-qualified tool name (prefix_toolname)"),
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments as key-value pairs"
    ),
) -> str:
    """Execute a tool from an active MCP server.

    Tool names must be prefixed with the server's prefix (e.g., filesystem_read_file).

    Note: This is a simplified implementation that provides basic tool execution.
    Full MCP protocol support (capabilities negotiation, resources, prompts) would
    require significant additional implementation.

    Returns:
        Tool execution result
    """
    await initialize_registry()

    # Parse prefix from tool name (expecting mcp_prefix_toolname format)
    if not tool_name.startswith("mcp_"):
        return f"Invalid tool name format. Expected: mcp_prefix_toolname, got: {tool_name}"

    parts = tool_name.split("_")
    if len(parts) < 3:
        return f"Invalid tool name format. Expected: mcp_prefix_toolname, got: {tool_name}"

    prefix = parts[1]  # Extract prefix after "mcp_"
    actual_tool_name = "_".join(parts[2:])  # Rest after prefix

    # Find active mount by prefix
    active_mounts = await registry.list_active_mounts()
    mount = None
    for m in active_mounts:
        if m.prefix == prefix:
            mount = m
            break

    if not mount:
        return f"No active server found with prefix: {prefix}"

    # Check if we have an MCP client for this container
    client = mcp_client_manager.get_client(mount.container_id)

    if not client:
        return f"""MCP client not available for {mount.name}.

Container: {mount.container_id[:12] if mount.container_id else "N/A"}

The server may not be running or the connection was lost.
Try removing and re-adding the server with registry_remove and registry_add.
"""

    # Execute tool via MCP client
    try:
        result = await client.call_tool(actual_tool_name, arguments)
        return f"""Tool executed successfully: {tool_name}

Result:
{result}
"""
    except Exception as e:
        logger.error(f"Tool execution failed for {tool_name}: {e}", exc_info=True)
        return f"""Tool execution failed: {tool_name}

Error: {str(e)}

This may indicate the tool doesn't exist or the server encountered an error.
Use the server's documentation to verify tool names and arguments.
"""


@mcp.tool(name="mcp_registry_refresh")
async def registry_refresh(
    source: str = Field(..., description="Source to refresh: docker, mcpservers, or all"),
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


@mcp.tool(name="mcp_registry_status")
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


# NOTE: Self-restart tool removed
# A self-restart mechanism using os.execv() is incompatible with Zed's process management.
# When Zed launches the MCP server, it manages the process lifecycle and stdio connections.
# Attempting to replace the process breaks these connections and can spawn multiple instances.
# To restart the server, use Zed's built-in MCP server restart functionality instead.


def main() -> None:
    """Main entry point for the server."""
    logger.info("Starting mcp-registry server")

    # Run the server
    mcp.run()


if __name__ == "__main__":
    main()
