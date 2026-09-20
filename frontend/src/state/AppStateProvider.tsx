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

const message = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  const [opportunitiesError, setOpportunitiesError] = useState<string | null>(null);

  /**
   * この画面で行った操作の結果。サーバーの status に重ねて表示する。
   *
   * 「気になる」は POST /opportunities/{id}/interest が status を更新するが、
   * 解除する API と「次の一歩」に進める API（POST .../calendar）はまだ無いため、
   * そのぶんはこのブラウザの中だけで保持する。docs/api.md の 7/8 が実装されたら
   * ここをサーバーの値に置き換える。
   */
  const [statusOverrides, setStatusOverrides] = useState<Record<string, OpportunityStatus>>({});
  const [reactions, setReactions] = useState<Record<string, Reaction>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

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
        // 解除する API が無いので、この画面での表示だけ元の状態に戻す。
        setStatusOverrides((prev) => ({ ...prev, [id]: opportunity.status }));
        toast.show('「気になる」から外しました');
        return;
      }
      try {
        const result = await markInterested(id);
        setStatusOverrides((prev) => ({ ...prev, [id]: result.status }));
        toast.show('「気になる」に保存しました');
      } catch (err) {
        toast.show(message(err, '保存できませんでした'));
      }
    },
    [statusOf, toast],
  );

  const markAsStep = useCallback((opportunity: Opportunity) => {
    // TODO: POST /api/opportunities/{id}/calendar 実装後はその結果を使う。
    setStatusOverrides((prev) => ({ ...prev, [opportunity.opportunity_id]: 'registered' }));
  }, []);

  const sendReaction = useCallback(
    async (opportunityId: string, reaction: Reaction) => {
      setReactions((prev) => ({ ...prev, [opportunityId]: reaction }));
      try {
        await sendFeedback(opportunityId, { reaction });
        toast.show(reaction === 'like' ? '興味を記録しました' : 'フィードバックを記録しました');
      } catch (err) {
        toast.show(message(err, 'フィードバックを送れませんでした'));
      }
    },
    [toast],
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
