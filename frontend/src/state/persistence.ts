/**
 * このブラウザに残すもの一覧と、その検証。
 *
 * 残すのは「ユーザーとの関係」と「入力途中の下書き」だけ。
 * Web 上の事実（日時・場所・費用）と AI の評価（score / reason）は残さない。
 * それらはサーバーが正で、キャッシュすると古い値を事実として見せてしまう。
 *
 * ここにあるものは、サーバーに置き場所が無いから手元に残しているだけで、
 * 対応する API が実装されたらサーバーの値に置き換える（docs/api.md の 7 / 8）。
 */
import type { OpportunityStatus, Reaction } from '../types';
import { safeHttpUrl } from '../utils/display';
import {
  oneOf,
  readStored,
  recordOf,
  storedString,
  storedStrings,
  writeStored,
} from '../utils/storage';

export const STORAGE_KEY = {
  /** サーバーの status に重ねる、この端末での操作結果。 */
  statusOverrides: 'status-overrides',
  /** 送信済みの 👍 / 👎。どちらを押したかを返す API が無いぶん。 */
  reactions: 'reactions',
  /** POST /interest が返した登録先。 */
  registrationUrls: 'registration-urls',
  /** 参加準備の自己紹介メモ。外部には送っていない。 */
  notes: 'notes',
  /** 目標・興味ダイアログの入力途中。 */
  profileDraft: 'profile-draft',
} as const;

const OPPORTUNITY_STATUSES = [
  'discovered',
  'recommended',
  'interested',
  'registered',
  'attended',
  'dismissed',
] as const satisfies readonly OpportunityStatus[];

const REACTIONS = ['like', 'dislike'] as const satisfies readonly Reaction[];

export const reviveStatusOverrides = recordOf(oneOf(OPPORTUNITY_STATUSES));
export const reviveReactions = recordOf(oneOf(REACTIONS));
export const reviveNotes = recordOf(storedString);

/**
 * 登録先は Agent が Web から取り出した Untrusted Data で、保存後に書き換えられ得る。
 * 表示側でも safeHttpUrl を通すが、読み込んだ時点で http / https 以外を捨てる。
 */
export const reviveRegistrationUrls = recordOf((raw: unknown) => safeHttpUrl(storedString(raw)));

/** 目標・興味ダイアログの入力内容。フォームの見たまま（配列に分解する前）を残す。 */
export type ProfileDraft = {
  name: string;
  goals: string;
  interests: string[];
  location: string;
  occupation: string;
  skills: string;
  about: string;
};

export const EMPTY_PROFILE_DRAFT: ProfileDraft = {
  name: '',
  goals: '',
  interests: [],
  location: '',
  occupation: '',
  skills: '',
  about: '',
};

/** 何も入力されていない下書きは「下書きなし」と同じ。保存済みプロフィールを隠さない。 */
function isEmpty(draft: ProfileDraft): boolean {
  return (
    !draft.name &&
    !draft.goals &&
    !draft.interests.length &&
    !draft.location &&
    !draft.occupation &&
    !draft.skills &&
    !draft.about
  );
}

function reviveProfileDraft(raw: unknown): ProfileDraft | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const stored = raw as Record<string, unknown>;
  const draft: ProfileDraft = {
    name: storedString(stored.name) ?? '',
    goals: storedString(stored.goals) ?? '',
    interests: storedStrings(stored.interests) ?? [],
    location: storedString(stored.location) ?? '',
    occupation: storedString(stored.occupation) ?? '',
    skills: storedString(stored.skills) ?? '',
    about: storedString(stored.about) ?? '',
  };
  return isEmpty(draft) ? null : draft;
}

export function loadProfileDraft(): ProfileDraft | null {
  return readStored(STORAGE_KEY.profileDraft, reviveProfileDraft);
}

export function saveProfileDraft(draft: ProfileDraft): void {
  writeStored(STORAGE_KEY.profileDraft, isEmpty(draft) ? null : draft);
}

/** 保存が通ったら下書きは役目を終える。次に開くときは保存済みの内容から始める。 */
export function clearProfileDraft(): void {
  writeStored(STORAGE_KEY.profileDraft, null);
}
