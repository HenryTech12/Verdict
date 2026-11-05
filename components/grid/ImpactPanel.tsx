import { CircleDollarSign, Clock3, ShieldCheck, Users } from "lucide-react";
import type { Metrics } from "@/lib/api/client";
import { money } from "@/lib/format";

function Metric({ label, value, icon, accent, note }: { label: string; value: string; icon: React.ReactNode; accent?: boolean; note?: string }) {
  return <div className={accent ? "metric accent" : "metric"}><span>{icon}{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

export default function ImpactPanel({ metrics, pending }: { metrics: Metrics | null; pending: number }) {
  return <section className="impact" aria-label="Impact">
    <div className="section-heading"><div><p className="eyebrow">IMPACT</p><h2>Modeled estimates</h2></div><span className="assumption" title={metrics ? `${metrics.assumptions.revenue_recovered} ${metrics.assumptions.time_saved}` : undefined}>ⓘ {metrics ? `MODELED, not measured · ${metrics.assumptions.minutes_per_manual_case} min per manual case` : "Loading assumptions"}</span></div>
    <div className="impact-grid">
      <Metric label="Disputes handled" value={String(metrics?.disputes_handled ?? 0)} icon={<Users size={17} />} note={`${metrics?.auto_resolved ?? 0} resolved automatically`} />
      <Metric label="Revenue recovered (modeled)" value={money(metrics?.modeled_revenue_recovered ?? 0)} icon={<CircleDollarSign size={17} />} accent note="Disputed amount × win likelihood on submitted packets" />
      <Metric label="Time saved (modeled)" value={`${metrics?.modeled_hours_saved ?? 0} h`} icon={<Clock3 size={17} />} note="Handled disputes × manual minutes" />
      <Metric label="Pending approvals" value={String(pending)} icon={<ShieldCheck size={17} />} note="Waiting for your decision" />
    </div>
  </section>;
}
