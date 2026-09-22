import { useEffect } from 'react';

const IDLE_INTERVAL_MS = 30_000;
const ACTIVE_INTERVAL_MS = 5_000;

/**
 * アプリ内の各画面で、最新の run を控えめに取り直す。
 *
 * Agent は定期チェックなどで自分から探索を始めることがある。画面を開いたとき・
 * タブに戻ったとき・一定間隔で取り、気づけるようにする。タブが隠れている間は取らない。
 * 自動で始めた探索が進行中のときだけ間隔を縮める（終わったら結果へのリンクに変えるため）。
 */
export function useLatestRunWatch(refresh: () => Promise<unknown>, active: boolean) {
  useEffect(() => {
    void refresh();
    const onFocus = () => void refresh();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refresh]);

  useEffect(() => {
    const timer = setInterval(
      () => {
        if (document.visibilityState === 'visible') void refresh();
      },
      active ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS,
    );
    return () => clearInterval(timer);
  }, [refresh, active]);
}
