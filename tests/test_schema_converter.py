"""Tests for JSON Schema to Python function converter."""

import inspect
from typing import Any

import pytest
from mcp_registry_server.schema_converter import (
    convert_tool_to_function,
    create_dynamic_tool_function,
    json_type_to_python_type,
    parse_schema_property,
    validate_tool_schema,
)


class TestJsonTypeToPythonType:
    """Test JSON Schema type to Python type conversion."""

    def test_string_type(self):
        """Test string type conversion."""
        assert json_type_to_python_type("string") == str

    def test_number_type(self):
        """Test number type conversion."""
        assert json_type_to_python_type("number") == float

    def test_integer_type(self):
        """Test integer type conversion."""
        assert json_type_to_python_type("integer") == int

    def test_boolean_type(self):
        """Test boolean type conversion."""
        assert json_type_to_python_type("boolean") == bool

    def test_object_type(self):
        """Test object type conversion."""
        assert json_type_to_python_type("object") == dict

    def test_array_type(self):
        """Test array type conversion."""
        assert json_type_to_python_type("array") == list

    def test_null_type(self):
        """Test null type conversion."""
        assert json_type_to_python_type("null") == type(None)

    def test_unknown_type(self):
        """Test unknown type defaults to Any."""
        assert json_type_to_python_type("unknown") == Any

    def test_union_type_with_null(self):
        """Test union type with null becomes optional."""
        result = json_type_to_python_type(["string", "null"])
        # Should be str | None
        assert result == str | None

    def test_union_type_without_null(self):
        """Test union type without null picks first type."""
        result = json_type_to_python_type(["string", "integer"])
        assert result == str


class TestParseSchemaProperty:
    """Test schema property parsing."""

    def test_required_string_property(self):
        """Test parsing required string property."""
        schema = {"type": "string", "description": "A test string"}
        name, typ, default, desc = parse_schema_property("test", schema, required=True)

        assert name == "test"
        assert typ == str
        assert default is ...  # Required field marker
        assert desc == "A test string"

    def test_optional_string_property(self):
        """Test parsing optional string property."""
        schema = {"type": "string", "description": "An optional string"}
        name, typ, default, desc = parse_schema_property("test", schema, required=False)

        assert name == "test"
        assert typ == str | None
        assert default is None
        assert desc == "An optional string"

    def test_property_with_default(self):
        """Test property with explicit default value."""
        schema = {"type": "integer", "default": 42, "description": "A number"}
        name, typ, default, desc = parse_schema_property(
            "count", schema, required=False
        )

        assert name == "count"
        assert typ == int
        assert default == 42
        assert desc == "A number"

    def test_property_without_description(self):
        """Test property without description."""
        schema = {"type": "boolean"}
        name, typ, default, desc = parse_schema_property("flag", schema, required=True)

        assert name == "flag"
        assert typ == bool
        assert default is ...
        assert desc == ""


class TestCreateDynamicToolFunction:
    """Test dynamic tool function creation."""

    @pytest.mark.asyncio
    async def test_function_with_no_parameters(self):
        """Test creating function with no parameters."""

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            return f"Executed {tool_name}"

        schema = {"type": "object", "properties": {}}

        func = create_dynamic_tool_function(
            tool_name="test_tool",
            tool_description="A test tool",
            input_schema=schema,
            executor=executor,
        )

        assert callable(func)
        assert func.__name__ == "test_tool"
        assert func.__doc__ == "A test tool"

        # Should be callable with no arguments
        result = await func()
        assert result == "Executed test_tool"

    @pytest.mark.asyncio
    async def test_function_with_required_parameter(self):
        """Test creating function with required parameter."""
        call_count = []

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            call_count.append((tool_name, arguments))
            return f"Executed {tool_name} with {arguments}"

        schema = {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "SQL query"}},
            "required": ["query"],
        }

        func = create_dynamic_tool_function(
            tool_name="read_query",
            tool_description="Execute a query",
            input_schema=schema,
            executor=executor,
        )

        # Check signature
        sig = inspect.signature(func)
        assert "query" in sig.parameters
        param = sig.parameters["query"]
        assert param.annotation == str

        # Call function
        result = await func(query="SELECT * FROM users")
        assert "Executed read_query" in result
        assert len(call_count) == 1
        assert call_count[0][0] == "read_query"
        assert call_count[0][1] == {"query": "SELECT * FROM users"}

    @pytest.mark.asyncio
    async def test_function_with_optional_parameter(self):
        """Test creating function with optional parameter."""
        call_count = []

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            call_count.append((tool_name, arguments))
            return "OK"

        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query"},
                "limit": {
                    "type": "integer",
                    "description": "Row limit",
                    "default": 100,
                },
            },
            "required": ["query"],
        }

        func = create_dynamic_tool_function(
            tool_name="read_query",
            tool_description="Execute a query",
            input_schema=schema,
            executor=executor,
        )

        # Check signature
        sig = inspect.signature(func)
        assert "query" in sig.parameters
        assert "limit" in sig.parameters

        # Call with only required parameter
        await func(query="SELECT * FROM users")
        assert call_count[0][1] == {"query": "SELECT * FROM users", "limit": 100}

        # Call with both parameters
        call_count.clear()
        await func(query="SELECT * FROM users", limit=50)
        assert call_count[0][1] == {"query": "SELECT * FROM users", "limit": 50}

    @pytest.mark.asyncio
    async def test_function_with_multiple_types(self):
        """Test creating function with multiple parameter types."""

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            return str(arguments)

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "score": {"type": "number"},
                "active": {"type": "boolean"},
                "metadata": {"type": "object"},
                "tags": {"type": "array"},
            },
            "required": ["name"],
        }

        func = create_dynamic_tool_function(
            tool_name="multi_type",
            tool_description="Multiple types",
            input_schema=schema,
            executor=executor,
        )

        # Check signature types
        sig = inspect.signature(func)
        assert sig.parameters["name"].annotation == str
        assert sig.parameters["age"].annotation == int | None
        assert sig.parameters["score"].annotation == float | None
        assert sig.parameters["active"].annotation == bool | None
        assert sig.parameters["metadata"].annotation == dict | None
        assert sig.parameters["tags"].annotation == list | None


class TestConvertToolToFunction:
    """Test full tool conversion."""

    @pytest.mark.asyncio
    async def test_convert_simple_tool(self):
        """Test converting a simple tool definition."""
        executions = []

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            executions.append((tool_name, arguments))
            return "Success"

        tool_def = {
            "name": "list_tables",
            "description": "List all database tables",
            "inputSchema": {"type": "object", "properties": {}},
        }

        name, func = convert_tool_to_function(tool_def, "sqlite", executor)

        assert name == "mcp_sqlite_list_tables"
        assert callable(func)
        assert "List all database tables" in func.__doc__

        # Call function
        result = await func()
        assert result == "Success"
        assert len(executions) == 1
        assert executions[0][0] == "list_tables"

    @pytest.mark.asyncio
    async def test_convert_tool_with_parameters(self):
        """Test converting tool with parameters."""
        executions = []

        async def executor(tool_name: str, arguments: dict[str, Any]) -> str:
            executions.append((tool_name, arguments))
            return f"Executed with {arguments}"

        tool_def = {
            "name": "read_query",
            "description": "Execute a SELECT query",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query to run"},
                    "limit": {
                        "type": "integer",
                        "description": "Max rows",
                        "default": 100,
                    },
                },
                "required": ["query"],
            },
        }

        name, func = convert_tool_to_function(tool_def, "sqlite", executor)

        assert name == "mcp_sqlite_read_query"

        # Call with parameters
        result = await func(query="SELECT * FROM users", limit=50)
        assert "Executed with" in result
        assert executions[0] == (
            "read_query",
            {"query": "SELECT * FROM users", "limit": 50},
        )


class TestValidateToolSchema:
    """Test tool schema validation."""

    def test_valid_tool_schema(self):
        """Test validating a valid tool schema."""
        tool_def = {
            "name": "test_tool",
            "description": "A test",
            "inputSchema": {
                "type": "object",
                "properties": {"param": {"type": "string"}},
            },
        }

        valid, error = validate_tool_schema(tool_def)
        assert valid is True
        assert error == ""

    def test_tool_without_input_schema(self):
        """Test tool without inputSchema is valid."""
        tool_def = {"name": "test_tool", "description": "A test"}

        valid, error = validate_tool_schema(tool_def)
        assert valid is True

    def test_tool_without_name(self):
        """Test tool without name is invalid."""
        tool_def = {"description": "A test"}

        valid, error = validate_tool_schema(tool_def)
        assert valid is False
        assert "name" in error.lower()

    def test_tool_not_dict(self):
        """Test non-dict tool is invalid."""
        valid, error = validate_tool_schema("not a dict")
        assert valid is False
        assert "dict" in error.lower()

    def test_invalid_input_schema_type(self):
        """Test invalid inputSchema type."""
        tool_def = {
            "name": "test_tool",
            "inputSchema": "not a dict",
        }

        valid, error = validate_tool_schema(tool_def)
        assert valid is False
        assert "inputSchema" in error

    def test_invalid_properties_type(self):
        """Test invalid properties type."""
        tool_def = {
            "name": "test_tool",
            "inputSchema": {
                "type": "object",
                "properties": "not a dict",
            },
        }

        valid, error = validate_tool_schema(tool_def)
        assert valid is False
        assert "properties" in error

    def test_complex_type_warning(self, caplog):
        """Test that complex types generate warnings but don't fail validation."""
        tool_def = {
            "name": "test_tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "nested": {"type": "object", "description": "Nested object"},
                    "items": {"type": "array", "description": "Array of items"},
                },
            },
        }

        valid, error = validate_tool_schema(tool_def)
        assert valid is True
        # Should have logged warnings about complex types
