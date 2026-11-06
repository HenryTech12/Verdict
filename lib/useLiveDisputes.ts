"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamUrl, type Dispute, type Metrics } from "@/lib/api/client";

type Health = { paypal_mode: string; llm_provider: string };

/** Loads disputes, approvals and impact metrics, then keeps them fresh from the /stream server-sent events. */
export function useLiveDisputes() {
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [pending, setPending] = useState(0);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      const [list, approvals, summary] = await Promise.all([api.getDisputes({ page_size: 500 }), api.getApprovals(), api.getMetrics()]);
      setDisputes(list.items);
      setPending(approvals.length);
      setMetrics(summary);
      setError(null);
    } catch {
      setError("Cannot reach the Verdict API. Start the backend and refresh.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void api.getHealth().then(setHealth).catch(() => undefined);
    const debounced = () => { window.clearTimeout(timer.current); timer.current = window.setTimeout(() => void refresh(), 200); };
    const source = new EventSource(streamUrl());
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    ["dispute_created", "dispute_updated", "audit_added", "metrics_updated"].forEach((name) => source.addEventListener(name, debounced));
    source.addEventListener("notification", (event) => { try { setToast((JSON.parse((event as MessageEvent).data) as { message: string }).message); } catch { /* ignore malformed event */ } debounced(); });
    const poll = window.setInterval(() => void refresh(), 30000); // safety net if the stream drops
    return () => { source.close(); window.clearInterval(poll); window.clearTimeout(timer.current); };
  }, [refresh]);

  return { disputes, pending, metrics, health, connected, error, toast, dismissToast: () => setToast(null), refresh };
}
