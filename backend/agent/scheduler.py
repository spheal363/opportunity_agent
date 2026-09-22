"""定期チェック（自動探索, #85）。Agent が「いつ探すか」を自分で決める。

N 秒ごとに services/auto_explore.py の判定を回し、始めると決めたら
run_agent を別スレッドで実行する。**判定も上限もあちらが持つ。** ここは回すだけ。

`AUTO_EXPLORE_SCHEDULE=true` のときだけ main.py の lifespan が起動する（既定オフ）。
テストでも起動しない。

**1 プロセス（uvicorn 1 worker）が前提。** worker を増やすと定期チェックも増える。
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime

from agent.loop import run_agent
from config import Settings
from db.session import SessionLocal
from logging_config import describe_exception, get_logger
from models import UserProfile
from services import auto_explore

logger = get_logger(__name__)


def start(settings: Settings) -> asyncio.Task | None:
    """フラグがオンなら定期チェックを 1 本起動する。オフなら何もしない。"""
    if not settings.auto_explore_schedule:
        return None
    interval = settings.auto_explore_tick_seconds
    logger.info("auto_explore.scheduler started interval_seconds=%s", interval)
    return asyncio.create_task(_run_forever(interval), name="auto_explore_scheduler")


async def stop(task: asyncio.Task | None) -> None:
    """終了時に止める。

    実行中の run はスレッドで動いているので止められず、最後まで走る
    （手動の run を BackgroundTasks で走らせているときと同じ）。途中で
    プロセスが落ちた run は、次の判定で止まった run として片付く。
    """
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    logger.info("auto_explore.scheduler stopped")


async def _run_forever(interval: int) -> None:
    while True:
        # **起動直後には判定しない。** `--reload` で立ち上がり直すたびに
        # 判定が走ると、保存のたびに探索を始めかねない。
        await asyncio.sleep(interval)
        try:
            await tick()
        except Exception as exc:  # 1 回の失敗で定期チェックを止めない
            # 例外の文字列は出さない。型と場所だけ（describe_exception）。
            logger.error("auto_explore.tick_failed %s", describe_exception(exc))


async def tick(now: datetime | None = None) -> list[str]:
    """1 回分の判定と実行。始めた run_id を返す。

    run が終わるまで待つ。待っている間は次の判定をしない
    （どのみち実行中の run があれば始めない）。
    """
    started = await asyncio.to_thread(_decide_all, now or datetime.now(UTC))
    for run_id, user_id in started:
        await asyncio.to_thread(run_agent, run_id, user_id)
    return [run_id for run_id, _ in started]


def _decide_all(now: datetime) -> list[tuple[str, str]]:
    """プロフィールのある全員について判定し、始めた (run_id, user_id) を返す。

    自前のセッションを使う（Agent Loop と同じく、リクエストの寿命の外で動くため）。
    **1 人の判定で例外が出ても、他の人の判定は続ける。**
    """
    db = SessionLocal()
    try:
        user_ids = [user_id for (user_id,) in db.query(UserProfile.user_id).all()]
        started: list[tuple[str, str]] = []
        for user_id in user_ids:
            try:
                run_id = auto_explore.start_on_tick(db, user_id, now)
            except Exception as exc:
                db.rollback()
                logger.error(
                    "auto_explore.decide_failed user_id=%s %s", user_id, describe_exception(exc)
                )
                continue
            if run_id is not None:
                started.append((run_id, user_id))
        return started
    finally:
        db.close()
