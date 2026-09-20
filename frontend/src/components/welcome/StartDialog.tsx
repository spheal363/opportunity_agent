import { Link } from 'react-router-dom';

import { Dialog } from '../Dialog';
import { BUTTON, EYEBROW } from './styles';

export function StartDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      labelledBy="startTitle"
      className={
        'w-[min(495px,calc(100vw-32px))] p-[38px] border border-[#dce2d2] rounded-[18px] ' +
        'bg-home-paper text-home-ink shadow-[0_30px_70px_#34412b33] ' +
        'lte640:px-[25px] lte640:py-[34px]'
      }
    >
      <button
        type="button"
        aria-label="閉じる"
        onClick={onClose}
        className="absolute right-[16px] top-[10px] border-0 bg-transparent text-[#7b8671] text-[28px] w-[35px] h-[35px]"
      >
        ×
      </button>
      <span className={EYEBROW}>WELCOME TO OPPORTUNITY</span>
      <h2
        id="startTitle"
        className="text-[28px] leading-[1.7] font-bold tracking-[.04em] my-[15px] lte640:text-[25px]"
      >
        まずは、あなたの
        <br />
        「やってみたい」から。
      </h2>
      <p className="text-[16px] text-[#7a8471] mb-[25px]">
        目標と興味を入力すると、あなたに合う機会の探索が始まります。
      </p>
      <Link className={`${BUTTON} flex w-full`} to="/app?edit=1">
        目標を伝えてはじめる <span>↗</span>
      </Link>
      <Link
        className="block text-center text-[14px] text-[#6d7e5f] my-[17px] font-medium tracking-[.04em]"
        to="/app/results"
      >
        入力せず、おすすめを見る
      </Link>
      <small className="block text-center text-[12px] text-[#929987]">
        今回は体験版のため、アカウント作成は不要です。
      </small>
    </Dialog>
  );
}
