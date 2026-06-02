import { Database, Key, Brain, Palette } from "lucide-react";

export default function Settings() {
  return (
    <div className="p-6 max-w-3xl animate-fade-in">
      <h1 className="text-xl font-semibold text-text-primary mb-1">Settings</h1>
      <p className="text-sm text-text-secondary mb-6">Configure your workspace</p>

      <div className="space-y-6">
        {/* Profile */}
        <SettingsSection icon={<Database size={16} />} title="Profile">
          <SettingsField label="Name" value="Ankit Joshi" />
          <SettingsField label="Email" value="Ankit10.Joshi@ril.com" />
          <SettingsField label="Team" value="Data Engineering" />
        </SettingsSection>

        {/* ADO Connection */}
        <SettingsSection icon={<Key size={16} />} title="ADO Connection">
          <SettingsField label="Organization" value="JioMedia" />
          <SettingsField label="Project" value="JioNews-MobileApp" />
          <SettingsField label="Area Path" value="JioNews-MobileApp\JioNews-DE-DS" />
          <div>
            <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold block mb-1">
              PAT Token (Read)
            </label>
            <input type="password" defaultValue="EIVktS1KrAv3..." className="input-field" />
          </div>
        </SettingsSection>

        {/* Knowledge Base */}
        <SettingsSection icon={<Database size={16} />} title="Knowledge Base">
          <SettingsField label="Path" value="C:\Users\...\knowledge-base" />
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs text-text-secondary">Last indexed: </span>
              <span className="text-xs text-text-primary">April 8, 2026 10:30 AM</span>
            </div>
            <button className="btn-ghost text-xs">Reindex</button>
          </div>
        </SettingsSection>

        {/* AI */}
        <SettingsSection icon={<Brain size={16} />} title="AI Configuration">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold block mb-1">
              Analysis Model
            </label>
            <select className="input-field">
              <option>Claude Sonnet 4</option>
              <option>Claude Opus 4</option>
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold block mb-1">
              Implementation Model
            </label>
            <select className="input-field">
              <option>Claude Opus 4</option>
              <option>Claude Sonnet 4</option>
            </select>
          </div>
        </SettingsSection>

        {/* Appearance */}
        <SettingsSection icon={<Palette size={16} />} title="Appearance">
          <div className="flex items-center justify-between">
            <span className="text-sm text-text-primary">Dark Mode</span>
            <div className="w-10 h-5 rounded-full bg-accent-de flex items-center px-0.5">
              <div className="w-4 h-4 rounded-full bg-white translate-x-5 transition-transform" />
            </div>
          </div>
        </SettingsSection>
      </div>
    </div>
  );
}

function SettingsSection({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-accent-de">{icon}</span>
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function SettingsField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <label className="text-[10px] uppercase tracking-wider text-text-muted font-semibold block mb-1">
        {label}
      </label>
      <input type="text" defaultValue={value} className="input-field" />
    </div>
  );
}
