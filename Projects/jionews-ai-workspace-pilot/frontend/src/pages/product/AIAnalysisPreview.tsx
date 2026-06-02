import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import { mockRequirements } from "../../lib/mockData";
import { TEAM_CONFIG } from "../../lib/constants";
import type { TeamRole } from "../../lib/types";

const TEAM_ORDER: TeamRole[] = ["de", "backend", "frontend", "qa"];

export default function AIAnalysisPreview() {
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(false);

  const requirement = mockRequirements[0];
  const drafts = requirement.ticketDrafts || [];

  const handleCreate = () => {
    setCreating(true);
    setTimeout(() => {
      setCreating(false);
      setCreated(true);
    }, 1500);
  };

  return (
    <div className="p-6 max-w-5xl mx-auto animate-fade-in">
      <button onClick={() => navigate(-1)} className="btn-ghost mb-4">
        <ArrowLeft size={16} /> Back
      </button>

      <div className="flex items-center gap-2 mb-2">
        <Sparkles size={20} className="text-accent-product" />
        <h1 className="text-xl font-semibold text-text-primary">AI Analysis</h1>
      </div>
      <p className="text-sm text-text-secondary mb-6 max-w-2xl">
        "{requirement.description.slice(0, 120)}..."
      </p>

      {/* Dependency flow visualization */}
      <div className="card p-6 mb-6">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
          Dependency Flow
        </h2>
        <div className="flex items-center justify-center gap-2 py-4">
          {TEAM_ORDER.map((team, i) => {
            const config = TEAM_CONFIG[team];
            return (
              <div key={team} className="flex items-center gap-2">
                <div
                  className="flex items-center gap-2 px-4 py-2.5 rounded-xl border transition-all"
                  style={{
                    borderColor: `${config.color}40`,
                    backgroundColor: `${config.color}08`,
                  }}
                >
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: config.color }}
                  />
                  <span className="text-sm font-medium" style={{ color: config.color }}>
                    {config.label}
                  </span>
                </div>
                {i < TEAM_ORDER.length - 1 && (
                  <ArrowRight size={16} className="text-text-muted" />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Ticket drafts */}
      <div className="space-y-4 mb-6">
        <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider">
          Suggested Tickets ({drafts.length})
        </h2>
        {drafts.map((draft, i) => {
          const config = TEAM_CONFIG[draft.team];
          return (
            <div key={i} className="card p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-bold text-white"
                    style={{ backgroundColor: config.color }}
                  >
                    {draft.dependencyOrder}
                  </span>
                  <span className="badge" style={{ backgroundColor: `${config.color}15`, color: config.color }}>
                    {config.label}
                  </span>
                </div>
                <span className="text-xs text-text-muted">
                  Priority: {draft.priority === 2 ? "High" : "Medium"}
                </span>
              </div>
              <input
                type="text"
                defaultValue={draft.title}
                className="input-field font-medium"
              />
              <textarea
                defaultValue={draft.description}
                className="input-field resize-none h-16 text-sm"
              />
            </div>
          );
        })}
      </div>

      {/* CTA */}
      <div className="flex justify-end">
        {created ? (
          <div className="flex items-center gap-2 text-accent-qa animate-slide-up">
            <CheckCircle2 size={20} />
            <span className="font-medium">Tickets created in ADO!</span>
          </div>
        ) : (
          <button
            onClick={handleCreate}
            disabled={creating}
            className="btn-primary text-base px-6 py-3"
          >
            {creating ? (
              <>
                <span className="animate-spin">&#9696;</span> Creating...
              </>
            ) : (
              <>Create Tickets in ADO</>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
