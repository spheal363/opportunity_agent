"""Tool の権限制御。LLM が騙されても重要操作を勝手に実行できないことを担保する。"""

import pytest

from tools import ApprovalRequired, PermissionLevel, registry
from tools import calendar as calendar_tools


def test_registered_tools():
    assert registry.names() == [
        "add_calendar_event",
        "check_calendar",
        # 検索専用モデルで候補を探す（#47）。検索はモデルの内側で行われる
        "discover_events",
        "read_page",
        "search_web",
    ]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("search_web", PermissionLevel.AUTO),
        ("read_page", PermissionLevel.AUTO),
        ("check_calendar", PermissionLevel.AUTO),
        ("add_calendar_event", PermissionLevel.APPROVAL),
    ],
)
def test_permission_levels(name, expected):
    assert registry.get(name).permission is expected


def test_approval_required_tool_is_blocked_without_approval():
    with pytest.raises(ApprovalRequired):
        registry.invoke("add_calendar_event", event={})


def test_approved_call_reaches_the_tool(monkeypatch):
    # 承認済みなら Tool 本体まで到達する
    reached = []

    class _Client:
        def insert_event(self, event):
            reached.append(event)
            return "inserted"

    monkeypatch.setattr(calendar_tools, "get_client", lambda: _Client())

    result = registry.invoke("add_calendar_event", approved=True, event="draft")

    assert reached == ["draft"]
    assert result.data == "inserted"
