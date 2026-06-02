import type { Ticket } from "../../lib/types";
import { KANBAN_COLUMNS, STATE_CONFIG } from "../../lib/constants";
import TicketCard from "./TicketCard";

interface KanbanBoardProps {
  tickets: Ticket[];
  onTicketClick: (ticket: Ticket) => void;
}

export default function KanbanBoard({ tickets, onTicketClick }: KanbanBoardProps) {
  return (
    <div className="flex gap-4 overflow-x-auto pb-4 px-6">
      {KANBAN_COLUMNS.map((col) => {
        const colTickets = tickets.filter((t) => t.state === col);
        return (
          <div key={col} className="flex-shrink-0 w-72">
            <div className="flex items-center gap-2 mb-3 px-1">
              <span className={`${STATE_CONFIG[col].className} text-xs`}>{col}</span>
              <span className="text-xs text-text-muted">{colTickets.length}</span>
            </div>
            <div className="space-y-2">
              {colTickets.map((ticket) => (
                <TicketCard key={ticket.id} ticket={ticket} onClick={onTicketClick} />
              ))}
              {colTickets.length === 0 && (
                <div className="border border-dashed border-surface-border rounded-xl p-4 text-center text-xs text-text-muted">
                  No tickets
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
