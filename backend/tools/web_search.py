"""Web Search Tool。

TODO(agent): 検索 API を接続する。今は Agent Loop を通すためのスタブ。
"""

from typing import Any

from tools.base import PermissionLevel, Tool, ToolResult, registry


class WebSearchTool(Tool):
    name = "search_web"
    description = "キーワードで Web を検索し、候補ページの一覧を返す"
    permission = PermissionLevel.AUTO

    def run(self, query: str, limit: int = 10, **_: Any) -> ToolResult:
        raise NotImplementedError("web search tool is not implemented yet")


registry.register(WebSearchTool())
