"use client";

import { useEffect, useState } from "react";
import { fetchStudioSource, type AnalyticsRow } from "../data";

export function useStudioRows(source: "disputes" | "guardrails") {
  const [rows, setRows] = useState<AnalyticsRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const next = await fetchStudioSource(source);
        if (active) { setRows(next); setError(null); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Analytics unavailable");
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    const onRefresh = () => void load();
    window.addEventListener("verdict:analytics-refresh", onRefresh);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("verdict:analytics-refresh", onRefresh); };
  }, [source]);

  return { rows, loading, error };
}

export function asNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function asDate(value: unknown): number {
  const parsed = new Date(String(value ?? "")).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}
