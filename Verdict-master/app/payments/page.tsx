"use client";

import Script from "next/script";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, CreditCard, ExternalLink, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";

type PayPalSdk = { Buttons: (options: { createOrder: () => Promise<string>; onApprove: (data: { orderID: string }) => Promise<void>; onError: (error: unknown) => void; onCancel?: () => void; style?: { layout?: string; color?: string; shape?: string; label?: string } }) => { render: (element: HTMLElement) => Promise<void>; close?: () => void } };
type PayPalWindow = Window & { paypal?: PayPalSdk };
type Config = { mode: string; client_id: string | null; currency: string };

export default function PaymentsPage() {
  const [config, setConfig] = useState<Config | null>(null);
  const [sdkReady, setSdkReady] = useState(false);
  const [amount, setAmount] = useState("10.00");
  const [status, setStatus] = useState("Loading PayPal sandbox configuration…");
  const [busy, setBusy] = useState(false);
  const [capture, setCapture] = useState<Record<string, unknown> | null>(null);
  const buttonHost = useRef<HTMLDivElement>(null);
  const renderButtons = useCallback(async () => {
    const paypal = (window as PayPalWindow).paypal;
    const host = buttonHost.current;
    if (!paypal || !host || !config || config.mode !== "sandbox" || !config.client_id) return;
    host.innerHTML = "";
    const buttons = paypal.Buttons({
      style: { layout: "vertical", color: "blue", shape: "rect", label: "paypal" },
      createOrder: async () => {
        const numeric = Number(amount);
        if (!Number.isFinite(numeric) || numeric <= 0 || numeric > 5000) throw new Error("Enter an amount between $0.01 and $5,000.");
        setBusy(true); setCapture(null); setStatus("Creating PayPal sandbox order…");
        try { const order = await api.createPayPalOrder(numeric); setStatus(`PayPal order ${order.id} created. Approve it in the PayPal popup.`); return order.id; }
        catch (error) { setStatus(error instanceof Error ? error.message : "Could not create PayPal order."); setBusy(false); throw error; }
      },
      onApprove: async (data) => {
        setStatus("Capturing approved sandbox payment…");
        try { const result = await api.capturePayPalOrder(data.orderID); setCapture(result); setStatus("Sandbox payment captured successfully."); }
        catch (error) { setStatus(error instanceof Error ? error.message : "Payment capture failed."); }
        finally { setBusy(false); }
      },
      onCancel: () => { setStatus("Checkout was cancelled. No payment was captured."); setBusy(false); },
      onError: (error) => { setStatus(error instanceof Error ? error.message : "PayPal checkout encountered an error."); setBusy(false); },
    });
    try { await buttons.render(host); } catch { setStatus("PayPal buttons could not be rendered. Check the sandbox client ID and allowed origins."); }
  }, [amount, config]);

  useEffect(() => { let active = true; api.getPayPalConfig().then((value) => { if (active) { setConfig(value); setStatus(value.mode === "sandbox" ? "Ready to create a sandbox payment." : "PayPal is in mock mode. Set PAYPAL_MODE=sandbox and configure sandbox credentials to enable checkout."); } }).catch((error) => { if (active) setStatus(error instanceof ApiError ? `${error.code}: ${error.message}` : "Could not load PayPal configuration."); }); return () => { active = false; }; }, []);
  useEffect(() => { if (sdkReady) void renderButtons(); }, [sdkReady, renderButtons]);

  const sdkUrl = config?.mode === "sandbox" && config.client_id ? `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(config.client_id)}&currency=USD&intent=capture` : null;
  return <main className="main payments-page">
    <Link href="/" className="back-link"><ArrowLeft size={16}/> Back to command center</Link>
    <header className="payments-heading"><div><p className="eyebrow">VERDICT / PAYMENTS</p><h1>PayPal sandbox checkout</h1><p className="assumption">Create and capture test payments using a PayPal sandbox buyer account. This is separate from dispute handling.</p></div><span className="mode-pill blue"><span/> PAYPAL SANDBOX</span></header>
    <div className="payments-grid">
      <section className="payments-card">
        <div className="payments-card-title"><CreditCard size={20}/><div><h2>Test a payment</h2><p>Funds are sandbox-only and have no real-world value.</p></div></div>
        <label className="payment-amount-label" htmlFor="payment-amount">Payment amount (USD)</label>
        <div className="payment-amount-input"><span>$</span><input id="payment-amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} disabled={busy}/></div>
        {sdkUrl && <Script src={sdkUrl} strategy="afterInteractive" onLoad={() => setSdkReady(true)} onError={() => setStatus("Could not load the PayPal JavaScript SDK.")}/>}
        {config?.mode === "sandbox" && config.client_id ? <div className="paypal-button-host" ref={buttonHost}/> : <div className="paypal-disabled"><ShieldCheck size={20}/><span>Checkout is unavailable until the backend is configured for PayPal sandbox with a Client ID and Client Secret.</span></div>}
        <p className="payment-status" role="status">{status}</p>
        {capture && <div className="capture-result"><strong>Capture response</strong><pre>{JSON.stringify(capture, null, 2)}</pre></div>}
      </section>
      <aside className="payments-card payments-help"><h2>How to test</h2><ol><li>Enter a small amount, such as $10.</li><li>Click the PayPal button and sign in with a sandbox Personal (buyer) account.</li><li>Approve the payment in the PayPal popup.</li><li>Verdict captures the approved order through the backend and displays the response.</li></ol><p><b>Important:</b> Use a sandbox buyer account, not your personal PayPal account. Never put the PayPal Client Secret in frontend environment variables.</p><a href="https://developer.paypal.com/dashboard/accounts" target="_blank" rel="noreferrer">Open PayPal developer sandbox accounts <ExternalLink size={13}/></a></aside>
    </div>
  </main>;
}
