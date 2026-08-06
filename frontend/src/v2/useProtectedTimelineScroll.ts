import { useCallback, useEffect, useRef, useState, type RefObject, type UIEventHandler } from "react";

export const TIMELINE_FOLLOW_THRESHOLD_PX = 120;

type NoticeKind = "message" | "result" | null;

type ProtectedTimelineScroll = {
  notice: NoticeKind;
  resultHighlighted: boolean;
  onScroll: UIEventHandler<HTMLOListElement>;
  followNotice: () => void;
};

export function isNearTimelineBottom(element: Pick<HTMLElement, "scrollHeight" | "scrollTop" | "clientHeight">) {
  return element.scrollHeight - element.scrollTop - element.clientHeight <= TIMELINE_FOLLOW_THRESHOLD_PX;
}

export function useProtectedTimelineScroll({
  timelineRef,
  resultRef,
  contentKey,
  resultReady,
  resetKey,
}: {
  timelineRef: RefObject<HTMLOListElement | null>;
  resultRef: RefObject<HTMLDivElement | null>;
  contentKey: string;
  resultReady: boolean;
  resetKey: string;
}): ProtectedTimelineScroll {
  const following = useRef(true);
  const previousContentKey = useRef(contentKey);
  const previousResultReady = useRef(resultReady);
  const highlightTimer = useRef<number | null>(null);
  const [notice, setNotice] = useState<NoticeKind>(null);
  const [resultHighlighted, setResultHighlighted] = useState(false);

  useEffect(() => {
    following.current = true;
    previousContentKey.current = contentKey;
    previousResultReady.current = resultReady;
    setNotice(null);
    setResultHighlighted(false);
    const timeline = timelineRef.current;
    if (timeline) timeline.scrollTop = timeline.scrollHeight;
  }, [resetKey]); // content state is deliberately re-baselined only when the session/run changes

  useEffect(() => {
    const contentChanged = previousContentKey.current !== contentKey;
    const resultPublished = !previousResultReady.current && resultReady;
    previousContentKey.current = contentKey;
    previousResultReady.current = resultReady;
    if (!contentChanged && !resultPublished) return;

    const timeline = timelineRef.current;
    if (!timeline) return;
    if (following.current) {
      timeline.scrollTop = timeline.scrollHeight;
      setNotice(null);
      return;
    }
    setNotice(resultPublished ? "result" : "message");
  }, [contentKey, resultReady, timelineRef]);

  useEffect(
    () => () => {
      if (highlightTimer.current != null) window.clearTimeout(highlightTimer.current);
    },
    [],
  );

  const onScroll: UIEventHandler<HTMLOListElement> = useCallback((event) => {
    following.current = isNearTimelineBottom(event.currentTarget);
    if (following.current) setNotice(null);
  }, []);

  const followNotice = useCallback(() => {
    if (notice === "result" && resultRef.current) {
      const target =
        resultRef.current.querySelector<HTMLElement>(".v2-job-card") ?? resultRef.current;
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setResultHighlighted(true);
      if (highlightTimer.current != null) window.clearTimeout(highlightTimer.current);
      highlightTimer.current = window.setTimeout(() => setResultHighlighted(false), 1800);
    } else {
      const timeline = timelineRef.current;
      if (timeline) timeline.scrollTop = timeline.scrollHeight;
    }
    following.current = true;
    setNotice(null);
  }, [notice, resultRef, timelineRef]);

  return { notice, resultHighlighted, onScroll, followNotice };
}
