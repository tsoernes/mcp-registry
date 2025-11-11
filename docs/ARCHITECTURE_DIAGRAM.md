# MCP Registry Architecture - Container Stdio Communication

## System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        MCP Registry Server                          │
│                     (FastMCP on stdio transport)                    │
└────────────────────────────────────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │     Registry Tools        │
                    │  - registry_find          │
                    │  - registry_add           │
                    │  - registry_exec          │
                    │  - registry_remove        │
                    └─────────────┬─────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        ▼                         ▼                         ▼
┌──────────────┐         ┌────────────────┐       ┌─────────────────┐
│   Registry   │         │  PodmanRunner  │       │ MCPClientManager│
│   Database   │         │  (Container)   │       │  (Clients Map)  │
└──────────────┘         └────────────────┘       └─────────────────┘
        │                         │                         │
        │                         │                         │
        ▼                         ▼                         ▼
┌──────────────┐         ┌────────────────┐       ┌─────────────────┐
│Entry Storage │         │Interactive Proc│       │   MCPClient     │
│Active Mounts │         │stdin/stdout    │       │   (JSON-RPC)    │
└──────────────┘         └────────────────┘       └─────────────────┘
                                  │                         │
                                  └─────────┬───────────────┘
                                            │
                                            ▼
                              ┌──────────────────────────┐
                              │   Podman Container       │
                              │  (MCP Server Process)    │
                              │                          │
                              │  Examples:               │
                              │  - docker.io/mcp/sqlite  │
                              │  - mcp/filesystem        │
                              │  - mcp/postgres          │
                              └──────────────────────────┘
```

## Detailed Flow: Activating a Server

```
User calls registry_add("docker/sqlite", editor="zed", prefix="sqlite")
                              │
                              ▼
         ┌────────────────────────────────────────────┐
         │  1. Look up entry in Registry              │
         │     - Search by ID                         │
         │     - Verify launch_method == PODMAN       │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  2. Pull Container Image                   │
         │     podman pull docker.io/mcp/sqlite       │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  3. Start Interactive Container            │
         │     podman run -i --name X --rm image cmd  │
         │     → Returns (container_id, process)      │
         │     → stdin/stdout/stderr pipes created    │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  4. Create MCP Client                      │
         │     client = MCPClient(process)            │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  5. Initialize MCP Connection              │
         │     → Send: {"method": "initialize", ...}  │
         │     ← Receive: capabilities response       │
         │     → Send: {"method": "initialized"}      │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  6. Discover Tools                         │
         │     → Send: {"method": "tools/list"}       │
         │     ← Receive: [{name, desc, schema}, ...] │
         │     → Store tool names in memory           │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  7. Register Client                        │
         │     manager.register_client(id, client)    │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  8. Create Active Mount                    │
         │     ActiveMount(                           │
         │       entry_id, prefix, container_id,      │
         │       environment, tools[]                 │
         │     )                                      │
         │     → Persist to cache                     │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  9. Return Success Message                 │
         │     "Successfully activated: SQLite"       │
         │     "Tools: sqlite_list_tables, ..."       │
         └────────────────────────────────────────────┘
```

## Detailed Flow: Executing a Tool

```
User calls registry_exec("sqlite_list_tables", {})
                              │
                              ▼
         ┌────────────────────────────────────────────┐
         │  1. Parse Tool Name                        │
         │     prefix = "sqlite"                      │
         │     tool_name = "list_tables"              │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  2. Find Active Mount by Prefix            │
         │     mount = registry.get_by_prefix("sqlite")│
         │     → container_id = mount.container_id    │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  3. Get MCP Client from Manager            │
         │     client = manager.get_client(id)        │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  4. Execute Tool via MCP Protocol          │
         │     → Send: {                              │
         │         "method": "tools/call",            │
         │         "params": {                        │
         │           "name": "list_tables",           │
         │           "arguments": {}                  │
         │         }                                  │
         │       }                                    │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  5. Container Processes Request            │
         │     (MCP Server running in container)      │
         │     - Validates arguments                  │
         │     - Executes business logic              │
         │     - Generates result                     │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  6. Receive Response                       │
         │     ← Receive: {                           │
         │         "result": {                        │
         │           "content": [                     │
         │             {"text": "[...]"}              │
         │           ]                                │
         │         }                                  │
         │       }                                    │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  7. Extract and Format Result              │
         │     result = response.content[0].text      │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  8. Return to User                         │
         │     "Tool executed successfully"           │
         │     "Result: []"                           │
         └────────────────────────────────────────────┘
```

## Detailed Flow: Removing a Server

```
User calls registry_remove("docker/sqlite")
                              │
                              ▼
         ┌────────────────────────────────────────────┐
         │  1. Get Active Mount                       │
         │     mount = registry.get_mount(entry_id)   │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  2. Remove MCP Client                      │
         │     manager.remove_client(container_id)    │
         │     → client.close()                       │
         │     → process.stdin.close()                │
         │     → await process.wait()                 │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  3. Container Auto-Removes                 │
         │     (--rm flag causes automatic cleanup)   │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  4. Remove Active Mount from Registry      │
         │     registry.remove_mount(entry_id)        │
         │     → Update cache                         │
         └────────────┬───────────────────────────────┘
                      ▼
         ┌────────────────────────────────────────────┐
         │  5. Return Success Message                 │
         │     "Successfully deactivated: SQLite"     │
         └────────────────────────────────────────────┘
```

## Communication Protocol Detail

### JSON-RPC 2.0 Message Format

**Request (Client → Server):**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "list_tables",
    "arguments": {}
  }
}
```

**Response (Server → Client):**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "[]"
      }
    ]
  }
}
```

**Error Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32602,
    "message": "Invalid params",
    "data": "Missing required argument: query"
  }
}
```

## State Management

### Active Mount Structure
```python
ActiveMount(
    entry_id="docker/sqlite",
    name="SQLite (Archived)",
    prefix="sqlite",
    container_id="interactive-mcp-registry-sqlite",
    environment={},
    tools=[
        "read_query",
        "write_query",
        "create_table",
        "list_tables",
        "describe_table",
        "append_insight"
    ]
)
```

### Client Manager State
```python
{
    "interactive-mcp-registry-sqlite": (
        MCPClient(process),
        asyncio.subprocess.Process
    ),
    "interactive-mcp-registry-filesystem": (
        MCPClient(process),
        asyncio.subprocess.Process
    )
}
```

## Error Handling Strategy

```
┌─────────────────┐
│  Operation      │
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │ Timeout │◄─── asyncio.wait_for(op, timeout=10.0)
    │ Handler │
    └────┬───┘
         │
         ├─── Success ──────► Continue
         │
         ├─── Timeout ──────► Cleanup & Error Message
         │
         └─── Exception ────► Log & Cleanup & Error Message
```

## Security Boundaries

```
┌──────────────────────────────────────────────────┐
│             Host System (Podman Host)             │
│                                                   │
│  ┌────────────────────────────────────────────┐  │
│  │  mcp-registry process (MCP Server)         │  │
│  │  - Manages lifecycle                       │  │
│  │  - Owns stdio pipes                        │  │
│  │  - No direct filesystem/network access     │  │
│  └──────────────┬─────────────────────────────┘  │
│                 │ stdio pipes                     │
│  ┌──────────────▼─────────────────────────────┐  │
│  │  Podman Container (Isolated Namespace)     │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │  MCP Server Process                  │  │  │
│  │  │  - Isolated PID namespace            │  │  │
│  │  │  - Isolated network (optional)       │  │  │
│  │  │  - Isolated filesystem (overlay)     │  │  │
│  │  │  - Limited resources (cgroups)       │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```
