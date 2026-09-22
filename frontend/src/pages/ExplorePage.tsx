/**
 * ③ Agent 探索中。
 * GET /api/agent/runs/{run_id} をポーリングして、Agent がいま何をしているかを見せる。
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PageIntro } from '../components/app/Chrome';
import { MotionCompanion, StillPose } from '../components/app/Pose';
import {
  EYEBROW,
  INSPECTOR_CARD,
  INSPECTOR_HEADING_H3,
  OUTLINE_BUTTON,
  PRIMARY,
  PROCESS_HEADING,
  PROCESS_HEADING_H3,
  PROCESS_HEADING_NOTE,
  SPARK,
  TEXT_BUTTON,
} from '../components/app/styles';
import ErrorMessage from '../components/ErrorMessage';
import { useAgentRun } from '../hooks/useAgentRun';
import { categoryLabel } from '../utils/display';
import { POSE_SLOTS } from '../utils/poses';
import { useAppState } from '../state/context';
import { AGENT_STEP_LABEL, type AgentStep } from '../types';

/** 表示する順番。backend/schemas/agent.py の AgentStep と対応。 */
const STEPS: { step: AgentStep; detail: string }[] = [
  {
    step: 'analyzing_profile',
    detail: '目標・興味・これまでの経験を、探索のヒントにまとめます。',
  },
  { step: 'planning', detail: '関心の組み合わせから、探索する分野を組み立てます。' },
  { step: 'searching', detail: 'Web から候補を集めます。' },
  { step: 'evaluating', detail: '興味との一致と参加しやすさから、候補を絞ります。' },
  { step: 'verifying', detail: '公式ページで日時・場所・募集状況を確認します。' },
  { step: 'completed', detail: 'あなたの次の一歩になる候補がまとまりました。' },
];

const CANDIDATE_ICONS = ['♫', '✳', '◎', '✎', '✧', '⌘'];

export default function ExplorePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const runId = params.get('run_id');
  const titleRef = useRef<HTMLHeadingElement>(null);

  const { opportunities, refreshOpportunities, startRun, showToast } = useAppState();
  const { run, logs, error, watch, setWatch } = useAgentRun(runId);
  const [starting, setStarting] = useState(false);

  const done = run?.status === 'completed';
  const failed = run?.status === 'failed';
  const running = watch === 'watching' && !done && !failed && Boolean(runId);
  const paused = watch === 'paused';

  // 探索が終わったら結果を取り直す。
  useEffect(() => {
    if (done) void refreshOpportunities();
  }, [done, refreshOpportunities]);

  const currentIndex = useMemo(() => {
    if (!run?.current_step) return -1;
    return STEPS.findIndex((s) => s.step === run.current_step);
  }, [run?.current_step]);

  /** ステップごとの記録。1つのステップに複数行つくことがある。 */
  const logsByStep = useMemo(() => {
    const grouped: Partial<Record<AgentStep, string[]>> = {};
    for (const log of logs) (grouped[log.step] ??= []).push(log.message);
    return grouped;
  }, [logs]);

  const handleStart = async () => {
    setStarting(true);
    try {
      const id = await startRun();
      navigate(`/app/explore?run_id=${id}`);
    } catch (err) {
      showToast(err instanceof Error ? err.message : '探索を開始できませんでした');
    } finally {
      setStarting(false);
    }
  };

  const headline = !runId
    ? 'どこに、可能性が隠れているかな。'
    : failed
      ? 'うまく探せませんでした。'
      : done
        ? '次の一歩の候補が、見つかりました。'
        : paused
          ? 'ゆっくり見てね。画面の更新を止めています。'
          : run?.current_step
            ? `${AGENT_STEP_LABEL[run.current_step]}。`
            : '探索の準備をしています。';

  const badge = done
    ? '探索完了'
    : failed
      ? 'エラー'
      : paused
        ? '更新停止中'
        : runId
          ? '探索中'
          : '探索の準備';

  const percent = run?.progress ?? 0;
  const items = opportunities ?? [];
  const candidates = done ? items : [];

  return (
    <>
      <PageIntro
        titleRef={titleRef}
        title="あなたに合う機会を探索中。"
        copy="探す方向から、候補を絞るまで。道のりを一緒に。"
        editDisabled={running}
      />

      <div className="grid grid-cols-[minmax(0,1.75fr)_minmax(260px,1fr)] gap-[24px] lte1180:grid-cols-[minmax(0,1.4fr)_minmax(240px,1fr)] lte1180:gap-[18px] lte620:grid-cols-1">
        <div className="min-w-0">
          <div
            className={`flex bg-[#edf0e5] border border-[#dde4d5] rounded-[18px] overflow-hidden relative min-h-[320px] lte1180:block ${
              running ? 'is-running' : ''
            }`}
          >
            <div className="pt-[28px] pr-[20px] pb-[28px] pl-[26px] flex-1 z-[1] min-w-0 lte1180:pb-[8px] lte620:pt-[23px] lte620:px-[22px] lte620:pb-[8px]">
              <span className="text-[12px] text-[#526748] bg-[#ffffff80] px-[10px] py-[5px] rounded-[4px]">
                {badge}
              </span>
              <h2 className="text-[22px] font-medium leading-[1.65] mt-[15px] mb-[10px]">
                {headline}
              </h2>
              <p className="text-[14px] text-[#64715c] leading-[1.9] m-0 lte620:max-w-full">
                {run?.message ??
                  (currentIndex >= 0
                    ? STEPS[currentIndex].detail
                    : '目標を手がかりに、いつもの興味の少し外側まで。')}
              </p>

              <div className="flex gap-[16px] items-center flex-wrap mt-[20px] lte620:gap-[12px]">
                {!runId || failed ? (
                  <button
                    type="button"
                    onClick={() => void handleStart()}
                    disabled={starting}
                    className={`${PRIMARY} lte620:text-[13px] lte620:gap-[8px]`}
                  >
                    {starting ? 'はじめています…' : '探索をはじめる'} ↗
                  </button>
                ) : done ? (
                  <>
                    <button
                      type="button"
                      onClick={() =>
                        navigate(runId ? `/app/results?run_id=${runId}` : '/app/results')
                      }
                      className={`${PRIMARY} lte620:text-[13px] lte620:gap-[8px]`}
                    >
                      結果を見る ↗
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleStart()}
                      className={TEXT_BUTTON}
                    >
                      もう一度
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => setWatch(paused ? 'watching' : 'paused')}
                      className={OUTLINE_BUTTON}
                    >
                      {paused ? '▶ 更新を再開' : 'Ⅱ 画面の更新を止める'}
                    </button>
                    <button type="button" onClick={() => navigate('/app')} className={TEXT_BUTTON}>
                      ホームに戻る
                    </button>
                  </>
                )}
              </div>
              {paused ? (
                <p className="text-[12px] text-[#7b8675] mt-[12px]">
                  表示だけを止めています。Agent の探索はそのまま進みます。
                </p>
              ) : null}
            </div>

            <div className="min-w-[210px] w-[42%] relative flex items-center justify-center lte1180:w-full lte1180:h-[245px] lte1180:min-w-0 lte620:h-[238px] lte620:self-center">
              <MotionCompanion step={run?.current_step ?? null} playing={running} done={done} />
              <span className={`${SPARK} text-[34px] top-[18%] right-[12%]`}>✧</span>
              <span className={`${SPARK} spark-2 text-[20px] bottom-[18%] left-[5%]`}>✧</span>
              <span className="path-dot absolute w-[5px] h-[5px] bg-[#bf886d] rounded-[50%] bottom-[18%] opacity-0 left-[24%]" />
              <span className="path-dot path-dot-2 absolute w-[5px] h-[5px] bg-[#bf886d] rounded-[50%] bottom-[18%] opacity-0 left-[43%]" />
              <span className="path-dot path-dot-3 absolute w-[5px] h-[5px] bg-[#bf886d] rounded-[50%] bottom-[18%] opacity-0 left-[62%]" />
            </div>
          </div>

          <div className="flex justify-between gap-[15px] text-[14px] text-[#66755e] mt-[23px] mx-[2px] mb-[9px] items-center lte620:flex-wrap">
            <span>
              {done
                ? '探索が完了しました'
                : !runId
                  ? '探索をはじめると、活動がここに表示されます'
                  : currentIndex >= 0
                    ? `STEP ${currentIndex + 1} / ${STEPS.length}\u3000${AGENT_STEP_LABEL[STEPS[currentIndex].step]}`
                    : '準備中'}
            </span>
            <b className="font-medium">{percent}%</b>
          </div>
          <div
            role="progressbar"
            aria-label="探索の進捗"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            className="h-[7px] rounded-[8px] bg-[#e5e9df] overflow-hidden mb-[30px]"
          >
            <div
              style={{ width: `${percent}%` }}
              className="h-full bg-[#708767] rounded-[8px] transition-[width] duration-700 ease"
            />
          </div>

          <ErrorMessage error={error} />

          <div className={PROCESS_HEADING}>
            <h3 className={PROCESS_HEADING_H3}>探索の道のり</h3>
            <span className={PROCESS_HEADING_NOTE}>Agent の作業記録</span>
          </div>
          <ol className="p-0 list-none mt-0 mx-0 mb-[28px]">
            {STEPS.map((item, i) => {
              const finished = done || (currentIndex >= 0 && i < currentIndex);
              const current = !finished && i === currentIndex;
              const evidence = logsByStep[item.step] ?? [];
              const status = finished ? '完了' : current ? (paused ? '停止中' : '進行中') : '待機';
              return (
                <li
                  key={item.step}
                  className={`process-step grid grid-cols-[36px_minmax(0,1fr)_45px] gap-[14px] pt-[18px] px-[14px] pb-[19px] border-b border-line relative lte620:px-[6px] lte620:grid-cols-[32px_minmax(0,1fr)_40px] lte620:gap-[10px] ${
                    current ? 'bg-[#f0f3e9] rounded-[10px]' : ''
                  }`}
                >
                  <span
                    className={`w-[32px] h-[32px] border rounded-[50%] text-[12px] flex items-center justify-center z-[1] ${
                      finished || current
                        ? 'bg-[#627a55] border-[#627a55] text-white'
                        : 'bg-bg border-[#dce1d4] text-[#8b9383]'
                    }`}
                  >
                    {finished ? '✓' : String(i + 1).padStart(2, '0')}
                  </span>
                  <div>
                    <h4 className="text-[16px] mt-px mb-[4px] font-medium tracking-[.04em]">
                      {AGENT_STEP_LABEL[item.step]}
                    </h4>
                    <p className="m-0 text-[14px] text-[#7c8475]">{item.detail}</p>
                    {evidence.map((line, index) => (
                      <div
                        key={index}
                        className="evidence-enter mt-[12px] bg-white border border-[#e0e5d7] rounded-[7px] px-[14px] py-[12px] text-[13px] leading-[1.9] text-[#536447]"
                      >
                        {line}
                      </div>
                    ))}
                  </div>
                  <span
                    className={`text-[12px] text-right pt-[6px] ${
                      current ? 'text-[#547147]' : 'text-[#949c8d]'
                    }`}
                  >
                    {status}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>

        <aside className="min-w-0">
          <div className={INSPECTOR_CARD}>
            <span className={EYEBROW}>YOUR COMPASS</span>
            <h3 className="text-[17px] font-medium mt-[8px] mb-[12px]">今回の探索の軸</h3>
            {/*
              **この run の入力原文をそのまま出す（#47）。**
              以前は現在のプロフィールを表示していたため、あとから
              プロフィールを編集すると過去 run の条件まで変わって見えた。
              **AI の要約や英語の分類名で原文を置き換えない。**
            */}
            {run?.wishes_source ? (
              <p className="text-[15px] leading-[1.9] mt-[12px] mb-[16px] whitespace-pre-line">
                {run.wishes_source}
              </p>
            ) : (
              <p className="text-[14px] leading-[1.9] mt-[12px] mb-[16px] text-muted">
                この探索の入力原文は保存されていません。
                <span className="block">
                  （この項目が付く前の探索です。現在のプロフィールでは補っていません）
                </span>
              </p>
            )}
            {/* **AI が整理した結果は別枠。** 原文の置き換えには使わない。 */}
            {run?.goal_directions?.length ? (
              <div className="border-t border-line pt-[13px] mt-[4px]">
                <span className="text-[12px] text-[#7a8977] block mb-[6px]">
                  AIが整理した探索方向
                </span>
                <div className="flex flex-wrap gap-[6px]">
                  {run.goal_directions.map((d) => (
                    <span
                      key={d}
                      className="text-[12px] px-[9px] py-[3px] rounded-[20px] bg-[#eef0e8] text-[#657454]"
                    >
                      {d}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="grid gap-[7px] border-t border-line pt-[15px] mt-[18px] text-[13px] text-[#777f70]">
              <span>⌖ {run?.region_source ?? '（この探索の地域は保存されていません）'}</span>
            </div>
          </div>

          <div className={INSPECTOR_CARD}>
            <div className={PROCESS_HEADING}>
              <h3 className={INSPECTOR_HEADING_H3}>見つかった候補</h3>
              <span className={PROCESS_HEADING_NOTE}>{candidates.length}</span>
            </div>
            <div>
              {candidates.length ? (
                candidates.map((o, i) => (
                  <div
                    key={o.opportunity_id}
                    className="soft-enter flex gap-[10px] py-[14px] border-t border-[#edf0e8]"
                  >
                    <span className="w-[28px] h-[30px] rounded-[6px] bg-[#f2e9dc] text-[#9d7450] flex items-center justify-center shrink-0">
                      {CANDIDATE_ICONS[i % CANDIDATE_ICONS.length]}
                    </span>
                    <div>
                      <strong className="font-medium text-[13px] leading-[1.7] block">
                        {o.title}
                      </strong>
                      <small className="text-[12px] text-[#8a9281] block mt-[3px]">
                        {categoryLabel(o.type)} · {o.location ?? '場所未定'}
                      </small>
                    </div>
                    <span className="ml-auto text-[#718266]">{o.verified ? '✓' : '−'}</span>
                  </div>
                ))
              ) : (
                <p className="text-muted text-[14px]">
                  探索が終わると、見つけた機会がここに届きます。
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-[9px] bg-[#f4eee5] rounded-[12px] p-[12px] lte620:p-[14px]">
            <StillPose
              slot={POSE_SLOTS.note}
              size="w-[92px] h-[92px] lte620:w-[100px] lte620:h-[100px]"
              className="shrink-0"
              label="案内役のマスコット"
            />
            <div>
              <strong className="text-[12px] font-medium text-[#937454]">探索のポイント</strong>
              <p className="text-[13px] leading-[1.9] my-[5px] text-[#726957]">
                ぴったりなものだけでなく、ちょっと意外な出会いも大切に。
              </p>
            </div>
          </div>

          <p className="text-[12px] text-[#868c7e] leading-[1.9] px-[6px]">
            表示しているのは Agent
            の作業記録です。日時・場所・募集状況は公式ページの確認結果に基づき、
            確認できなかった項目は「未確認」と表示します。
          </p>
        </aside>
      </div>
    </>
  );
}
