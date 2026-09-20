import { useCallback, useEffect, useRef, useState } from 'react';
import { useReducedMotion } from './useReducedMotion';

const INTERVAL_MS = 4000;
const SETTLE_MS = 160;

/**
 * The three-step story advances on its own every four seconds and can also be
 * driven by swipe, mouse drag, the arrows, the tabs or the keyboard. Any of
 * hover, focus, dragging, a hidden tab, an open dialog or scrolling out of view
 * suspends the auto-advance until the reader is done.
 */
export function useFlowCarousel(count: number, suspended: boolean) {
  const reduced = useReducedMotion();
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(!reduced);
  const [dragging, setDragging] = useState(false);

  const trackRef = useRef<HTMLDivElement | null>(null);
  const sectionRef = useRef<HTMLElement | null>(null);

  const indexRef = useRef(0);
  const playingRef = useRef(playing);
  const reducedRef = useRef(reduced);
  const suspendedRef = useRef(suspended);
  const hoverRef = useRef(false);
  const focusRef = useRef(false);
  const dragRef = useRef<{ x: number; left: number } | null>(null);
  const visibleRef = useRef(true);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const settle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const goToRef = useRef<(next: number) => void>(() => {});

  const cards = () =>
    Array.from(trackRef.current?.querySelectorAll<HTMLElement>('[data-flow-card]') ?? []);

  const schedule = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    const canPlay =
      playingRef.current &&
      !hoverRef.current &&
      !focusRef.current &&
      !dragRef.current &&
      !document.hidden &&
      !suspendedRef.current &&
      visibleRef.current;
    if (!canPlay) return;
    timer.current = setTimeout(() => goToRef.current(indexRef.current + 1), INTERVAL_MS);
  }, []);

  /** Update the active index without moving the track. */
  const mark = useCallback((next: number) => {
    indexRef.current = next;
    setIndex(next);
  }, []);

  const goTo = useCallback(
    (next: number) => {
      const target = ((next % count) + count) % count;
      mark(target);
      const track = trackRef.current;
      const list = cards();
      if (track && list.length > target) {
        track.scrollTo({
          left: list[target].offsetLeft - list[0].offsetLeft,
          behavior: reducedRef.current ? 'instant' : 'smooth',
        });
      }
      schedule();
    },
    [count, mark, schedule],
  );

  goToRef.current = goTo;

  const nearestCard = () => {
    const track = trackRef.current;
    const list = cards();
    if (!track || !list.length) return indexRef.current;
    const base = list[0].offsetLeft;
    return list.reduce(
      (best, card, i) =>
        Math.abs(card.offsetLeft - base - track.scrollLeft) <
        Math.abs(list[best].offsetLeft - base - track.scrollLeft)
          ? i
          : best,
      0,
    );
  };

  const togglePlay = useCallback(() => {
    playingRef.current = !playingRef.current;
    setPlaying(playingRef.current);
    schedule();
  }, [schedule]);

  // Touch and trackpads use native scrolling; a mouse can drag the cards too.
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    const track = trackRef.current;
    if (!track) return;
    dragRef.current = { x: event.clientX, left: track.scrollLeft };
    track.setPointerCapture(event.pointerId);
    setDragging(true);
    schedule();
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    const track = trackRef.current;
    if (!drag || !track) return;
    track.scrollLeft = drag.left - (event.clientX - drag.x);
  };

  const finishDrag = () => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setDragging(false);
    goTo(nearestCard());
  };

  const onScroll = () => {
    if (timer.current) clearTimeout(timer.current);
    if (settle.current) clearTimeout(settle.current);
    settle.current = setTimeout(() => {
      mark(nearestCard());
      schedule();
    }, SETTLE_MS);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    goTo(indexRef.current + (event.key === 'ArrowRight' ? 1 : -1));
  };

  const onMouseEnter = () => {
    hoverRef.current = true;
    schedule();
  };

  const onMouseLeave = () => {
    hoverRef.current = false;
    schedule();
  };

  const onFocus = () => {
    focusRef.current = true;
    schedule();
  };

  const onBlur = (event: React.FocusEvent<HTMLElement>) => {
    if (sectionRef.current?.contains(event.relatedTarget as Node | null)) return;
    focusRef.current = false;
    schedule();
  };

  useEffect(() => {
    suspendedRef.current = suspended;
    schedule();
  }, [suspended, schedule]);

  useEffect(() => {
    reducedRef.current = reduced;
    playingRef.current = !reduced;
    setPlaying(!reduced);
    schedule();
  }, [reduced, schedule]);

  useEffect(() => {
    const onVisibility = () => schedule();
    document.addEventListener('visibilitychange', onVisibility);

    let observer: IntersectionObserver | undefined;
    if ('IntersectionObserver' in window && sectionRef.current) {
      visibleRef.current = false;
      observer = new IntersectionObserver(
        (entries) => {
          visibleRef.current = entries[0].isIntersecting;
          schedule();
        },
        { threshold: 0.2 },
      );
      observer.observe(sectionRef.current);
    }

    schedule();
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      observer?.disconnect();
      if (timer.current) clearTimeout(timer.current);
      if (settle.current) clearTimeout(settle.current);
    };
  }, [schedule]);

  return {
    index,
    playing,
    dragging,
    trackRef,
    sectionRef,
    goTo,
    togglePlay,
    trackHandlers: { onPointerDown, onPointerMove, onScroll, onKeyDown },
    finishDrag,
    sectionHandlers: { onMouseEnter, onMouseLeave, onFocus, onBlur },
  };
}
