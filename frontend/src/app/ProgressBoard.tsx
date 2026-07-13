export const FLOW_STAGES = [
  { key: "resume", label: "简历确认", short: "简历" },
  { key: "intent", label: "目标咨询", short: "目标" },
  { key: "retrieval", label: "检索匹配", short: "检索" },
  { key: "strategy", label: "职业策略", short: "策略" },
  { key: "verification", label: "监督核查", short: "核查" },
  { key: "finalization", label: "结果整理", short: "整理" },
  { key: "result", label: "查看结果", short: "结果" },
] as const;

export type FlowStage = (typeof FLOW_STAGES)[number]["key"];

type ProgressBoardProps = {
  completedStages: string[];
  activeStage?: string | null;
  totalStages?: number;
};

function stagePosition(activeStage: string | null | undefined): number {
  const index = FLOW_STAGES.findIndex((stage) => stage.key === activeStage);
  return index < 0 ? 1 : index + 1;
}

export function ProgressBoard({
  completedStages,
  activeStage,
  totalStages = FLOW_STAGES.length,
}: ProgressBoardProps) {
  const current = stagePosition(activeStage);
  const summary = `第 ${current}/${totalStages} 阶段`;

  return (
    <section className="progress-board" aria-labelledby="flow-progress-title">
      <div className="progress-heading">
        <div>
          <p className="eyebrow">完整流程</p>
          <h2 id="flow-progress-title">任务进度板</h2>
        </div>
        <span className="stage-count">{summary}</span>
      </div>
      <ol className="progress-steps" aria-label="职业匹配流程进度">
        {FLOW_STAGES.map((stage, index) => {
          const isComplete = completedStages.includes(stage.key);
          const isActive = activeStage === stage.key;
          return (
            <li
              key={stage.key}
              data-state={isComplete ? "complete" : isActive ? "active" : "pending"}
            >
              <span className="step-marker" aria-hidden="true">
                {isComplete ? "✓" : index + 1}
              </span>
              <span aria-current={isActive ? "step" : undefined}>{stage.label}</span>
            </li>
          );
        })}
      </ol>
      <details className="progress-compact">
        <summary>{summary}</summary>
        <ol>
          {FLOW_STAGES.map((stage) => (
            <li key={stage.key}>{stage.label}</li>
          ))}
        </ol>
      </details>
    </section>
  );
}
