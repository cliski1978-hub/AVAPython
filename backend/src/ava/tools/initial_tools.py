"""Initial runtime-independent read-only Workspace tool declarations."""

from ava.contracts.tools import (
    ToolCapability,
    ToolDefinition,
    ToolExecutionCategory,
    ToolRisk,
)
from ava.tools.authority import ToolOperationType

_NO_EXTRA = {"additionalProperties": False}


def initial_workspace_tools() -> tuple[ToolDefinition, ...]:
    """Return fresh AVA-owned definitions; registration grants no availability."""
    return (
        ToolDefinition(
            tool_id="workspace.list_files",
            name="List Workspace files",
            description="List a bounded page of entries in the authorized Workspace directory.",
            tool_version="1",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    "cursor": {"type": "string", "maxLength": 12},
                },
                "required": ["path"],
                **_NO_EXTRA,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["file", "directory"]},
                                "size_bytes": {"type": "integer", "minimum": 0},
                                "modified_at": {"type": "string"},
                            },
                            "required": ["name", "type", "modified_at"],
                            "additionalProperties": False,
                        },
                    },
                    "next_cursor": {"type": "string"},
                },
                "required": ["entries"],
                "additionalProperties": False,
            },
            required_capabilities=(ToolCapability.FILE_READ,),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        ),
        ToolDefinition(
            tool_id="workspace.read_file",
            name="Read Workspace file",
            description="Read a bounded UTF-8 text file from the authorized Workspace.",
            tool_version="1",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "max_bytes": {"type": "integer", "minimum": 1, "maximum": 1048576},
                },
                "required": ["path"],
                **_NO_EXTRA,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "encoding": {"type": "string", "enum": ["utf-8"]},
                    "truncated": {"type": "boolean"},
                    "size_bytes": {"type": "integer", "minimum": 0},
                },
                "required": ["content", "encoding", "truncated", "size_bytes"],
                "additionalProperties": False,
            },
            required_capabilities=(ToolCapability.FILE_READ,),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        ),
        ToolDefinition(
            tool_id="workspace.file_info",
            name="Workspace file information",
            description="Retrieve bounded metadata for a regular file in the authorized Workspace.",
            tool_version="1",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1, "maxLength": 1024}},
                "required": ["path"],
                **_NO_EXTRA,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["file"]},
                    "size_bytes": {"type": "integer", "minimum": 0},
                    "modified_at": {"type": "string"},
                },
                "required": ["type", "size_bytes", "modified_at"],
                "additionalProperties": False,
            },
            required_capabilities=(ToolCapability.FILE_READ,),
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        ),
    )


INITIAL_WORKSPACE_OPERATIONS = {
    "workspace.list_files": ToolOperationType.READ,
    "workspace.read_file": ToolOperationType.READ,
    "workspace.file_info": ToolOperationType.READ,
}
