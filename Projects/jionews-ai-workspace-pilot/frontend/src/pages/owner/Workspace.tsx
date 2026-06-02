import { useState, useRef, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  Send,
  Database,
  Globe,
  Code,
  CheckCircle2,
  XCircle,
  Loader2,
  FileText,

  BookOpen,
  Sparkles,
} from "lucide-react";
import { mockTicketsDE } from "../../lib/mockData";
import type { ChatMessage, ToolCall } from "../../lib/types";

const DEMO_CONVERSATION: ChatMessage[] = [
  {
    id: "m1",
    role: "assistant",
    content:
      "I've loaded the context for **Ticket #48201** — Telugu headlines feed failing with 403 errors. I've already reviewed the knowledge base docs for the `headlines-ingestion` pipeline.\n\nLet me start by examining the feed fetcher code to understand the current HTTP header configuration.",
    timestamp: "2026-04-08T15:00:00+05:30",
    toolCalls: [
      {
        id: "tc1",
        name: "get_pipeline_doc",
        params: { pipeline: "headlines-ingestion", doc_type: "tech_spec" },
        result: "Loaded TECH-SPEC.md (287 lines) — feed fetcher uses httpx with default headers",
        status: "complete",
        category: "kb",
      },
      {
        id: "tc2",
        name: "read_file",
        params: { path: "Headlines Ingestion/newrawheadlinesingestion-fetchheadlines.py" },
        result: "Read file (142 lines) — HTTP headers defined at line 23",
        status: "complete",
        category: "code",
      },
    ],
  },
  {
    id: "m2",
    role: "assistant",
    content:
      "Found it. The feed fetcher at `fetchheadlines.py:23` uses a bare `httpx.AsyncClient()` with no custom User-Agent header. The partner ABN Andhra Jyothi has likely added bot protection that blocks requests without a browser-like UA.\n\n**Proposed fix:**\n1. Add a configurable `user_agent` field to the partner YAML config\n2. Update the HTTP client to use partner-specific headers\n3. Add a fallback retry with an alternate UA on 403 responses\n\nI'd like to make these changes. Here's the first one:",
    timestamp: "2026-04-08T15:01:00+05:30",
    approval: {
      id: "apr1",
      action: "propose_edit",
      description: "Add User-Agent header to feed fetcher HTTP client",
      details: {
        file: "Headlines Ingestion/newrawheadlinesingestion-fetchheadlines.py",
        change: "Add DEFAULT_UA and partner-specific UA configuration to httpx client headers",
      },
      status: "pending",
    },
  },
];

export default function Workspace() {
  const { ticketId } = useParams();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>(DEMO_CONVERSATION);
  const [input, setInput] = useState("");
  const [activeTab, setActiveTab] = useState<"ticket" | "files" | "diff" | "knowledge">("ticket");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const ticket = mockTicketsDE.find((t) => t.id === Number(ticketId));

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim()) return;
    const userMsg: ChatMessage = {
      id: `m${messages.length + 1}`,
      role: "user",
      content: input,
      timestamp: new Date().toISOString(),
    };
    setMessages([...messages, userMsg]);
    setInput("");
  };

  const handleApproval = (msgId: string, approved: boolean) => {
    setMessages((msgs) =>
      msgs.map((m) =>
        m.id === msgId && m.approval
          ? { ...m, approval: { ...m.approval, status: approved ? "approved" : "rejected" } }
          : m
      )
    );
  };

  return (
    <div className="h-full flex flex-col animate-fade-in">
      {/* Header bar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-surface-border bg-surface-raised">
        <button onClick={() => navigate(-1)} className="btn-ghost py-1 px-2">
          <ArrowLeft size={14} />
        </button>
        <Sparkles size={16} className="text-accent-de" />
        <span className="text-sm font-medium text-text-primary">AI Workspace</span>
        <span className="text-xs text-text-muted">#{ticketId}</span>
        <div className="flex-1" />
        <span className="text-[10px] text-text-muted font-mono">Tokens: 4,512 in / 2,108 out</span>
      </div>

      {/* Split pane */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Conversation */}
        <div className="w-[45%] flex flex-col border-r border-surface-border">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} onApproval={handleApproval} />
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-surface-border">
            <div className="flex gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSend();
                }}
                placeholder="Ask the AI to analyze, fix, or implement..."
                className="input-field resize-none h-10 flex-1"
                rows={1}
              />
              <button onClick={handleSend} className="btn-primary px-3">
                <Send size={16} />
              </button>
            </div>
            <div className="text-[10px] text-text-muted mt-1">Ctrl+Enter to send</div>
          </div>
        </div>

        {/* Right: Context panel */}
        <div className="flex-1 flex flex-col">
          {/* Tabs */}
          <div className="flex border-b border-surface-border">
            {(["ticket", "files", "diff", "knowledge"] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors ${
                  activeTab === tab
                    ? "text-text-primary border-b-2 border-accent-de"
                    : "text-text-muted hover:text-text-secondary"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto p-4">
            {activeTab === "ticket" && ticket && (
              <div className="space-y-4 animate-fade-in">
                <div>
                  <h3 className="text-sm font-semibold text-text-primary mb-1">#{ticket.id}</h3>
                  <p className="text-base font-medium text-text-primary">{ticket.title}</p>
                </div>
                <div className="text-sm text-text-secondary leading-relaxed">{ticket.description}</div>
                <div className="flex gap-2 flex-wrap">
                  {ticket.tags.map((tag) => (
                    <span key={tag} className="badge bg-surface-overlay text-text-secondary">{tag}</span>
                  ))}
                </div>
              </div>
            )}
            {activeTab === "files" && (
              <div className="space-y-2 animate-fade-in">
                <div className="text-xs text-text-muted mb-3">Files referenced in this session</div>
                {["Headlines Ingestion/newrawheadlinesingestion-fetchheadlines.py", "Headlines Ingestion/config/partners.yaml"].map((f) => (
                  <div key={f} className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-surface-hover cursor-pointer transition-colors">
                    <FileText size={14} className="text-text-muted" />
                    <span className="text-sm font-mono text-text-secondary">{f}</span>
                  </div>
                ))}
              </div>
            )}
            {activeTab === "diff" && (
              <div className="animate-fade-in">
                <div className="text-xs text-text-muted mb-3">Proposed changes</div>
                <div className="bg-surface rounded-lg p-4 font-mono text-xs overflow-x-auto">
                  <div className="text-text-muted mb-2">--- a/fetchheadlines.py</div>
                  <div className="text-text-muted mb-3">+++ b/fetchheadlines.py</div>
                  <div className="text-text-secondary">@@ -20,6 +20,12 @@</div>
                  <div className="text-text-secondary"> import httpx</div>
                  <div className="text-text-secondary"> import asyncio</div>
                  <div className="text-text-secondary"> </div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+DEFAULT_UA = "Mozilla/5.0 (compatible; JioNewsBot/1.0)"</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+def get_headers(partner_config):</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+    ua = partner_config.get("user_agent", DEFAULT_UA)</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+    return {"{"}\"User-Agent\": ua{"}"}</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+</div>
                  <div className="text-text-secondary"> async def fetch_feed(url, config):</div>
                  <div className="text-accent-frontend bg-accent-frontend/5 px-2 -mx-2">-    async with httpx.AsyncClient() as client:</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+    headers = get_headers(config)</div>
                  <div className="text-accent-qa bg-accent-qa/5 px-2 -mx-2">+    async with httpx.AsyncClient(headers=headers) as client:</div>
                </div>
              </div>
            )}
            {activeTab === "knowledge" && (
              <div className="space-y-3 animate-fade-in">
                <div className="text-xs text-text-muted mb-3">Knowledge base docs loaded</div>
                {["headlines-ingestion/TECH-SPEC.md", "headlines-ingestion/ARCHITECTURE.md", "shared/infrastructure/PUBSUB-REGISTRY.md"].map((doc) => (
                  <div key={doc} className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-surface-hover cursor-pointer transition-colors">
                    <BookOpen size={14} className="text-accent-de" />
                    <span className="text-sm font-mono text-text-secondary">{doc}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  onApproval,
}: {
  message: ChatMessage;
  onApproval: (msgId: string, approved: boolean) => void;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[90%] rounded-xl px-4 py-3 ${
          isUser
            ? "bg-accent-de/10 text-text-primary"
            : "bg-surface-overlay text-text-primary"
        }`}
      >
        {/* Tool calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-1.5 mb-3">
            {message.toolCalls.map((tc) => (
              <ToolCallBadge key={tc.id} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Content */}
        <div className="text-sm leading-relaxed whitespace-pre-wrap">
          {message.content.split("**").map((part, i) =>
            i % 2 === 1 ? (
              <strong key={i} className="font-semibold">{part}</strong>
            ) : (
              <span key={i}>{part}</span>
            )
          )}
        </div>

        {/* Approval card */}
        {message.approval && (
          <div className="mt-3 card p-3 border-accent-de/30">
            <div className="flex items-center gap-2 mb-2">
              <Code size={14} className="text-accent-de" />
              <span className="text-xs font-semibold text-text-primary">{message.approval.action}</span>
            </div>
            <p className="text-xs text-text-secondary mb-3">{message.approval.description}</p>
            {message.approval.status === "pending" ? (
              <div className="flex gap-2">
                <button
                  onClick={() => onApproval(message.id, true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-qa/10 text-accent-qa text-xs font-medium hover:bg-accent-qa/20 transition-colors"
                >
                  <CheckCircle2 size={14} /> Approve
                </button>
                <button
                  onClick={() => onApproval(message.id, false)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-frontend/10 text-accent-frontend text-xs font-medium hover:bg-accent-frontend/20 transition-colors"
                >
                  <XCircle size={14} /> Reject
                </button>
              </div>
            ) : (
              <span
                className={`badge ${
                  message.approval.status === "approved"
                    ? "bg-accent-qa/20 text-accent-qa"
                    : "bg-accent-frontend/20 text-accent-frontend"
                }`}
              >
                {message.approval.status === "approved" ? "Approved" : "Rejected"}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolCallBadge({ toolCall }: { toolCall: ToolCall }) {
  const CATEGORY_COLORS: Record<string, string> = {
    kb: "bg-accent-de/10 text-accent-de border-accent-de/20",
    ado: "bg-accent-product/10 text-accent-product border-accent-product/20",
    code: "bg-accent-qa/10 text-accent-qa border-accent-qa/20",
  };
  const CATEGORY_ICONS: Record<string, React.ReactNode> = {
    kb: <Database size={10} />,
    ado: <Globe size={10} />,
    code: <Code size={10} />,
  };

  return (
    <div className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-[10px] font-mono ${CATEGORY_COLORS[toolCall.category]}`}>
      {CATEGORY_ICONS[toolCall.category]}
      <span>{toolCall.name}</span>
      {toolCall.status === "running" && <Loader2 size={10} className="animate-spin" />}
      {toolCall.status === "complete" && <CheckCircle2 size={10} />}
    </div>
  );
}
