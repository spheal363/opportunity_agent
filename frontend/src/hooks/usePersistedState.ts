import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';

import { readStored, watchStored, writeStored } from '../utils/storage';

/**
 * useState と同じだが、値をこのブラウザに残して次回の読み込みで復元する。
 *
 * revive は localStorage から読んだ未検証の値を受け取り、使える形なら返す。
 * 復元した値も含めて毎回書き戻すので、検証で落ちた項目は保存側からも消える。
 */
export function usePersistedState<T>(
  key: string,
  initial: T,
  revive: (raw: unknown) => T | null,
): [T, Dispatch<SetStateAction<T>>] {
  // 初回のレンダーでだけ読む。以降はこの state が正。
  const [value, setValue] = useState<T>(() => readStored(key, revive) ?? initial);

  // clear されたときに戻る先。毎レンダー新しい {} が渡ってくるので ref に置く。
  const initialRef = useRef(initial);

  useEffect(() => {
    writeStored(key, value);
  }, [key, value]);

  /**
   * 他のタブの書き込みを取り込む。
   *
   * 取り込まないと、2 つのタブを開いているときに後から書いた側が相手の変更を
   * 消す（こちらは自分の state を丸ごと書き戻すため）。同じ値の書き戻しでは
   * storage イベントは飛ばないので、タブ同士で往復し続けることはない。
   */
  useEffect(
    () => watchStored(key, revive, (next) => setValue(next ?? initialRef.current)),
    [key, revive],
  );

  return [value, setValue];
}
