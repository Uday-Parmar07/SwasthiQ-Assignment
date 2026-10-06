import React from 'react';
import { AgentRunRecord } from '../types';
import { Terminal } from 'lucide-react';

export const TranscriptView: React.FC<{ conversation: AgentRunRecord }> = ({ conversation }) => (
  <div className="transcript-card">
    <div className="section-label"><Terminal size={14} /><span>Transcript and tool calls</span></div>
    <div className="turns-stream">
      {conversation.events?.length ? conversation.events.map((event, index) => (
        event.role === 'tool' ? (
          <div className="tool-call-box" key={index}>
            <div className="tool-signature">{event.name}({JSON.stringify(event.arguments)})</div>
            {event.result != null && <div className="tool-output">→ {JSON.stringify(event.result)}</div>}
          </div>
        ) : (
          <div className={`turn-${event.role}`} key={index}>
            <span className={`speaker-tag${event.role === 'agent' ? '-agent' : ''}`}>
              {event.role.toUpperCase()} · Turn {event.turn}
            </span>
            <div className={`bubble-${event.role}`}>{event.text}</div>
          </div>
        )
      )) : <p>Event history is unavailable for this older run. Run the conversation again to see its timeline.</p>}
    </div>
  </div>
);
