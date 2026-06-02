import { useEffect, useState } from "react";
import { CheckCircle2, X, AlertCircle, Info } from "lucide-react";

export type ToastType = "success" | "error" | "info";

interface ToastProps {
  message: string;
  type?: ToastType;
  onClose: () => void;
  duration?: number;
}

const ICONS: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle2 size={16} className="text-accent-qa" />,
  error: <AlertCircle size={16} className="text-accent-frontend" />,
  info: <Info size={16} className="text-accent-de" />,
};

export default function Toast({ message, type = "info", onClose, duration = 3000 }: ToastProps) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onClose, 200);
    }, duration);
    return () => clearTimeout(timer);
  }, [duration, onClose]);

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 card px-4 py-3 flex items-center gap-3 shadow-2xl shadow-black/40 transition-all duration-200 ${
        visible ? "animate-slide-up" : "opacity-0 translate-y-2"
      }`}
    >
      {ICONS[type]}
      <span className="text-sm text-text-primary">{message}</span>
      <button onClick={onClose} className="text-text-muted hover:text-text-secondary ml-2">
        <X size={14} />
      </button>
    </div>
  );
}
