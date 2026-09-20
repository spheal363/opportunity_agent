import { useEffect, useRef, useState } from 'react';

import type { UserProfile, UserProfileInput } from '../../types';
import { parseList } from '../../utils/date';
import { Dialog } from '../Dialog';
import { DIALOG, DIALOG_CLOSE, DIALOG_H2, EYEBROW, FORM_HINT, MUTED, PRIMARY } from './styles';

const LABEL = 'block text-[14px] mt-[20px] mb-[7px]';
const FIELD = 'w-full p-[12px] border border-[#d4dbd0] rounded-[7px] bg-white text-ink text-[14px]';

/** 興味の候補。プロフィールに入っているものと合わせて表示する。 */
const SUGGESTED_INTERESTS = ['AI', 'Startup', 'Music', 'Design', 'Community', 'International'];

/** 目標は文章で書けるよう、改行だけで区切る（読点では分けない）。 */
const parseGoals = (value: string) =>
  value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

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
  const [goals, setGoals] = useState('');
  const [interests, setInterests] = useState<string[]>([]);
  const [location, setLocation] = useState('');
  const [occupation, setOccupation] = useState('');
  const [skills, setSkills] = useState('');
  const [about, setAbout] = useState('');
  const [adding, setAdding] = useState('');

  const goalRef = useRef<HTMLTextAreaElement>(null);

  // 開くたびに、いま保存されている内容から始める。
  useEffect(() => {
    if (!open) return;
    setName(profile?.name ?? '');
    setGoals((profile?.goals ?? []).join('\n'));
    setInterests(profile?.interests ?? []);
    setLocation(profile?.location ?? '');
    setOccupation(profile?.occupation ?? '');
    setSkills((profile?.skills ?? []).join(', '));
    setAbout(profile?.about ?? '');
    setAdding('');
  }, [open, profile]);

  const chips = Array.from(new Set([...interests, ...SUGGESTED_INTERESTS]));

  const toggle = (interest: string) =>
    setInterests((prev) =>
      prev.includes(interest) ? prev.filter((t) => t !== interest) : [...prev, interest],
    );

  const addInterest = () => {
    const value = adding.trim();
    if (!value) return;
    setInterests((prev) => (prev.includes(value) ? prev : [...prev, value]));
    setAdding('');
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = parseGoals(goals);
    if (!parsed.length) {
      goalRef.current?.setCustomValidity('目標をひとこと入力してください');
      goalRef.current?.reportValidity();
      return;
    }
    goalRef.current?.setCustomValidity('');
    onSubmit({
      name: name.trim(),
      location: location.trim() || null,
      occupation: occupation.trim() || null,
      skills: parseList(skills),
      interests,
      goals: parsed,
      about: about.trim() || null,
      // 画面に出していない項目は、保存済みの内容をそのまま残す。
      languages: profile?.languages ?? [],
      experience: profile?.experience ?? [],
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
          お名前
        </label>
        <input
          id="profile-name"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          className={FIELD}
        />

        <label className={LABEL} htmlFor="profile-goals">
          やってみたいこと・目標 <span className={MUTED}>改行で複数書けます</span>
        </label>
        <textarea
          id="profile-goals"
          ref={goalRef}
          required
          rows={3}
          value={goals}
          onChange={(event) => {
            setGoals(event.target.value);
            goalRef.current?.setCustomValidity('');
          }}
          className={`${FIELD} resize-y min-h-[110px]`}
        />

        <label className={LABEL}>
          興味のあること <span className={MUTED}>複数選べます</span>
        </label>
        <div className="flex flex-wrap gap-[8px]">
          {chips.map((interest) => {
            const selected = interests.includes(interest);
            return (
              <button
                key={interest}
                type="button"
                aria-pressed={selected}
                onClick={() => toggle(interest)}
                className={`border px-[13px] py-[6px] rounded-[25px] text-[13px] font-medium tracking-[.04em] ${
                  selected
                    ? 'bg-[#e4ecdf] border-[#81977a] text-[#3d5734]'
                    : 'bg-white border-[#d9ded3]'
                }`}
              >
                {interest}
              </button>
            );
          })}
          <input
            aria-label="興味を追加"
            placeholder="＋ 追加"
            value={adding}
            onChange={(event) => setAdding(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter') return;
              event.preventDefault();
              addInterest();
            }}
            onBlur={addInterest}
            className="border border-dashed border-[#d9ded3] bg-white px-[13px] py-[6px] rounded-[25px] text-[13px] w-[104px]"
          />
        </div>

        <div className="grid grid-cols-2 gap-[14px] lte620:grid-cols-1 lte620:gap-0">
          <div>
            <label className={LABEL} htmlFor="profile-location">
              活動したい地域
            </label>
            <input
              id="profile-location"
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              className={FIELD}
            />
          </div>
          <div>
            <label className={LABEL} htmlFor="profile-occupation">
              いまの立場
            </label>
            <input
              id="profile-occupation"
              value={occupation}
              onChange={(event) => setOccupation(event.target.value)}
              className={FIELD}
            />
          </div>
        </div>

        <label className={LABEL} htmlFor="profile-skills">
          できること <span className={MUTED}>カンマ区切り</span>
        </label>
        <input
          id="profile-skills"
          value={skills}
          onChange={(event) => setSkills(event.target.value)}
          className={FIELD}
        />

        <label className={LABEL} htmlFor="profile-about">
          自己紹介 <span className={MUTED}>任意</span>
        </label>
        <textarea
          id="profile-about"
          rows={3}
          value={about}
          onChange={(event) => setAbout(event.target.value)}
          className={`${FIELD} resize-y min-h-[110px]`}
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
