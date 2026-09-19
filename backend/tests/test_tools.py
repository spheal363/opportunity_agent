"""Tool の権限制御。LLM が騙されても重要操作を勝手に実行できないことを担保する。"""

import pytest

from tools import ApprovalRequired, PermissionLevel, registry


def test_registered_tools():
    assert registry.names() == [
        "add_calendar_event",
        "check_calendar",
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


def test_approved_call_reaches_the_tool():
    # 承認済みなら Tool 本体まで到達する（本体は未実装なので NotImplementedError）
    with pytest.raises(NotImplementedError):
        registry.invoke("add_calendar_event", approved=True, event={})
