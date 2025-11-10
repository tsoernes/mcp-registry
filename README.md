# mcp-registry

A dynamic MCP (Model Context Protocol) registry server that aggregates MCP servers from multiple sources and enables on-demand discovery and activation using Podman.

## Overview

`mcp-registry` is a FastMCP-based server that provides a unified interface to discover, search, and dynamically activate MCP servers from multiple sources:

- **Docker MCP Registry**: Official Docker MCP catalog (https://github.com/docker/mcp-registry)
- **mcpservers.org**: Community-curated MCP servers with rich metadata (official, featured, categories)
- **Future sources**: Extensible architecture for additional registries

Unlike the Docker Dynamic MCP which uses Docker containers, `mcp-registry` uses **Podman** for containerized MCP servers and supports **stdio-based servers** with automatic editor configuration, making it ideal for rootless container environments and Fedora-based systems.

## Features

### Core Capabilities

- **Multi-source aggregation**: Unified search across Docker registry, mcpservers.org, and more
- **Fuzzy search**: Find servers by name, description, tags, or categories using intelligent matching
- **Popularity ranking**: Search results sorted by relevance + popularity (official, featured, categories)
- **Dynamic activation**: Add/remove MCP servers on-demand during a session
- **Podman integration**: Run containerized MCP servers using Podman (rootless compatible)
- **Stdio server support**: Automatically configure npm/npx/python-based servers in editor configs
- **Editor integration**: Automatic configuration for Zed and Claude Desktop
- **Session persistence**: Active servers persist across restarts
- **Auto-refresh**: Background updates from sources (max once per 24h)
- **Rich metadata**: Categories, tags, official/featured flags, API key requirements

### Registry Tools

The server exposes the following tools to AI agents:

- `registry-find`: Search for MCP servers by name, description, tags, or categories (sorted by popularity)
- `registry-list`: List all available servers in the aggregated registry
- `registry-add`: Activate an MCP server (Podman container or editor config)
- `registry-remove`: Deactivate a previously added server
- `registry-active`: List currently active/mounted servers
- `registry-config-set`: Configure environment variables for a server
- `registry-exec`: Execute a tool from any active server
- `registry-refresh`: Force refresh a specific source (respects rate limits)
- `registry-status`: View registry statistics and health information

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

### Connecting to Claude Desktop

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

### Example workflow

Once connected to an MCP client (like Claude Desktop):

```
User: "Find MCP servers for working with databases"
→ Server uses registry-find to search

User: "Add the postgres server to Claude Desktop"
→ Server uses registry-add to activate it (Podman container)

User: "Add the filesystem server to Zed"
→ Server uses registry-add with editor integration (stdio server)

User: "Run a query: SELECT * FROM users LIMIT 5"
→ Server uses registry-exec to dispatch to postgres tools
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
```

## Security Considerations

- Container images are validated before running
- Environment variable injection is restricted to an allowlist
- Podman runs containers without privileged access
- Editor config files are backed up before modification
- Source repositories are cloned/pulled with verification
- Rate limiting prevents excessive refresh attempts

## Roadmap

- [x] Multi-source aggregation framework
- [x] Podman integration
- [x] Fuzzy search with RapidFuzz
- [x] Session persistence
- [x] Background refresh scheduler
- [x] Comprehensive test suite with pytest
- [x] Registry tools (find, list, add, remove, active, status, config-set, refresh)
- [x] Stdio server support with automatic editor configuration
- [x] Zed and Claude Desktop integration
- [ ] Automatic image building from source
- [ ] Tool dispatch (registry-exec implementation)
- [ ] Authentication/secrets management
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
- ✅ Podman container management
- ✅ Stdio server support with editor configuration
- ✅ Zed and Claude Desktop integration
- ✅ Background refresh scheduler
- ✅ Comprehensive test suite (70%+ coverage)
- ⏳ Tool dispatch to mounted servers (in progress)
- ⏳ Source-based server building (planned)

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Inspired by [Docker Dynamic MCP](https://docs.docker.com/ai/mcp-catalog-and-toolkit/dynamic-mcp/)
- Aggregates data from [Docker MCP Registry](https://github.com/docker/mcp-registry) and [mcpservers.org](https://mcpservers.org)

## Support

- GitHub Issues: [Report bugs or request features](https://github.com/tsoernes/mcp-registry/issues)
- Discussions: [Ask questions or share ideas](https://github.com/tsoernes/mcp-registry/discussions)