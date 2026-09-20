"""LLM 呼び出しを並列で回すための小さなヘルパ。

抽出も評価も**1 件ずつが独立した HTTP 呼び出し**で、直列にすると
そのまま待ち時間の合計になる。実測では 20 件の抽出に 108 秒、
20 件の評価に 159 秒かかり、1 回の探索 296 秒のうち 90% を占めていた。

`httpx.Client` はスレッドセーフなので、同じクライアントを共有したまま
ワーカーを増やせる（`ai/llm.get_client()` は lru_cache の singleton）。
"""

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

from ai import cost

# 同時に投げる LLM 呼び出しの数。
# 増やすほど速いが、provider 側のレート制限に当たると 429 が増えて
# かえって遅くなる（Retry が挟まるため）。実測で調整する値。
DEFAULT_WORKERS = 5


def map_parallel[T, R](
    items: Iterable[T],
    fn: Callable[[T], R],
    *,
    workers: int = DEFAULT_WORKERS,
) -> list[R]:
    """`fn` を並列に適用する。**戻り値は入力の順序を保つ。**

    順序が崩れると「どの検索結果から抽出したか」の対応が追えなくなる。
    例外はそのまま呼び出し元へ伝わるので、握るかどうかは `fn` 側で決める。
    """
    items = list(items)
    if len(items) <= 1:
        return [fn(x) for x in items]

    # **ThreadPoolExecutor は contextvars を自動で引き継がない。**
    # 引き継がないと、ワーカー内のコスト記録（ai/cost.py）が黙って落ちて
    # 「安く済んだ」ように見える。
    #
    # **context 全体は複製しない。** `copy_context()` を使うと、将来
    # 認証情報やトレース ID を ContextVar で持たせたときに、それらまで
    # 気づかれずにワーカーへ流れる。**引き継ぐものは cost 側が決める。**
    snap = cost.snapshot()

    def run(item: T) -> R:
        with cost.restore(snap):
            return fn(item)

    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(run, items))
