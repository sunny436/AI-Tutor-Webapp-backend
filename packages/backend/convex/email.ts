"use node";

import { v } from "convex/values";
import nodemailer from "nodemailer";
import { internalAction } from "./_generated/server";

/**
 * Outbound auth mail. Delivery is attempted in order:
 *
 *   1. Resend  — if `RESEND_API_KEY` is set (plain HTTPS call, no SDK dependency)
 *   2. SMTP    — if `SMTP_HOST` is set (any provider; also a local Mailpit inbox)
 *   3. Log     — always, when neither is configured or both failed
 *
 * The log fallback is what keeps local development usable with no mail service,
 * but it is NOT a delivery mechanism: until step 1 or 2 is configured, a real user
 * can never complete sign-up, verification or password reset.
 *
 * `from` defaults to Resend's shared `onboarding@resend.dev` sender, which works
 * without domain verification but may only deliver to the Resend account owner's
 * own address. Set `AUTH_EMAIL_FROM` (or `RESEND_SENDER_EMAIL_AUTH`) to a verified
 * domain address before real users sign up.
 */

const BRAND = "Ayurveda by Ollasoftware";

function sender(): string {
  return (
    process.env.AUTH_EMAIL_FROM ??
    process.env.RESEND_SENDER_EMAIL_AUTH ??
    `${BRAND} <onboarding@resend.dev>`
  );
}

function renderText(heading: string, intro: string, code: string, ttl: number) {
  return `${heading}\n\n${intro}\n\nYour code is: ${code}\n\nIt expires in ${ttl} minutes. If you didn't request it, you can safely ignore this email.\n\n— ${BRAND}`;
}

/**
 * Inline styles and a table shell — the only combination email clients render
 * reliably. Deliberately dependency-free so it cannot break the Convex bundle.
 */
function renderHtml(heading: string, intro: string, code: string, ttl: number) {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return `<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f9f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f9f7;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border:1px solid #e3ece7;border-radius:16px;padding:32px;">
        <tr><td style="text-align:center;padding-bottom:8px;font-size:28px;">&#127807;</td></tr>
        <tr><td style="text-align:center;font-size:13px;color:#6b7f74;padding-bottom:20px;">${esc(BRAND)}</td></tr>
        <tr><td style="font-size:20px;font-weight:700;color:#0f2f22;padding-bottom:8px;">${esc(heading)}</td></tr>
        <tr><td style="font-size:14px;line-height:22px;color:#4a5f55;padding-bottom:24px;">${esc(intro)}</td></tr>
        <tr><td align="center" style="padding-bottom:24px;">
          <div style="display:inline-block;background:#f0faf5;border:1px solid #b9e3cd;border-radius:12px;padding:16px 28px;font-size:30px;font-weight:700;letter-spacing:7px;color:#0f7a4d;font-family:'SFMono-Regular',Consolas,monospace;">${esc(code)}</div>
        </td></tr>
        <tr><td style="font-size:13px;line-height:20px;color:#6b7f74;">This code expires in ${ttl} minutes. If you didn't request it, you can safely ignore this email.</td></tr>
      </table>
      <div style="max-width:480px;padding-top:16px;font-size:11px;color:#9aada3;text-align:center;">Educational wellness guidance only &middot; Ayurveda &amp; Yoga</div>
    </td></tr>
  </table>
</body></html>`;
}

async function sendViaResend(to: string, subject: string, html: string, text: string) {
  const apiKey = process.env.RESEND_API_KEY;
  if (!apiKey) return false;
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      authorization: `Bearer ${apiKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ from: sender(), to: [to], subject, html, text }),
  });
  if (!response.ok) {
    // Surface Resend's own message (bad key, unverified domain, …) — these are the
    // failures that otherwise look like "the email just never arrived".
    throw new Error(`Resend ${response.status}: ${await response.text()}`);
  }
  return true;
}

async function sendViaSmtp(to: string, subject: string, html: string, text: string) {
  const host = process.env.SMTP_HOST;
  if (!host) return false;
  const transport = nodemailer.createTransport({
    host,
    port: Number(process.env.SMTP_PORT ?? "1025"),
    secure: process.env.SMTP_SECURE === "true",
    ...(process.env.SMTP_USER
      ? { auth: { user: process.env.SMTP_USER, pass: process.env.SMTP_PASS ?? "" } }
      : {}),
  });
  await transport.sendMail({ from: sender(), to, subject, text, html });
  return true;
}

/** Send one auth code. Falls back down the chain; never throws. */
export const sendAuthCode = internalAction({
  args: {
    to: v.string(),
    subject: v.string(),
    heading: v.string(),
    intro: v.string(),
    code: v.string(),
    ttlMinutes: v.number(),
  },
  handler: async (_ctx, { to, subject, heading, intro, code, ttlMinutes }) => {
    const html = renderHtml(heading, intro, code, ttlMinutes);
    const text = renderText(heading, intro, code, ttlMinutes);

    for (const [name, send] of [
      ["resend", sendViaResend],
      ["smtp", sendViaSmtp],
    ] as const) {
      try {
        if (await send(to, subject, html, text)) {
          console.info(`[email] sent "${subject}" to ${to} via ${name}`);
          return { delivered: true, via: name };
        }
      } catch (error) {
        console.error(`[email] ${name} delivery failed:`, (error as Error)?.message);
      }
    }

    // Nothing configured (or everything failed) — dev fallback so the flow is testable.
    console.warn(
      `[email] NOT DELIVERED. Configure RESEND_API_KEY or SMTP_HOST. Code for ${to}: ${code}`,
    );
    return { delivered: false, via: "log" };
  },
});

/** Generic sender kept for non-auth mail (e.g. subscription notices). */
export const sendEmail = internalAction({
  args: { to: v.string(), subject: v.string(), text: v.string() },
  handler: async (_ctx, { to, subject, text }) => {
    const html = `<p style="font-family:sans-serif;font-size:14px;color:#0f2f22;">${text.replace(/</g, "&lt;")}</p>`;
    try {
      if (await sendViaResend(to, subject, html, text)) return;
      if (await sendViaSmtp(to, subject, html, text)) return;
    } catch (error) {
      console.error("[email] delivery failed:", (error as Error)?.message);
    }
    console.warn(`[email] NOT DELIVERED to ${to}: ${subject}`);
  },
});
