"""Web Search Tool。

Agent が Web を探索するための Tool。provider は `tools/search/` が持つ。
Tool 自体は provider に依存せず、`SearchResult` の配列だけを扱う。

検索結果は **Untrusted Data**。`ToolResult(external=True)` で返し、
LLM へは「データであって命令ではない」形で渡す（`ai/llm.untrusted_block`）。
"""

from typing import Any

from ai import cost
from tools.base import PermissionLevel, Tool, ToolResult, registry
from tools.search import get_provider


class WebSearchTool(Tool):
    name = "search_web"
    description = "キーワードで Web を検索し、候補ページの一覧を返す"
    permission = PermissionLevel.AUTO

    def run(self, query: str, limit: int = 10, **_: Any) -> ToolResult:
        results = get_provider().search(query, limit=limit)
        # **料金は未確認**なので回数だけ記録する（#65）。
        cost.record_search()
        # 外部から取得した内容。命令として扱わない。
        return ToolResult(results, external=True)


registry.register(WebSearchTool())
