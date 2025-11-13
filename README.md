# mcp-registry

A dynamic MCP (Model Context Protocol) registry server that aggregates MCP servers from multiple sources and enables on-demand discovery and activation using Podman.

## Overview

`mcp-registry` is a FastMCP-based server that provides a unified interface to discover, search, and dynamically activate MCP servers from multiple sources:

- **Docker MCP Registry**: Official Docker MCP catalog (https://github.com/docker/mcp-registry)
- **mcpservers.org**: Community-curated MCP servers with rich metadata (official, featured, categories)
- **Future sources**: Extensible architecture for additional registries

Unlike the Docker Dynamic MCP which uses Docker containers, `mcp-registry` uses **Podman** for containerized MCP servers, making it ideal for rootless container environments and Fedora-based systems. The server features **dynamic tool exposure**, automatically registering discovered tools from containerized MCP servers as callable functions.

## Features

### Core Capabilities

- **Multi-source aggregation**: Unified search across Docker registry, mcpservers.org, and more
- **Fuzzy search**: Find servers by name, description, tags, or categories using intelligent matching
- **Popularity ranking**: Search results sorted by relevance + popularity (official, featured, categories)
- **Dynamic activation**: Add/remove MCP servers on-demand during a session
- **Dynamic tool exposure**: Discovered tools automatically registered as callable MCP functions
- **Live notifications**: Automatic `notifications/tools/list_changed` sent to clients when tools are added/removed
- **Podman integration**: Run containerized MCP servers using Podman (rootless compatible)
- **Type-safe tool calls**: Full type checking and IDE support for dynamically registered tools
- **Session persistence**: Active servers persist across restarts
- **Auto-refresh**: Background updates from sources (max once per 24h)
- **Rich metadata**: Categories, tags, official/featured flags, API key requirements

### Registry Tools

The server exposes the following tools to AI agents:

- `mcp_registry_find`: Search for MCP servers by name, description, tags, or categories (sorted by popularity)
- `mcp_registry_list`: List all available servers in the aggregated registry
- `mcp_registry_get_docs`: Get documentation and setup instructions for an MCP server
- `mcp_registry_launch_stdio`: Launch a stdio-based MCP server with custom command, args, and environment
- `mcp_registry_add`: Activate an MCP server (Podman container with dynamic tool registration)
- `mcp_registry_remove`: Deactivate a previously added server
- `mcp_registry_active`: List currently active/mounted servers with tool/resource/prompt counts
- `mcp_registry_config_set`: Configure environment variables for a server
- `mcp_registry_exec`: Execute a tool from any active server
- `mcp_registry_refresh`: Force refresh a specific source (respects rate limits)
- `mcp_registry_status`: View registry statistics and health information

## Installation

### Prerequisites

- Python 3.12 or later
- Podman (installed and accessible on PATH)
- Git (for cloning source repositories)

### Install from source

```bash
git clone https://github.com/tsoernes/mcp-registry.git
cd mcp-registry
pip install -e .
```

### Install with dev dependencies

```bash
pip install -e ".[dev]"
```

## Usage

### Running the server

```bash
# Run with FastMCP CLI
fastmcp run mcp_registry_server/server.py

# Or use the installed script
mcp-registry
```

### Connecting to MCP Clients

#### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "mcp-registry": {
      "command": "mcp-registry",
      "args": []
    }
  }
}
```

#### Zed Editor

The server can be used directly in Zed through its MCP integration. No additional configuration needed if installed in your Python environment.

#### Other MCP Clients

Any MCP client that supports stdio transport can connect to `mcp-registry`. The server follows the standard MCP protocol.

### Example workflow

Once connected to an MCP client (like Claude Desktop or Zed):

```
User: "Find MCP servers for working with databases"
→ Agent uses mcp_registry_find to search
→ Returns results sorted by relevance and popularity

User: "Get documentation for the SQLite server"
→ Agent uses mcp_registry_get_docs to show setup instructions

User: "Add the SQLite server"
→ Agent uses mcp_registry_add to activate it (Podman container or stdio process)
→ Tools, resources, and prompts are automatically discovered
→ Discovered tools are registered with dynamic Python functions

User: "List active servers"
→ Agent uses mcp_registry_active
→ Shows server details including tool/resource/prompt counts

User: "Execute a query on the SQLite server"
→ Agent uses mcp_registry_exec with tool_name="sqlite_read_query" 
→ Type-safe tool invocation with JSON Schema validation
→ Results returned from the active MCP server

User: "Remove the SQLite server"
→ Agent uses mcp_registry_remove to deactivate and clean up
```

## Architecture

```
mcp-registry/
├── mcp_registry_server/
│   ├── __init__.py
│   ├── server.py           # FastMCP server instance and tool definitions
│   ├── models.py           # Pydantic models for registry entries
│   ├── registry.py         # Core registry logic and search index
│   ├── sources/            # Git clones of external registries
│   ├── cache/              # JSON metadata cache files
│   ├── scrapers/           # mcpservers.org scraper integration
│   ├── podman_runner.py    # Podman container management
│   └── tasks.py            # Background refresh scheduling
├── tests/                  # pytest test suite
├── scripts/                # Existing mcpservers.org scraper
├── pyproject.toml
├── README.md
└── LICENSE
```

## Data Model

Each registry entry includes:

- `id`: Stable deterministic slug
- `name`: Display name
- `description`: Human-readable description
- `source`: Origin (docker, mcpservers, etc.)
- `repo_url`: Source code repository
- `container_image`: Docker/Podman image reference
- `categories`: Functional categories
- `tags`: Searchable tags
- `official`: Official status (from mcpservers.org) - boosts search ranking
- `featured`: Featured status (from mcpservers.org) - boosts search ranking
- `requires_api_key`: Whether API credentials are needed
- `tools`: Available tool names (discovered on activation)
- `resources`: Available resource templates (discovered on activation)
- `prompts`: Available prompt templates (discovered on activation)
- `launch_method`: How to run (podman, stdio-proxy, remote-http)
- `server_command`: Command configuration for stdio servers (command, args, env)
- `last_refreshed`: Last metadata update timestamp

### Search Ranking

Search results are sorted by a combination of:
- **Fuzzy match score** (60% weight): How well the query matches the server name/description
- **Popularity score** (40% weight): Based on official status, featured status, number of categories, and source
- Official servers get +20 points
- Featured servers get +10 points
- Docker registry servers get +5 points
- Servers with container images get +3 points

## Configuration

### Environment variables

- `MCP_REGISTRY_CACHE_DIR`: Override cache directory (default: `mcp_registry_server/cache`)
- `MCP_REGISTRY_SOURCES_DIR`: Override sources directory (default: `mcp_registry_server/sources`)
- `MCP_REGISTRY_REFRESH_INTERVAL`: Refresh interval in hours (default: 24)

### Persistence

Active servers are persisted to `cache/active_mounts.json` and automatically restored on server startup.

### Performance Considerations

The server includes background tasks that periodically refresh registry data. To prevent excessive CPU usage:

- **mcpservers.org scraping is limited to 500 servers by default** - The full site contains 5000+ servers, and parsing all HTML files is extremely CPU-intensive
- **GitHub stars fetching is disabled during background refreshes** - This reduces HTTP requests and improves performance
- **Refresh checks occur every 6 hours** - But actual refreshes only happen if data is older than 24 hours

If you experience high CPU usage:
1. Check if a background refresh is running (logs will show "Starting X refresh")
2. The initial refresh after installation processes more data than subsequent refreshes
3. The scraper uses cached HTML when available to reduce network and parsing overhead

You can adjust these settings in `mcp_registry_server/tasks.py` if needed.

## MCP Protocol Support

### Tools List Changed Notifications

The server implements the MCP `notifications/tools/list_changed` protocol to keep clients updated when the available tool list changes. Notifications are automatically sent when:

- **Adding a server** (`mcp_registry_add`): After successfully activating a Podman container and registering its tools
- **Launching a stdio server** (`mcp_registry_launch_stdio`): After successfully spawning a process and registering its tools
- **Removing a server** (`mcp_registry_remove`): After successfully removing dynamically registered tools

This allows MCP clients (like Claude Desktop, Zed, or custom clients) to:
- Update their tool cache automatically
- Refresh UI displays of available tools
- Avoid polling for tool list updates

The notifications are sent using FastMCP's `ctx.send_tool_list_changed()` method within the tool execution context, ensuring they are only sent during active MCP request contexts as per the MCP protocol specification.

**Note**: Notifications are not sent during server initialization or when tools are registered outside of an active request context.

## Development

### Setting up development environment

```bash
# Clone the repository
git clone https://github.com/tsoernes/mcp-registry.git
cd mcp-registry

# Install with development dependencies
pip install -e ".[dev]"
```

### Running tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_registry.py

# Run specific test
pytest tests/test_models.py::TestRegistryEntry::test_create_valid_entry
```

### Running with coverage

```bash
# Generate coverage report
pytest --cov=mcp_registry_server --cov-report=html

# View coverage in browser
open htmlcov/index.html
```

### Code formatting and linting

```bash
# Format code
ruff format .

# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .
```

### Manual testing

```bash
# Test the server with fastmcp CLI
fastmcp dev mcp_registry_server/server.py

# Or run directly
python -m mcp_registry_server.server

# Test with an MCP client
# The server uses stdio transport and is designed to be used through
# MCP clients like Claude Desktop or Zed editor
```

## Security Considerations

- Container images are validated before running
- Environment variable injection is restricted to an allowlist (API_KEY, API_TOKEN, AUTH_, DATABASE_, DB_, GITHUB_, OPENAI_, ANTHROPIC_, AWS_, AZURE_, GCP_, SLACK_, DISCORD_, NOTION_, MCP_)
- Podman runs containers without privileged access (rootless mode supported)
- Source repositories are cloned/pulled with verification
- Rate limiting prevents excessive refresh attempts (24h minimum between refreshes)
- Stdio servers run in isolated processes with controlled environment

## Roadmap

- [x] Multi-source aggregation framework
- [x] Podman integration
- [x] Fuzzy search with RapidFuzz
- [x] Session persistence
- [x] Background refresh scheduler
- [x] Comprehensive test suite with pytest
- [x] Registry tools (mcp_registry_find, mcp_registry_list, mcp_registry_get_docs, mcp_registry_launch_stdio, mcp_registry_add, mcp_registry_remove, mcp_registry_active, mcp_registry_status, mcp_registry_config_set, mcp_registry_exec, mcp_registry_refresh)
- [x] Stdio server support with custom launch commands
- [x] Zed and Claude Desktop integration
- [x] Dynamic tool discovery and registration
- [x] Resource and prompt discovery
- [x] Tool dispatch (mcp_registry_exec implementation)
- [ ] Automatic image building from source
- [ ] Authentication/secrets management integration
- [ ] Code-mode tool composition
- [ ] Additional registry sources (Awesome MCP)
- [ ] WebUI for registry exploration
- [ ] Docker Compose example
- [ ] CI/CD pipeline

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Project Status

**Current Version:** 0.1.0 (Early Development)

- ✅ Core registry and search functionality complete
- ✅ mcpservers.org scraper integrated
- ✅ Docker registry git source integration
- ✅ Podman container management with MCP stdio protocol
- ✅ Stdio server support with custom launch commands (registry_launch_stdio)
- ✅ Dynamic tool/resource/prompt discovery and registration
- ✅ Tool execution via mcp_registry_exec
- ✅ Zed and Claude Desktop integration
- ✅ Background refresh scheduler
- ✅ Comprehensive test suite (70%+ coverage)
- ⏳ Source-based server building (planned)
- ⏳ Enhanced secrets management (planned)

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Inspired by [Docker Dynamic MCP](https://docs.docker.com/ai/mcp-catalog-and-toolkit/dynamic-mcp/)
- Aggregates data from [Docker MCP Registry](https://github.com/docker/mcp-registry) and [mcpservers.org](https://mcpservers.org)

## Support

- GitHub Issues: [Report bugs or request features](https://github.com/tsoernes/mcp-registry/issues)
- Discussions: [Ask questions or share ideas](https://github.com/tsoernes/mcp-registry/discussions)