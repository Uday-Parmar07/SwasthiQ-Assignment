import React from 'react';
import { Inbox, PlayCircle, Activity } from 'lucide-react';

interface SidebarProps {
  openCount: number;
  onOpenSimulate: () => void;
  onQueue: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  openCount,
  onOpenSimulate,
  onQueue,
}) => {
  return (
    <aside className="sidebar">
      <div className="clinic-brand">
        <div className="clinic-logo-icon">🏥</div>
        <div>
          <h1>Sunrise Clinic</h1>
          <span>SwasthiQ Agent</span>
        </div>
      </div>

      <ul className="nav-links">
        <li>
          <button
            onClick={onQueue}
            className="nav-item active"
            style={{ width: '100%', background: 'transparent', textAlign: 'left' }}
          >
            <Inbox size={18} />
            <span>Handoff Queue</span>
            {openCount > 0 && <span className="nav-badge">{openCount}</span>}
          </button>
        </li>
      </ul>

      <div className="sidebar-footer">
        <button className="btn-simulate" onClick={onOpenSimulate}>
          <PlayCircle size={18} />
          <span>Run Simulation</span>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem', color: '#64748b', fontSize: '0.75rem' }}>
          <Activity size={14} color="#34d399" />
          <span>Clinic front desk</span>
        </div>
      </div>
    </aside>
  );
};
