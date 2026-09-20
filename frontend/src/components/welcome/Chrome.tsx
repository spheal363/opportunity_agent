import { Link } from 'react-router-dom';

import { BRAND, BRAND_DOT, BRAND_MARK, BUTTON, BUTTON_SMALL, EYEBROW } from './styles';

interface BrandProps {
  /** Font size classes, including any responsive variants. */
  size: string;
  markSize: string;
}

export function Brand({ size, markSize }: BrandProps) {
  return (
    <Link className={`${BRAND} ${size}`} to="/">
      <span className={`${BRAND_MARK} ${markSize}`}>✳</span>opportunity
      <i className={BRAND_DOT}>.</i>
    </Link>
  );
}

export function SiteHeader({ onStart }: { onStart: () => void }) {
  return (
    <header
      className={
        'h-[94px] max-w-[1360px] px-[60px] mx-auto flex items-center justify-between gap-[22px] ' +
        'lte1250:px-[35px] lte900:h-[82px] lte900:px-[25px] ' +
        'lte640:h-[76px] lte640:px-[20px]'
      }
    >
      <Brand
        size="text-[29px] lte640:text-[24px]"
        markSize="text-[42px] mr-[10px] lte640:text-[34px] lte640:mr-[7px]"
      />
      <nav
        aria-label="ページ内ナビゲーション"
        className="flex gap-[30px] items-center text-[14px] lte900:gap-[18px] lte640:gap-[12px]"
      >
        <a href="#how" className="text-[#667060] hover:text-[#a26745] lte900:hidden">
          サービスの使い方
        </a>
        <a href="#possibilities" className="text-[#667060] hover:text-[#a26745] lte900:hidden">
          見つかる機会
        </a>
        <Link to="/app" className="text-[#667060] hover:text-[#a26745] lte640:hidden">
          アプリを開く
        </Link>
        <button type="button" onClick={onStart} className={BUTTON_SMALL}>
          はじめる ↗
        </button>
      </nav>
    </header>
  );
}

export function Ribbon() {
  return (
    <div
      className={
        'border-t border-b border-home-line flex items-center justify-center gap-[52px] ' +
        'min-h-[75px] text-[#8c9481] text-[13px] tracking-[.06em] font-en ' +
        'lte1250:gap-[30px] lte1250:text-[12px] lte900:gap-[20px] ' +
        'lte640:min-h-[66px] lte640:gap-[13px] lte640:overflow-hidden ' +
        'lte640:whitespace-nowrap lte640:justify-start lte640:pl-[25px]'
      }
    >
      <span>HACKATHONS</span>
      <b className="text-[25px] font-normal text-[#b5ae8e] lte640:text-[19px]">✧</b>
      <span>COMMUNITIES</span>
      <b className="text-[25px] font-normal text-[#b5ae8e] lte640:text-[19px]">✧</b>
      <span>WORKSHOPS</span>
      <b className="text-[25px] font-normal text-[#b5ae8e] lte640:text-[19px]">✧</b>
      <span>NEW CHALLENGES</span>
    </div>
  );
}

export function Closing({ onStart }: { onStart: () => void }) {
  return (
    <section
      className={
        'text-center mx-[32px] mt-0 mb-[66px] pt-[60px] px-[20px] pb-[67px] bg-[#eef0e5] ' +
        'border border-[#e3e8d6] rounded-[18px] lte640:mx-[17px] lte640:mt-[12px] ' +
        'lte640:mb-[42px] lte640:pt-[42px] lte640:pb-[45px]'
      }
    >
      <span className={EYEBROW}>LET'S FIND YOUR NEXT</span>
      <h2 className="text-[34px] leading-[1.8] font-bold tracking-[.04em] mt-[17px] mb-[14px] lte640:text-[25px]">
        最初の一歩は、
        <br />
        「こんなこと、してみたい」。
      </h2>
      <p className="text-[#7b886f] text-[16px] m-0 mb-[25px]">
        あなたに合う機会から、次の一歩を見つけましょう。
      </p>
      <button
        type="button"
        onClick={onStart}
        className={`${BUTTON} lte640:text-[14px] lte640:px-[18px] lte640:py-[14px]`}
      >
        自分の可能性を探してみる <span>↗</span>
      </button>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer
      className={
        'max-w-[1240px] mx-auto flex items-center gap-[26px] px-[25px] pb-[38px] flex-wrap ' +
        'lte640:gap-[15px] lte640:pb-[30px]'
      }
    >
      <Brand size="text-[22px]" markSize="text-[30px] mr-[10px] lte640:mr-[7px]" />
      <p className="text-[14px] text-[#818a76] lte640:m-0">小さなきっかけから、新しい自分へ。</p>
      <small className="ml-auto text-[#989d8d] text-[12px] lte900:ml-0 lte900:w-full lte640:leading-[1.8]">
        PROTOTYPE · 実際のAI検索・会員登録・応募は行いません。
      </small>
    </footer>
  );
}
