"use client";
/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api/client";

type Approval = Awaited<ReturnType<typeof api.getApprovals>>[number];

export default function ApprovalsPage() {
  const [items, setItems] = useState<Approval[]>([]);
  const load = async () => { setItems(await api.getApprovals()); };
  useEffect(() => { void load(); }, []);
  const decide = async (id: string, action: "approve" | "reject") => { await (action === "approve" ? api.approve(id) : api.reject(id)); await load(); };
  return <main className="main"><p className="eyebrow">VERDICT / APPROVALS</p><h1>Approval queue</h1><p className="assumption">Recommendations are reviewed here before any high-value action.</p><div className="approval-list">{items.length === 0 ? <div className="empty"><strong>Nothing needs your attention.</strong><span>New escalations will appear here.</span></div> : items.map((item) => <article className="approval-card" key={item.id}><div><p className="eyebrow">{item.dispute_id}</p><h2>{item.requested_action}</h2><p>{item.recommendation_summary}</p></div><div className="approval-actions"><Link className="case-button" href={`/?dispute=${item.dispute_id}`}>Review</Link><button className="case-button" onClick={() => void decide(item.dispute_id, "reject")}>Reject</button><button className="case-button primary" onClick={() => void decide(item.dispute_id, "approve")}>Approve</button></div></article>)}</div></main>;
}
