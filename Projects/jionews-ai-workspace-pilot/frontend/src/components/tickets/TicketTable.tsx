import { Bug, BookOpen, CheckSquare, Zap, Sparkles } from "lucide-react";
import type { Ticket, TicketType } from "../../lib/types";
import { STATE_CONFIG, PRIORITY_CONFIG } from "../../lib/constants";

const TYPE_ICONS: Record<TicketType, React.ReactNode> = {
  Bug: <Bug size={14} className="text-accent-frontend" />,
  "User Story": <BookOpen size={14} className="text-accent-de" />,
  Task: <CheckSquare size={14} className="text-accent-backend" />,
  Feature: <Zap size={14} className="text-accent-product" />,
};

interface TicketTableProps {
  tickets: Ticket[];
  onTicketClick: (ticket: Ticket) => void;
  onAnalyze?: (ticket: Ticket) => void;
}

export default function TicketTable({ tickets, onTicketClick, onAnalyze }: TicketTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-surface-border text-left">
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-20">ID</th>
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Title</th>
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-28">Type</th>
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-24">Priority</th>
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-32">State</th>
            <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-36">Assigned To</th>
            <th className="px-4 py-3 w-12"></th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <tr
              key={ticket.id}
              onClick={() => onTicketClick(ticket)}
              className="border-b border-surface-border/50 hover:bg-surface-hover/50 cursor-pointer transition-colors group"
            >
              <td className="px-4 py-3 text-sm font-mono text-text-secondary">#{ticket.id}</td>
              <td className="px-4 py-3 text-sm text-text-primary font-medium">{ticket.title}</td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-1.5 text-xs text-text-secondary">
                  {TYPE_ICONS[ticket.type]}
                  {ticket.type}
                </span>
              </td>
              <td className="px-4 py-3">
                <span className="flex items-center gap-1.5 text-xs">
                  <span className={`w-2 h-2 rounded-full ${PRIORITY_CONFIG[ticket.priority].dotColor}`} />
                  <span className={PRIORITY_CONFIG[ticket.priority].color}>
                    {PRIORITY_CONFIG[ticket.priority].label}
                  </span>
                </span>
              </td>
              <td className="px-4 py-3">
                <span className={STATE_CONFIG[ticket.state].className}>{ticket.state}</span>
              </td>
              <td className="px-4 py-3 text-xs text-text-secondary">{ticket.assignedTo}</td>
              <td className="px-4 py-3">
                {onAnalyze && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onAnalyze(ticket);
                    }}
                    className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-md hover:bg-accent-de/10 text-accent-de"
                    title="Analyze with AI"
                  >
                    <Sparkles size={16} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
