import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Search, Bell, Command } from "lucide-react";
import NotificationPanel from "./NotificationPanel";

const BREADCRUMB_MAP: Record<string, string[]> = {
  "/product/intake": ["Product", "New Requirement"],
  "/product/submissions": ["Product", "My Submissions"],
  "/de/dashboard": ["Data Engineering", "Dashboard"],
  "/backend/dashboard": ["Backend", "Dashboard"],
  "/frontend/dashboard": ["Frontend", "Dashboard"],
  "/qa/dashboard": ["QA", "Dashboard"],
  "/progress": ["Progress"],
  "/settings": ["Settings"],
};

export default function TopBar() {
  const location = useLocation();
  const [showNotifications, setShowNotifications] = useState(false);
  const [showSearch, setShowSearch] = useState(false);

  const breadcrumbs = BREADCRUMB_MAP[location.pathname] || ["Dashboard"];
  const unreadCount = 3;

  return (
    <header className="h-14 border-b border-surface-border bg-surface-raised flex items-center justify-between px-6">
      {/* Breadcrumbs */}
      <nav className="flex items-center gap-2 text-sm">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-2">
            {i > 0 && <span className="text-text-muted">/</span>}
            <span
              className={
                i === breadcrumbs.length - 1
                  ? "text-text-primary font-medium"
                  : "text-text-secondary"
              }
            >
              {crumb}
            </span>
          </span>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-2">
        {/* Search trigger */}
        <button
          onClick={() => setShowSearch(!showSearch)}
          className="btn-ghost flex items-center gap-2 text-text-muted"
        >
          <Search size={16} />
          <span className="text-xs hidden sm:inline">Search</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-surface border border-surface-border text-[10px] text-text-muted">
            <Command size={10} /> K
          </kbd>
        </button>

        {/* Notifications */}
        <div className="relative">
          <button
            onClick={() => setShowNotifications(!showNotifications)}
            className="btn-ghost relative"
          >
            <Bell size={18} />
            {unreadCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-accent-frontend text-[10px] font-bold text-white flex items-center justify-center">
                {unreadCount}
              </span>
            )}
          </button>
          {showNotifications && (
            <NotificationPanel onClose={() => setShowNotifications(false)} />
          )}
        </div>
      </div>
    </header>
  );
}
