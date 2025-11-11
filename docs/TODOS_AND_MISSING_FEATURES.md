# TODOs and Missing Features

**Last Updated:** 2025-11-11  
**Status:** Post-Initial Implementation

---

## 🚨 Critical Missing Features

### 1. Dynamic Tool Exposure to MCP Clients

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** **CRITICAL**  
**Impact:** High - Core functionality gap

**Problem:**
Currently, when an MCP server is activated via `registry_add`, the tools are:
- ✅ Discovered from the containerized server
- ✅ Stored in `ActiveMount.tools` list
- ❌ **NOT exposed as callable tools through the registry's MCP interface**

**Current Behavior:**
```python
# After registry_add("docker/sqlite", "zed", "sqlite")
# Tools are discovered: ['read_query', 'write_query', 'list_tables', ...]
# But MCP clients only see the static registry tools:
# - registry_find
# - registry_add
# - registry_exec  # ← User must manually call this
# - registry_remove
# etc.
```

**Expected Behavior:**
```python
# After registry_add("docker/sqlite", "zed", "sqlite")
# MCP clients should see dynamically added tools:
# - mcp_sqlite_read_query
# - mcp_sqlite_write_query
# - mcp_sqlite_list_tables
# - mcp_sqlite_create_table
# - etc.
```

**Solution Required:**
Use FastMCP's `add_tool()` method to dynamically register discovered tools.

**CRITICAL LIMITATION DISCOVERED:**
FastMCP does not support registering functions with `**kwargs` as tools. This means we CANNOT use a simple wrapper function like:

```python
async def dynamic_tool(**kwargs):
    return await registry_exec(...)
```

This will fail with: `Functions with **kwargs are not supported as tools`

**Required Approach:**
Must convert MCP tool JSON Schema to explicit Python function parameters:

```python
# In registry_add, after discovering tools:
for tool in tools:
    tool_name = tool.get("name")
    tool_description = tool.get("description", "")
    tool_schema = tool.get("inputSchema", {})
    
    # STEP 1: Convert JSON Schema to Python function signature
    # This requires parsing the schema and creating typed parameters
    params = convert_json_schema_to_params(tool_schema)
    
    # STEP 2: Dynamically create function with explicit parameters
    # Cannot use **kwargs!
    dynamic_fn = create_typed_function(params, tool_name, prefix)
    
    # STEP 3: Register with FastMCP
    mcp.add_tool(
        name=f"mcp_{prefix}_{tool_name}",
        description=tool_description,
    )(dynamic_fn)
```

**Challenges:**
- ⚠️ **CRITICAL**: Must convert MCP JSON Schema to explicit Python parameters (no **kwargs)
- Need to dynamically generate function signatures at runtime
- Need to preserve type annotations for FastMCP schema generation
- Need to maintain function references for cleanup
- Need to handle tool name collisions
- Need to unregister tools when server is deactivated
- Complex types (nested objects, arrays, unions) require special handling

**Implementation Complexity:** HIGH - Requires runtime function generation with proper type annotations

**Files to Modify:**
- `mcp_registry_server/server.py` - Add dynamic tool registration in `registry_add`
- `mcp_registry_server/server.py` - Add tool unregistration in `registry_remove`

---

### 2. Tool Name Prefix Standardization

**Status:** ⚠️ INCONSISTENT  
**Priority:** **HIGH**  
**Impact:** Medium - User confusion

**Problem:**
Tool names from activated servers should be prefixed with `mcp_` for clarity, but currently are not.

**Current Behavior:**
```
registry_add → discovers tools → exposes as "sqlite_list_tables"
```

**Expected Behavior:**
```
registry_add → discovers tools → exposes as "mcp_sqlite_list_tables"
```

**Solution:**
Update all tool name formatting to include `mcp_` prefix:

```python
# In registry_add output
f"  - mcp_{prefix}_{tool}"

# In registry_exec parsing
if not tool_name.startswith("mcp_"):
    return "Invalid tool name. Must start with 'mcp_'"
    
prefix = tool_name.split("_")[1]  # Extract prefix after "mcp_"
actual_tool_name = "_".join(tool_name.split("_")[2:])  # Rest after prefix
```

**Files to Modify:**
- `mcp_registry_server/server.py` - Update `registry_add` output formatting
- `mcp_registry_server/server.py` - Update `registry_exec` parsing logic
- `mcp_registry_server/server.py` - Update dynamic tool registration (when implemented)

---

## ⚠️ High Priority Features

### 3. MCP Resources Support

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** HIGH  
**Impact:** Medium - Missing core MCP feature

**Description:**
MCP protocol supports resources (files, data sources) in addition to tools. Containerized servers may expose resources that should be accessible.

**Implementation Needed:**
- Discover resources via `resources/list` during activation
- Implement `resources/read` forwarding
- Dynamically expose resources through registry server
- Handle resource subscriptions if needed

**Files to Modify:**
- `mcp_registry_server/mcp_client.py` - Add `list_resources()`, `read_resource()`
- `mcp_registry_server/server.py` - Add resource discovery in `registry_add`
- `mcp_registry_server/models.py` - Add resources to `ActiveMount`

---

### 4. MCP Prompts Support

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** HIGH  
**Impact:** Medium - Missing core MCP feature

**Description:**
MCP protocol supports prompts (templates for LLM interactions). Should be discovered and exposed.

**Implementation Needed:**
- Discover prompts via `prompts/list` during activation
- Implement `prompts/get` forwarding
- Dynamically expose prompts through registry server

**Files to Modify:**
- `mcp_registry_server/mcp_client.py` - Add `list_prompts()`, `get_prompt()`
- `mcp_registry_server/server.py` - Add prompt discovery in `registry_add`
- `mcp_registry_server/models.py` - Add prompts to `ActiveMount`

---

### 5. Connection Health Monitoring

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** HIGH  
**Impact:** Medium - Reliability issue

**Description:**
No health checks for active MCP connections. Containers may crash or hang without detection.

**Implementation Needed:**
- Periodic ping/health check to MCP clients
- Automatic reconnection on failure
- Status reporting in `registry_active`
- Alerts/logging for unhealthy connections

**Suggested Approach:**
```python
class MCPClient:
    async def ping(self) -> bool:
        """Send a ping to check if connection is alive."""
        try:
            # MCP doesn't have ping, but we can use tools/list
            await asyncio.wait_for(self.list_tools(), timeout=5.0)
            return True
        except:
            return False

# Background task
async def health_check_loop():
    while True:
        for container_id, client in mcp_client_manager._clients.items():
            if not await client.ping():
                logger.error(f"Connection lost to {container_id}")
                # Mark as unhealthy or attempt reconnect
        await asyncio.sleep(30)  # Check every 30s
```

**Files to Modify:**
- `mcp_registry_server/mcp_client.py` - Add health check method
- `mcp_registry_server/tasks.py` - Add health check background task
- `mcp_registry_server/models.py` - Add health status to `ActiveMount`

---

### 6. Environment Variable Application Without Restart

**Status:** ⚠️ LIMITATION  
**Priority:** HIGH  
**Impact:** Medium - Poor UX

**Current Behavior:**
`registry_config_set` updates environment variables in ActiveMount, but requires container restart to take effect.

**Desired Behavior:**
Apply environment changes to running container if possible, or auto-restart container.

**Options:**
1. **Auto-restart on config change** (safest)
   ```python
   async def registry_config_set(...):
       # Update config
       # Stop container
       # Restart with new environment
       # Reinitialize MCP client
   ```

2. **Runtime environment injection** (if supported by MCP server)
   - Some servers may support runtime config updates
   - Could send a custom notification to server

**Files to Modify:**
- `mcp_registry_server/server.py` - Implement auto-restart in `registry_config_set`

---

## 📋 Medium Priority Features

### 7. JSON Schema to Dynamic Function Signature Conversion

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** **CRITICAL** (blocking feature #1)  
**Impact:** HIGH - Required for dynamic tools, FastMCP limitation discovered

**Description:**
⚠️ **CRITICAL BLOCKER**: FastMCP does not support `**kwargs` in tool functions. Must convert MCP tool JSON Schemas to explicit Python function parameters with proper type annotations.

**Problem:**
```python
# THIS DOES NOT WORK - FastMCP rejects it
async def dynamic_tool(**kwargs):
    return await registry_exec(tool_name=..., arguments=kwargs)

# Error: "Functions with **kwargs are not supported as tools"
```

**Required Solution:**
```python
# MCP JSON Schema
{
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "SQL query to execute"
        },
        "limit": {
            "type": "integer",
            "default": 100
        }
    },
    "required": ["query"]
}

# Must dynamically generate THIS function signature:
from typing import Annotated
from pydantic import Field

async def mcp_sqlite_read_query(
    query: Annotated[str, Field(..., description="SQL query to execute")],
    limit: Annotated[int, Field(100)] = 100
) -> str:
    return await registry_exec(
        tool_name="mcp_sqlite_read_query",
        arguments={"query": query, "limit": limit}
    )
```

**Implementation Approaches:**

1. **Runtime code generation** (using `exec()`)
   - Generate function source code as string
   - Execute with `exec()` to create function object
   - Pros: Full control over signature
   - Cons: Security concerns, harder to debug

2. **Function factory with annotations** (using `typing.get_type_hints()`)
   - Build function dynamically with `types.FunctionType()`
   - Attach `__annotations__` dict
   - Pros: More secure, type-safe
   - Cons: Complex, may not work with all FastMCP features

3. **Pydantic model wrapper** (using BaseModel)
   - Create Pydantic model for each tool
   - Wrap in function that accepts model instance
   - Pros: Type-safe, validated
   - Cons: May not integrate cleanly with FastMCP

**Recommended:** Approach #1 (code generation) with careful sanitization

**Files to Create:**
- `mcp_registry_server/schema_converter.py` - JSON Schema → Python function signature converter
- `mcp_registry_server/dynamic_tools.py` - Runtime function generation and registration

**Complexity:** Very High - Requires careful handling of:
- Type mapping (JSON Schema → Python types)
- Optional vs required parameters
- Default values
- Nested objects and arrays
- Union types
- Description propagation
- Security (code injection prevention)

---

### 8. Tool Execution Timeout Configuration

**Status:** ⚠️ HARDCODED  
**Priority:** MEDIUM  
**Impact:** Low - Edge case handling

**Current State:**
Tool execution timeout is hardcoded to 15 seconds in some places, 10 seconds in others.

**Improvement:**
Make timeout configurable per-server or per-tool:

```python
# In ActiveMount
class ActiveMount(BaseModel):
    ...
    tool_timeout: int = 30  # Default timeout in seconds
    
# In registry_exec
result = await asyncio.wait_for(
    client.call_tool(actual_tool_name, arguments),
    timeout=mount.tool_timeout
)
```

**Files to Modify:**
- `mcp_registry_server/models.py` - Add timeout field
- `mcp_registry_server/server.py` - Use configurable timeout

---

### 9. Better Error Messages with Troubleshooting

**Status:** ⚠️ BASIC  
**Priority:** MEDIUM  
**Impact:** Low - UX improvement

**Current State:**
Error messages are functional but could be more helpful.

**Improvement Examples:**
```python
# Current
return "Failed to initialize MCP client for SQLite: timeout"

# Better
return """Failed to initialize MCP client for SQLite: timeout

Troubleshooting:
1. Check that the container image supports MCP protocol
2. Verify the container command is correct (try: podman logs <container>)
3. Ensure required environment variables are set
4. Check container resource limits

For more help: https://docs.mcp-registry.io/troubleshooting
"""
```

**Files to Modify:**
- `mcp_registry_server/server.py` - Enhance all error messages

---

### 10. Streaming Tool Results

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** MEDIUM  
**Impact:** Low - Nice to have

**Description:**
Some tools may produce streaming output (e.g., large query results). Support streaming if MCP protocol allows.

**Implementation:**
- Check if MCP protocol supports streaming results
- Implement streaming in MCPClient
- Return streaming results through registry_exec

---

## 🔧 Low Priority / Nice to Have

### 11. Volume Mount Support

**Status:** ⚠️ DISABLED  
**Priority:** LOW  
**Impact:** Low - Security vs. functionality tradeoff

**Current State:**
Volume mounts are explicitly disabled in `podman_runner.py` for security.

**Consideration:**
Enable volume mounts with strict validation:
- Whitelist allowed mount paths
- Read-only mounts by default
- User confirmation required

**Files to Modify:**
- `mcp_registry_server/podman_runner.py` - Add secure volume mount support

---

### 12. Connection Pooling / Multiplexing

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Performance optimization

**Description:**
Currently one container = one MCP connection. Could support multiple clients to same container.

**Use Case:**
Multiple concurrent tool executions to same server.

---

### 13. Server Metrics & Monitoring

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Observability

**Desired Features:**
- Tool execution counts
- Average execution time
- Error rates
- Container resource usage
- Active connection count

**Implementation:**
- Add metrics collection in `registry_exec`
- Expose via `registry_status` or separate tool
- Consider Prometheus export

---

### 14. Auto-Restart on Failure

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Reliability improvement

**Description:**
Automatically restart containers that crash or become unresponsive.

**Implementation:**
- Detect failure via health checks
- Attempt restart with exponential backoff
- Limit retry attempts
- Log failures

---

### 15. Service Mesh Integration

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Advanced deployment

**Description:**
For production deployments, integrate with service mesh (Istio, Linkerd) for:
- Traffic management
- Security policies
- Observability
- Resilience

---

## 🧪 Testing Gaps

### 16. Integration Test Coverage

**Status:** ⚠️ PARTIAL  
**Priority:** MEDIUM  
**Impact:** Medium - Quality assurance

**Current Coverage:** 44%  
**Target Coverage:** 70%

**Missing Tests:**
- Full server lifecycle tests
- Error handling scenarios
- Concurrent tool execution
- Container failure recovery
- Environment variable changes
- Multiple active servers
- Tool name collision handling

**Files Needed:**
- `tests/test_integration.py` - Full workflow tests
- `tests/test_mcp_client.py` - MCP client unit tests
- `tests/test_podman_runner.py` - Container management tests

---

### 17. Load Testing

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Performance validation

**Needed:**
- Concurrent tool execution stress test
- Multiple server activation test
- Long-running connection stability test

---

## 📚 Documentation Gaps

### 18. User-Facing Workflow Guide

**Status:** ⚠️ PARTIAL  
**Priority:** MEDIUM  
**Impact:** Medium - Adoption

**Needed:**
Update QUICKSTART.md with:
- Step-by-step activation workflow
- Common use cases
- Troubleshooting guide
- Best practices

---

### 19. API Reference Documentation

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** MEDIUM  
**Impact:** Medium - Developer experience

**Needed:**
- Auto-generated API docs from docstrings
- Tool schema documentation
- Example requests/responses
- Error code reference

---

## 🔒 Security Enhancements

### 20. Resource Limits

**Status:** ⚠️ NOT ENFORCED  
**Priority:** MEDIUM  
**Impact:** Medium - Security

**Current State:**
Containers run without explicit resource limits.

**Recommendation:**
```python
await podman_runner.run_interactive_container(
    image=image,
    name=name,
    environment=env,
    command=cmd,
    # Add resource limits
    memory_limit="512m",
    cpu_limit=1.0,
    pids_limit=100
)
```

**Files to Modify:**
- `mcp_registry_server/podman_runner.py` - Add resource limit parameters

---

### 21. Network Isolation

**Status:** ⚠️ NOT ENFORCED  
**Priority:** MEDIUM  
**Impact:** Medium - Security

**Current State:**
Containers have default network access.

**Recommendation:**
Use `--network=none` by default, allow opt-in network access.

**Files to Modify:**
- `mcp_registry_server/podman_runner.py` - Add network isolation

---

### 22. Security Scanning

**Status:** ❌ NOT IMPLEMENTED  
**Priority:** LOW  
**Impact:** Low - Proactive security

**Desired:**
- Scan container images before activation
- Check for known vulnerabilities
- Warn users of security issues

---

## 📊 Summary

### By Priority

| Priority | Count | Items |
|----------|-------|-------|
| CRITICAL | 2 | #1 (Dynamic Tools), #2 (Prefix) |
| HIGH | 4 | #3 (Resources), #4 (Prompts), #5 (Health), #6 (Env) |
| MEDIUM | 8 | #7-14, #16, #18-21 |
| LOW | 8 | #11-15, #17, #22 |

### By Category

| Category | Count |
|----------|-------|
| Missing Features | 11 |
| Improvements | 6 |
| Testing | 2 |
| Documentation | 2 |
| Security | 3 |

### Immediate Action Items

1. ~~**Implement dynamic tool exposure** (#1) - CRITICAL~~ 
   - ⚠️ **BLOCKED**: FastMCP limitation discovered - no **kwargs support
   - Requires #7 (JSON Schema conversion) to be implemented first
2. **✅ Standardize tool name prefix** (#2) - IMPLEMENTED (mcp_ prefix added)
3. **Implement JSON Schema to function signature converter** (#7) - NOW CRITICAL
4. **Add connection health monitoring** (#5) - HIGH
5. **Implement auto-restart on config change** (#6) - HIGH

---

**Next Steps:**
1. ✅ **DONE**: Implemented #2 (mcp_ prefix standardization)
2. ⚠️ **BLOCKED**: #1 requires #7 to be implemented first
3. **URGENT**: Implement #7 (JSON Schema → function signature conversion)
   - Research best approach for runtime function generation
   - Implement secure code generation with type preservation
   - Add comprehensive tests for various schema patterns
4. Resume #1 after #7 is complete
5. Plan architecture for #3 and #4 (resources/prompts)
6. Add integration tests (#16) for existing functionality
7. Update user documentation (#18)

**Current Status:**
- Registry stdio communication: ✅ Working
- Tool discovery: ✅ Working  
- Tool execution via registry_exec: ✅ Working
- Dynamic tool registration: ⚠️ Blocked by FastMCP limitation
- Tool name prefix: ✅ Implemented (mcp_ prefix)