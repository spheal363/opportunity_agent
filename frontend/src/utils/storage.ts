/**
 * このブラウザの中だけに残す値の読み書き。
 *
 * localStorage は Private Window・容量超過・ブラウザ設定で普通に失敗する。
 * 失敗しても「保存できなかっただけ」で画面は動き続ける形にする。
 *
 * 読み出した値は、前のバージョンの自分や同じオリジンの何かが書いたもので、
 * 型の保証が無い。必ず検証して、通らない項目は捨てる（推測で埋めない）。
 *
 * MVP は認証なしの単一ユーザーなので key にユーザーを含めない。
 * 認証を足すときは PREFIX にユーザーを入れて分ける。
 */

/** 保存する形を変えたら v を上げる。古い値は revive に落とされて捨てられる。 */
const PREFIX = 'opportunity-agent.v1.';

/** 保存されている値を読む。無い・壊れている・検証に通らないときは null。 */
export function readStored<T>(key: string, revive: (raw: unknown) => T | null): T | null {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(PREFIX + key);
  } catch {
    // Storage が使えない環境。保存無しで動かす。
    return null;
  }
  if (raw === null) return null;
  try {
    return revive(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** 値を保存する。null / undefined のときはその key を消す。 */
export function writeStored(key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) {
      window.localStorage.removeItem(PREFIX + key);
      return;
    }
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // 保存できなくても画面は動く。
  }
}

/**
 * 他のタブが同じ key を書き換えたときに呼ぶ。解除する関数を返す。
 *
 * storage イベントは「書いた側以外」のタブにだけ届く。取り込まないでいると、
 * こちらの古い値を丸ごと書き戻したときに相手の変更を消してしまう。
 * 値が空（clear された・消された）のときは null を渡す。
 */
export function watchStored<T>(
  key: string,
  revive: (raw: unknown) => T | null,
  onChange: (value: T | null) => void,
): () => void {
  const fullKey = PREFIX + key;
  const handle = (event: StorageEvent) => {
    // clear() のときだけ key が null になる。そのときも読み直す。
    if (event.key !== null && event.key !== fullKey) return;
    onChange(readStored(key, revive));
  };
  window.addEventListener('storage', handle);
  return () => window.removeEventListener('storage', handle);
}

/** 文字列キーの Record として読む。値の検証に通らない項目は捨てる。 */
export function recordOf<T>(reviveValue: (raw: unknown) => T | null) {
  return (raw: unknown): Record<string, T> | null => {
    if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
    const result: Record<string, T> = {};
    for (const [key, value] of Object.entries(raw)) {
      const revived = reviveValue(value);
      if (revived !== null) result[key] = revived;
    }
    return result;
  };
}

/** 決まった値のどれかであることを確かめる。知らない値は捨てる。 */
export function oneOf<T extends string>(allowed: readonly T[]) {
  return (raw: unknown): T | null =>
    typeof raw === 'string' && (allowed as readonly string[]).includes(raw) ? (raw as T) : null;
}

export function storedString(raw: unknown): string | null {
  return typeof raw === 'string' ? raw : null;
}

export function storedStrings(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.filter((item): item is string => typeof item === 'string');
}
