"""Google Calendar Tool。

read は自動実行、write はユーザー承認を必須にする。
"""

from datetime import datetime
from typing import Any

from tools.base import PermissionLevel, Tool, ToolResult, registry


class CalendarReadTool(Tool):
    name = "check_calendar"
    description = "指定期間の予定を取得し、空いているか確認する"
    permission = PermissionLevel.AUTO

    def run(self, start: datetime, end: datetime, **_: Any) -> ToolResult:
        raise NotImplementedError("calendar read tool is not implemented yet")


class CalendarWriteTool(Tool):
    name = "add_calendar_event"
    description = "ユーザーの Google Calendar へ予定を追加する"
    permission = PermissionLevel.APPROVAL

    def run(self, event: dict, **_: Any) -> ToolResult:
        raise NotImplementedError("calendar write tool is not implemented yet")


registry.register(CalendarReadTool())
registry.register(CalendarWriteTool())
