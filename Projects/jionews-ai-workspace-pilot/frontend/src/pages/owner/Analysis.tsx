import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Sparkles,
  Database,
  AlertTriangle,
  Code,
  FileText,
  Clock,
  Shield,
  Wrench,
} from "lucide-react";
import { mockTicketsDE, mockAnalysisResult } from "../../lib/mockData";
import { AnalysisSkeleton } from "../../components/shared/SkeletonLoader";

const ANALYSIS_STEPS = [
  "Reading ticket details...",
  "Scanning knowledge base for affected pipelines...",
  "Analyzing headlines-ingestion architecture...",
  "Checking database schemas and data specs...",
  "Generating root cause hypothesis...",
  "Formulating fix recommendations...",
];

export default function Analysis() {
  const { team, ticketId } = useParams();
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [showContext, setShowContext] = useState(false);

  const ticket = mockTicketsDE.find((t) => t.id === Number(ticketId));
  const analysis = mockAnalysisResult;

  // Simulate streaming analysis
  useEffect(() => {
    if (currentStep < ANALYSIS_STEPS.length) {
      const timer = setTimeout(() => setCurrentStep((s) => s + 1), 800);
      return () => clearTimeout(timer);
    } else if (!isComplete) {
      const timer = setTimeout(() => setIsComplete(true), 400);
      return () => clearTimeout(timer);
    }
  }, [currentStep, isComplete]);

  if (!ticket) return <div className="p-6 text-text-secondary">Ticket not found</div>;

  return (
    <div className="p-6 max-w-4xl animate-fade-in">
      <button onClick={() => navigate(-1)} className="btn-ghost mb-4">
        <ArrowLeft size={16} /> Back to ticket
      </button>

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles size={20} className="text-accent-de" />
          <h1 className="text-xl font-semibold text-text-primary">AI Analysis</h1>
        </div>
        <p className="text-sm text-text-secondary">
          #{ticket.id} — {ticket.title}
        </p>
      </div>

      {/* Optional context */}
      <button
        onClick={() => setShowContext(!showContext)}
        className="text-xs text-text-muted hover:text-text-secondary mb-4 underline"
      >
        {showContext ? "Hide" : "Add"} context for the AI
      </button>
      {showContext && (
        <textarea
          placeholder="Add any additional context for the analysis..."
          className="input-field mb-4 h-20 resize-none"
        />
      )}

      {/* Progress Steps */}
      {!isComplete && (
        <div className="card p-4 mb-6 space-y-2">
          {ANALYSIS_STEPS.map((step, i) => (
            <div key={i} className="flex items-center gap-3">
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-300 ${
                  i < currentStep
                    ? "bg-accent-de/20 text-accent-de"
                    : i === currentStep
                    ? "bg-accent-de/10 text-accent-de animate-pulse"
                    : "bg-surface-border/30 text-text-muted"
                }`}
              >
                {i < currentStep ? (
                  <span className="text-[10px]">&#10003;</span>
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-current" />
                )}
              </div>
              <span
                className={`text-sm transition-colors duration-300 ${
                  i < currentStep
                    ? "text-text-secondary"
                    : i === currentStep
                    ? "text-text-primary"
                    : "text-text-muted"
                }`}
              >
                {step}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Results */}
      {isComplete ? (
        <div className="space-y-4 animate-slide-up">
          {/* Affected Systems */}
          <ResultSection icon={<Database size={16} />} title="Affected Systems" accentColor="text-accent-de">
            <div className="flex gap-2 flex-wrap">
              {analysis.affectedPipelines.map((p) => (
                <span key={p} className="badge bg-accent-de/10 text-accent-de">{p}</span>
              ))}
            </div>
          </ResultSection>

          {/* Root Cause */}
          <ResultSection icon={<AlertTriangle size={16} />} title="Root Cause" accentColor="text-accent-product">
            <p className="text-sm text-text-primary leading-relaxed">{analysis.rootCause}</p>
          </ResultSection>

          {/* Suggested Fix */}
          <ResultSection icon={<Wrench size={16} />} title="Suggested Fix" accentColor="text-accent-qa">
            <div className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap font-mono bg-surface p-4 rounded-lg">
              {analysis.suggestedFix}
            </div>
          </ResultSection>

          {/* Affected Files */}
          <ResultSection icon={<FileText size={16} />} title="Affected Files" accentColor="text-accent-backend">
            <div className="space-y-1">
              {analysis.affectedFiles.map((f) => (
                <div key={f} className="flex items-center gap-2">
                  <Code size={12} className="text-text-muted" />
                  <span className="text-sm font-mono text-text-secondary">{f}</span>
                </div>
              ))}
            </div>
          </ResultSection>

          {/* Risk & Effort */}
          <div className="grid grid-cols-2 gap-4">
            <ResultSection icon={<Shield size={16} />} title="Risk Assessment" accentColor="text-accent-qa">
              <span className={`badge ${
                analysis.riskLevel === "Low" ? "bg-accent-qa/20 text-accent-qa" :
                analysis.riskLevel === "Medium" ? "bg-accent-product/20 text-accent-product" :
                "bg-accent-frontend/20 text-accent-frontend"
              }`}>
                {analysis.riskLevel}
              </span>
            </ResultSection>
            <ResultSection icon={<Clock size={16} />} title="Estimated Effort" accentColor="text-accent-de">
              <span className="text-sm text-text-primary">{analysis.estimatedEffort}</span>
            </ResultSection>
          </div>

          {/* CTA */}
          <div className="pt-4">
            <button
              onClick={() => navigate(`/${team}/ticket/${ticketId}/workspace`)}
              className="btn-primary text-base px-6 py-3"
            >
              <Sparkles size={18} /> Work on this Ticket
            </button>
          </div>
        </div>
      ) : (
        <AnalysisSkeleton />
      )}
    </div>
  );
}

function ResultSection({
  icon,
  title,
  accentColor,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  accentColor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className={accentColor}>{icon}</span>
        <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
      </div>
      {children}
    </div>
  );
}
