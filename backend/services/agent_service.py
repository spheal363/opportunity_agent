"""Agent Run の作成・状態取得。"""

import uuid

from sqlalchemy.orm import Session

from ai import interstitial
from ai import window as search_window
from models import DEFAULT_USER_ID, AgentLog, AgentRun, Opportunity
from schemas.agent import (
    AgentLogEntry,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    SearchCandidate,
)
from schemas.opportunity import OpportunitySummary


def create_run(db: Session, user_id: str = DEFAULT_USER_ID) -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db.add(AgentRun(run_id=run_id, user_id=user_id, status=AgentRunStatus.QUEUED))
    db.commit()
    return run_id


def get_run(db: Session, run_id: str, user_id: str) -> AgentRunState | None:
    """その人の run だけを返す（#69）。他人の run は存在しないのと同じに扱う。"""
    row = db.get(AgentRun, run_id)
    if row is None or row.user_id != user_id:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def list_logs(db: Session, run_id: str) -> list[AgentLogEntry]:
    """run の Log。**呼ぶ前に `get_run` で所有者を確かめること。**"""
    rows = db.query(AgentLog).filter(AgentLog.run_id == run_id).order_by(AgentLog.id.asc()).all()
    return [AgentLogEntry.model_validate(r, from_attributes=True) for r in rows]


def get_result(db: Session, run_id: str) -> AgentRunResult | None:
    """この run の最終選定を順位順で返す。

    **`GET /api/opportunities` とは別経路。** あちらは status で絞った最新の
    一覧（保存一覧の母集合）で、こちらは**その run が選んだものだけ**。

    区別するもの:
      run が無い        -> None（呼び出し側が 404）
      未完了            -> recorded=False, status=running
      結果の記録が無い   -> recorded=False（列を足す前の古い run）
      完了したが 0 件    -> recorded=True, selected=[]
    """
    run = db.get(AgentRun, run_id)
    if run is None:
        return None

    ids = run.selected_ids
    if ids is None:
        # **失敗したときこそ理由が要る。** 「記録されていません」だけでは、
        # 設定が足りないのか、探しても見つからなかったのかが分からない。
        return AgentRunResult(run_id=run_id, status=run.status, recorded=False, error=run.error)

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity).filter(Opportunity.opportunity_id.in_(ids)).all()
    }
    win = search_window.SearchWindow.from_dict(run.search_window)
    # **順位を保つ。** DB の返す順ではなく selected_ids の順。
    selected = [_summary(rows[i], win) for i in ids if i in rows]

    # **推薦しなかったが、読んで抽出できた候補。**
    #
    # 条件は「この run で見つけ」「本文から抽出できている」こと。
    # 検索しただけで読んでいない候補は `Opportunity` の行にならないので、
    # ここには入らない。**未読の保留候補を、確認済みの推薦と同じ扱いにしない。**
    #
    # 一覧を開くだけで外部 API は呼ばない。DB にある分だけを返す。
    chosen = set(ids)
    others = [
        _summary(r, win)
        for r in db.query(Opportunity)
        .filter(Opportunity.run_id == run_id, Opportunity.user_id == run.user_id)
        .order_by(Opportunity.score.desc())
        .all()
        if r.opportunity_id not in chosen
    ]
    return AgentRunResult(
        run_id=run_id,
        status=run.status,
        recorded=True,
        selected=selected,
        others=others,
        search_candidates=_search_candidates(db, run, chosen, win),
        shortfall_reason=run.shortfall_reason,
        search_window=({**win.to_dict(), "days": win.days} if win else None),
        # **失敗の理由を隠さない。** 設定不足なら直せる。
        error=run.error,
    )


def _summary(row: Opportunity, win: "search_window.SearchWindow | None") -> OpportunitySummary:
    """期間との関係を付けて返す。**期間が分からない run では付けない。**

    この列が付く前の run を、今日の日付で作り直した期間で判定しない。
    """
    out = OpportunitySummary.model_validate(row, from_attributes=True)
    if win is None:
        return out
    status = search_window.classify(
        opportunity_type=row.type,
        start_at=row.start_at,
        end_at=row.end_at,
        window=win,
    )
    out.window_status = status.value
    out.window_note = search_window.label(status, win)
    return out


def _search_candidates(
    db: Session, run: AgentRun, chosen: set[str], win: "search_window.SearchWindow | None"
) -> list[SearchCandidate]:
    """検索で見つかった候補を一覧にする。**外部 API は呼ばない。**

    保存済みの検索候補と、抽出できた Opportunity 行を URL で突き合わせる。

    **読んでいない候補に日時や受付状況を付けない。** 検索結果の公開日や
    抜粋中の日付を開催日として流用しない。分からないものは分からないまま返す。

    この列が付く前の run では空を返す。**件数を水増ししない。**
    """
    rows_all = (
        db.query(Opportunity)
        .filter(Opportunity.run_id == run.run_id, Opportunity.user_id == run.user_id)
        .all()
    )
    saved = run.search_candidates or []
    if not saved:
        # **この列が付く前の run。** 検索候補そのものは残っていない。
        # 読んで抽出できた分だけは Opportunity から復元できるので、それを出す。
        # **読まなかった候補は復元できない。** 件数を 20 に水増ししない。
        saved = [{"title": r.title, "url": r.url} for r in rows_all if r.url]

    rows = {r.url: r for r in rows_all if r.url}
    out: list[SearchCandidate] = []
    seen: set[str] = set()
    for item in saved:
        url = (item or {}).get("url")
        if not url or url in seen:
            # **同じ URL を 2 度出さない。**
            continue
        seen.add(url)
        row = rows.get(url)
        # **取得失敗の中間ページは通常の候補として出さない（#47）。**
        # 古い run にはフィルタを通す前の行が残っている。
        if interstitial.looks_like_interstitial(
            title=(row.title if row is not None else item.get("title")),
            content=(row.description if row is not None else None),
        ):
            continue
        if row is None:
            out.append(SearchCandidate(title=(item.get("title") or url)[:200], url=url, read=False))
            continue
        out.append(
            SearchCandidate(
                title=row.title or item.get("title") or url,
                url=url,
                read=True,
                recommended=row.opportunity_id in chosen,
                start_at=row.start_at,
                start_at_is_date_only=row.start_at_is_date_only,
                window_status=(
                    search_window.classify(
                        opportunity_type=row.type,
                        start_at=row.start_at,
                        end_at=row.end_at,
                        window=win,
                    ).value
                    if win
                    else None
                ),
                availability=row.availability,
                verified=bool(row.verified),
            )
        )
    return out
