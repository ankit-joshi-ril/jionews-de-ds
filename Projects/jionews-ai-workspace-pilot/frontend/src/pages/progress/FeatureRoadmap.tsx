import { mockFeatureProgress, mockActivityFeed } from "../../lib/mockData";
import { TEAM_CONFIG } from "../../lib/constants";
import type { FeatureStage, TeamRole } from "../../lib/types";

export default function FeatureRoadmap() {
  return (
    <div className="p-6 space-y-8 animate-fade-in">
      <div>
        <h1 className="text-xl font-semibold text-text-primary mb-1">Progress</h1>
        <p className="text-sm text-text-secondary">Cross-team feature progress and activity</p>
      </div>

      {/* Feature flows */}
      <div className="space-y-6">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">Feature Roadmap</h2>
        {mockFeatureProgress.map((feature) => (
          <div key={feature.id} className="card p-5">
            <div className="mb-4">
              <h3 className="text-base font-semibold text-text-primary">{feature.name}</h3>
              <p className="text-xs text-text-secondary">{feature.requirement}</p>
            </div>

            {/* Stage flow */}
            <div className="flex items-center gap-1">
              {feature.stages.map((stage, i) => (
                <StageNode key={i} stage={stage} isLast={i === feature.stages.length - 1} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Activity feed */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">Activity Feed</h2>
        <div className="card divide-y divide-surface-border">
          {mockActivityFeed.map((activity) => {
            const config = TEAM_CONFIG[activity.team];
            return (
              <div key={activity.id} className="flex items-start gap-3 px-4 py-3 hover:bg-surface-hover/50 transition-colors">
                <div
                  className="w-2 h-2 rounded-full mt-1.5 flex-shrink-0"
                  style={{ backgroundColor: config.color }}
                />
                <div className="flex-1">
                  <p className="text-sm text-text-primary">
                    <span className="font-medium" style={{ color: config.color }}>
                      {config.label}
                    </span>{" "}
                    {activity.action}
                  </p>
                  {activity.ticketId && (
                    <span className="text-xs font-mono text-text-muted">#{activity.ticketId}</span>
                  )}
                </div>
                <span className="text-[10px] text-text-muted flex-shrink-0">
                  {new Date(activity.timestamp).toLocaleDateString()}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StageNode({ stage, isLast }: { stage: FeatureStage; isLast: boolean }) {
  const config = TEAM_CONFIG[stage.team as TeamRole];
  const isComplete = stage.status === "completed";
  const isActive = stage.status === "in_progress";

  return (
    <div className="flex items-center flex-1">
      <div className="flex-1">
        <div
          className="relative rounded-lg px-3 py-2.5 border transition-all"
          style={{
            borderColor: isComplete
              ? `${config.color}60`
              : isActive
              ? `${config.color}40`
              : "#2A2A3A",
            backgroundColor: isComplete
              ? `${config.color}10`
              : isActive
              ? `${config.color}05`
              : "transparent",
          }}
        >
          {/* Progress bar */}
          <div
            className="absolute bottom-0 left-0 h-0.5 rounded-b-lg transition-all duration-500"
            style={{
              width: `${stage.completionPercent}%`,
              backgroundColor: config.color,
            }}
          />

          <div className="text-[10px] uppercase tracking-wider font-semibold mb-0.5" style={{ color: config.color }}>
            {config.label}
          </div>
          <div className="text-xs text-text-primary font-medium">{stage.label}</div>
          {stage.assignee && (
            <div className="text-[10px] text-text-muted mt-0.5">{stage.assignee}</div>
          )}
          <div className="text-[10px] text-text-muted mt-0.5">
            {stage.completionPercent}%
          </div>
        </div>
      </div>
      {!isLast && (
        <div className="w-6 flex items-center justify-center flex-shrink-0">
          <div
            className="w-4 h-px"
            style={{ backgroundColor: isComplete ? config.color : "#2A2A3A" }}
          />
        </div>
      )}
    </div>
  );
}
