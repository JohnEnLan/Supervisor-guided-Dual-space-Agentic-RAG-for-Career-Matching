import type { MissionChapter } from "./onboardingContent";

type ChapterNavigationProps = {
  activeChapter: number;
  chapters: readonly MissionChapter[];
};

export function ChapterNavigation({
  activeChapter,
  chapters,
}: ChapterNavigationProps) {
  return (
    <nav className="chapter-navigation" aria-label="远征章节">
      <ol>
        {chapters.map((chapter, index) => (
          <li key={chapter.id}>
            <a
              href={`#scene-${chapter.id}`}
              aria-current={index === activeChapter ? "step" : undefined}
            >
              <span>{chapter.number}</span>
              <strong>{chapter.title}</strong>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
