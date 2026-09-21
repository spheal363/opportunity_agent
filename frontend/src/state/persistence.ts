/**
 * このブラウザに残すもの一覧と、その検証。
 *
 * 残すのは「ユーザーとその機会の関係」だけ。
 * Web 上の事実（日時・場所・費用）と AI の評価（score / reason）は残さない。
 * それらはサーバーが正で、キャッシュすると古い値を事実として見せてしまう。
 *
 * ここにあるものは、サーバーに置き場所が無いから手元に残しているだけで、
 * 対応する API が実装されたらサーバーの値に置き換える（docs/api.md の 7 / 8）。
 */
import type { OpportunityStatus, Reaction } from '../types';
import { safeHttpUrl } from '../utils/display';
import { oneOf, recordOf, storedString } from '../utils/storage';

export const STORAGE_KEY = {
  /** サーバーの status に重ねる、この端末での操作結果。 */
  statusOverrides: 'status-overrides',
  /** 送信済みの 👍 / 👎。どちらを押したかを返す API が無いぶん。 */
  reactions: 'reactions',
  /** POST /interest が返した登録先。 */
  registrationUrls: 'registration-urls',
  /** 参加準備の自己紹介メモ。外部には送っていない。 */
  notes: 'notes',
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
