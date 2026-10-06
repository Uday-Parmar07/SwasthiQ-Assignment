import { AgentRunRecord, HandoffStats } from '../types';

const configuredBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
// Render service references may contain a hostname rather than an absolute URL.
const API_BASE_URL = configuredBase && !/^(https?:\/\/|\/)/.test(configuredBase)
  ? `https://${configuredBase}` : configuredBase;
const apiUrl = (path: string) => `${API_BASE_URL}${path}`;

export const INITIAL_STATS: HandoffStats = {
  total_conversations: 0, completed_by_agent: 0, completion_rate: 0,
  escalated_count: 0, open_escalated: 0, urgent_count: 0,
};

async function request(path: string, init?: RequestInit) {
  const response = await fetch(apiUrl(path), init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}). Please retry.`);
  }
  return response.json();
}

function normalizeRecord(record: any): AgentRunRecord {
  return {
    ...record, id: record.conversation_id ?? record.id,
    caller_preview: record.caller_preview ?? record.raw_turns?.[0] ?? '',
    turns_count: record.metrics?.turns ?? 0,
    resolved: record._resolved ?? false, raw_turns: record.raw_turns ?? [],
    tool_calls: record.tool_calls ?? [], events: record.events ?? [],
  };
}

export async function fetchStats(): Promise<HandoffStats> {
  return request('/api/conversations/stats');
}
export async function fetchConversations(): Promise<AgentRunRecord[]> {
  const data = await request('/api/conversations');
  return data.conversations.map(normalizeRecord);
}
export async function fetchConversationDetail(id: string): Promise<AgentRunRecord> {
  return normalizeRecord(await request(`/api/conversations/${encodeURIComponent(id)}`));
}
export async function resolveHandoff(id: string): Promise<void> {
  await request(`/api/conversations/${encodeURIComponent(id)}/resolve`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resolved_by: 'staff' }),
  });
}
export async function runAgentSimulation(payload: {
  conversation_id: string; today: string; turns: string[];
}): Promise<AgentRunRecord> {
  await request('/agent/run', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  return fetchConversationDetail(payload.conversation_id);
}
