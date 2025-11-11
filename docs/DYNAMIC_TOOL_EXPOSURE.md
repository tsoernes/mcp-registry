# Dynamic Tool Exposure

**Status:** ✅ Implemented  
**Version:** 1.0  
**Last Updated:** 2025-11-11

---

## Overview

The MCP Registry Server now supports **dynamic tool exposure**, automatically converting tools discovered from containerized MCP servers into first-class FastMCP tools that can be called directly by MCP clients.

When you activate an MCP server using `registry_add`, the system:
1. Starts the container and establishes an MCP connection
2. Discovers available tools via the MCP protocol
3. Converts each tool's JSON Schema to a Python function with explicit typed parameters
4. Registers these functions as callable tools through the registry's MCP interface
5. Properly cleans up when the server is deactivated

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                     MCP Client                              │
│              (Zed, Claude Desktop, etc.)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      │ MCP Protocol
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                MCP Registry Server                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          FastMCP Tool Registry                       │  │
│  │  - registry_find                                     │  │
│  │  - registry_add                                      │  │
│  │  - registry_remove                                   │  │
│  │  - mcp_sqlite_read_query        ← Dynamic            │  │
│  │  - mcp_sqlite_write_query       ← Dynamic            │  │
│  │  - mcp_sqlite_list_tables       ← Dynamic            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │       Schema Converter (schema_converter.py)         │  │
│  │  - validate_tool_schema()                            │  │
│  │  - json_type_to_python_type()                        │  │
│  │  - parse_schema_property()                           │  │
│  │  - create_dynamic_tool_function()                    │  │
│  │  - convert_tool_to_function()                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         MCP Client Manager                           │  │
│  │  - Manages connections to containerized servers      │  │
│  │  - Routes tool calls to appropriate MCP client       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      │ MCP Protocol (stdio)
                      │
┌─────────────────────▼───────────────────────────────────────┐
│           Podman Container                                  │
│     ┌───────────────────────────────────────┐              │
│     │   MCP Server (e.g., SQLite)           │              │
│     │   - read_query                        │              │
│     │   - write_query                       │              │
│     │   - list_tables                       │              │
│     │   - create_table                      │              │
│     └───────────────────────────────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Tool Discovery:**
   - Container starts in interactive mode
   - MCP client sends `initialize` request
   - MCP client sends `tools/list` request
   - Server responds with tool definitions (name, description, inputSchema)

2. **Schema Conversion:**
   - Each tool's JSON Schema is validated
   - JSON Schema types are mapped to Python types
   - Required vs optional parameters are identified
   - A Python function with explicit parameters is generated dynamically

3. **Tool Registration:**
   - Generated function is registered with FastMCP using `mcp.add_tool()`
   - Tool name is prefixed with `mcp_{prefix}_` for namespacing
   - Function signature is preserved for schema generation

4. **Tool Execution:**
   - MCP client calls the dynamic tool (e.g., `mcp_sqlite_read_query`)
   - FastMCP validates parameters against the function signature
   - Function executor forwards the call to the MCP client
   - MCP client sends `tools/call` request to the container
   - Result is returned to the caller

5. **Cleanup:**
   - When server is deactivated, all dynamic tools are unregistered
   - MCP client connection is closed
   - Container is stopped

---

## JSON Schema to Python Conversion

### Type Mapping

| JSON Schema Type | Python Type | Notes |
|------------------|-------------|-------|
| `string` | `str` | |
| `number` | `float` | |
| `integer` | `int` | |
| `boolean` | `bool` | |
| `object` | `dict` | No nested validation |
| `array` | `list` | No item type validation |
| `null` | `type(None)` | |
| `["string", "null"]` | `str \| None` | Union types |

### Parameter Handling

#### Required Parameters

JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "SQL query to execute"
    }
  },
  "required": ["query"]
}
```

Generated Python signature:
```python
async def dynamic_tool(
    query: str = Field(..., description="SQL query to execute")
) -> str:
    ...
```

#### Optional Parameters with Defaults

JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "limit": {
      "type": "integer",
      "description": "Max rows to return",
      "default": 100
    }
  }
}
```

Generated Python signature:
```python
async def dynamic_tool(
    limit: int = Field(100, description="Max rows to return")
) -> str:
    ...
```

#### Optional Parameters without Defaults

JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "filter": {
      "type": "string",
      "description": "Optional filter"
    }
  }
}
```

Generated Python signature:
```python
async def dynamic_tool(
    filter: str | None = Field(None, description="Optional filter")
) -> str:
    ...
```

### Complex Example

Given this MCP tool definition:
```json
{
  "name": "read_query",
  "description": "Execute a SELECT query on the database",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "SELECT SQL query to execute"
      },
      "limit": {
        "type": "integer",
        "description": "Maximum number of rows to return",
        "default": 100
      },
      "offset": {
        "type": "integer",
        "description": "Number of rows to skip"
      }
    },
    "required": ["query"]
  }
}
```

The converter generates:
```python
async def read_query(
    query: str = Field(..., description="SELECT SQL query to execute"),
    limit: int = Field(100, description="Maximum number of rows to return"),
    offset: int | None = Field(None, description="Number of rows to skip")
) -> str:
    """Execute a SELECT query on the database"""
    # Executor forwards to MCP client
    arguments = {"query": query, "limit": limit}
    if offset is not None:
        arguments["offset"] = offset
    return await mcp_client.call_tool("read_query", arguments)
```

---

## Usage Examples

### Activating a Server

```python
# Activate SQLite server
result = await registry_add(
    entry_id="docker/sqlite",
    editor="zed",
    prefix="sqlite"
)

# Output:
# Successfully activated: SQLite MCP Server
# 
# Type: Podman container (interactive/stdio mode)
# Container ID: abc123def456
# Prefix: sqlite
# Image: docker.io/mcp/sqlite
# Tools discovered: 4
# 
# Available tools (callable via MCP):
#   - mcp_sqlite_read_query
#   - mcp_sqlite_write_query
#   - mcp_sqlite_create_table
#   - mcp_sqlite_list_tables
# 
# These tools are now directly available through this MCP server!
```

### Calling Dynamic Tools

```python
# List all tables (no parameters)
tables = await mcp_sqlite_list_tables()

# Execute a SELECT query (required parameter)
results = await mcp_sqlite_read_query(
    query="SELECT * FROM users WHERE age > 18"
)

# Execute with optional parameter
results = await mcp_sqlite_read_query(
    query="SELECT * FROM users",
    limit=50
)

# Create a new table (multiple required parameters)
await mcp_sqlite_create_table(
    table_name="products",
    schema="id INTEGER PRIMARY KEY, name TEXT, price REAL"
)
```

### Deactivating a Server

```python
# Deactivate and clean up
result = await registry_remove(entry_id="docker/sqlite")

# All dynamic tools are automatically unregistered:
# - mcp_sqlite_read_query ✗ (removed)
# - mcp_sqlite_write_query ✗ (removed)
# - mcp_sqlite_create_table ✗ (removed)
# - mcp_sqlite_list_tables ✗ (removed)
```

---

## Implementation Details

### Schema Converter Module

**File:** `mcp_registry_server/schema_converter.py`

#### Key Functions

##### `validate_tool_schema(tool_definition: dict) -> tuple[bool, str]`

Validates that a tool definition has a valid schema for conversion.

**Returns:** `(is_valid, error_message)`

**Example:**
```python
tool_def = {
    "name": "test_tool",
    "description": "A test",
    "inputSchema": {
        "type": "object",
        "properties": {"param": {"type": "string"}}
    }
}

valid, error = validate_tool_schema(tool_def)
# valid = True, error = ""
```

##### `json_type_to_python_type(json_type: str, json_format: str | None = None) -> type`

Converts JSON Schema type to Python type annotation.

**Example:**
```python
json_type_to_python_type("string")  # -> str
json_type_to_python_type("integer")  # -> int
json_type_to_python_type(["string", "null"])  # -> str | None
```

##### `parse_schema_property(prop_name: str, prop_schema: dict, required: bool) -> tuple`

Parses a JSON Schema property into Python function parameter components.

**Returns:** `(param_name, param_type, default_value, description)`

**Example:**
```python
schema = {"type": "string", "description": "A test string"}
name, typ, default, desc = parse_schema_property("test", schema, required=True)
# name = "test"
# typ = str
# default = ... (Ellipsis, marking required)
# desc = "A test string"
```

##### `create_dynamic_tool_function(tool_name: str, tool_description: str, input_schema: dict, executor: Callable) -> Callable`

Creates a dynamic function with explicit parameters from JSON Schema.

**Example:**
```python
async def executor(tool_name: str, arguments: dict) -> str:
    return f"Executed {tool_name} with {arguments}"

schema = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "SQL query"}
    },
    "required": ["query"]
}

func = create_dynamic_tool_function(
    tool_name="read_query",
    tool_description="Execute query",
    input_schema=schema,
    executor=executor
)

# func now has signature:
# async def read_query(query: str = Field(..., description="SQL query")) -> str
```

##### `convert_tool_to_function(tool_definition: dict, prefix: str, executor: Callable) -> tuple[str, Callable]`

High-level function that converts an MCP tool definition to a Python function.

**Returns:** `(full_tool_name, function)`

**Example:**
```python
tool_def = {
    "name": "list_tables",
    "description": "List all tables",
    "inputSchema": {"type": "object", "properties": {}}
}

async def exec(name, args):
    return "OK"

name, func = convert_tool_to_function(tool_def, "sqlite", exec)
# name = "mcp_sqlite_list_tables"
# func = callable async function
```

### Server Integration

**File:** `mcp_registry_server/server.py`

The `registry_add` function was updated to:

1. **Create executor function:**
```python
async def tool_executor(tool_name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool via the MCP client."""
    client = mcp_client_manager.get_client(container_id)
    if not client:
        return f"Error: MCP client not found"
    
    result = await client.call_tool(tool_name, arguments)
    return str(result)
```

2. **Convert and register tools:**
```python
for tool in tools:
    # Validate
    is_valid, error_msg = validate_tool_schema(tool)
    if not is_valid:
        logger.warning(f"Skipping tool: {error_msg}")
        continue
    
    # Convert
    full_tool_name, dynamic_function = convert_tool_to_function(
        tool_definition=tool,
        prefix=prefix,
        executor=tool_executor,
    )
    
    # Register
    mcp.add_tool(dynamic_function)
    registered_tool_names.append(full_tool_name)
```

3. **Track for cleanup:**
```python
_dynamic_tools[container_id] = registered_tool_names
```

The `registry_remove` function was updated to:

```python
# Remove dynamically registered tools
if mount.container_id and mount.container_id in _dynamic_tools:
    for tool_name in _dynamic_tools[mount.container_id]:
        try:
            mcp.remove_tool(tool_name)
            logger.info(f"Removed dynamic tool: {tool_name}")
        except Exception as e:
            logger.warning(f"Failed to remove tool {tool_name}: {e}")
    del _dynamic_tools[mount.container_id]
```

---

## Testing

### Unit Tests

**File:** `tests/test_schema_converter.py`

- 27 unit tests covering all schema converter functions
- Tests for type mapping, parameter parsing, function generation
- Edge cases: complex types, unions, defaults, errors

**Run:**
```bash
pytest tests/test_schema_converter.py -v
```

### Integration Tests

**File:** `tests/test_dynamic_tool_integration.py`

- 6 integration tests simulating real-world scenarios
- Tests for SQLite, filesystem, and complex parameter types
- Tests for tool naming, multiple prefixes, error handling

**Run:**
```bash
pytest tests/test_dynamic_tool_integration.py -v
```

### Test Coverage

```
Total: 103 tests (97 existing + 6 integration)
Schema converter: 27 tests
All tests passing ✅
```

---

## Limitations and Future Work

### Current Limitations

1. **Complex nested schemas:** Object and array types are mapped to `dict` and `list` without nested validation
2. **Union type handling:** For union types, the converter picks the first non-null type
3. **Array item types:** No runtime validation of array element types
4. **Enum constraints:** JSON Schema enums are not enforced at runtime
5. **Pattern validation:** String patterns and formats are not validated

### Planned Improvements

1. **Enhanced type validation:** Runtime validation of complex types
2. **Better union support:** Proper handling of multi-type unions
3. **Enum support:** Convert JSON Schema enums to Python Literal types
4. **Format validation:** Support for JSON Schema format hints (date-time, email, etc.)
5. **Auto-documentation:** Generate rich docstrings with parameter details
6. **Performance optimization:** Cache function generation for repeated use

### Workarounds

For complex types, you can:
- Use type hints in tool descriptions
- Validate inputs in the MCP server itself
- Document expected formats clearly

---

## Troubleshooting

### Tools Not Appearing

**Symptom:** After `registry_add`, dynamic tools are not visible

**Possible causes:**
1. Tool schema validation failed
2. Container failed to start
3. MCP client timeout

**Solution:**
```python
# Check logs
import logging
logging.basicConfig(level=logging.INFO)

# Check active mounts
result = await registry_active()
print(result)

# Verify tools were discovered
mount = await registry.get_active_mount(entry_id)
print(f"Tools: {mount.tools}")
```

### Type Errors

**Symptom:** FastMCP rejects dynamic tool registration

**Possible causes:**
1. Invalid type annotation
2. Malformed JSON Schema

**Solution:**
```python
# Test schema conversion manually
from mcp_registry_server.schema_converter import convert_tool_to_function

async def test_executor(name, args):
    return "OK"

name, func = convert_tool_to_function(tool_def, "test", test_executor)
print(f"Function signature: {func.__signature__}")
```

### Cleanup Issues

**Symptom:** Dynamic tools persist after `registry_remove`

**Possible cause:** Exception during cleanup

**Solution:**
```python
# Manually remove tools
from mcp_registry_server.server import mcp, _dynamic_tools

for tool_name in _dynamic_tools.get(container_id, []):
    try:
        mcp.remove_tool(tool_name)
    except Exception as e:
        print(f"Error removing {tool_name}: {e}")
```

---

## FAQ

**Q: Do I need to restart the registry server when adding/removing dynamic tools?**  
A: No, tools are registered and unregistered dynamically at runtime.

**Q: Can I have multiple servers with the same tool names?**  
A: Yes, tools are namespaced with prefixes (e.g., `mcp_sqlite_query` vs `mcp_postgres_query`).

**Q: What happens if a tool has an invalid schema?**  
A: The tool is skipped with a warning in the logs. Other tools are still registered.

**Q: Can I call dynamic tools from other dynamic tools?**  
A: Yes, all tools are registered with FastMCP and can call each other.

**Q: Are default parameter values preserved?**  
A: Yes, default values from the JSON Schema are applied when parameters are not provided.

**Q: What types of MCP servers are supported?**  
A: Currently only Podman container-based servers with stdio communication. Stdio proxy servers are partially supported.

---

## References

- [MCP Protocol Specification](https://modelcontextprotocol.io/docs)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [JSON Schema Specification](https://json-schema.org/)
- [Pydantic Field Documentation](https://docs.pydantic.dev/latest/api/fields/)

---

## Changelog

### 2025-11-11 - v1.0 - Initial Implementation

- ✅ Created `schema_converter.py` module
- ✅ Implemented JSON Schema to Python type mapping
- ✅ Implemented dynamic function generation with explicit parameters
- ✅ Integrated with `registry_add` and `registry_remove`
- ✅ Added 27 unit tests for schema converter
- ✅ Added 6 integration tests
- ✅ All 103 tests passing
- ✅ Documentation complete