import { useEffect, useState } from 'react';

import { fetchOpportunity } from '../../api';
import {
  availabilityLabel,
  categoryLabel,
  costLabel,
  deadlineKindLabel,
  deadlineLabel,
  isStep,
  scheduleLabel,
  safeHttpUrl,
} from '../../utils/display';
import { POSE_SLOTS } from '../../utils/poses';
import { useAppState } from '../../state/context';
import type { OpportunityDetail, Reaction } from '../../types';
import { formatDateTime } from '../../utils/date';
import { Dialog } from '../Dialog';
import { StillPose } from './Pose';
import { DIALOG, DIALOG_CLOSE, DIALOG_H2, EYEBROW, MUTED, PRIMARY } from './styles';

/** 詳細ダイアログの中では段落はすべて 14px。 */
const HINT = 'text-[14px] text-muted my-[22px]';
const H3 = 'text-[16px] font-bold tracking-[.04em] mt-[24px] mb-[7px]';

type Step = 'detail' | 'prepare' | 'done';

export function DetailDialog() {
  const {
    detailId,
    closeDetail,
    opportunities,
    statusOf,
    markAsStep,
    reactionOf,
    sendReaction,
    noteOf,
    setNote,
    profile,
    registrationUrlOf,
    showToast,
  } = useAppState();

  const [item, setItem] = useState<OpportunityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step>('detail');
  const [note, setLocalNote] = useState('');

  useEffect(() => {
    if (!detailId) return;
    setStep('detail');
    setItem(null);
    setError(null);
    let cancelled = false;
    fetchOpportunity(detailId)
      .then((found) => {
        if (!cancelled) setItem(found);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '取得に失敗しました');
      });
    return () => {
      cancelled = true;
    };
  }, [detailId]);

  const summary = opportunities?.find((o) => o.opportunity_id === detailId);
  /** 登録先は POST /interest の結果が最新。無ければ詳細の url に戻す。 */
  const officialUrl = item ? safeHttpUrl(registrationUrlOf(item.opportunity_id) ?? item.url) : null;
  const inSteps = summary ? isStep(statusOf(summary)) : false;

  const openPrepare = () => {
    if (!item) return;
    setLocalNote(
      noteOf(item.opportunity_id) ??
        `はじめまして。${(profile?.interests ?? []).join('、') || '新しい挑戦'}に興味があります。\n${
          (profile?.goals ?? []).join(' / ') || '次の一歩を探しています。'
        }\n今回の機会を通じて、経験とつながりを広げたいです。`,
    );
    setStep('prepare');
  };

  const react = (reaction: Reaction) => {
    if (!item) return;
    void sendReaction(item.opportunity_id, reaction);
  };

  return (
    <Dialog
      open={Boolean(detailId)}
      onClose={closeDetail}
      className={`${DIALOG} w-[min(620px,calc(100%-28px))]`}
      labelledBy="detail-dialog-title"
    >
      <button type="button" onClick={closeDetail} aria-label="閉じる" className={DIALOG_CLOSE}>
        ×
      </button>

      {error ? <p className="text-[14px] text-[#8d4a37]">{error}</p> : null}
      {!item && !error ? <p className={MUTED}>読み込み中…</p> : null}

      {item && step === 'detail' ? (
        <>
          <div className="flex items-center gap-[15px] mt-[15px] mb-[18px] bg-[#edf0e7] rounded-[12px] px-[18px] py-[8px]">
            <StillPose
              slot={POSE_SLOTS.detailCompanion}
              size="w-[105px] h-[105px]"
              className="text-[15px] leading-[1.9] text-[#637157]"
              label="案内役のマスコット"
            />
            <span className="text-[15px] leading-[1.9] text-[#637157]">
              気になったら、
              <br />
              一歩ずつ見てみよう。
            </span>
          </div>
          <span className="text-[12px] text-terra tracking-[.1em]">{categoryLabel(item.type)}</span>
          <h2 id="detail-dialog-title" className={DIALOG_H2}>
            {item.title}
          </h2>
          {item.description ? <p className="text-[14px]">{item.description}</p> : null}

          <dl className="grid grid-cols-[80px_1fr] gap-[10px] text-[14px] bg-[#edf0e7] p-[18px] rounded-[7px] my-[22px]">
            <dt className="text-muted">開催日時</dt>
            <dd className="m-0">{scheduleLabel(item)}</dd>
            <dt className="text-muted">開催場所</dt>
            <dd className="m-0">{item.location ?? '場所未定'}</dd>
            <dt className="text-muted">参加費</dt>
            <dd className="m-0">{costLabel(item.cost, item.cost_kind)}</dd>
            {/* **何に対する締切かを見出しに出す。** 早割の期限を申込締切として見せない。 */}
            <dt className="text-muted">{deadlineKindLabel(item.deadline_kind)}</dt>
            <dd className="m-0">
              {deadlineLabel(item)}
              {item.deadline_quote ? (
                <span className="block text-muted text-[13px]">{item.deadline_quote}</span>
              ) : null}
            </dd>
            <dt className="text-muted">公式情報</dt>
            <dd className="m-0">
              {item.verified ? `確認済み（${formatDateTime(item.verified_at)}）` : '未確認'}
            </dd>
            {/* 「情報を確認できたか」と「いま申し込めるか」は別。両方を出す。 */}
            <dt className="text-muted">受付状況</dt>
            <dd className="m-0">
              {availabilityLabel(item)}
              {item.availability_reason ? (
                <span className="block text-muted text-[13px]">{item.availability_reason}</span>
              ) : null}
            </dd>
          </dl>

          {item.reason ? (
            <>
              <h3 className={H3}>あなたとのつながり</h3>
              <p className="text-[14px]">{item.reason}</p>
            </>
          ) : null}
          <h3 className={H3}>参加条件</h3>
          <p className="text-[14px]">{item.eligibility ?? '記載なし'}</p>

          <div className="flex gap-[9px] my-[20px]">
            {(['like', 'dislike'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => react(value)}
                className={`flex-1 border rounded-[6px] p-[9px] text-[13px] font-medium tracking-[.04em] ${
                  reactionOf(item.opportunity_id) === value
                    ? 'border-green bg-[#e9efe3]'
                    : 'border-line bg-white'
                }`}
              >
                {value === 'like' ? '♡ 興味がある' : '今回は違うかも'}
              </button>
            ))}
          </div>

          <button type="button" onClick={openPrepare} className={`${PRIMARY} w-full`}>
            {inSteps ? '参加準備リストを見る' : '参加に向けて準備する'} ↗
          </button>
          <p className={HINT}>
            応募や情報送信はこの画面では行いません。参加登録はご自身で公式ページから行ってください。
          </p>
        </>
      ) : null}

      {item && step === 'prepare' ? (
        <>
          <span className={EYEBROW}>ONE SMALL STEP</span>
          <h2 id="detail-dialog-title" className={DIALOG_H2}>
            参加までの一歩を、整理しよう。
          </h2>
          <p className="text-[14px]">{item.title}</p>
          <ul className="text-[14px] p-0 list-none my-[1em]">
            <li className="checklist-item border-b border-line py-[10px]">
              日程を確認：{scheduleLabel(item)}
            </li>
            <li className="checklist-item border-b border-line py-[10px]">
              参加条件：{item.eligibility ?? '記載なし'}
            </li>
            <li className="checklist-item border-b border-line py-[10px]">
              {/* **何に対する締切かを出す。** 早割の期限を申込締切として見せない。 */}
              {deadlineKindLabel(item.deadline_kind)}：{deadlineLabel(item)}
            </li>
          </ul>

          {officialUrl ? (
            <p className="text-[14px]">
              公式ページ：
              <a href={officialUrl} target="_blank" rel="noreferrer" className="underline">
                {officialUrl}
              </a>
            </p>
          ) : null}

          <label className="block text-[14px] mt-[20px] mb-[7px]" htmlFor="application">
            自己紹介メモ（編集できます）
          </label>
          <textarea
            id="application"
            rows={4}
            value={note}
            onChange={(event) => setLocalNote(event.target.value)}
            className="w-full p-[12px] border border-[#d4dbd0] rounded-[7px] bg-white text-ink text-[14px] resize-y min-h-[110px]"
          />
          <p className={HINT}>
            予定の空き状況と公式情報は未確認です。実際に参加するときは、公式ページでご確認ください。
          </p>
          <button
            type="button"
            onClick={() => {
              if (!summary) {
                // 「次の一歩」は一覧を status で絞って出すため、一覧に無いものは表示先が無い。
                showToast('この機会はいまのおすすめ一覧に無いため、次の一歩に追加できません');
                return;
              }
              markAsStep(item.opportunity_id);
              setNote(item.opportunity_id, note);
              setStep('done');
            }}
            className={`${PRIMARY} w-full`}
          >
            次の一歩に追加する ↗
          </button>
        </>
      ) : null}

      {item && step === 'done' ? (
        <>
          <span className="block text-[38px] text-green mt-[15px]">✳</span>
          <h2 id="detail-dialog-title" className={DIALOG_H2}>
            次の一歩が、見えてきました。
          </h2>
          <p className="text-[14px]">「{item.title}」を準備リストに追加しました。</p>
          <p className={MUTED}>
            「次の一歩」から、いつでも準備メモを確認できます。外部への応募は行っていません。
            カレンダー連携は未実装のため、この内容はこのブラウザにのみ残ります。
          </p>
          <button type="button" onClick={closeDetail} className={`${PRIMARY} w-full`}>
            閉じる ↗
          </button>
        </>
      ) : null}
    </Dialog>
  );
}
