/**
 * 会員登録前のホームページ。
 * ここは Backend を呼ばない紹介ページで、表示しているのは固定の文言のみ。
 */
import { useEffect, useState } from 'react';

import { Closing, Ribbon, SiteFooter, SiteHeader } from '../components/welcome/Chrome';
import { Discoveries } from '../components/welcome/Discoveries';
import { FlowSection } from '../components/welcome/FlowSection';
import { Hero } from '../components/welcome/Hero';
import { StartDialog } from '../components/welcome/StartDialog';
import { usePageChrome } from '../hooks/usePageChrome';

export default function WelcomePage() {
  const [dialogOpen, setDialogOpen] = useState(false);
  usePageChrome('welcome');

  useEffect(() => {
    document.title = 'Opportunity — まだ知らない、あなたの可能性へ。';
  }, []);

  const open = () => setDialogOpen(true);

  return (
    <>
      <a
        className="absolute top-[-80px] left-[10px] z-20 bg-white p-[12px] focus:top-[10px]"
        href="#main"
      >
        本文へ移動
      </a>
      <SiteHeader onStart={open} />
      <main id="main">
        <Hero onStart={open} />
        <Ribbon />
        <FlowSection dialogOpen={dialogOpen} />
        <Discoveries />
        <Closing onStart={open} />
      </main>
      <SiteFooter />
      <StartDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </>
  );
}
