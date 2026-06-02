import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Lightbulb,
  Database,
  Server,
  Monitor,
  ShieldCheck,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  LayoutDashboard,
  User,
} from "lucide-react";
import type { TeamRole } from "../../lib/types";
import { TEAM_CONFIG } from "../../lib/constants";

const ROLE_ICONS: Record<TeamRole, React.ReactNode> = {
  product: <Lightbulb size={20} />,
  de: <Database size={20} />,
  backend: <Server size={20} />,
  frontend: <Monitor size={20} />,
  qa: <ShieldCheck size={20} />,
};

const ROLE_NAV: Record<TeamRole, { label: string; path: string; icon: React.ReactNode }[]> = {
  product: [
    { label: "New Requirement", path: "/product/intake", icon: <Sparkles size={18} /> },
    { label: "My Submissions", path: "/product/submissions", icon: <LayoutDashboard size={18} /> },
  ],
  de: [
    { label: "Dashboard", path: "/de/dashboard", icon: <LayoutDashboard size={18} /> },
  ],
  backend: [
    { label: "Dashboard", path: "/backend/dashboard", icon: <LayoutDashboard size={18} /> },
  ],
  frontend: [
    { label: "Dashboard", path: "/frontend/dashboard", icon: <LayoutDashboard size={18} /> },
  ],
  qa: [
    { label: "Dashboard", path: "/qa/dashboard", icon: <LayoutDashboard size={18} /> },
  ],
};

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [activeRole, setActiveRole] = useState<TeamRole>("de");
  const navigate = useNavigate();
  const location = useLocation();

  const teamColor = TEAM_CONFIG[activeRole].color;

  return (
    <aside
      className={`h-screen flex flex-col bg-surface-raised border-r border-surface-border transition-all duration-300 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-14 border-b border-surface-border">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-de to-accent-backend flex items-center justify-center flex-shrink-0">
          <Sparkles size={18} className="text-white" />
        </div>
        {!collapsed && (
          <span className="font-semibold text-sm text-text-primary whitespace-nowrap">
            JioNews AI
          </span>
        )}
      </div>

      {/* Role Switcher */}
      <div className={`flex flex-col gap-1 p-2 border-b border-surface-border ${collapsed ? "items-center" : ""}`}>
        {(Object.keys(TEAM_CONFIG) as TeamRole[]).map((role) => (
          <button
            key={role}
            onClick={() => {
              setActiveRole(role);
              const firstNav = ROLE_NAV[role][0];
              if (firstNav) navigate(firstNav.path);
            }}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-200 ${
              activeRole === role
                ? "text-text-primary"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-hover"
            } ${collapsed ? "justify-center px-2" : ""}`}
            style={activeRole === role ? { backgroundColor: `${teamColor}15`, color: teamColor } : undefined}
            title={collapsed ? TEAM_CONFIG[role].label : undefined}
          >
            {ROLE_ICONS[role]}
            {!collapsed && <span>{TEAM_CONFIG[role].label}</span>}
          </button>
        ))}
      </div>

      {/* Sub-navigation */}
      <div className="flex-1 overflow-y-auto p-2">
        {ROLE_NAV[activeRole].map((item) => (
          <button
            key={item.path}
            onClick={() => navigate(item.path)}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full transition-all duration-200 ${
              location.pathname === item.path
                ? "bg-surface-hover text-text-primary"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            } ${collapsed ? "justify-center px-2" : ""}`}
            title={collapsed ? item.label : undefined}
          >
            {item.icon}
            {!collapsed && <span>{item.label}</span>}
          </button>
        ))}

        {/* Progress & Settings — global nav */}
        <div className="mt-4 pt-4 border-t border-surface-border flex flex-col gap-1">
          <button
            onClick={() => navigate("/progress")}
            className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full transition-all duration-200 ${
              location.pathname.startsWith("/progress")
                ? "bg-surface-hover text-text-primary"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            } ${collapsed ? "justify-center px-2" : ""}`}
            title={collapsed ? "Progress" : undefined}
          >
            <BarChart3 size={18} />
            {!collapsed && <span>Progress</span>}
          </button>
        </div>
      </div>

      {/* Bottom section */}
      <div className="p-2 border-t border-surface-border flex flex-col gap-1">
        <button
          onClick={() => navigate("/settings")}
          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-all duration-200 ${collapsed ? "justify-center px-2" : ""}`}
        >
          <Settings size={18} />
          {!collapsed && <span>Settings</span>}
        </button>
        <div className={`flex items-center gap-3 px-3 py-2 ${collapsed ? "justify-center px-2" : ""}`}>
          <div className="w-7 h-7 rounded-full bg-accent-de/20 flex items-center justify-center flex-shrink-0">
            <User size={14} className="text-accent-de" />
          </div>
          {!collapsed && (
            <div className="text-xs">
              <div className="text-text-primary font-medium">Ankit Joshi</div>
              <div className="text-text-muted">DE Lead</div>
            </div>
          )}
        </div>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center py-1 text-text-muted hover:text-text-secondary transition-colors"
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
    </aside>
  );
}
