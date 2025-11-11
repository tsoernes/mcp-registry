# MCP Registry - Quick Start Guide

Get up and running with `mcp-registry` in 5 minutes!

## Prerequisites

- Python 3.12 or later
- Podman installed and on PATH
- Git

## Installation

### Option 1: Install from source (recommended for development)

```bash
# Clone the repository
git clone https://github.com/tsoernes/mcp-registry.git
cd mcp-registry

# Install with pip
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

### Option 2: Install from PyPI (when published)

```bash
pip install mcp-registry
```

## Verify Podman Installation

```bash
# Check Podman version
podman --version

# Should output something like: podman version 4.x.x
```

## Running the Server

### Method 1: Using the installed script

```bash
mcp-registry
```

### Method 2: Using FastMCP CLI

```bash
fastmcp run mcp_registry_server/server.py
```

### Method 3: Direct Python execution

```bash
python -m mcp_registry_server.server
```

## Connecting to Claude Desktop

Add the following to your Claude Desktop config file:

**macOS/Linux:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mcp-registry": {
      "command": "mcp-registry"
    }
  }
}
```

Or if you're running from source:

```json
{
  "mcpServers": {
    "mcp-registry": {
      "command": "python",
      "args": ["-m", "mcp_registry_server.server"]
    }
  }
}
```

Restart Claude Desktop for changes to take effect.

## First Steps

Once connected to Claude Desktop, try these prompts:

### 1. Check registry status

```
What's the status of the MCP registry?
```

### 2. Search for servers

```
Find MCP servers for working with databases
```

```
Search for servers that can help with file operations
```

```
Show me official MCP servers
```

### 3. List available servers

```
List all servers in the registry
```

```
Show me servers from the Docker registry
```

### 4. Activate a server

```
Add the SQLite MCP server
```

Note: Only Podman-based container servers are currently supported. The server will pull the container image, start it, discover available tools, and automatically register them as callable MCP functions.

### 5. List active servers

```
What servers are currently active?
```

### 6. Configure a server

```
Set the DATABASE_URL environment variable for postgres to postgres://localhost:5432/mydb
```

### 7. Deactivate a server

```
Remove the postgres server
```

## Understanding the Tools

The registry provides these tools:

- **registry-find**: Search for servers (fuzzy matching, filters)
- **registry-list**: Browse all available servers
- **registry-add**: Activate a Podman container server with dynamic tool registration
  - Pulls container image and starts container
  - Discovers available tools via MCP protocol
  - Automatically registers tools as callable functions (e.g., `mcp_sqlite_read_query`)
- **registry-remove**: Deactivate a server (stops container and unregisters tools)
- **registry-active**: List currently running servers
- **registry-config-set**: Configure environment variables
- **registry-refresh**: Force refresh a data source
- **registry-status**: View diagnostics and statistics
- **Dynamic tools**: When you activate a server, its tools become directly callable
  - Example: After activating SQLite, you can call `mcp_sqlite_read_query(query="SELECT * FROM users")`
  - Full type safety and IDE support

## Data Sources

The registry aggregates servers from:

1. **Docker MCP Registry** (official Docker catalog)
   - Cloned from https://github.com/docker/mcp-registry
   - Auto-refreshed every 24 hours
   - Podman-based container images

2. **mcpservers.org** (community catalog)
   - Scraped from https://mcpservers.org
   - Auto-refreshed every 24 hours
   - Includes official/featured flags, categories, tags
   - Podman container servers

## Cache and Data Storage

By default, data is stored at:

- **Cache:** `~/.cache/mcp-registry/`
  - `registry_entries.json` - All server metadata
  - `active_mounts.json` - Persisted active servers
  - `mcpservers_html/` - HTML cache from scraper

- **Sources:** `~/.local/share/mcp-registry/sources/`
  - `docker-mcp-registry/` - Cloned Docker registry repo

Active servers persist across restarts!

## Troubleshooting

### Server won't start

1. Check Podman is installed:
   ```bash
   podman --version
   ```

2. Check Python version:
   ```bash
   python --version  # Should be 3.12+
   ```

3. Check logs (stderr output from the server)

### No servers found

The registry needs to refresh sources on first run. This happens automatically in the background. Wait 1-2 minutes, then try:

```
Refresh all registry sources
```

### Container won't start

1. Check if Podman can pull images:
   ```bash
   podman pull docker.io/library/hello-world
   ```

2. Check container logs:
   ```bash
   podman logs <container-id>
   ```

3. Try removing and re-adding the server

### Dynamic tools not appearing

1. Check that the server was successfully activated:
   ```
   What servers are currently active?
   ```

2. Check the server activation output for the list of registered tools

3. Verify the container is running:
   ```bash
   podman ps
   ```

4. Try removing and re-adding the server

3. Check for backup files (`.backup` suffix) if config was corrupted

4. Look for the server under `context_servers` (Zed) or `mcpServers` (Claude)

### Import errors

Make sure you installed with:
```bash
pip install -e .
```

Or add the project directory to PYTHONPATH:
```bash
export PYTHONPATH=/path/to/mcp-registry:$PYTHONPATH
```

## Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with coverage
pytest --cov=mcp_registry_server

# Run specific test
pytest tests/test_registry.py -v
```

## Advanced Usage

### Custom cache directory

Set environment variables:

```bash
export MCP_REGISTRY_CACHE_DIR=/path/to/cache
export MCP_REGISTRY_SOURCES_DIR=/path/to/sources
```

### Custom refresh interval

Modify `mcp_registry_server/server.py`:

```python
registry = Registry(
    cache_dir=Path.home() / ".cache" / "mcp-registry",
    sources_dir=Path.home() / ".local" / "share" / "mcp-registry" / "sources",
    refresh_interval_hours=12,  # Refresh every 12 hours instead of 24
)
```

### Manual source refresh

```python
from mcp_registry_server import Registry
from mcp_registry_server.tasks import RefreshScheduler

registry = Registry()
scheduler = RefreshScheduler(registry)

# Force refresh a source
await scheduler.force_refresh(SourceType.DOCKER)
```

## Next Steps

- Read the [full README](README.md) for architecture details
- Check [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines (if you create it)
- Explore the [test suite](tests/) for usage examples
- Report issues on [GitHub](https://github.com/tsoernes/mcp-registry/issues)

## Need Help?

- **Issues:** https://github.com/tsoernes/mcp-registry/issues
- **Discussions:** https://github.com/tsoernes/mcp-registry/discussions

## Server Types

### Podman Servers (Containerized)
- Pre-built Docker images from Docker Hub
- Run in isolated Podman containers
- Require image pull before first use
- Good for official/production servers

### Stdio Servers (Direct)
- npm packages (via `npx`)
- Python packages (via `python -m`)
- Run directly on your system
- Automatically added to editor config
- Good for development and lightweight servers

### Editor Integration

**Supported Editors:**
- **Zed**: Config at `~/.config/zed/settings.json` (uses `context_servers`)
- **Claude Desktop**: Config at `~/Library/Application Support/Claude/` (uses `mcpServers`)

The registry automatically:
1. Detects npm/pypi packages from server metadata
2. Generates appropriate command configuration
3. Edits your editor's JSON config file
4. Creates backup before modification
5. Preserves existing server configurations

## What's Next?

This is version 0.1.0 with core functionality. Coming soon:

- Tool dispatch (`registry-exec` implementation)
- Automatic image building from source repositories
- Code-mode tool composition
- Additional registry sources
- Additional editor support (VS Code, etc.)
- WebUI for exploration
- Docker Compose examples

Happy hacking! 🚀