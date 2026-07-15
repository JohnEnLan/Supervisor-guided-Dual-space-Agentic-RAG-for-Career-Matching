type CareerConstellationProps = {
  activeChapter: number;
};

const SIGNALS = [
  { x: 92, y: 356, label: "ORIGIN" },
  { x: 188, y: 272, label: "FILTER" },
  { x: 278, y: 392, label: "RESUME EVIDENCE" },
  { x: 374, y: 238, label: "INTENT" },
  { x: 472, y: 354, label: "AGENT FLEET" },
  { x: 574, y: 246, label: "DUAL SPACE" },
  { x: 674, y: 356, label: "EVIDENCE OATH" },
] as const;

const ROUTE =
  "M92 356 C138 350 150 282 188 272 S246 378 278 392 S340 250 374 238 S438 326 472 354 S536 270 574 246 S632 326 674 356";

export function CareerConstellation({
  activeChapter,
}: CareerConstellationProps) {
  const boundedChapter = Math.min(
    SIGNALS.length - 1,
    Math.max(0, activeChapter),
  );
  const routeProgress = (boundedChapter + 1) / SIGNALS.length;

  return (
    <figure
      className="career-constellation"
      data-chapter={boundedChapter + 1}
      aria-label="职业证据星图，随远征章节逐步完成"
    >
      <svg
        viewBox="0 0 760 620"
        role="img"
        aria-labelledby="constellation-title constellation-desc"
      >
        <title id="constellation-title">职业证据星图</title>
        <desc id="constellation-desc">
          从简历证据出发，经过目标校准、Agent
          协作和双空间安全门，抵达可解释结果。
        </desc>
        <path
          className="constellation-route route-ghost"
          d={ROUTE}
          pathLength="1"
        />
        <path
          className="constellation-route route-active"
          d={ROUTE}
          pathLength="1"
          style={{ strokeDasharray: `${routeProgress} 1` }}
        />
        {SIGNALS.map((signal, index) => (
          <g
            key={signal.label}
            className={`constellation-signal${
              index <= boundedChapter ? " is-active" : ""
            }`}
            data-activation={index + 1}
            transform={`translate(${signal.x} ${signal.y})`}
          >
            <circle r={index === boundedChapter ? 11 : 7} />
            <circle className="signal-halo" r="22" />
            <text y={index % 2 === 0 ? 42 : -30} textAnchor="middle">
              {signal.label}
            </text>
          </g>
        ))}
        <g
          className={`supervisor-gate${
            boundedChapter >= 5 ? " is-active" : ""
          }`}
          transform="translate(618 356)"
        >
          <rect x="-32" y="-54" width="64" height="108" rx="32" />
          <text y="76" textAnchor="middle">
            SUPERVISOR GATE
          </text>
        </g>
      </svg>
      <figcaption>CAREER COORDINATES / EVIDENCE-GROUNDED</figcaption>
    </figure>
  );
}
