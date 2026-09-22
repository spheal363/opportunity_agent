/** backend/schemas/calendar.py と対応。 */
export type CalendarConflict = {
  title: string;
  start_at: string;
  end_at: string;
};

/**
 * **実際に送る内容そのもの。**
 *
 * 画面の確認表示はこれを使う。候補の行から別に組み立てると、確認した内容と
 * 送信した内容がずれる（終日かどうか・終了時刻の仮置きなど）。
 */
export type CalendarEventPreview = {
  title: string;
  start_at: string;
  end_at: string;
  /** 出典に時刻が無かったので終日予定にする */
  all_day: boolean;
  timezone: string;
  /** 終了時刻が取れておらず、こちらが仮に置いた */
  end_is_placeholder: boolean;
  location: string | null;
  source_url: string | null;
};

export type CalendarAvailability = {
  available: boolean;
  conflicts: CalendarConflict[];
  /** 登録する内容。日時が取れていない候補では null（登録できない） */
  event: CalendarEventPreview | null;
};

export type CalendarEventCreated = {
  calendar_event_id: string;
  status: string;
};
