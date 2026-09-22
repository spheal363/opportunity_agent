/** backend/schemas/profile.py と対応。 */
export type UserProfileInput = {
  /** 任意。未入力なら空文字。 */
  name?: string;
  /** **いま、やってみたいこと。** 初回フォームのメイン欄で、検索の中心。 */
  wants_now?: string | null;
  /** 将来の目標。任意。**今回の探索の必須条件にしない。** */
  future_goals?: string | null;
  location?: string | null;
  languages?: string[];
  occupation?: string | null;
  skills?: string[];
  experience?: string[];
  interests?: string[];
  goals?: string[];
  about?: string | null;
};

/**
 * 保存済みプロフィール。
 *
 * `occupation` / `skills` / `interests` / `goals` / `about` は初回フォームから
 * 外したが、**既存データは残る**ので型にも残す（#47）。
 */
export type UserProfile = Required<
  Omit<UserProfileInput, 'location' | 'occupation' | 'about' | 'wants_now' | 'future_goals'>
> & {
  user_id: string;
  wants_now: string | null;
  future_goals: string | null;
  location: string | null;
  occupation: string | null;
  about: string | null;
};
