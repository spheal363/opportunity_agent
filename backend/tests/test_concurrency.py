"""map_parallel の契約。

**この PR の並列化の安全性はここに依存している。** 順序が崩れると
「どの検索結果から抽出したか」の対応が失われ、別の催しの URL を保存する
事故になる（PR #4 で一度踏んだ）。
"""

import threading
import time

import pytest

from ai import concurrency
from ai.concurrency import map_parallel


def test_preserves_input_order_even_when_completion_order_reverses():
    """**完了順が逆転しても戻り値は入力順。**

    速いものが先に終わっても、遅いものの位置に割り込まない。
    """

    def slow_first(n: int) -> int:
        time.sleep(0.05 if n == 0 else 0)  # 先頭だけ遅らせる
        return n * 10

    assert map_parallel(range(5), slow_first) == [0, 10, 20, 30, 40]


def test_actually_runs_in_parallel():
    """直列だと待ち時間が積み上がる。並列になっていることを確かめる。"""
    started = threading.Barrier(3, timeout=2)

    def wait_for_others(_n: int) -> str:
        # 3 つが同時に走っていないと Barrier が解けずタイムアウトする
        started.wait()
        return "ok"

    assert map_parallel([1, 2, 3], wait_for_others) == ["ok", "ok", "ok"]


def test_exception_propagates_to_the_caller():
    """握るかどうかは fn 側で決める。ここでは素通しする。"""

    def boom(n: int) -> int:
        if n == 2:
            raise ValueError("boom")
        return n

    with pytest.raises(ValueError, match="boom"):
        map_parallel([1, 2, 3], boom)


def test_single_item_does_not_spawn_a_pool():
    """1 件のときはワーカーを立てない。"""
    seen: list[str] = []

    def record(n: int) -> int:
        seen.append(threading.current_thread().name)
        return n

    assert map_parallel([1], record) == [1]
    assert seen == [threading.current_thread().name]


def test_empty_input():
    assert map_parallel([], lambda x: x) == []


def test_workers_are_capped_by_item_count(monkeypatch):
    """要素より多いワーカーを立てない。

    **実際に動くスレッド数を数えても検知できない。** ThreadPoolExecutor は
    要素数までしかスレッドを起こさないため、キャップを外したままでも
    「2 要素なら 2 スレッド」になって通ってしまう。
    Executor に渡した max_workers を直接見る。
    """
    seen: list[int] = []
    real = concurrency.ThreadPoolExecutor

    def spy(max_workers=None, **kwargs):
        seen.append(max_workers)
        return real(max_workers=max_workers, **kwargs)

    monkeypatch.setattr(concurrency, "ThreadPoolExecutor", spy)
    map_parallel([1, 2], lambda n: n, workers=100)

    assert seen == [2]


def test_accepts_any_iterable():
    """generator を渡しても二度読みしない。"""
    assert map_parallel((x for x in range(3)), lambda n: n + 1) == [1, 2, 3]
