# mcp-registry

A dynamic MCP (Model Context Protocol) registry server that aggregates MCP servers from multiple sources and enables on-demand discovery and activation using Podman.

## Overview

`mcp-registry` is a FastMCP-based server that provides a unified interface to discover, search, and dynamically activate MCP servers from multiple sources:

- **Docker MCP Registry**: Official Docker MCP catalog (https://github.com/docker/mcp-registry)
- **mcpservers.org**: Community-curated MCP servers with rich metadata (official, featured, categories)
- **Future sources**: Extensible architecture for additional registries

Unlike the Docker Dynamic MCP which uses Docker containers, `mcp-registry` uses **Podman** for containerized MCP servers, making it ideal for rootless container environments and Fedora-based systems.

## Features

### Core Capabilities

- **Multi-source aggregation**: Unified search across Docker registry, mcpservers.org, and more
- **Fuzzy search**: Find servers by name, description, tags, or categories using intelligent matching
- **Dynamic activation**: Add/remove MCP servers on-demand during a session
- **Podman integration**: Run containerized MCP servers using Podman (rootless compatible)
- **Session persistence**: Active servers persist across restarts
- **Auto-refresh**: Background updates from sources (max once per 24h)
- **Rich metadata**: Categories, tags, official/featured flags, API key requirements

### Registry Tools

The server exposes the following tools to AI agents:

- `registry-find`: Search for MCP servers by name, description, tags, or categories
- `registry-list`: List all available servers in the aggregated registry
- `registry-add`: Activate an MCP server in the current session
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

User: "Add the postgres server"
→ Server uses registry-add to activate it

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
- `official`: Official status (from mcpservers.org)
- `featured`: Featured status (from mcpservers.org)
- `requires_api_key`: Whether API credentials are needed
- `tools`: Available tool names (discovered on activation)
- `launch_method`: How to run (podman, stdio-proxy, remote-http)
- `last_refreshed`: Last metadata update timestamp

## Configuration

### Environment variables

- `MCP_REGISTRY_CACHE_DIR`: Override cache directory (default: `mcp_registry_server/cache`)
- `MCP_REGISTRY_SOURCES_DIR`: Override sources directory (default: `mcp_registry_server/sources`)
- `MCP_REGISTRY_REFRESH_INTERVAL`: Refresh interval in hours (default: 24)

### Persistence

Active servers are persisted to `cache/active_mounts.json` and automatically restored on server startup.

## Development

### Running tests

```bash
pytest
```

### Running with coverage

```bash
pytest --cov=mcp_registry_server --cov-report=html
```

### Code formatting

```bash
ruff format .
```

### Linting

```bash
ruff check .
```

## Security Considerations

- Container images are validated before running
- Environment variable injection is restricted to an allowlist
- Podman runs containers without privileged access
- Source repositories are cloned/pulled with verification
- Rate limiting prevents excessive refresh attempts

## Roadmap

- [x] Multi-source aggregation framework
- [x] Podman integration
- [x] Fuzzy search with RapidFuzz
- [x] Session persistence
- [x] Background refresh scheduler
- [ ] Automatic image building from source
- [ ] Authentication/secrets management
- [ ] Code-mode tool composition
- [ ] Additional registry sources
- [ ] WebUI for registry exploration

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details.

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Inspired by [Docker Dynamic MCP](https://docs.docker.com/ai/mcp-catalog-and-toolkit/dynamic-mcp/)
- Aggregates data from [Docker MCP Registry](https://github.com/docker/mcp-registry) and [mcpservers.org](https://mcpservers.org)