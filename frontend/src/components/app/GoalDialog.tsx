import { useEffect, useRef, useState } from 'react';

import {
  EMPTY_PROFILE_DRAFT,
  loadProfileDraft,
  saveProfileDraft,
  type ProfileDraft,
} from '../../state/persistence';
import type { UserProfile, UserProfileInput } from '../../types';
import { Dialog } from '../Dialog';
import { DIALOG, DIALOG_CLOSE, DIALOG_H2, EYEBROW, FORM_HINT, MUTED, PRIMARY } from './styles';

const LABEL = 'block text-[14px] mt-[20px] mb-[7px]';
const FIELD = 'w-full p-[12px] border border-[#d4dbd0] rounded-[7px] bg-white text-ink text-[14px]';

/** 保存済みプロフィールを、フォームの見たままの形に戻す。 */
const fromProfile = (profile: UserProfile | null): ProfileDraft =>
  profile
    ? {
        name: profile.name ?? '',
        // **Backend が旧 goals をそのまま本文として返す。**
        // ここで分割・書き換えをしない。
        wantsNow: profile.wants_now ?? '',
        futureGoals: profile.future_goals ?? '',
        location: profile.location ?? '',
      }
    : EMPTY_PROFILE_DRAFT;

interface GoalDialogProps {
  open: boolean;
  profile: UserProfile | null;
  submitting: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: UserProfileInput) => void;
}

/**
 * ① 目標と興味の入力。
 * 検索キーワードは受け取らない。Agent が目標から「何を探すか」を決める。
 */
export function GoalDialog({
  open,
  profile,
  submitting,
  error,
  onClose,
  onSubmit,
}: GoalDialogProps) {
  const [name, setName] = useState('');
  const [wantsNow, setWantsNow] = useState('');
  const [futureGoals, setFutureGoals] = useState('');
  const [location, setLocation] = useState('');
  /** 復元が終わるまでは下書きを書かない。開いた瞬間の空の値で上書きしないため。 */
  const [restored, setRestored] = useState(false);

  const goalRef = useRef<HTMLTextAreaElement>(null);

  // 開くたびに、書きかけの下書きがあればそこから、無ければ保存されている内容から始める。
  useEffect(() => {
    if (!open) {
      setRestored(false);
      return;
    }
    const draft = loadProfileDraft() ?? fromProfile(profile);
    setName(draft.name);
    setWantsNow(draft.wantsNow);
    setFutureGoals(draft.futureGoals);
    setLocation(draft.location);
    setRestored(true);
  }, [open, profile]);

  // 入力の途中経過をこのブラウザに残す。閉じても・再読み込みしても続きから書ける。
  useEffect(() => {
    if (!open || !restored) return;
    saveProfileDraft({ name, wantsNow, futureGoals, location });
  }, [open, restored, name, wantsNow, futureGoals, location]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!wantsNow.trim()) {
      goalRef.current?.setCustomValidity('やってみたいことをひとこと入力してください');
      goalRef.current?.reportValidity();
      return;
    }
    goalRef.current?.setCustomValidity('');
    // **4 項目だけ送る。** 以前のフォームの項目（興味タグ・立場・できること・
    // 自己紹介）は送らないことで、Backend 側の保存値がそのまま残る。
    onSubmit({
      name: name.trim(),
      wants_now: wantsNow.trim(),
      future_goals: futureGoals.trim() || null,
      location: location.trim() || null,
    });
  };

  return (
    <Dialog open={open} onClose={onClose} className={DIALOG} labelledBy="goal-dialog-title">
      <form onSubmit={handleSubmit}>
        <button type="button" onClick={onClose} aria-label="閉じる" className={DIALOG_CLOSE}>
          ×
        </button>
        <span className={EYEBROW}>YOUR COMPASS</span>
        <h2 id="goal-dialog-title" className={DIALOG_H2}>
          どんな「次」を見つけたい？
        </h2>
        <p className={MUTED}>まだ、ぼんやりしていても大丈夫。</p>

        <label className={LABEL} htmlFor="profile-name">
          お名前 <span className={MUTED}>任意</span>
        </label>
        <input
          id="profile-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />

        <label className={LABEL} htmlFor="profile-wants-now">
          いま、やってみたいこと <span className={MUTED}>改行で複数書けます</span>
        </label>
        <textarea
          id="profile-wants-now"
          ref={goalRef}
          required
          rows={4}
          value={wantsNow}
          onChange={(event) => {
            setWantsNow(event.target.value);
            goalRef.current?.setCustomValidity('');
          }}
          className={`${FIELD} resize-y min-h-[130px]`}
        />

        <label className={LABEL} htmlFor="profile-future-goals">
          将来の目標 <span className={MUTED}>任意</span>
        </label>
        <textarea
          id="profile-future-goals"
          rows={2}
          value={futureGoals}
          onChange={(event) => setFutureGoals(event.target.value)}
          className={`${FIELD} resize-y min-h-[72px]`}
        />
        <p className={MUTED}>長期の目標です。今回探す機会の必須条件にはしません。</p>

        <label className={LABEL} htmlFor="profile-location">
          活動したい地域 <span className={MUTED}>任意・「オンライン」も指定できます</span>
        </label>
        <input
          id="profile-location"
          value={location}
          onChange={(event) => setLocation(event.target.value)}
          className={FIELD}
        />

        {error ? (
          <p className="mt-[18px] rounded-[7px] border border-[#e5c9c2] bg-[#faf1ee] px-[14px] py-[10px] text-[13px] text-[#8d4a37]">
            {error}
          </p>
        ) : null}

        <p className={FORM_HINT}>
          入力した内容から、Agent が探索する分野を決めます。検索キーワードの入力は不要です。
        </p>
        <button type="submit" disabled={submitting} className={`${PRIMARY} w-full`}>
          {submitting ? '探索をはじめています…' : 'この目標で探してみる'} <span>↗</span>
        </button>
      </form>
    </Dialog>
  );
}
