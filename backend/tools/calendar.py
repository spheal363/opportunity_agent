"""Google Calendar Tool（#44 / #46）。

read は自動実行、write はユーザー承認を必須にする。
Google との通信は tools/google_calendar.py が持ち、ここは権限の境界だけを担う。
"""

from datetime import datetime
from functools import lru_cache
from typing import Any

from tools.base import PermissionLevel, Tool, ToolResult, registry
from tools.google_calendar import EventDraft, GoogleCalendarClient


@lru_cache
def get_client() -> GoogleCalendarClient:
    """プロセス内で使い回す。接続は張らず、トークンは呼び出しごとに読む。"""
    return GoogleCalendarClient()


class CalendarReadTool(Tool):
    name = "check_calendar"
    description = "指定期間の予定を取得し、空いているか確認する"
    permission = PermissionLevel.AUTO

    def run(
        self,
        start: datetime,
        end: datetime,
        ignore_event_id: str | None = None,
        **_: Any,
    ) -> ToolResult:
        busy = get_client().list_busy(start, end, ignore_event_id=ignore_event_id)
        # 招待で入った予定のタイトルは他人が書いたもの。LLM へ渡すなら命令として扱わない。
        return ToolResult(busy, external=True)


class CalendarWriteTool(Tool):
    name = "add_calendar_event"
    description = "ユーザーの Google Calendar へ予定を追加する"
    permission = PermissionLevel.APPROVAL

    def run(self, event: EventDraft, **_: Any) -> ToolResult:
        return ToolResult(get_client().insert_event(event))


registry.register(CalendarReadTool())
registry.register(CalendarWriteTool())
