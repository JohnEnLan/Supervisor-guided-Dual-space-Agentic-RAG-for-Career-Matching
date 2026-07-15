import { useEffect, useRef } from "react";

export const POINTER_PARTICLE_COUNT = 18;

const TRAIL_IDLE_MS = 420;

type Point = {
  x: number;
  y: number;
};

export function PointerComet() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const finePointer = window.matchMedia("(pointer: fine)").matches;
    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (!finePointer || reducedMotion || !rootRef.current) {
      return;
    }

    const particles = Array.from(
      rootRef.current.querySelectorAll<HTMLElement>(
        ".pointer-comet-particle",
      ),
    );
    const points: Point[] = Array.from(
      { length: POINTER_PARTICLE_COUNT },
      () => ({ x: -40, y: -40 }),
    );
    let target: Point = { x: -40, y: -40 };
    let lastMoveAt = 0;
    let frame: number | null = null;

    const hide = () => {
      particles.forEach((particle) => {
        particle.style.opacity = "0";
      });
    };

    const stop = () => {
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
      }
      frame = null;
      hide();
    };

    const tick = (now: number) => {
      points[0].x += (target.x - points[0].x) * 0.42;
      points[0].y += (target.y - points[0].y) * 0.42;

      for (let index = 1; index < points.length; index += 1) {
        points[index].x +=
          (points[index - 1].x - points[index].x) * 0.34;
        points[index].y +=
          (points[index - 1].y - points[index].y) * 0.34;
      }

      particles.forEach((particle, index) => {
        const scale = 1 - index / (POINTER_PARTICLE_COUNT * 1.25);
        particle.style.transform = `translate3d(${points[index].x}px, ${points[index].y}px, 0) scale(${scale})`;
        particle.style.opacity = String(Math.max(0, 0.72 - index * 0.035));
      });

      if (now - lastMoveAt >= TRAIL_IDLE_MS || document.hidden) {
        stop();
        return;
      }
      frame = window.requestAnimationFrame(tick);
    };

    const onPointerMove = (event: PointerEvent) => {
      target = { x: event.clientX, y: event.clientY };
      lastMoveAt = performance.now();
      if (frame === null) {
        frame = window.requestAnimationFrame(tick);
      }
    };

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("blur", stop);
    document.addEventListener("visibilitychange", stop);

    return () => {
      stop();
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("blur", stop);
      document.removeEventListener("visibilitychange", stop);
    };
  }, []);

  return (
    <div
      ref={rootRef}
      className="pointer-comet"
      data-testid="pointer-comet"
      aria-hidden="true"
      style={{ pointerEvents: "none" }}
    >
      {Array.from({ length: POINTER_PARTICLE_COUNT }, (_, index) => (
        <span
          key={index}
          className="pointer-comet-particle"
          data-particle={index}
        />
      ))}
    </div>
  );
}
