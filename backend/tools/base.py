"""Tool 実行基盤。

Tool ごとに権限レベルを持たせ、「LLM が騙されても重要操作を勝手に実行できない」
状態を仕組みで担保する。

    search / read_page / calendar.read  -> AUTO      （自動実行）
    calendar.write                      -> APPROVAL  （ユーザー承認が必要）
    submit_application                  -> APPROVAL
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from logging_config import get_logger

logger = get_logger(__name__)


class PermissionLevel(StrEnum):
    AUTO = "auto"
    APPROVAL = "approval"


class ApprovalRequired(Exception):
    """承認が必要な Tool を承認なしで呼んだときに送出する。"""

    def __init__(self, tool_name: str, summary: str) -> None:
        super().__init__(f"'{tool_name}' requires human approval: {summary}")
        self.tool_name = tool_name
        self.summary = summary


class ToolResult:
    """Tool の実行結果。

    external が True の内容は Untrusted Data として扱い、
    LLM へ渡すときは「命令ではなくデータ」であることを明示する。
    """

    def __init__(self, data: Any, *, external: bool = False) -> None:
        self.data = data
        self.external = external


class Tool(ABC):
    name: str
    description: str
    permission: PermissionLevel = PermissionLevel.AUTO

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def invoke(self, name: str, *, approved: bool = False, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool.permission is PermissionLevel.APPROVAL and not approved:
            raise ApprovalRequired(tool.name, tool.description)
        logger.info("tool.invoke name=%s", name)
        return tool.run(**kwargs)


registry = ToolRegistry()
