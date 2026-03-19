"""Auto-register all built-in assistant tools on import."""

from src.agents.assistant.tools.academic_tools import (
    SearchAcademicPapersTool,
    WebSearchTool,
)
from src.agents.assistant.tools.dummy_time import GetSystemTimeTool
from src.agents.assistant.tools.experiment_tools import ParseCSVLogTool
from src.agents.assistant.tools.fs_tools import (
    EditFileTool,
    GlobSearchTool,
    ReadFileTool,
    WriteFileTool,
)
from src.agents.assistant.tools.latex_tools import CompileLatexTool
from src.agents.assistant.tools.python_repl import RunPythonCodeTool
from src.agents.assistant.tools.registry import ToolRegistry
from src.agents.assistant.tools.shell_tool import RunBashCommandTool

ToolRegistry.register(GetSystemTimeTool())
ToolRegistry.register(ReadFileTool())
ToolRegistry.register(WriteFileTool())
ToolRegistry.register(EditFileTool())
ToolRegistry.register(GlobSearchTool())
ToolRegistry.register(RunBashCommandTool())
ToolRegistry.register(RunPythonCodeTool())
ToolRegistry.register(SearchAcademicPapersTool())
ToolRegistry.register(WebSearchTool())
ToolRegistry.register(CompileLatexTool())
ToolRegistry.register(ParseCSVLogTool())
