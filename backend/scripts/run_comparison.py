"""構成 A / C を 1 run ずつ実行し、入力と出力を保存する（#65）。

**目的は比較の基準線を作ること。** 次の実験では Web 検索も抽出もやり直さず、
ここで保存した**同じ評価入力**を Jev へ渡す。

    # 必要なキーの確認だけ（API は呼ばない）
    cd backend && .venv/bin/python -m scripts.run_comparison C
    # 実行
    cd backend && .venv/bin/python -m scripts.run_comparison C --confirm

## 1 run ずつは予備比較

**優劣の確定とは扱わない。** 出力長も検索結果も実行ごとに変わる。

## 実ユーザーの DB は触らない

`DATABASE_URL` を実験用へ差し替えてから `db.session` を import する。
**import 順を変えない。** 先に import すると実 DB に繋がる。

## 保存しないもの

**API キーと認証ヘッダは保存しない。** 記録するのは LLM へ渡した
messages（system / user）と応答であって、リクエストヘッダではない。

取得した本文は各サービスの利用条件に従い、**この端末の
`backend/experiments/`（git 管理外）にのみ置く。** 公開しない。
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

# --- 構成を選ぶ。**環境変数は db.session の import より先に決める。** ----
#
# 既定の .env は触らない。ここで環境変数を上書きするだけにする。
_ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
_CONFIRM = "--confirm" in sys.argv
_CONFIG = (_ARGS[0] if _ARGS else "A").upper()
_CONFIGS = {
    # 基準線。**本番の既定と同じ構成。**
    "A": {
        "SEARCH_PROVIDER": "tavily",
        "PAGE_FETCHER": "tavily",
        "EVALUATOR": "llm",
        "SEARCH_PIPELINE": "full",
    },
    # 検索サービスと処理方法の**両方**が変わる。
    # 差を Serper 単体や Jev 単体の効果とは説明できない。
    "C": {
        "SEARCH_PROVIDER": "serper",
        "PAGE_FETCHER": "jina",
        "EVALUATOR": "jev",
        "SEARCH_PIPELINE": "prefilter",
    },
}
if _CONFIG not in _CONFIGS:
    print(f"構成は {'/'.join(_CONFIGS)} のいずれかです（指定: {_CONFIG}）")
    raise SystemExit(2)

_STAMP = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
_OUT = Path(__file__).resolve().parent.parent / "experiments" / f"run-{_CONFIG}-{_STAMP}"
_OUT.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_OUT / 'experiment.db'}"
# 実探索で走らせる。既定の .env は stub=true のまま触らない。
os.environ["AGENT_STUB_MODE"] = "false"
os.environ.update(_CONFIGS[_CONFIG])
# **実費を取る。** 見積もりと別の欄に置く。
os.environ["ORCAROUTER_INCLUDE_COST"] = "true"

from agent import loop  # noqa: E402
from ai import cost  # noqa: E402
from ai.orcarouter import OrcaRouterClient  # noqa: E402
from config import get_settings  # noqa: E402
from db.base import Base  # noqa: E402
from db.session import SessionLocal, engine  # noqa: E402
from models import AgentLog, AgentRun, Opportunity, UserProfile  # noqa: E402
from schemas.agent import AgentRunStatus  # noqa: E402
from tools import registry  # noqa: E402

USER_ID = "user_experiment"

# --- 固定プロフィール。**個人情報を含まない。** ----------------------------
# 実在の人物ではない。次の実験でも同じものを使い、入力を揃える。
PROFILE = {
    "user_id": USER_ID,
    "name": "実験用プロフィール",
    "location": "東京, 日本",
    "languages": ["日本語", "英語"],
    "occupation": "バックエンドエンジニア",
    "skills": ["Python", "TypeScript", "AWS", "AI Agent 開発"],
    "experience": [
        "Web アプリケーションのバックエンド開発 3 年",
        "個人開発で LLM を使ったツールを公開",
    ],
    "interests": ["AI Agent", "プロダクト開発", "音楽制作", "DJ", "起業"],
    "goals": [
        "AI Agent を作れるエンジニアになる",
        "将来は自分で事業を立ち上げる",
    ],
    "about": "AI Agent の開発に取り組んでいる。技術と音楽の両方に関心がある。",
}


class Capture:
    """LLM / Tool / Jev の呼び出しと、粗選別の結果を記録する。

    **キーと認証ヘッダは記録しない。** 記録するのは messages と応答だけ。
    """

    def __init__(self) -> None:
        self.llm: list[dict] = []
        self.tools: list[dict] = []
        self.jev: list[dict] = []
        # **C が読まなかった候補。** 取りこぼし監査の入力になる。
        self.prefilter: dict | None = None

    def wrap_llm(self) -> None:
        original = OrcaRouterClient.chat

        def chat(client_self, messages, **kwargs):
            started = time.perf_counter()
            error = None
            res = None
            try:
                res = original(client_self, messages, **kwargs)
                return res
            except Exception as exc:  # noqa: BLE001 - 記録してから投げ直す
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                self.llm.append(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "step": cost.current_step(),
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                        "tier": str(kwargs.get("tier")),
                        "max_tokens": kwargs.get("max_tokens"),
                        # **実際に渡した入力（切り詰め後）。**
                        "messages": messages,
                        "model": getattr(getattr(res, "usage", None), "model", None),
                        "response": getattr(res, "content", None),
                        "usage": _usage_of(res),
                        "error": error,
                    }
                )

        OrcaRouterClient.chat = chat  # type: ignore[method-assign]

    def wrap_jev(self) -> None:
        """Jev の使用量を別に数える。**LLM と混ぜない。**"""
        from ai.jev.client import JevClient

        original = JevClient.ask

        def ask(client_self, state, questions, **kwargs):
            started = time.perf_counter()
            res = original(client_self, state, questions, **kwargs)
            self.jev.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "step": cost.current_step(),
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "model": res.model,
                    "input_tokens": res.input_tokens,
                    "output_tokens": res.output_tokens,
                    "questions": list(questions),
                }
            )
            return res

        JevClient.ask = ask  # type: ignore[method-assign]

    def wrap_prefilter(self) -> None:
        """**読んだ候補と読まなかった候補を残す。**

        C の取りこぼしは、C が実際に捨てた候補を見ないと測れない。
        A の検索結果との照合では分からない。
        """
        original = loop._choose_what_to_read

        def choose(db, state, candidates):
            read, deferred = original(db, state, candidates)
            self.prefilter = {
                "total": len(candidates),
                "read": [_candidate(d, r) for d, r in read],
                "deferred": [_candidate(d, r) for d, r in deferred],
            }
            return read, deferred

        loop._choose_what_to_read = choose  # type: ignore[assignment]

    def wrap_tools(self) -> None:
        original = registry.invoke

        def invoke(name, **kwargs):
            started = time.perf_counter()
            result = original(name, **kwargs)
            self.tools.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "step": cost.current_step(),
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "tool": name,
                    "args": {k: v for k, v in kwargs.items()},
                    "result": _jsonable(result.data),
                }
            )
            return result

        registry.invoke = invoke  # type: ignore[method-assign]


def _candidate(direction, result) -> dict:
    """候補 1 件の記録。**本文は持たない**（監査で取り直す）。"""
    return {
        "query": direction.query,
        "title": result.title,
        "url": result.url,
        "snippet": result.snippet,
        "has_content": bool(result.content),
    }


def _usage_of(res) -> dict | None:
    u = getattr(res, "usage", None)
    if u is None:
        return None
    return {
        "model": u.model,
        "tier": str(u.tier),
        "prompt_tokens": u.prompt_tokens,
        "completion_tokens": u.completion_tokens,
        "reasoning_tokens": u.reasoning_tokens,
    }


def _jsonable(value):
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {f: _jsonable(getattr(value, f)) for f in value.__dataclass_fields__}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _preflight(settings) -> list[str]:
    """走らせる前に、足りないものを挙げる。**API は呼ばない。**

    キーの値は見ない。**有無だけ**を確かめる。
    """
    missing: list[str] = []
    if not settings.orcarouter_api_key:
        missing.append("ORCAROUTER_API_KEY（LLM。A / C とも必須）")
    if settings.search_provider == "tavily" and not settings.search_api_key:
        missing.append("SEARCH_API_KEY（Tavily 検索）")
    if settings.search_provider == "serper" and not settings.serper_api_key:
        missing.append("SERPER_API_KEY（Serper 検索。無料枠 2,500 クエリ、カード不要）")
    if settings.evaluator == "jev" and not settings.typesafe_api_key:
        missing.append("TYPESAFE_API_KEY（Jev 評価）")
    return missing


def main() -> int:
    settings = get_settings()
    print("=== 実行設定（値は表示しない）===")
    print(f"  DB                 {_OUT / 'experiment.db'}  （**実ユーザーの DB ではない**）")
    print(f"  AGENT_STUB_MODE    {settings.agent_stub_mode}  （False でなければ中止）")
    print(f"  SEARCH_PROVIDER    {settings.search_provider}")
    print(f"  PAGE_FETCHER       {settings.page_fetcher}")
    note = "（**本番の既定と同じ**）" if _CONFIG == "A" else "（**この run だけの上書き**）"
    print(f"  EVALUATOR          {settings.evaluator}  {note}")
    print(f"  SEARCH_PIPELINE    {settings.search_pipeline}  {note}")
    print(f"  LLM_MODEL_STANDARD {settings.llm_model_standard}")
    print(f"  LLM_MODEL_POWERFUL {settings.llm_model_powerful}")
    print(f"  SEARCH_API_KEY     {'設定あり' if settings.search_api_key else '**未設定**'}")
    print()

    print("=== 必要なキー（**有無だけ確認。値は見ない**）===")
    for label, present in (
        ("ORCAROUTER_API_KEY", settings.orcarouter_api_key),
        ("SEARCH_API_KEY (Tavily)", settings.search_api_key),
        ("SERPER_API_KEY", settings.serper_api_key),
        ("TYPESAFE_API_KEY (Jev)", settings.typesafe_api_key),
        ("JINA_API_KEY", settings.jina_api_key),
    ):
        mark = "設定あり" if present else "未設定"
        note = "（**キー無しでも動く**）" if "JINA" in label and not present else ""
        print(f"  {label:26} {mark}{note}")
    print()

    missing = _preflight(settings)
    if missing:
        print(f"=== 構成 {_CONFIG} を走らせるには足りないものがあります ===")
        for item in missing:
            print(f"  **{item}**")
        print("\n  backend/.env に設定してください（**チャットには貼らない**）。")
        return 1

    if not _CONFIRM:
        print(f"=== 構成 {_CONFIG} は走らせられます ===")
        print("  実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0

    if settings.agent_stub_mode:
        print("AGENT_STUB_MODE を false にできていません。中止します。")
        return 1
    want = _CONFIGS[_CONFIG]
    got = {
        "SEARCH_PROVIDER": settings.search_provider,
        "PAGE_FETCHER": settings.page_fetcher,
        "EVALUATOR": settings.evaluator,
        "SEARCH_PIPELINE": settings.search_pipeline,
    }
    if got != want:
        print(f"構成が一致しません。中止します。\n  期待 {want}\n  実際 {got}")
        return 1

    # **実 DB に繋がっていないことを、テーブルを作る前に確かめる。**
    # 環境変数の差し替えが効かなかった場合、ここを通すと実ユーザーの DB を
    # 触ってしまう。停止条件にする。
    actual = str(engine.url)
    if str(_OUT) not in actual:
        print(f"DB が実験用になっていません: {actual}")
        print("中止します（実ユーザーの DB を触らないため）。")
        return 1

    Base.metadata.create_all(bind=engine)

    run_id = f"run_baseline_{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    db.merge(UserProfile(**PROFILE))
    db.add(AgentRun(run_id=run_id, user_id=USER_ID, status=AgentRunStatus.QUEUED))
    db.commit()
    db.close()

    capture = Capture()
    capture.wrap_llm()
    capture.wrap_tools()
    capture.wrap_jev()
    capture.wrap_prefilter()

    print(f"=== 実行開始 {run_id} ===")
    started = time.perf_counter()
    loop.run_agent(run_id, USER_ID)
    total_ms = int((time.perf_counter() - started) * 1000)
    print(f"=== 実行終了 {total_ms} ms ===\n")

    _save(run_id, total_ms, capture, settings)
    _report(run_id, total_ms)
    return 0


def _save(run_id: str, total_ms: int, capture: Capture, settings) -> None:
    db = SessionLocal()
    run = db.get(AgentRun, run_id)
    rows = db.query(Opportunity).filter(Opportunity.user_id == USER_ID).all()
    logs = db.query(AgentLog).filter(AgentLog.run_id == run_id).all()

    payload = {
        "run_id": run_id,
        "at": datetime.now(UTC).isoformat(),
        "total_ms": total_ms,
        # **実行設定。キーは含めない。**
        "config": {
            "name": _CONFIG,
            "search_provider": settings.search_provider,
            "page_fetcher": settings.page_fetcher,
            "evaluator": settings.evaluator,
            "search_pipeline": settings.search_pipeline,
            "model_cheap": settings.llm_model_cheap,
            "model_standard": settings.llm_model_standard,
            "model_powerful": settings.llm_model_powerful,
            "max_results_per_direction": loop.MAX_RESULTS_PER_DIRECTION,
            "max_verify": loop.MAX_VERIFY,
            "max_promotions": loop.MAX_PROMOTIONS,
        },
        "profile": PROFILE,
        "status": run.status if run else None,
        "selected_ids": run.selected_ids if run else None,
        "shortfall_reason": run.shortfall_reason if run else None,
        "usage": run.usage_json if run else None,
        "logs": [{"step": lg.step, "message": lg.message} for lg in logs],
        "opportunities": [
            {
                "opportunity_id": r.opportunity_id,
                "type": r.type,
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "start_at": _iso(r.start_at),
                "end_at": _iso(r.end_at),
                "deadline": _iso(r.deadline),
                "location": r.location,
                "score": r.score,
                "serendipity_score": r.serendipity_score,
                "match_reasons": r.match_reasons,
                "reason": r.reason,
                "verified": r.verified,
                "verification_source": r.verification_source,
                "availability": r.availability,
                "availability_reason": r.availability_reason,
                "availability_checked_at": _iso(r.availability_checked_at),
                "availability_source": r.availability_source,
                "status": r.status,
            }
            for r in rows
        ],
        # **次の実験でやり直さないための入力。**
        "llm_calls": capture.llm,
        "tool_calls": capture.tools,
        "jev_calls": capture.jev,
        # **C が読まなかった候補。** 取りこぼし監査の入力。
        "prefilter": capture.prefilter,
    }
    db.close()

    path = _OUT / "run.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"保存しました: {path}")
    print(f"  LLM 呼び出し {len(capture.llm)} 件 / Tool 呼び出し {len(capture.tools)} 件")
    print("  **キー・認証ヘッダは含まれない。**\n")


def _service_note(name: str | None) -> str:
    """そのサービスの費用をどう扱うか。**無料枠と継続費用を分ける。**"""
    return {
        "tavily": "**単価・残量とも未確認**",
        "serper": "無料枠 2,500 クエリを消費。**単価は未確認**",
        "jina": "キー無し 20 RPM の範囲。**支払いは発生しないが使用量は出る**",
    }.get(name or "", "**未確認**")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _report(run_id: str, total_ms: int) -> None:
    db = SessionLocal()
    run = db.get(AgentRun, run_id)
    usage = run.usage_json or {}
    rows = {r.opportunity_id: r for r in db.query(Opportunity).all()}

    print("=== ① 所要時間 ===")
    print(f"  全体  {total_ms / 1000:.1f} 秒")
    by_step = usage.get("by_step", {})
    for name, u in by_step.items():
        print(f"    {name:16} {u.get('elapsed_ms', 0) / 1000:6.1f} 秒")
    print("  （工程時間は**並列呼び出しの合計ではなく**、工程に入って出るまで）\n")

    print("=== ② 使用量と費用（**サービス別。合算しない**）===")
    cfg = usage.get("search_provider"), usage.get("page_fetcher")
    print(f"  検索  {cfg[0]:8} {usage.get('search_calls', 0)} 回   {_service_note(cfg[0])}")
    print(
        f"  本文  {cfg[1]:8} 試行 {usage.get('extract_calls', 0)} 件 /"
        f" 成功 {usage.get('extract_successes', 0)} 件   {_service_note(cfg[1])}"
    )
    jev_usd = sum(u.get("jev", {}).get("usd", 0.0) for u in by_step.values())
    jev_req = sum(u.get("jev", {}).get("request_attempts", 0) for u in by_step.values())
    if jev_req:
        print(
            f"  Jev   {'typesafe':8} {jev_req} 回   公式単価 x 実トークン ${jev_usd:.6f}"
            "（**請求額ではない**）"
        )
    total = {"logical": 0, "attempts": 0, "records": 0, "nousage": 0, "retries": 0, "fb": 0}
    jpy = 0.0
    tokens = 0
    for u in by_step.values():
        total["logical"] += u.get("logical_calls", 0)
        total["attempts"] += u.get("request_attempts", 0)
        total["records"] += u.get("usage_records", 0)
        total["nousage"] += u.get("attempts_without_usage", 0)
        total["retries"] += u.get("retries", 0)
        total["fb"] += u.get("fallbacks", 0)
        jpy += u.get("jpy", 0.0)
        tokens += u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)
    print(f"  LLM 論理呼び出し  {total['logical']}")
    print(f"  LLM 実リクエスト  {total['attempts']}  （Retry / Fallback を含む）")
    print(f"  使用量を取得      {total['records']}")
    print(f"  使用量不明        {total['nousage']}  （**費用ゼロとは限らない**）")
    print(f"  Retry / Fallback  {total['retries']} / {total['fb']}")
    print(f"  トークン          {tokens}")
    actual = usage.get("actual_usd", 0.0)
    missing = usage.get("responses_without_actual_cost", 0)
    print(f"  LLM 見積もり      ¥{jpy:.2f}  （単価表からの推定）")
    print(f"  LLM 実費          ${actual:.6f}  （OrcaRouter の cost_usd）")
    if missing:
        print(
            f"                    **実費不明 {missing} 件**。確定額は GET /v1/generation?id= で引く"
        )
    print(f"  request ID        {len(usage.get('request_ids', []))} 件を保存\n")
    print("  **OrcaRouter の実費は LLM 分だけ。** 検索・本文取得・Jev は含まれない。\n")

    print("=== ③ 受付状況と最終 TOP3 ===")
    counts: dict[str, int] = {}
    for r in rows.values():
        counts[r.availability] = counts.get(r.availability, 0) + 1
    print(f"  候補 {len(rows)} 件  内訳 {counts}")
    print(f"  除外理由 {usage.get('dropped', {})}")
    selected = run.selected_ids or []
    print(f"  最終選定 {len(selected)} 件  不足理由 {run.shortfall_reason or 'なし'}")
    for i, oid in enumerate(selected, 1):
        r = rows.get(oid)
        if r is None:
            continue
        print(f"    {i}. {r.title}")
        print(
            f"       score={r.score} serendipity={r.serendipity_score} "
            f"availability={r.availability} verified={r.verified}"
        )
        print(f"       {r.url}")
    print()

    print("=== ⑤ 評価工程（Jev に置き換わる範囲）===")
    ev = by_step.get("evaluation", {})
    print(
        f"  時間    {ev.get('elapsed_ms', 0) / 1000:.1f} 秒  （全体の "
        f"{ev.get('elapsed_ms', 0) / max(total_ms, 1) * 100:.0f}%）"
    )
    print(
        f"  論理呼び出し {ev.get('logical_calls', 0)} / 実リクエスト "
        f"{ev.get('request_attempts', 0)}"
    )
    print(f"  トークン {ev.get('prompt_tokens', 0) + ev.get('completion_tokens', 0)}")
    print(f"  費用    ¥{ev.get('jpy', 0.0):.2f}  （**見積もり**）")
    db.close()


def _cleanup_if_unused() -> None:
    """確認だけで終わったら、空の実験ディレクトリを残さない。"""
    try:
        if _OUT.exists() and not any(_OUT.iterdir()):
            _OUT.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    code = main()
    _cleanup_if_unused()
    sys.exit(code)
