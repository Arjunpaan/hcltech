// EventLog.jsx - Live feed of what the backend is doing right now
// (which agent is working, which check ran, which human approved). Links open the full logs.
import React, { useEffect, useRef, useState } from "react";
import { api, link } from "../api.js";

export default function EventLog({ runId }) {
  const [events, setEvents] = useState([]);
  const lastId = useRef(0);

  // Ask only for NEW events every 2 seconds and add them to the list.
  useEffect(() => {
    let alive = true;
    lastId.current = 0;
    setEvents([]);
    const load = async () => {
      try {
        const rows = await api.get(`/api/runs/${runId}/events?after_id=${lastId.current}`);
        if (!alive || !rows.length) return;
        lastId.current = rows[rows.length - 1].id;
        setEvents((old) => [...old, ...rows]);
      } catch {
        /* try again on the next tick */
      }
    };
    load();
    const timer = setInterval(load, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [runId]);

  return (
    <div className="panel events">
      <h4>Live backend activity <a href={link(`/api/runs/${runId}/llm_calls`)} target="_blank" rel="noreferrer">AI calls</a></h4>
      <ul>
        {[...events].reverse().map((e) => (
          <li key={e.id}>
            <span className="time">{e.created_at.slice(11, 19)}</span>
            <span className={`actor ${e.actor}`}>{e.actor}</span> {e.message}
            {e.link && <> <a href={link(e.link)} target="_blank" rel="noreferrer">view log</a></>}
          </li>
        ))}
      </ul>
    </div>
  );
}
