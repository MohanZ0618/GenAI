import { useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";

type Position = { following: boolean; top: number };
type Options = {
  viewport: RefObject<HTMLDivElement | null>;
  content: RefObject<HTMLDivElement | null>;
  sessionKey: string;
  open: boolean;
  active: boolean;
  suspended: boolean;
  completed: boolean;
};

/** Follow growing text inside the dialog, without taking over manual reading. */
export function useInvestigationFollowScroll({
  viewport,
  content,
  sessionKey,
  open,
  active,
  suspended,
  completed,
}: Options) {
  const positions = useRef(new Map<string, Position>());
  const previous = useRef<
    { key: string; active: boolean; open: boolean } | undefined
  >(undefined);
  const jump = useRef<(() => void) | undefined>(undefined);
  const [following, setFollowing] = useState(true);

  useLayoutEffect(() => {
    const position = positions.current.get(sessionKey) ?? {
      following: true,
      top: 0,
    };
    positions.current.set(sessionKey, position);
    const last = previous.current;
    previous.current = { key: sessionKey, active, open };
    if (suspended) position.following = false;
    setFollowing(position.following);
    const element = viewport.current;
    if (!open || !element || suspended) return;

    // A completed report starts at its conclusion, rather than following the
    // much longer report to its footer. Paused readers keep their own position.
    if (!active) {
      if (
        last?.key === sessionKey &&
        last.open &&
        last.active &&
        position.following
      ) {
        element.scrollTop = completed
          ? 0
          : element.scrollHeight - element.clientHeight;
        position.top = element.scrollTop;
      }
      return;
    }
    let frame: number | undefined;
    let expectedTop: number | undefined;
    const markFollowing = (value: boolean) => {
      position.following = value;
      setFollowing(value);
    };
    const cancelFrame = () => {
      if (frame !== undefined) cancelAnimationFrame(frame);
      frame = undefined;
    };
    const pause = () => {
      cancelFrame();
      expectedTop = undefined;
      markFollowing(false);
    };
    const scrollTo = (top: number) => {
      element.scrollTop = top;
      expectedTop = element.scrollTop;
      position.top = element.scrollTop;
    };
    const latest = () =>
      scrollTo(Math.max(0, element.scrollHeight - element.clientHeight));
    const schedule = () => {
      if (!position.following || frame !== undefined) return;
      frame = requestAnimationFrame(() => {
        frame = undefined;
        if (position.following) latest();
      });
    };
    const onScroll = () => {
      const top = Math.max(0, element.scrollTop);
      const lastTop = position.top;
      position.top = top;
      if (expectedTop !== undefined && Math.abs(top - expectedTop) <= 1) {
        expectedTop = undefined;
        return;
      }
      expectedTop = undefined;
      // Layout shrinkage (for example a refreshed verification summary) can
      // move scrollTop upward too. Only user input pauses following.
      if (top < lastTop - 1) return;
      if (
        element.scrollHeight - element.clientHeight - top <= 24 &&
        !position.following
      ) {
        markFollowing(true);
        schedule();
      }
    };
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY < 0 && element.scrollHeight > element.clientHeight + 1)
        pause();
    };
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable=true]"))
        return;
      if (["ArrowUp", "PageUp", "Home"].includes(event.key)) pause();
    };
    const onScrollbar = (event: PointerEvent) => {
      const bounds = element.getBoundingClientRect();
      if (event.clientX >= bounds.right - 22 && event.target === element)
        pause();
    };
    const onDisclosure = (event: MouseEvent) => {
      if (
        (event.target as HTMLElement).closest(
          "summary, .investigation-progress-toggle",
        )
      )
        pause();
    };
    jump.current = () => {
      markFollowing(true);
      latest();
      element.focus({ preventScroll: true });
    };
    // The DOM is recreated when a window is closed, but its reading position is not.
    scrollTo(position.top);
    element.addEventListener("scroll", onScroll, { passive: true });
    element.addEventListener("wheel", onWheel, { passive: true });
    element.addEventListener("keydown", onKey);
    element.addEventListener("pointerdown", onScrollbar);
    element.addEventListener("click", onDisclosure, true);
    const observer = new ResizeObserver(schedule);
    if (content.current) observer.observe(content.current);
    observer.observe(element);
    schedule();
    return () => {
      cancelFrame();
      observer.disconnect();
      jump.current = undefined;
      element.removeEventListener("scroll", onScroll);
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("keydown", onKey);
      element.removeEventListener("pointerdown", onScrollbar);
      element.removeEventListener("click", onDisclosure, true);
    };
  }, [open, active, suspended, completed, sessionKey, viewport, content]);

  return { following, jumpToLatest: () => jump.current?.() };
}
