import { useEffect, useState } from 'react';
import { Outlet, useNavigate, useSearchParams } from 'react-router-dom';

import { usePageChrome } from '../../hooks/usePageChrome';
import { useAppState } from '../../state/context';
import { clearProfileDraft } from '../../state/persistence';
import type { UserProfileInput } from '../../types';
import { AppFooter, AppHeader, Sidebar, Toast } from './Chrome';
import { DetailDialog } from './DetailDialog';
import { GoalDialog } from './GoalDialog';

export default function AppLayout() {
  usePageChrome('app');

  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { profile, goalOpen, openGoal, closeGoal, saveProfileAndStart, openDetail } = useAppState();

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ホームページの「目標を伝えてはじめる」と、旧 /profile からの遷移。
  useEffect(() => {
    if (params.get('edit') !== '1') return;
    openGoal();
    const next = new URLSearchParams(params);
    next.delete('edit');
    setParams(next, { replace: true });
  }, [params, setParams, openGoal]);

  // 旧 /opportunities/:id からの遷移で詳細を開く。
  useEffect(() => {
    const detail = params.get('detail');
    if (!detail) return;
    openDetail(detail);
    const next = new URLSearchParams(params);
    next.delete('detail');
    setParams(next, { replace: true });
  }, [params, setParams, openDetail]);

  const handleSubmit = async (input: UserProfileInput) => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const runId = await saveProfileAndStart(input);
      // 保存できた内容は下書きとして残さない。次に開くときは保存済みの内容から。
      clearProfileDraft();
      closeGoal();
      navigate(`/app/explore?run_id=${runId}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '保存に失敗しました');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <AppHeader />
      <div className="grid grid-cols-[228px_1fr] max-w-[1600px] mx-auto lte1150:grid-cols-[190px_1fr] lte850:block">
        <Sidebar />
        <main className="pt-[39px] px-[46px] pb-[22px] min-w-0 max-w-[1400px] gte1450:px-[60px] lte1150:py-[30px] lte1150:px-[26px] lte850:py-[27px] lte850:px-[22px]">
          <Outlet />
          <AppFooter />
        </main>
      </div>

      <GoalDialog
        open={goalOpen}
        profile={profile}
        submitting={submitting}
        error={submitError}
        onClose={closeGoal}
        onSubmit={handleSubmit}
      />
      <DetailDialog />
      <Toast />
    </>
  );
}
