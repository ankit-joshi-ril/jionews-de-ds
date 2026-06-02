import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Sparkles, ExternalLink, Clock, Tag } from "lucide-react";
import { mockTicketsDE } from "../../lib/mockData";
import { STATE_CONFIG, PRIORITY_CONFIG } from "../../lib/constants";

export default function TicketDetail() {
  const { team, ticketId } = useParams();
  const navigate = useNavigate();

  const ticket = mockTicketsDE.find((t) => t.id === Number(ticketId));

  if (!ticket) {
    return (
      <div className="p-6">
        <p className="text-text-secondary">Ticket not found</p>
      </div>
    );
  }

  return (
    <div className="p-6 animate-fade-in">
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="btn-ghost mb-4"
      >
        <ArrowLeft size={16} /> Back
      </button>

      <div className="grid grid-cols-3 gap-6">
        {/* Main content */}
        <div className="col-span-2 space-y-6">
          {/* Header */}
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="text-sm font-mono text-text-muted">#{ticket.id}</span>
              <span className={STATE_CONFIG[ticket.state].className}>{ticket.state}</span>
            </div>
            <h1 className="text-2xl font-semibold text-text-primary">{ticket.title}</h1>
          </div>

          {/* CTA */}
          <div className="flex gap-3">
            <button
              onClick={() => navigate(`/${team}/ticket/${ticket.id}/analyze`)}
              className="btn-primary text-base px-6 py-3"
            >
              <Sparkles size={18} /> Analyze with AI
            </button>
            <button className="btn-ghost">
              <ExternalLink size={16} /> Open in ADO
            </button>
          </div>

          {/* Description */}
          <div className="card p-6">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-3">Description</h2>
            <p className="text-sm text-text-primary leading-relaxed whitespace-pre-wrap">
              {ticket.description}
            </p>
          </div>

          {/* Tags */}
          {ticket.tags.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <Tag size={14} className="text-text-muted" />
              {ticket.tags.map((tag) => (
                <span key={tag} className="badge bg-surface-overlay text-text-secondary">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Sidebar metadata */}
        <div className="space-y-4">
          <div className="card p-4 space-y-4">
            <MetaItem label="Priority">
              <span className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${PRIORITY_CONFIG[ticket.priority].dotColor}`} />
                <span className={`text-sm ${PRIORITY_CONFIG[ticket.priority].color}`}>
                  {PRIORITY_CONFIG[ticket.priority].label}
                </span>
              </span>
            </MetaItem>
            <MetaItem label="Type">
              <span className="text-sm text-text-primary">{ticket.type}</span>
            </MetaItem>
            <MetaItem label="Assigned To">
              <span className="text-sm text-text-primary">{ticket.assignedTo}</span>
            </MetaItem>
            <MetaItem label="Sprint">
              <span className="text-sm text-text-primary">{ticket.iterationPath}</span>
            </MetaItem>
            <MetaItem label="Area Path">
              <span className="text-xs text-text-secondary font-mono">{ticket.areaPath}</span>
            </MetaItem>
          </div>

          <div className="card p-4 space-y-3">
            <MetaItem label="Created">
              <span className="flex items-center gap-1.5 text-xs text-text-secondary">
                <Clock size={12} />
                {new Date(ticket.createdDate).toLocaleDateString()}
              </span>
            </MetaItem>
            <MetaItem label="Last Updated">
              <span className="flex items-center gap-1.5 text-xs text-text-secondary">
                <Clock size={12} />
                {new Date(ticket.changedDate).toLocaleDateString()}
              </span>
            </MetaItem>
          </div>
        </div>
      </div>
    </div>
  );
}

function MetaItem({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-text-muted font-semibold mb-1">{label}</div>
      {children}
    </div>
  );
}
