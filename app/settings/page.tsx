"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type Settings = Awaited<ReturnType<typeof api.getSettings>>;
const initial: Settings = { auto_refund_cap: "100.00", approval_threshold: "250.00", fight_min_win_likelihood: 0.6, refund_max_win_likelihood: 0.35, min_confidence: 0.7, shipping_policy_text: "Orders ship within 2 business days." };

export default function SettingsPage() {
  const [value, setValue] = useState(initial); const [notice, setNotice] = useState("");
  useEffect(() => { void api.getSettings().then(setValue).catch(() => setValue(initial)); }, []);
  const save = async (event: FormEvent) => { event.preventDefault(); try { await api.updateSettings(value); setNotice("Settings saved"); } catch { setNotice("Check that fight threshold is above refund threshold"); } };
  return <main className="main"><p className="eyebrow">VERDICT / SETTINGS</p><h1>Merchant policy</h1><form className="settings-form" onSubmit={save}><label>Auto-refund cap<input type="number" min="1" step="0.01" value={value.auto_refund_cap} onChange={(event) => setValue({ ...value, auto_refund_cap: event.target.value })} /></label><label>Approval threshold<input type="number" min="1" step="0.01" value={value.approval_threshold} onChange={(event) => setValue({ ...value, approval_threshold: event.target.value })} /></label><label>Fight minimum likelihood<input type="number" min="0" max="1" step="0.01" value={value.fight_min_win_likelihood} onChange={(event) => setValue({ ...value, fight_min_win_likelihood: Number(event.target.value) })} /></label><label>Refund maximum likelihood<input type="number" min="0" max="1" step="0.01" value={value.refund_max_win_likelihood} onChange={(event) => setValue({ ...value, refund_max_win_likelihood: Number(event.target.value) })} /></label><label>Minimum confidence<input type="number" min="0" max="1" step="0.01" value={value.min_confidence} onChange={(event) => setValue({ ...value, min_confidence: Number(event.target.value) })} /></label><label>Shipping policy<textarea value={value.shipping_policy_text} onChange={(event) => setValue({ ...value, shipping_policy_text: event.target.value })} /></label><p className="assumption">Fight when win likelihood is {Math.round(value.fight_min_win_likelihood * 100)}% or higher and confidence is {Math.round(value.min_confidence * 100)}% or higher.</p><button className="case-button primary" type="submit">Save settings</button><span>{notice}</span></form></main>;
}
