/**
 * Class strings shared by several welcome-page elements. The numbers are the
 * original stylesheet's, kept literal so the port stays comparable to it.
 *
 * Size-bearing utilities are never baked into a shared string, because two
 * utilities for the same property would resolve by stylesheet order rather
 * than by the order they appear in `className`.
 */

const BUTTON_BASE =
  'inline-flex items-center justify-center bg-home-green text-white border border-home-green ' +
  'rounded-[7px] leading-[1.5] font-medium tracking-[.04em] ' +
  'transition-[background-color,box-shadow,translate] duration-200 ' +
  'hover:bg-[#3c543d] hover:shadow-[0_6px_15px_#35512d1a]';

export const BUTTON = `${BUTTON_BASE} gap-[30px] px-[23px] py-[15px] text-[16px]`;

export const BUTTON_SMALL = `${BUTTON_BASE} gap-[20px] px-[18px] py-[11px] text-[14px] lte640:px-[12px] lte640:py-[9px]`;

export const EYEBROW = 'text-[12px] tracking-[.06em] text-[#788469] font-medium font-en';

export const SECTION = 'max-w-[1190px] mx-auto px-[12px] lte1250:px-[38px] lte640:px-[25px]';

export const SECTION_LABEL =
  'flex items-center justify-between text-[12px] tracking-[.06em] text-[#8a927d] ' +
  'mb-[32px] font-en lte640:block lte640:mb-[22px]';

export const SECTION_LABEL_NOTE = 'text-[12px] tracking-[.04em] lte640:block lte640:mt-[4px]';

/** Font sizes are supplied per placement — the header and footer differ. */
export const BRAND =
  'inline-flex items-center font-semibold tracking-[-.045em] leading-none font-en';
export const BRAND_MARK = 'text-[#56714f]';
export const BRAND_DOT = 'not-italic text-[#ba825e]';
