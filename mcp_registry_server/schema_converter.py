"""JSON Schema to Python function signature converter for dynamic MCP tool registration.

This module provides utilities to convert MCP tool JSON Schema definitions into
Python functions with explicit, typed parameters that can be registered with FastMCP.

FastMCP does not support functions with **kwargs, so we must dynamically generate
functions with explicit parameter signatures based on the tool's inputSchema.
"""

import inspect
import logging
from typing import Any, Callable, get_args, get_origin

from pydantic import Field

logger = logging.getLogger(__name__)


def json_type_to_python_type(json_type: str, json_format: str | None = None) -> type:
    """Convert JSON Schema type to Python type annotation.

    Args:
        json_type: JSON Schema type (string, number, integer, boolean, object, array, null)
        json_format: Optional JSON Schema format hint

    Returns:
        Python type for use in type annotations
    """
    type_mapping = {
        "string": str,
        "number": float,
        "integer": int,
        "boolean": bool,
        "object": dict,
        "array": list,
        "null": type(None),
    }

    # Handle array of types (e.g., ["string", "null"])
    if isinstance(json_type, list):
        # Union type - for now, pick the first non-null type
        non_null_types = [t for t in json_type if t != "null"]
        if non_null_types:
            base_type = type_mapping.get(non_null_types[0], Any)
            if "null" in json_type:
                # Optional type
                return base_type | None
            return base_type
        return type(None)

    return type_mapping.get(json_type, Any)


def parse_schema_property(
    prop_name: str,
    prop_schema: dict[str, Any],
    required: bool = False,
) -> tuple[str, type, Any, str]:
    """Parse a JSON Schema property into Python function parameter components.

    Args:
        prop_name: Property name
        prop_schema: Property schema definition
        required: Whether this property is required

    Returns:
        Tuple of (param_name, param_type, default_value, description)
    """
    # Get type
    json_type = prop_schema.get("type", "string")
    json_format = prop_schema.get("format")
    param_type = json_type_to_python_type(json_type, json_format)

    # Get description
    description = prop_schema.get("description", "")

    # Determine default value
    if required:
        # Use ... (Ellipsis) for required fields (Pydantic convention)
        default_value = ...
    else:
        # Use schema default if provided, otherwise None
        if "default" in prop_schema:
            default_value = prop_schema["default"]
        else:
            # Make it optional
            if param_type != type(None) and not (
                get_origin(param_type) is type(None)
                or (
                    hasattr(param_type, "__args__")
                    and type(None) in get_args(param_type)
                )
            ):
                param_type = param_type | None
            default_value = None

    return (prop_name, param_type, default_value, description)


def create_dynamic_tool_function(
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    executor: Callable,
) -> Callable:
    """Create a dynamic function with explicit parameters from JSON Schema.

    This function dynamically generates a Python function with typed parameters
    based on the tool's JSON Schema, allowing it to be registered with FastMCP.

    Args:
        tool_name: Name of the tool (will be used for function name)
        tool_description: Tool description (will be used as docstring)
        input_schema: JSON Schema definition of tool inputs
        executor: Async function to call with the arguments (signature: async def(tool_name, **kwargs))

    Returns:
        Async function with explicit typed parameters

    Example:
        >>> schema = {
        ...     "type": "object",
        ...     "properties": {
        ...         "query": {"type": "string", "description": "SQL query"},
        ...         "limit": {"type": "integer", "description": "Row limit"}
        ...     },
        ...     "required": ["query"]
        ... }
        >>> async def executor(name, **kwargs):
        ...     return f"Executed {name} with {kwargs}"
        >>> fn = create_dynamic_tool_function("read_query", "Execute query", schema, executor)
        >>> # fn now has signature: async def fn(query: str = Field(...), limit: int | None = Field(None))
    """
    # Parse schema
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    # Build parameter specifications
    params = []
    annotations = {}
    defaults = {}
    raw_defaults = {}  # Store raw default values for kwargs reconstruction

    for prop_name, prop_schema in properties.items():
        is_required = prop_name in required_fields
        param_name, param_type, default_value, description = parse_schema_property(
            prop_name, prop_schema, is_required
        )

        # Store annotation
        annotations[param_name] = param_type

        # Store default (wrapped in Field for better FastMCP integration)
        if default_value is ...:
            defaults[param_name] = Field(..., description=description)
            raw_defaults[param_name] = None  # No default for required params
        else:
            defaults[param_name] = Field(default_value, description=description)
            raw_defaults[param_name] = default_value

        params.append(param_name)

    # Create function dynamically
    # We need to build the function with proper signature

    # Build the parameter list for the function signature
    sig_params = []
    for param_name in params:
        param_type = annotations[param_name]
        default = defaults[param_name]

        # Create parameter with annotation and default
        sig_params.append(
            inspect.Parameter(
                param_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=param_type,
            )
        )

    # Create signature
    sig = inspect.Signature(
        parameters=sig_params,
        return_annotation=str,  # All MCP tools return str
    )

    # Create the function body
    # We need to create a closure that captures the executor and tool_name
    def make_function():
        async def dynamic_tool(**kwargs) -> str:
            """Dynamically generated tool from MCP server."""
            # Build complete arguments with defaults applied
            clean_kwargs = {}

            # First, apply all defaults
            for param_name, default_val in raw_defaults.items():
                if default_val is not None:
                    clean_kwargs[param_name] = default_val

            # Then override with provided values
            for key, value in kwargs.items():
                clean_kwargs[key] = value

            # Call the executor with the tool name and arguments
            return await executor(tool_name, clean_kwargs)

        return dynamic_tool

    func = make_function()

    # Update function metadata
    func.__name__ = tool_name.replace("-", "_")  # Ensure valid Python identifier
    func.__doc__ = tool_description or f"Tool: {tool_name}"
    func.__signature__ = sig
    func.__annotations__ = {**annotations, "return": str}

    return func


def convert_tool_to_function(
    tool_definition: dict[str, Any],
    prefix: str,
    executor: Callable,
) -> tuple[str, Callable]:
    """Convert an MCP tool definition to a Python function.

    Args:
        tool_definition: MCP tool definition with name, description, inputSchema
        prefix: Prefix for the tool name (e.g., "sqlite" -> "mcp_sqlite_toolname")
        executor: Async executor function (signature: async def(tool_name, arguments: dict))

    Returns:
        Tuple of (full_tool_name, function)

    Example:
        >>> tool_def = {
        ...     "name": "read_query",
        ...     "description": "Execute SQL",
        ...     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}}
        ... }
        >>> async def exec(name, args):
        ...     return f"Executed {name}"
        >>> name, func = convert_tool_to_function(tool_def, "sqlite", exec)
        >>> name
        'mcp_sqlite_read_query'
    """
    tool_name = tool_definition.get("name", "unknown")
    tool_description = tool_definition.get("description", "")
    input_schema = tool_definition.get(
        "inputSchema", {"type": "object", "properties": {}}
    )

    # Create full tool name with prefix
    full_tool_name = f"mcp_{prefix}_{tool_name}"

    # Create the dynamic function
    func = create_dynamic_tool_function(
        tool_name=tool_name,
        tool_description=tool_description,
        input_schema=input_schema,
        executor=executor,
    )

    return (full_tool_name, func)


def validate_tool_schema(tool_definition: dict[str, Any]) -> tuple[bool, str]:
    """Validate that a tool definition has a valid schema for conversion.

    Args:
        tool_definition: MCP tool definition

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(tool_definition, dict):
        return (False, "Tool definition must be a dict")

    if "name" not in tool_definition:
        return (False, "Tool definition missing 'name' field")

    if "inputSchema" not in tool_definition:
        # Some tools may have no inputs - that's OK
        return (True, "")

    schema = tool_definition["inputSchema"]
    if not isinstance(schema, dict):
        return (False, "inputSchema must be a dict")

    # Check if schema is too complex
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return (False, "inputSchema.properties must be a dict")

    # Warn about complex types (but don't reject)
    for prop_name, prop_schema in properties.items():
        if isinstance(prop_schema, dict):
            prop_type = prop_schema.get("type")
            if prop_type in ["object", "array"]:
                logger.warning(
                    f"Tool {tool_definition.get('name')} has complex type '{prop_type}' "
                    f"for parameter '{prop_name}'. This may not work perfectly."
                )

    return (True, "")
