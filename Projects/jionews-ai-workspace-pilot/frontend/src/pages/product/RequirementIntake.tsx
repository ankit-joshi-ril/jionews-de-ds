import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lightbulb, ArrowRight, Sparkles } from "lucide-react";
import { mockRequirements } from "../../lib/mockData";

export default function RequirementIntake() {
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState("");
  const [showSuggestion, setShowSuggestion] = useState(false);

  const handleProceed = () => {
    if (requirement.trim()) {
      navigate("/product/analysis-preview");
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-[calc(100vh-3.5rem)] p-6 animate-fade-in">
      {/* Hero area */}
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-text-primary mb-2">
            What would you like to build?
          </h1>
          <p className="text-text-secondary">
            Describe your requirement, feature, or bug — AI will analyze and create tickets
          </p>
        </div>

        {/* Prompt area */}
        <div className="relative">
          <div className="relative card overflow-hidden">
            {/* Glow border effect */}
            <div className="absolute inset-0 rounded-xl opacity-0 transition-opacity duration-500 focus-within:opacity-100 pointer-events-none"
              style={{
                background: "linear-gradient(135deg, #06B6D4, #8B5CF6, #F59E0B)",
                padding: "1px",
                mask: "linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)",
                maskComposite: "xor",
                WebkitMaskComposite: "xor",
              }}
            />
            <textarea
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="e.g., We need to support Odia language video summaries for JioBharat, auto-generated from video transcripts using Gemini..."
              className="w-full bg-transparent px-6 py-5 text-text-primary placeholder:text-text-muted text-base resize-none focus:outline-none min-h-[160px]"
            />
            <div className="flex items-center justify-between px-4 py-3 border-t border-surface-border">
              {/* AI suggestion button */}
              <button
                onClick={() => setShowSuggestion(!showSuggestion)}
                className={`btn-ghost text-xs ${showSuggestion ? "text-accent-product" : ""}`}
              >
                <Lightbulb size={14} /> AI Suggestions
              </button>
              <button
                onClick={handleProceed}
                disabled={!requirement.trim()}
                className="btn-primary disabled:opacity-30 disabled:cursor-not-allowed"
              >
                Proceed <ArrowRight size={16} />
              </button>
            </div>
          </div>

          {/* AI suggestion panel */}
          {showSuggestion && (
            <div className="card mt-3 p-4 animate-slide-up">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles size={14} className="text-accent-product" />
                <span className="text-xs font-semibold text-text-primary">AI Suggestions</span>
              </div>
              <div className="space-y-2">
                {[
                  "Consider specifying the target languages and content types",
                  "Include any performance requirements or SLA expectations",
                  "Mention any dependencies on existing pipelines or APIs",
                ].map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-text-secondary">
                    <span className="text-accent-product mt-0.5">&#8226;</span>
                    <span>{s}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Recent submissions */}
        <div className="mt-12">
          <h2 className="text-sm font-semibold text-text-secondary mb-4">Recent Submissions</h2>
          <div className="space-y-2">
            {mockRequirements.slice(0, 3).map((req) => (
              <div key={req.id} className="card-hover p-4 cursor-pointer">
                <div className="flex items-center justify-between mb-1">
                  <span className={`badge ${
                    req.status === "Draft" ? "badge-todo" :
                    req.status === "Tickets Created" ? "badge-in-progress" :
                    req.status === "In Progress" ? "badge-in-progress" :
                    "badge-done"
                  }`}>
                    {req.status}
                  </span>
                  <span className="text-[10px] text-text-muted">{req.submittedBy}</span>
                </div>
                <p className="text-sm text-text-primary line-clamp-1">{req.description}</p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
