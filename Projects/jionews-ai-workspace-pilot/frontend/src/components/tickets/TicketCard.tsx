import { Bug, BookOpen, CheckSquare, Zap } from "lucide-react";
import type { Ticket, TicketType } from "../../lib/types";
import { PRIORITY_CONFIG } from "../../lib/constants";

const TYPE_ICONS: Record<TicketType, React.ReactNode> = {
  Bug: <Bug size={12} className="text-accent-frontend" />,
  "User Story": <BookOpen size={12} className="text-accent-de" />,
  Task: <CheckSquare size={12} className="text-accent-backend" />,
  Feature: <Zap size={12} className="text-accent-product" />,
};

interface TicketCardProps {
  ticket: Ticket;
  onClick: (ticket: Ticket) => void;
}

export default function TicketCard({ ticket, onClick }: TicketCardProps) {
  return (
    <div
      onClick={() => onClick(ticket)}
      className="card-hover p-3 cursor-pointer space-y-2"
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-mono text-text-muted">#{ticket.id}</span>
        <span className={`w-2 h-2 rounded-full ${PRIORITY_CONFIG[ticket.priority].dotColor}`} />
      </div>
      <p className="text-sm text-text-primary font-medium leading-tight line-clamp-2">
        {ticket.title}
      </p>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-[10px] text-text-muted">
          {TYPE_ICONS[ticket.type]}
          {ticket.type}
        </span>
        <span className="text-[10px] text-text-muted">{ticket.assignedTo.split(" ")[0]}</span>
      </div>
    </div>
  );
}
