/**
 * ④ 探索結果。**この run が選んだものを順位順で表示する。**
 *
 * `GET /api/agent/runs/{run_id}/result` を使う。保存一覧が使う
 * `opportunities`（status で絞った最新の一覧）とは別経路。混ぜると
 * 過去 run の高スコア候補が混ざり、Agent の選定と画面がずれる。
 *
 * `run_id` は URL に持つ。**直接開いても再読み込みしても対象 run が決まる。**
 * 無い場合は最後に実行した run（保存済み）へ委ねる。
 */
import { useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { BottomNote, PageIntro } from '../components/app/Chrome';
import { CardGrid, ResultsHead } from '../components/app/CardGrid';
import { ResultWelcome } from '../components/app/ResultWelcome';
import ErrorMessage from '../components/ErrorMessage';
import { CandidateSections } from '../components/app/CandidateSections';
import { CompactCandidateList } from '../components/app/CompactCandidateList';
import { OpportunityCalendar } from '../components/app/OpportunityCalendar';
import { SearchCandidateList } from '../components/app/SearchCandidateList';
import { useRunResult } from '../hooks/useRunResult';
import { groupByDate, splitCandidates, type CompactGroup } from '../utils/candidates';
import { useAppState } from '../state/context';

export default function ResultsPage() {
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  const [params, setParams] = useSearchParams();
  const { profile, lastRunId } = useAppState();

  const runId = params.get('run_id') ?? lastRunId;

  // 直接開かれたときも URL に run_id を残す。再読み込みで対象が変わらないように。
  useEffect(() => {
    if (!params.get('run_id') && lastRunId) {
      setParams({ run_id: lastRunId }, { replace: true });
    }
  }, [params, lastRunId, setParams]);

  const { result, error, loading } = useRunResult(runId);

  const selected = result?.selected ?? [];
  const others = result?.others ?? [];
  const win = result?.search_window ?? null;
  // **おすすめ欄は「期間内と確認できたイベント」だけ。**
  // 日程未確認や通年のものを混ぜると「60日以内が3件」と読まれる。
  // 期間が分からない run（この列が付く前）は、従来どおり選定をそのまま出す。
  const buckets = splitCandidates(selected, others);
  const pick = (key: string) => buckets.find((b) => b.key === key)?.items ?? [];

  // **おすすめは評価で選ぶ。** 件数は Backend が返す `recommended_count`。
  // 評価できなかった run は 0 件で、**未評価の候補をおすすめと呼ばない。**
  const recommendedCount = result?.recommended_count ?? 0;
  const topIds = new Set(selected.slice(0, recommendedCount).map((o) => o.opportunity_id));
  const items = selected.slice(0, recommendedCount);

  const inWindow = win ? pick('in_window') : selected;
  // 上に出した候補は下に出さない。**同じ候補 ID を 2 つの枠に出さない。**
  const rest = [...inWindow]
    .filter((o) => !topIds.has(o.opportunity_id))
    .sort((a, b) => new Date(a.start_at ?? 0).getTime() - new Date(b.start_at ?? 0).getTime());
  const ongoing = (win ? pick('ongoing') : []).filter((o) => !topIds.has(o.opportunity_id));
  const scheduleUnknown = (win ? pick('schedule_unknown') : []).filter(
    (o) => !topIds.has(o.opportunity_id),
  );
  const compact: CompactGroup[] = [
    ...groupByDate(rest),
    ...(ongoing.length
      ? [{ key: 'ongoing', heading: '開催中（期間より前に始まっています）', items: ongoing }]
      : []),
    ...(scheduleUnknown.length
      ? [{ key: 'unknown', heading: '日程を確認できていない候補', items: scheduleUnknown }]
      : []),
  ];
  // 件数の意味を揃える。**見つかった = おすすめ + ほかの候補。**
  const otherCount = rest.length + ongoing.length + scheduleUnknown.length;
  const foundCount = items.length + otherCount;
  const notRecorded = result !== null && !result.recorded;

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="見つけたのは、あなたの新しい一歩。"
        copy={
          items.length
            ? 'あなたの目標と興味から、候補を選びました。'
            : 'まずは、どんな機会に出会えるか見てみましょう。'
        }
      />

      <ResultWelcome
        interests={profile?.interests ?? []}
        items={items}
        onExplore={() => navigate('/app')}
        onGoExplore={() => navigate('/app/explore')}
      />

      <ResultsHead
        eyebrow="CURATED FOR YOU"
        title={
          foundCount
            ? items.length
              ? `見つかった候補 ${foundCount}件 — おすすめ ${items.length}件`
              : `見つかった候補 ${foundCount}件`
            : win
              ? '今後60日以内と確認できたイベントはありません'
              : 'まだ結果がありません'
        }
        count={items.length}
        note={
          items.length
            ? 'マッチ度はAIによる希望との適合度の目安です。出典は未確認です。'
            : '評価できなかったため、おすすめは選んでいません。'
        }
      />
      <ErrorMessage error={error} />

      {/* 3 件に満たなかった理由を隠さない。期限切れで埋めるより正直に伝える。 */}
      {/* **失敗の理由を隠さない。** 設定不足なら直せる。 */}
      {result?.error ? (
        <p role="alert" className="text-[14px] text-[#9a5c4c] my-[12px]">
          探索に失敗しました：{result.error}
        </p>
      ) : null}
      {result?.shortfall_reason ? <p role="status">{result.shortfall_reason}</p> : null}

      {notRecorded && !loading ? (
        <p role="status">
          {result?.status === 'running'
            ? 'まだ探索中です。'
            : 'この探索の結果は記録されていません。'}
        </p>
      ) : null}

      {/* **この run が対象にした期間。** 結果の読み方に効くので隠さない。 */}
      {win ? (
        <p className="text-[14px] text-muted mt-[4px] mb-0">
          対象期間: {win.start} 〜 {win.end}（{win.days}日間 / {win.tz}）
        </p>
      ) : null}

      <CardGrid items={items} isResult />

      {/* 開催日の見取り図。**検索候補の可視化で、予定登録はしない。**
          おすすめとほかの候補を合わせた、この run の候補全体を出す。 */}
      {win ? (
        <OpportunityCalendar
          items={[...items, ...rest, ...ongoing]}
          recommendedIds={topIds}
          window={win}
          scheduleUnknown={scheduleUnknown}
        />
      ) : null}

      {/* 上位 3 件を除いた残り。**開催日ごとに 1〜2 行で並べる。** */}
      {otherCount > 0 ? (
        <>
          <ResultsHead
            eyebrow="MORE CANDIDATES"
            title={`ほかの候補 ${otherCount}件`}
            count={otherCount}
            note="開催日が近い順に並べています。"
          />
          <CompactCandidateList groups={compact} />
        </>
      ) : null}

      {/* **期間との関係で分ける。** 0 件なら 0 件と言い、別枠で埋めない。
          上で出した 3 つの枠は、ここでは出さない（重複させない）。 */}
      <CandidateSections
        selected={selected}
        others={others}
        hasWindow={win !== null}
        skipKeys={['in_window', 'ongoing', 'schedule_unknown']}
      />
      {/* 旧経路だけ。**新経路では上の 2 つの枠と重複するので出さない。**
          検索ページの記録自体は消していない。 */}
      {result?.discovery_route ? null : (
        <SearchCandidateList
          items={result?.search_candidates ?? []}
          recommendedUrls={items.map((o) => o.url ?? '').filter(Boolean)}
        />
      )}
      <BottomNote />
    </>
  );
}
