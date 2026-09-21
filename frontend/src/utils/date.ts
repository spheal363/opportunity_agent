/** Backend は ISO8601 (UTC) で返す。表示はブラウザのタイムゾーンに合わせる。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '日時未定';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '日時未定';
  return new Intl.DateTimeFormat('ja-JP', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

/**
 * 出典に時刻が無かったものは、日付だけで見せる。
 *
 * **こちらが 00:00 へ正規化した値を、出典の時刻として見せない。**
 * 「10月7日」としか書かれていないページから「10月7日 0:00」と出すと、
 * 書かれていない事実を伝えることになる。
 */
export function formatDateOrDateTime(
  value: string | null | undefined,
  dateOnly: boolean,
): string {
  if (!value) return '日時未定';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '日時未定';
  if (!dateOnly) return formatDateTime(value);
  return new Intl.DateTimeFormat('ja-JP', { dateStyle: 'medium' }).format(date);
}

/** "Java, Python, AWS" のような入力を配列にする。 */
export function parseList(value: string): string[] {
  return value
    .split(/[,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
