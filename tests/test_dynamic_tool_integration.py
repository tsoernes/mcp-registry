"""Integration test for dynamic tool exposure through FastMCP.

This test verifies that tools discovered from MCP servers are properly
converted to Python functions and registered with FastMCP.
"""

import asyncio
from typing import Any

import pytest
from mcp_registry_server.schema_converter import (
    convert_tool_to_function,
    validate_tool_schema,
)


class TestDynamicToolIntegration:
    """Integration tests for dynamic tool registration workflow."""

    @pytest.mark.asyncio
    async def test_sqlite_tool_conversion(self):
        """Test converting actual SQLite MCP server tool definitions."""
        # Simulate tool definitions from SQLite MCP server
        sqlite_tools = [
            {
                "name": "read_query",
                "description": "Execute a SELECT query on the SQLite database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SELECT SQL query to execute",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "write_query",
                "description": "Execute an INSERT, UPDATE, or DELETE query",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute",
                        }
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "create_table",
                "description": "Create a new table in the database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Name of the table to create",
                        },
                        "schema": {
                            "type": "string",
                            "description": "Table schema definition",
                        },
                    },
                    "required": ["table_name", "schema"],
                },
            },
            {
                "name": "list_tables",
                "description": "List all tables in the database",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

        executions = []

        async def mock_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            """Mock executor that records calls."""
            executions.append((tool_name, arguments))
            return f"Executed {tool_name} with {arguments}"

        # Convert all tools
        converted_tools = []
        for tool in sqlite_tools:
            # Validate schema
            is_valid, error = validate_tool_schema(tool)
            assert is_valid, f"Invalid schema for {tool['name']}: {error}"

            # Convert to function
            full_name, func = convert_tool_to_function(tool, "sqlite", mock_executor)
            converted_tools.append((full_name, func))

        # Verify all tools were converted
        assert len(converted_tools) == 4

        # Test read_query
        read_query_name, read_query_func = converted_tools[0]
        assert read_query_name == "mcp_sqlite_read_query"
        result = await read_query_func(query="SELECT * FROM users")
        assert "Executed read_query" in result
        assert executions[-1] == ("read_query", {"query": "SELECT * FROM users"})

        # Test create_table
        create_table_name, create_table_func = converted_tools[2]
        assert create_table_name == "mcp_sqlite_create_table"
        result = await create_table_func(
            table_name="users", schema="id INTEGER, name TEXT"
        )
        assert "Executed create_table" in result
        assert executions[-1] == (
            "create_table",
            {"table_name": "users", "schema": "id INTEGER, name TEXT"},
        )

        # Test list_tables (no parameters)
        list_tables_name, list_tables_func = converted_tools[3]
        assert list_tables_name == "mcp_sqlite_list_tables"
        result = await list_tables_func()
        assert "Executed list_tables" in result
        assert executions[-1] == ("list_tables", {})

    @pytest.mark.asyncio
    async def test_filesystem_tool_conversion(self):
        """Test converting filesystem MCP server tool definitions."""
        filesystem_tools = [
            {
                "name": "read_file",
                "description": "Read contents of a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"}
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write contents to a file",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                        "content": {"type": "string", "description": "File content"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "list_directory",
                "description": "List directory contents",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path"},
                        "recursive": {
                            "type": "boolean",
                            "description": "List recursively",
                            "default": False,
                        },
                    },
                    "required": ["path"],
                },
            },
        ]

        executions = []

        async def mock_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            executions.append((tool_name, arguments))
            return "OK"

        # Convert all tools
        for tool in filesystem_tools:
            is_valid, error = validate_tool_schema(tool)
            assert is_valid, f"Invalid schema: {error}"

            full_name, func = convert_tool_to_function(
                tool, "filesystem", mock_executor
            )

            # Verify naming
            assert full_name.startswith("mcp_filesystem_")
            assert tool["name"] in full_name

        # Test list_directory with default parameter
        _, list_dir_func = convert_tool_to_function(
            filesystem_tools[2], "filesystem", mock_executor
        )
        await list_dir_func(path="/tmp")
        assert executions[-1] == (
            "list_directory",
            {"path": "/tmp", "recursive": False},
        )

        # Test with explicit parameter
        executions.clear()
        await list_dir_func(path="/tmp", recursive=True)
        assert executions[-1] == ("list_directory", {"path": "/tmp", "recursive": True})

    @pytest.mark.asyncio
    async def test_complex_parameter_types(self):
        """Test handling of complex parameter types."""
        complex_tools = [
            {
                "name": "complex_tool",
                "description": "Tool with various parameter types",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "count": {"type": "integer", "default": 10},
                        "threshold": {"type": "number", "default": 0.5},
                        "enabled": {"type": "boolean", "default": True},
                        "tags": {"type": "array", "description": "List of tags"},
                        "metadata": {"type": "object", "description": "Metadata dict"},
                    },
                    "required": ["text"],
                },
            }
        ]

        executions = []

        async def mock_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            executions.append((tool_name, arguments))
            return "OK"

        _, func = convert_tool_to_function(complex_tools[0], "test", mock_executor)

        # Call with only required parameter
        await func(text="hello")
        assert executions[-1] == (
            "complex_tool",
            {
                "text": "hello",
                "count": 10,
                "threshold": 0.5,
                "enabled": True,
            },
        )

        # Call with all parameters
        executions.clear()
        await func(
            text="hello",
            count=5,
            threshold=0.8,
            enabled=False,
            tags=["a", "b"],
            metadata={"key": "value"},
        )
        assert executions[-1] == (
            "complex_tool",
            {
                "text": "hello",
                "count": 5,
                "threshold": 0.8,
                "enabled": False,
                "tags": ["a", "b"],
                "metadata": {"key": "value"},
            },
        )

    @pytest.mark.asyncio
    async def test_tool_name_sanitization(self):
        """Test that tool names with hyphens are properly sanitized."""
        tools = [
            {
                "name": "read-query",
                "description": "Tool with hyphenated name",
                "inputSchema": {"type": "object", "properties": {}},
            }
        ]

        async def mock_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            return "OK"

        full_name, func = convert_tool_to_function(tools[0], "test", mock_executor)

        # Function name should have underscores
        assert func.__name__ == "read_query"
        # Full tool name should have the mcp_ prefix
        assert full_name == "mcp_test_read-query"

    @pytest.mark.asyncio
    async def test_multiple_prefixes(self):
        """Test that different prefixes create distinct tool names."""
        tool = {
            "name": "query",
            "description": "Execute query",
            "inputSchema": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        }

        async def mock_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            return "OK"

        # Convert with different prefixes
        name1, func1 = convert_tool_to_function(tool, "sqlite", mock_executor)
        name2, func2 = convert_tool_to_function(tool, "postgres", mock_executor)

        assert name1 == "mcp_sqlite_query"
        assert name2 == "mcp_postgres_query"
        assert name1 != name2

    @pytest.mark.asyncio
    async def test_error_handling_in_executor(self):
        """Test that executor errors are propagated properly."""

        async def failing_executor(tool_name: str, arguments: dict[str, Any]) -> str:
            raise ValueError("Execution failed")

        tool = {
            "name": "test_tool",
            "description": "Test",
            "inputSchema": {"type": "object", "properties": {}},
        }

        _, func = convert_tool_to_function(tool, "test", failing_executor)

        with pytest.raises(ValueError, match="Execution failed"):
            await func()
