import { Search, List, LayoutGrid } from "lucide-react";
import type { TicketState, TicketType } from "../../lib/types";
import { STATE_CONFIG } from "../../lib/constants";

interface TicketFiltersProps {
  viewMode: "table" | "kanban";
  onViewModeChange: (mode: "table" | "kanban") => void;
  stateFilter: TicketState | "All";
  onStateFilterChange: (state: TicketState | "All") => void;
  typeFilter: TicketType | "All";
  onTypeFilterChange: (type: TicketType | "All") => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export default function TicketFilters({
  viewMode,
  onViewModeChange,
  stateFilter,
  onStateFilterChange,
  typeFilter,
  onTypeFilterChange,
  searchQuery,
  onSearchChange,
}: TicketFiltersProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      {/* View toggle */}
      <div className="flex items-center rounded-lg border border-surface-border overflow-hidden">
        <button
          onClick={() => onViewModeChange("table")}
          className={`p-2 transition-colors ${
            viewMode === "table" ? "bg-surface-hover text-text-primary" : "text-text-muted hover:text-text-secondary"
          }`}
        >
          <List size={16} />
        </button>
        <button
          onClick={() => onViewModeChange("kanban")}
          className={`p-2 transition-colors ${
            viewMode === "kanban" ? "bg-surface-hover text-text-primary" : "text-text-muted hover:text-text-secondary"
          }`}
        >
          <LayoutGrid size={16} />
        </button>
      </div>

      {/* State filter */}
      <select
        value={stateFilter}
        onChange={(e) => onStateFilterChange(e.target.value as TicketState | "All")}
        className="input-field w-auto text-xs"
      >
        <option value="All">All States</option>
        {Object.keys(STATE_CONFIG).map((state) => (
          <option key={state} value={state}>{state}</option>
        ))}
      </select>

      {/* Type filter */}
      <select
        value={typeFilter}
        onChange={(e) => onTypeFilterChange(e.target.value as TicketType | "All")}
        className="input-field w-auto text-xs"
      >
        <option value="All">All Types</option>
        <option value="Bug">Bug</option>
        <option value="User Story">User Story</option>
        <option value="Task">Task</option>
        <option value="Feature">Feature</option>
      </select>

      {/* Search */}
      <div className="relative flex-1 min-w-48">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search tickets..."
          className="input-field pl-8 text-xs"
        />
      </div>
    </div>
  );
}
