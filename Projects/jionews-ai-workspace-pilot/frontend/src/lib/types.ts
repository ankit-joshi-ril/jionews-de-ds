export type TeamRole = "product" | "de" | "backend" | "frontend" | "qa";

export type TicketState =
  | "To Do"
  | "In Progress"
  | "Dev Complete"
  | "Ready for QA"
  | "Done"
  | "Closed";

export type TicketType = "Bug" | "User Story" | "Task" | "Feature";

export type Priority = 1 | 2 | 3 | 4;

export interface Ticket {
  id: number;
  title: string;
  state: TicketState;
  type: TicketType;
  priority: Priority;
  assignedTo: string;
  areaPath: string;
  iterationPath: string;
  description: string;
  tags: string[];
  createdDate: string;
  changedDate: string;
}

export interface AnalysisResult {
  ticketId: number;
  affectedPipelines: string[];
  rootCause: string;
  suggestedFix: string;
  affectedFiles: string[];
  riskLevel: "Low" | "Medium" | "High";
  estimatedEffort: string;
  cached: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  toolCalls?: ToolCall[];
  approval?: ApprovalRequest;
}

export interface ToolCall {
  id: string;
  name: string;
  params: Record<string, unknown>;
  result?: string;
  status: "running" | "complete" | "error";
  category: "kb" | "ado" | "code";
}

export interface ApprovalRequest {
  id: string;
  action: string;
  description: string;
  details: Record<string, unknown>;
  status: "pending" | "approved" | "rejected";
}

export interface Notification {
  id: string;
  type: "unblocked" | "assigned" | "comment" | "completed";
  title: string;
  description: string;
  ticketId?: number;
  timestamp: string;
  read: boolean;
}

export interface Requirement {
  id: string;
  description: string;
  status: "Draft" | "Tickets Created" | "In Progress" | "Completed";
  submittedBy: string;
  submittedAt: string;
  ticketDrafts?: TicketDraft[];
}

export interface TicketDraft {
  team: TeamRole;
  title: string;
  description: string;
  priority: Priority;
  dependencyOrder: number;
}

export interface FeatureProgress {
  id: string;
  name: string;
  requirement: string;
  stages: FeatureStage[];
}

export interface FeatureStage {
  team: TeamRole;
  label: string;
  status: "not_started" | "in_progress" | "completed";
  ticketId?: number;
  assignee?: string;
  completionPercent: number;
}

export interface ActivityItem {
  id: string;
  team: TeamRole;
  action: string;
  ticketId?: number;
  featureId?: string;
  timestamp: string;
}
