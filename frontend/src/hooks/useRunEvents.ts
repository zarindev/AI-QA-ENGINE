import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export interface RunEvent {
  type: string;
  stage?: string;
  message?: string;
  overall?: number;
  fraction?: number;
  page_id?: string;
  url?: string;
  screenshot?: string;
  role?: string;
  at: string;
  error?: string;
  result?: "pass" | "fail" | "blocked" | "error";
  test_id?: string;
}

/** Subscribe to a run's server-sent events. History arrives first, then live events until the run ends. */
export function useRunEvents(slug: string | undefined, runId: string | undefined, enabled = true) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const qc = useQueryClient();
  const lastInvalidate = useRef(0);

  useEffect(() => {
    if (!slug || !runId || !enabled) return;
    setEvents([]);
    const source = new EventSource(`/api/projects/${slug}/runs/${runId}/events`);
    const push = (raw: string) => {
      try {
        const evt = JSON.parse(raw) as RunEvent;
        setEvents((prev) => [...prev.slice(-400), evt]);
        const now = Date.now();
        // keep the cached run/pages fresh, at most twice a second
        if (now - lastInvalidate.current > 500 || evt.type !== "progress") {
          lastInvalidate.current = now;
          qc.invalidateQueries({ queryKey: ["run", slug, runId] });
          if (evt.type === "stage_done" || evt.type.startsWith("run_")) {
            qc.invalidateQueries({ queryKey: ["runs", slug] });
            qc.invalidateQueries({ queryKey: ["projects"] });
          }
        }
      } catch {
        /* ignore malformed lines */
      }
    };
    source.onopen = () => setConnected(true);
    source.addEventListener("history", (e) => push((e as MessageEvent).data));
    for (const type of ["progress", "stage_started", "stage_done", "run_started", "run_completed", "run_failed", "run_cancelled", "usage"]) {
      source.addEventListener(type, (e) => push((e as MessageEvent).data));
    }
    source.addEventListener("state", () => {
      qc.invalidateQueries({ queryKey: ["run", slug, runId] });
    });
    source.onerror = () => {
      setConnected(false);
      source.close();
    };
    return () => source.close();
  }, [slug, runId, enabled, qc]);

  return { events, connected };
}
