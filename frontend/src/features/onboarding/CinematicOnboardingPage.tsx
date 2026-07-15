import { ArrowDown, ArrowRight, BriefcaseBusiness } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import "../../styles/onboarding-cinematic.css";
import { CareerConstellation } from "./CareerConstellation";
import { ChapterNavigation } from "./ChapterNavigation";
import { MissionScene } from "./MissionScene";
import { EXPEDITION_CHAPTERS } from "./onboardingContent";
import { PointerComet } from "./PointerComet";

export function CinematicOnboardingPage() {
  const [activeChapter, setActiveChapter] = useState(0);
  const sceneRefs = useRef<Array<HTMLElement | null>>([]);

  useEffect(() => {
    if (!("IntersectionObserver" in window)) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const current = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (left, right) => right.intersectionRatio - left.intersectionRatio,
          )[0];
        const index = current
          ? Number((current.target as HTMLElement).dataset.sceneIndex)
          : Number.NaN;
        if (Number.isInteger(index)) {
          setActiveChapter(index);
        }
      },
      {
        rootMargin: "-28% 0px -42%",
        threshold: [0.2, 0.45, 0.7],
      },
    );

    sceneRefs.current.forEach((scene) => {
      if (scene) {
        observer.observe(scene);
      }
    });

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let frame: number | null = null;

    const update = () => {
      const maximum = Math.max(
        1,
        document.documentElement.scrollHeight - window.innerHeight,
      );
      const progress = Math.min(1, Math.max(0, window.scrollY / maximum));
      document.documentElement.style.setProperty(
        "--expedition-progress",
        progress.toFixed(4),
      );
      frame = null;
    };

    const onScroll = () => {
      if (frame === null) {
        frame = window.requestAnimationFrame(update);
      }
    };

    update();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
      }
      window.removeEventListener("scroll", onScroll);
      document.documentElement.style.removeProperty("--expedition-progress");
    };
  }, []);

  return (
    <main
      className="cinematic-onboarding"
      data-active-chapter={activeChapter + 1}
      data-observer={
        "IntersectionObserver" in window ? "available" : "fallback"
      }
    >
      <PointerComet />

      <header className="expedition-header">
        <span className="expedition-brand">
          <span className="expedition-brand-mark" aria-hidden="true">
            <BriefcaseBusiness size={19} />
          </span>
          <span>
            <strong>Career RAG</strong>
            <small>EVIDENCE EXPEDITION</small>
          </span>
        </span>
        <Link className="expedition-skip" to="/workspace">
          跳过远征
          <ArrowRight size={17} aria-hidden="true" />
        </Link>
      </header>

      <h1 className="expedition-document-title">职业远征</h1>
      <div className="expedition-progress" aria-hidden="true">
        <span />
      </div>
      <ChapterNavigation
        activeChapter={activeChapter}
        chapters={EXPEDITION_CHAPTERS}
      />

      <div className="expedition-stage">
        <div className="constellation-sticky">
          <CareerConstellation activeChapter={activeChapter} />
          <a className="scroll-invitation" href="#scene-fog">
            向下展开航线
            <ArrowDown size={16} aria-hidden="true" />
          </a>
        </div>

        <div className="mission-track">
          {EXPEDITION_CHAPTERS.map((chapter, index) => (
            <MissionScene
              key={chapter.id}
              ref={(node) => {
                sceneRefs.current[index] = node;
              }}
              chapter={chapter}
              index={index}
            >
              {chapter.id === "departure" ? (
                <Link className="departure-cta" to="/workspace">
                  进入职业匹配工作台
                  <ArrowRight size={18} aria-hidden="true" />
                </Link>
              ) : null}
            </MissionScene>
          ))}
        </div>
      </div>

      <p className="chapter-announcement" aria-live="polite">
        第 {activeChapter + 1} 章，共 {EXPEDITION_CHAPTERS.length} 章
      </p>
    </main>
  );
}
