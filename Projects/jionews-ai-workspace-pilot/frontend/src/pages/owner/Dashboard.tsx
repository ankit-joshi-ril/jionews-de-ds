import { useState, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Bug, Clock, AlertTriangle, CheckCircle2 } from "lucide-react";
import type { Ticket, TicketState, TicketType, TeamRole } from "../../lib/types";
import { TEAM_CONFIG } from "../../lib/constants";
import { mockTicketsDE, mockTicketsBE, mockTicketsFE, mockTicketsQA } from "../../lib/mockData";
import TicketTable from "../../components/tickets/TicketTable";
import KanbanBoard from "../../components/tickets/KanbanBoard";
import TicketFilters from "../../components/tickets/TicketFilters";

const TEAM_TICKETS: Record<string, Ticket[]> = {
  de: mockTicketsDE,
  backend: mockTicketsBE,
  frontend: mockTicketsFE,
  qa: mockTicketsQA,
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { team } = useParams<{ team: string }>();
  const teamRole = (team || "de") as TeamRole;
  const teamConfig = TEAM_CONFIG[teamRole];

  const [viewMode, setViewMode] = useState<"table" | "kanban">("table");
  const [stateFilter, setStateFilter] = useState<TicketState | "All">("All");
  const [typeFilter, setTypeFilter] = useState<TicketType | "All">("All");
  const [searchQuery, setSearchQuery] = useState("");

  const allTickets = TEAM_TICKETS[teamRole] || [];

  const filteredTickets = useMemo(() => {
    return allTickets.filter((t) => {
      if (stateFilter !== "All" && t.state !== stateFilter) return false;
      if (typeFilter !== "All" && t.type !== typeFilter) return false;
      if (searchQuery && !t.title.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [allTickets, stateFilter, typeFilter, searchQuery]);

  const stats = useMemo(() => {
    const open = allTickets.filter((t) => t.state !== "Done" && t.state !== "Closed").length;
    const bugs = allTickets.filter((t) => t.type === "Bug").length;
    const inProgress = allTickets.filter((t) => t.state === "In Progress").length;
    const critical = allTickets.filter((t) => t.priority === 1).length;
    return { open, bugs, inProgress, critical };
  }, [allTickets]);

  const handleTicketClick = (ticket: Ticket) => {
    navigate(`/${teamRole}/ticket/${ticket.id}`);
  };

  const handleAnalyze = (ticket: Ticket) => {
    navigate(`/${teamRole}/ticket/${ticket.id}/analyze`);
  };

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-text-primary">
          {teamConfig.label} Dashboard
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          Manage your team's tickets and track progress
        </p>
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={<Clock size={18} />} label="Open" value={stats.open} color="text-accent-de" />
        <StatCard icon={<Bug size={18} />} label="Bugs" value={stats.bugs} color="text-accent-frontend" />
        <StatCard icon={<AlertTriangle size={18} />} label="In Progress" value={stats.inProgress} color="text-accent-product" />
        <StatCard icon={<CheckCircle2 size={18} />} label="Critical" value={stats.critical} color="text-red-400" />
      </div>

      {/* Filters */}
      <TicketFilters
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        stateFilter={stateFilter}
        onStateFilterChange={setStateFilter}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
      />

      {/* Tickets */}
      <div className="card overflow-hidden">
        {viewMode === "table" ? (
          <TicketTable
            tickets={filteredTickets}
            onTicketClick={handleTicketClick}
            onAnalyze={teamRole === "de" ? handleAnalyze : undefined}
          />
        ) : (
          <div className="py-4">
            <KanbanBoard tickets={filteredTickets} onTicketClick={handleTicketClick} />
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div className="card p-4 flex items-center gap-3">
      <div className={`${color} opacity-70`}>{icon}</div>
      <div>
        <div className="text-xl font-semibold text-text-primary">{value}</div>
        <div className="text-xs text-text-muted">{label}</div>
      </div>
    </div>
  );
}
