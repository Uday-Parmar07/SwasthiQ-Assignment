import React, { useCallback, useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { HandoffQueue } from './pages/HandoffQueue';
import { ConversationDetail } from './pages/ConversationDetail';
import { RunSimulationModal } from './components/RunSimulationModal';
import { AgentRunRecord, HandoffStats } from './types';
import { fetchStats, fetchConversations, resolveHandoff, INITIAL_STATS } from './api/client';

export const App: React.FC = () => {
  const [stats, setStats] = useState<HandoffStats>(INITIAL_STATS);
  const [conversations, setConversations] = useState<AgentRunRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isSimulateOpen, setIsSimulateOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [nextStats, records] = await Promise.all([fetchStats(), fetchConversations()]);
      setStats(nextStats);
      setConversations(records);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load the dashboard.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const handleResolve = async (id: string, event: React.MouseEvent) => {
    event.stopPropagation();
    try {
      await resolveHandoff(id);
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not resolve handoff.'); }
  };
  const handleSimulationComplete = (record: AgentRunRecord) => {
    setConversations(previous => [record, ...previous.filter(c => c.id !== record.id)]);
    setSelectedId(record.id);
    void refresh();
  };
  const active = conversations.find(c => c.id === selectedId);
  return (
    <div className="app-container">
      <Sidebar openCount={stats.open_escalated} onOpenSimulate={() => setIsSimulateOpen(true)} onQueue={() => setSelectedId(null)} />
      <div className="workspace">
        {error && <div className="error-banner" role="alert">{error} <button onClick={() => void refresh()}>Retry</button></div>}
        {loading ? <p className="loading-state" role="status">Loading conversations…</p> : active ? (
          <ConversationDetail conversation={active} onBack={() => setSelectedId(null)} />
        ) : (
          <HandoffQueue stats={stats} conversations={conversations.filter(c => c.terminal_state === 'escalated' && !c.resolved)}
            onSelectConversation={setSelectedId} onResolve={handleResolve} />
        )}
      </div>
      <RunSimulationModal isOpen={isSimulateOpen} onClose={() => setIsSimulateOpen(false)} onSimulationComplete={handleSimulationComplete} />
    </div>
  );
};
export default App;
