import type { TeamRole, TicketState } from "./types";

export const TEAM_CONFIG: Record<
  TeamRole,
  { label: string; color: string; bgColor: string; icon: string }
> = {
  product: {
    label: "Product",
    color: "#F59E0B",
    bgColor: "bg-accent-product",
    icon: "Lightbulb",
  },
  de: {
    label: "Data Engineering",
    color: "#06B6D4",
    bgColor: "bg-accent-de",
    icon: "Database",
  },
  backend: {
    label: "Backend",
    color: "#8B5CF6",
    bgColor: "bg-accent-backend",
    icon: "Server",
  },
  frontend: {
    label: "Frontend",
    color: "#F43F5E",
    bgColor: "bg-accent-frontend",
    icon: "Monitor",
  },
  qa: {
    label: "QA",
    color: "#10B981",
    bgColor: "bg-accent-qa",
    icon: "ShieldCheck",
  },
};

export const STATE_CONFIG: Record<
  TicketState,
  { label: string; className: string; order: number }
> = {
  "To Do": { label: "To Do", className: "badge-todo", order: 0 },
  "In Progress": {
    label: "In Progress",
    className: "badge-in-progress",
    order: 1,
  },
  "Dev Complete": {
    label: "Dev Complete",
    className: "badge-dev-complete",
    order: 2,
  },
  "Ready for QA": {
    label: "Ready for QA",
    className: "badge-ready-qa",
    order: 3,
  },
  Done: { label: "Done", className: "badge-done", order: 4 },
  Closed: { label: "Closed", className: "badge-done", order: 5 },
};

export const PRIORITY_CONFIG: Record<
  number,
  { label: string; color: string; dotColor: string }
> = {
  1: { label: "Critical", color: "text-red-400", dotColor: "bg-red-400" },
  2: { label: "High", color: "text-orange-400", dotColor: "bg-orange-400" },
  3: { label: "Medium", color: "text-yellow-400", dotColor: "bg-yellow-400" },
  4: { label: "Low", color: "text-text-secondary", dotColor: "bg-text-muted" },
};

export const KANBAN_COLUMNS: TicketState[] = [
  "To Do",
  "In Progress",
  "Dev Complete",
  "Ready for QA",
  "Done",
];

export const API_BASE = "http://localhost:8000/api";
