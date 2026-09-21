import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import {
  ApiRequestError,
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

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  const [opportunitiesError, setOpportunitiesError] = useState<string | null>(null);

  /**
   * この端末で行った操作の結果。サーバーの status に重ねて表示する。
   *
   * 「気になる」は POST /opportunities/{id}/interest が status を更新するが、
   * 解除する API と「次の一歩」に進める API（POST .../calendar）はまだ無いため、
   * そのぶんはこのブラウザの中だけで保持する。docs/api.md の 7/8 が実装されたら
   * ここをサーバーの値に置き換える。
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
    try {
      const items = await fetchOpportunities();
      setOpportunities(items);
      setOpportunitiesError(null);
    } catch (err) {
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

  const startRun = useCallback(async () => {
    const run = await startAgentRun();
    return run.run_id;
  }, []);

  const saveProfileAndStart = useCallback(async (input: UserProfileInput) => {
    await saveProfile(input);
    const saved = await fetchProfile().catch(() => null);
    if (saved) setProfile(saved);
    const run = await startAgentRun();
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
      // TODO: POST /api/opportunities/{id}/calendar 実装後はその結果を使う。
      setStatusOverrides((prev) => ({ ...prev, [opportunityId]: 'registered' }));
    },
    [setStatusOverrides],
  );

  const sendReaction = useCallback(
    async (opportunityId: string, reaction: Reaction) => {
      try {
        await sendFeedback(opportunityId, { reaction });
        setReactions((prev) => ({ ...prev, [opportunityId]: reaction }));
        toast.show(reaction === 'like' ? '興味を記録しました' : 'フィードバックを記録しました');
      } catch (err) {
        toast.show(message(err, 'フィードバックを送れませんでした'));
      }
    },
    [setReactions, toast],
  );

  const value: AppState = {
    profile,
    profileError,
    opportunities,
    opportunitiesError,
    refreshOpportunities,
    statusOf,
    savedCount,
    stepCount,
    saveProfileAndStart,
    startRun,
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
