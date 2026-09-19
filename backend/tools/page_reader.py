"""Web Page Reader Tool。

取得した本文は必ず external=True（Untrusted Data）で返す。
"""

from typing import Any

from tools.base import PermissionLevel, Tool, ToolResult, registry


class PageReaderTool(Tool):
    name = "read_page"
    description = "URL のページ本文を取得する"
    permission = PermissionLevel.AUTO

    def run(self, url: str, **_: Any) -> ToolResult:
        raise NotImplementedError("page reader tool is not implemented yet")


registry.register(PageReaderTool())
