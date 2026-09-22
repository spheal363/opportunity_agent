"""一覧ページから「次に読むリンク」を選ぶ（#47）の入出力。"""

from pydantic import BaseModel, Field


class PickedLink(BaseModel):
    """読む価値があると見立てたリンク。**URL は候補として渡したものだけ。**"""

    # 渡した一覧の中での位置。**URL 文字列を書かせない**（作られると困る）。
    index: int = Field(ge=0)
    # どの希望に当たりそうか。渡した希望の文言をそのまま返す。
    wish: str = ""
    # なぜ読む価値があるか。画面には出さず、Log とデバッグ用。
    reason: str = ""


class LinkPickOutput(BaseModel):
    """**0 件でよい。** 当たりが無い一覧で無理に選ばせない。"""

    # このページはイベント一覧・カレンダーか。
    # **記事の関連記事欄と、一覧の本体を区別させる。** 構造だけでは分けられない
    # （実測: clubberia の一覧と okinawatimes の記事が、どちらも同形リンク 20 本超）。
    is_listing: bool = False
    # なぜそう判断したか。Log に残す。
    listing_reason: str = ""
    picked: list[PickedLink] = Field(default_factory=list)
