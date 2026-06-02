import { Unlock, ClipboardList, MessageSquare, CheckCircle2 } from "lucide-react";
import { mockNotifications } from "../../lib/mockData";
import type { Notification } from "../../lib/types";

const NOTIF_ICONS: Record<Notification["type"], React.ReactNode> = {
  unblocked: <Unlock size={16} className="text-accent-de" />,
  assigned: <ClipboardList size={16} className="text-accent-product" />,
  comment: <MessageSquare size={16} className="text-accent-backend" />,
  completed: <CheckCircle2 size={16} className="text-accent-qa" />,
};

function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function NotificationPanel({ onClose }: { onClose: () => void }) {
  const unread = mockNotifications.filter((n) => !n.read);
  const read = mockNotifications.filter((n) => n.read);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="absolute right-0 top-full mt-2 w-96 card shadow-2xl shadow-black/40 z-50 animate-fade-in overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-surface-border">
          <h3 className="text-sm font-semibold text-text-primary">Notifications</h3>
          <button className="text-xs text-accent-de hover:underline">Mark all as read</button>
        </div>

        <div className="max-h-96 overflow-y-auto">
          {unread.length > 0 && (
            <div>
              <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                New
              </div>
              {unread.map((notif) => (
                <NotificationItem key={notif.id} notification={notif} />
              ))}
            </div>
          )}
          {read.length > 0 && (
            <div>
              <div className="px-4 py-2 text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                Earlier
              </div>
              {read.map((notif) => (
                <NotificationItem key={notif.id} notification={notif} />
              ))}
            </div>
          )}
        </div>

        <div className="px-4 py-2 border-t border-surface-border">
          <button className="text-xs text-text-secondary hover:text-text-primary w-full text-center">
            View all notifications
          </button>
        </div>
      </div>
    </>
  );
}

function NotificationItem({ notification }: { notification: Notification }) {
  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 hover:bg-surface-hover transition-colors cursor-pointer ${
        !notification.read ? "bg-surface-overlay/50" : ""
      }`}
    >
      <div className="mt-0.5 flex-shrink-0">{NOTIF_ICONS[notification.type]}</div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text-primary leading-tight">{notification.title}</p>
        <p className="text-xs text-text-secondary mt-0.5 truncate">{notification.description}</p>
      </div>
      <span className="text-[10px] text-text-muted flex-shrink-0 mt-0.5">
        {timeAgo(notification.timestamp)}
      </span>
    </div>
  );
}
