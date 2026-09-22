"""Logging 設定。

API Request / Error / Agent Run ID / Tool 実行 / LLM 実行 を追跡できる形式にする。
API Key や個人情報は Log へ出力しない。
"""

import logging
import os
import sys
import traceback

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # uvicorn のアクセスログは二重出力になるので root へ委譲する
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# 例外の場所として残す呼び出しの深さ。例外が起きた側から数える。
_TRACE_DEPTH = 5


def describe_exception(exc: BaseException) -> str:
    """ログに残す例外の説明。**例外の文字列は入れない。**

    例外の文字列には SQL のパラメータ（プロフィール本文）や外部 API の応答が入りうる
    （.claude/rules/security.md「プロフィール本文を Log に出さない」）。原因を追えるよう、
    型と、どこで起きたか（ファイル:行:関数）だけを残す。`raise ... from` などで
    包まれた元の例外も、型だけ添える。

        type=OperationalError at=session.py:120:commit <- loop.py:104:_run cause=TimeoutError
    """
    frames = traceback.extract_tb(exc.__traceback__)[-_TRACE_DEPTH:]
    where = " <- ".join(
        f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in reversed(frames)
    )
    text = f"type={type(exc).__name__} at={where or '-'}"
    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        text += f" cause={type(cause).__name__}"
    return text
