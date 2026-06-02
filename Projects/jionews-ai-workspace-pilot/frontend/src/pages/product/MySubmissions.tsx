import { mockRequirements } from "../../lib/mockData";

export default function MySubmissions() {
  return (
    <div className="p-6 animate-fade-in">
      <h1 className="text-xl font-semibold text-text-primary mb-1">My Submissions</h1>
      <p className="text-sm text-text-secondary mb-6">Track your submitted requirements</p>

      <div className="card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-surface-border text-left">
              <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Requirement</th>
              <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-36">Status</th>
              <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-36">Submitted By</th>
              <th className="px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider w-28">Date</th>
            </tr>
          </thead>
          <tbody>
            {mockRequirements.map((req) => (
              <tr key={req.id} className="border-b border-surface-border/50 hover:bg-surface-hover/50 cursor-pointer transition-colors">
                <td className="px-4 py-3 text-sm text-text-primary">{req.description.slice(0, 80)}...</td>
                <td className="px-4 py-3">
                  <span className={`badge ${
                    req.status === "Draft" ? "badge-todo" :
                    req.status === "Tickets Created" ? "badge-in-progress" :
                    req.status === "In Progress" ? "badge-in-progress" :
                    "badge-done"
                  }`}>
                    {req.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-text-secondary">{req.submittedBy}</td>
                <td className="px-4 py-3 text-xs text-text-secondary">
                  {new Date(req.submittedAt).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
