/** Class strings shared across the demo app's screens. */

export const PRIMARY =
  'bg-green border border-green text-white rounded-[6px] px-[19px] py-[11px] text-[14px] ' +
  'inline-flex items-center justify-center gap-[28px] font-medium tracking-[.04em] ' +
  'transition-[background-color,transform] duration-200 hover:bg-[#3f564a] hover:-translate-y-px ' +
  'disabled:opacity-55 disabled:cursor-not-allowed';

export const OUTLINE_BUTTON =
  'border border-[#d5dbd2] bg-transparent rounded-[6px] px-[15px] py-[9px] text-[14px] ' +
  'whitespace-nowrap font-medium tracking-[.04em] disabled:opacity-55 disabled:cursor-not-allowed';

export const TEXT_BUTTON =
  'border-0 bg-transparent p-0 text-[14px] text-green font-medium tracking-[.04em]';

export const EYEBROW = 'text-[12px] tracking-[.06em] font-semibold text-[#6b7c6f] font-en';

export const DIALOG =
  'border border-line rounded-[17px] w-[min(560px,calc(100%-28px))] p-[32px] text-ink bg-bg ' +
  'max-h-[90vh] overflow-auto shadow-[0_30px_100px_#27362c25] lte620:px-[22px] lte620:py-[27px]';

export const DIALOG_H2 = 'text-[24px] font-bold tracking-[.04em] mt-[9px] mb-[10px] leading-[1.6]';

export const DIALOG_CLOSE =
  'absolute right-[18px] top-[14px] text-[26px] border-0 bg-transparent w-[36px] h-[36px] text-muted';

export const FORM_HINT = 'text-[12px] text-muted my-[22px]';

export const MUTED = 'text-muted text-[14px]';

export const PROCESS_HEADING = 'flex items-center justify-between gap-[10px] mb-[12px]';
export const PROCESS_HEADING_H3 = 'text-[17px] font-medium m-0';
/** Inside an inspector card the same heading keeps the card's own margins. */
export const INSPECTOR_HEADING_H3 = 'text-[17px] font-medium mt-[8px] mb-[12px]';
export const PROCESS_HEADING_NOTE = 'text-[12px] text-[#7b8675]';

export const INSPECTOR_CARD = 'border border-line rounded-[13px] bg-white p-[22px] mb-[18px]';

export const SPARK = 'spark absolute text-[#bb8c3c] pointer-events-none';
