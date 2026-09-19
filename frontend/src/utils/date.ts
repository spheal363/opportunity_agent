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

/** "Java, Python, AWS" のような入力を配列にする。 */
export function parseList(value: string): string[] {
  return value
    .split(/[,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
