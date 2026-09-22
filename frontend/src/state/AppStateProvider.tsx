import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  ApiRequestError,
  fetchLatestAgentRun,
  fetchOpportunities,
  fetchProfile,
  markInterested,
  saveProfile,
  sendFeedback,
  startAgentRun,
} from '../api';
import { usePersistedState } from '../hooks/usePersistedState';
import { useToast } from '../hooks/useToast';
import { isSaved, isStep } from '../utils/display';
import type {
  AgentRun,
  Opportunity,
  OpportunityStatus,
  Reaction,
  UserProfile,
  UserProfileInput,
} from '../types';
import { AppStateContext, type AppState } from './context';
import {
  STORAGE_KEY,
  reviveNotes,
  reviveReactions,
  reviveRegistrationUrls,
  reviveSeenAutoRun,
  reviveStatusOverrides,
} from './persistence';

const message = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/**
 * 解除する API が無いため、このブラウザの中でだけ「未保存」に戻すときの値。
 *
 * サーバーが最初から interested を返していた場合、元の status を書き戻すだけでは
 * 実効状態が interested のままで解除にならない。
 */
const LOCALLY_CLEARED: OpportunityStatus = 'recommended';

const isActive = (run: AgentRun) => run.status === 'queued' || run.status === 'running';

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  // 最後に実行した run。結果画面を直接開いたときの既定にする。
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [opportunitiesError, setOpportunitiesError] = useState<string | null>(null);
  const opportunitiesRequestRef = useRef(0);

  /**
   * この端末で行った操作の結果。サーバーの status に重ねて表示する。
   *
   * 「気になる」は POST /opportunities/{id}/interest が status を更新するが、
   * 解除する API はまだ無い。「次の一歩」は、カレンダーに入れたときだけ
   * POST .../calendar がサーバー側も registered にする（docs/api.md の 8）。
   * 解除と、カレンダーに入れずに進めたぶんは、このブラウザの中だけで保持する。
   *
   * サーバーに置き場所が無い値なので、失うと操作がやり直しになる。
   * 再読み込みでも残るよう localStorage に保存する（このブラウザの中だけ）。
   */
  const [statusOverrides, setStatusOverrides] = usePersistedState<
    Record<string, OpportunityStatus>
  >(STORAGE_KEY.statusOverrides, {}, reviveStatusOverrides);
  const [reactions, setReactions] = usePersistedState<Record<string, Reaction>>(
    STORAGE_KEY.reactions,
    {},
    reviveReactions,
  );
  /** POST /interest が返す登録先。Verification 後の最新値なので url より優先する。 */
  const [registrationUrls, setRegistrationUrls] = usePersistedState<Record<string, string>>(
    STORAGE_KEY.registrationUrls,
    {},
    reviveRegistrationUrls,
  );
  const [notes, setNotes] = usePersistedState<Record<string, string>>(
    STORAGE_KEY.notes,
    {},
    reviveNotes,
  );

  /** いちばん新しい run。Agent が自分で始めた探索に気づくために取る。 */
  const [latestRun, setLatestRun] = useState<AgentRun | null>(null);
  const [seenAutoRunId, setSeenAutoRunId] = usePersistedState<string | null>(
    STORAGE_KEY.seenAutoRun,
    null,
    reviveSeenAutoRun,
  );
  /** 前回取った最新 run。自動で始めた run が新しく出た・終わった瞬間を知るため。 */
  const latestRef = useRef<AgentRun | null>(null);

  const [goalOpen, setGoalOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const toast = useToast();

  useEffect(() => {
    fetchProfile()
      .then(setProfile)
      .catch((err) => {
        // プロフィール未登録はエラーではなく「これから入力する」状態。
        if (err instanceof ApiRequestError && err.code === 'NOT_FOUND') return;
        setProfileError(message(err, 'プロフィールを取得できませんでした'));
      });
  }, []);

  const refreshOpportunities = useCallback(async () => {
    const requestId = ++opportunitiesRequestRef.current;
    try {
      const items = await fetchOpportunities();
      // 初回取得と自動探索後の更新が重なっても、古い応答で戻さない。
      if (requestId !== opportunitiesRequestRef.current) return;
      setOpportunities(items);
      setOpportunitiesError(null);
    } catch (err) {
      if (requestId !== opportunitiesRequestRef.current) return;
      setOpportunitiesError(message(err, '機会を取得できませんでした'));
    }
  }, []);

  useEffect(() => {
    void refreshOpportunities();
  }, [refreshOpportunities]);

  const statusOf = useCallback(
    (opportunity: Opportunity) => statusOverrides[opportunity.opportunity_id] ?? opportunity.status,
    [statusOverrides],
  );

  const { savedCount, stepCount } = useMemo(() => {
    const items = opportunities ?? [];
    return {
      savedCount: items.filter((o) => isSaved(statusOf(o))).length,
      stepCount: items.filter((o) => isStep(statusOf(o))).length,
    };
  }, [opportunities, statusOf]);

  const refreshLatestRun = useCallback(async () => {
    try {
      const run = await fetchLatestAgentRun();
      const previous = latestRef.current;
      latestRef.current = run;
      setLatestRun(run);
      // Agent が自分で始めた探索が終わったら、おすすめを取り直す。
      // ホームのカードが古い推薦のまま残らないように。ホーム以外にいる間に
      // 完了したこともあるので、最新 run の初回取得でも取り直す。
      const finished = run !== null && run.trigger !== 'manual' && run.status === 'completed';
      const changed = previous?.run_id !== run?.run_id || previous?.status !== run?.status;
      if (finished && changed) void refreshOpportunities();
      return run;
    } catch {
      // 知らせのための取得。失敗しても画面の操作は止めない（次の取得でやり直す）。
      return null;
    }
  }, [refreshOpportunities]);

  const autoRun =
    latestRun &&
    latestRun.trigger !== 'manual' &&
    latestRun.run_id !== lastRunId &&
    latestRun.run_id !== seenAutoRunId
      ? latestRun
      : null;

  const openAutoRun = useCallback(
    (runId: string) => {
      setLastRunId(runId);
      setSeenAutoRunId(runId);
    },
    [setSeenAutoRunId],
  );

  const dismissAutoRun = useCallback(
    (runId: string) => setSeenAutoRunId(runId),
    [setSeenAutoRunId],
  );

  const startRun = useCallback(async () => {
    const run = await startAgentRun();
    setLastRunId(run.run_id);
    return run.run_id;
  }, []);

  const saveProfileAndStart = useCallback(async (input: UserProfileInput) => {
    await saveProfile(input);
    const saved = await fetchProfile().catch(() => null);
    if (saved) setProfile(saved);
    const run = await startAgentRun();
    setLastRunId(run.run_id);
    return run.run_id;
  }, []);

  const toggleInterest = useCallback(
    async (opportunity: Opportunity) => {
      const id = opportunity.opportunity_id;
      if (isSaved(statusOf(opportunity))) {
        // 解除する API が無いので、このブラウザの表示だけ未保存に戻す。
        setStatusOverrides((prev) => ({ ...prev, [id]: LOCALLY_CLEARED }));
        toast.show('「気になる」から外しました（このブラウザの中だけ）');
        return;
      }
      try {
        const result = await markInterested(id);
        setStatusOverrides((prev) => ({ ...prev, [id]: result.status }));
        // 登録先は interest の結果が正。url とズレることがある。
        if (result.registration_url) {
          setRegistrationUrls((prev) => ({ ...prev, [id]: result.registration_url as string }));
        }
        toast.show('「気になる」に保存しました');
      } catch (err) {
        toast.show(message(err, '保存できませんでした'));
      }
    },
    [statusOf, setStatusOverrides, setRegistrationUrls, toast],
  );

  const markAsStep = useCallback(
    (opportunityId: string) => {
      // カレンダーに入れた場合は Backend 側も registered になっている（CalendarPanel）。
      // 入れずに進めた場合はサーバーに置き場所が無いので、このブラウザにだけ残す。
      setStatusOverrides((prev) => ({ ...prev, [opportunityId]: 'registered' }));
    },
    [setStatusOverrides],
  );

  const sendReaction = useCallback(
    async (opportunityId: string, reaction: Reaction) => {
      // 送る前に知っていた最新の run。これと違う run が出ていれば、今回の👎で始まった。
      const before = latestRef.current?.run_id ?? null;
      try {
        await sendFeedback(opportunityId, { reaction });
        setReactions((prev) => ({ ...prev, [opportunityId]: reaction }));
      } catch (err) {
        toast.show(message(err, 'フィードバックを送れませんでした'));
        return;
      }
      if (reaction === 'like') {
        toast.show('興味を記録しました');
        return;
      }
      // 👎が推薦の過半数に重なると、Agent が反応を踏まえて探し直すことがある
      // （Backend の自動探索。既定オフ）。feedback のレスポンスには出ないので、
      // 最新の run を取って確かめる。**画面は移らない。** 知らせから本人が開く。
      const latest = await refreshLatestRun();
      const retried =
        latest !== null &&
        latest.trigger === 'feedback' &&
        latest.run_id !== before &&
        latest.run_id !== lastRunId &&
        latest.run_id !== seenAutoRunId;
      toast.show(
        !retried
          ? 'フィードバックを記録しました'
          : isActive(latest)
            ? '反応を踏まえて探し直しています'
            : '反応を踏まえて探し直しました',
      );
    },
    [setReactions, toast, refreshLatestRun, lastRunId, seenAutoRunId],
  );

  const value: AppState = {
    profile,
    profileError,
    lastRunId,
    opportunities,
    opportunitiesError,
    refreshOpportunities,
    statusOf,
    savedCount,
    stepCount,
    saveProfileAndStart,
    startRun,
    latestRun,
    refreshLatestRun,
    autoRun,
    openAutoRun,
    dismissAutoRun,
    toggleInterest,
    markAsStep,
    reactionOf: (id) => reactions[id],
    registrationUrlOf: (id) => registrationUrls[id],
    sendReaction,
    noteOf: (id) => notes[id],
    setNote: (id, note) => setNotes((prev) => ({ ...prev, [id]: note })),
    goalOpen,
    openGoal: () => setGoalOpen(true),
    closeGoal: () => setGoalOpen(false),
    detailId,
    openDetail: setDetailId,
    closeDetail: () => setDetailId(null),
    toastMessage: toast.message,
    toastVisible: toast.visible,
    showToast: toast.show,
  };

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}
