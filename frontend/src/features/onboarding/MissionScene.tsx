import { forwardRef, type ReactNode } from "react";

import type { MissionChapter } from "./onboardingContent";

type MissionSceneProps = {
  chapter: MissionChapter;
  index: number;
  children?: ReactNode;
};

export const MissionScene = forwardRef<HTMLElement, MissionSceneProps>(
  function MissionScene({ chapter, index, children }, ref) {
    return (
      <section
        ref={ref}
        id={`scene-${chapter.id}`}
        className="mission-scene"
        data-scene={chapter.id}
        data-scene-index={index}
        aria-labelledby={`scene-title-${chapter.id}`}
        role="region"
      >
        <p className="mission-number" aria-hidden="true">
          {chapter.number}
        </p>
        <p className="mission-eyebrow">{chapter.eyebrow}</p>
        <h2 id={`scene-title-${chapter.id}`}>{chapter.title}</h2>
        <p className="mission-body">{chapter.body}</p>
        <p className="mission-coordinate">{chapter.coordinate}</p>
        {children}
      </section>
    );
  },
);
