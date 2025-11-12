# MCP Tools List Changed Notifications

## Overview

The mcp-registry server implements the MCP `notifications/tools/list_changed` protocol to automatically notify clients when the available tool list changes. This eliminates the need for clients to poll for tool updates and ensures they always have an up-to-date view of available tools.

## When Notifications Are Sent

The server sends `notifications/tools/list_changed` notifications in the following scenarios:

### 1. Adding a Podman Container Server (`mcp_registry_add`)

When a containerized MCP server is successfully activated:
1. Container is spawned using Podman
2. MCP client connection is established
3. Tools are discovered from the container
4. Tools are dynamically registered with FastMCP
5. **Notification is sent** ✅

### 2. Launching a Stdio Server (`mcp_registry_launch_stdio`)

When a stdio-based MCP server is successfully launched:
1. Process is spawned with the specified command
2. MCP client connection is established via stdio
3. Tools are discovered from the process
4. Tools are dynamically registered with FastMCP
5. **Notification is sent** ✅

### 3. Removing a Server (`mcp_registry_remove`)

When an active MCP server is deactivated:
1. Active mount is located
2. Dynamically registered tools are removed
3. MCP client is cleaned up
4. Container/process is stopped
5. **Notification is sent** ✅

## Implementation Details

### FastMCP Context Integration

The server uses FastMCP's `Context` object to send notifications:

```python
from fastmcp import Context, FastMCP

@mcp.tool()
async def registry_add(
    entry_id: str,
    prefix: str | None = None,
    ctx: Context = None,  # FastMCP injects this automatically
) -> str:
    # ... activate server and register tools ...
    
    # Send notification to client
    if ctx:
        await ctx.send_tool_list_changed()
        logger.info("Sent tools/list_changed notification to client")
    
    return "Success message"
```

### Key Points

1. **Context Parameter**: All tools that modify the tool list accept an optional `ctx: Context` parameter
2. **Automatic Injection**: FastMCP automatically injects the Context when the tool is called within an MCP request
3. **Optional/Backward Compatible**: The parameter defaults to `None`, so the tools work even without context
4. **Active Request Context Only**: Notifications are only sent during active MCP request contexts, not during server initialization

## Protocol Compliance

The implementation follows the MCP specification for tool list notifications:

- **Notification Method**: `notifications/tools/list_changed`
- **Direction**: Server → Client (one-way notification)
- **Timing**: Sent immediately after tools are added or removed
- **Purpose**: Inform clients that they should refresh their tool cache

## Client Behavior

MCP clients that support this notification can:

1. **Update Tool Cache**: Automatically refresh their internal list of available tools
2. **Update UI**: Refresh displays showing available tools to users
3. **Avoid Polling**: Eliminate the need to periodically check if tools have changed

### Example Client Handlers

```python
# Using FastMCP client
from fastmcp.client.messages import MessageHandler
import mcp.types

class ToolCacheHandler(MessageHandler):
    def __init__(self):
        self.cached_tools = []
    
    async def on_tool_list_changed(
        self, notification: mcp.types.ToolListChangedNotification
    ) -> None:
        """Clear tool cache when tools change."""
        print("Tools changed - clearing cache")
        self.cached_tools = []  # Force refresh on next access

client = Client("mcp-registry", message_handler=ToolCacheHandler())
```

## Testing

The notification feature includes comprehensive tests in `tests/test_notifications.py`:

- ✅ Context parameter is properly accepted by tools
- ✅ Notifications are not sent when operations fail early
- ✅ Tools work without context (backward compatibility)
- ✅ Protocol behavior is documented

Run tests with:
```bash
pytest tests/test_notifications.py -v
```

## Benefits

### For Users
- **Real-time Updates**: Clients stay synchronized with server state
- **Better UX**: No stale tool lists in UI
- **Reduced Latency**: Immediate awareness of new tools

### For Developers
- **Protocol Compliance**: Follows MCP specification
- **Clean Architecture**: Uses FastMCP's built-in notification system
- **Easy to Extend**: Pattern can be applied to resource and prompt notifications

## Future Enhancements

Potential improvements to the notification system:

1. **Resource Notifications**: Send `notifications/resources/list_changed` when resources are added/removed
2. **Prompt Notifications**: Send `notifications/prompts/list_changed` when prompts are added/removed
3. **Granular Updates**: Include details about which tools were added/removed in the notification
4. **Batch Operations**: Optimize notifications when multiple tools are registered simultaneously

## References

- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [FastMCP Documentation - Notifications](https://gofastmcp.com/servers/context)
- [FastMCP Documentation - Tools](https://gofastmcp.com/servers/tools)