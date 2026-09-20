import { useEffect } from 'react';

/**
 * ホームページとアプリ本体では下地の色と行間が違う。
 * body の data-page を切り替えて index.css 側で当てる。
 */
export function usePageChrome(page: 'welcome' | 'app') {
  useEffect(() => {
    document.body.dataset.page = page;
    return () => {
      delete document.body.dataset.page;
    };
  }, [page]);
}
