"use client";

import {
  Apple,
  ClipboardCheck,
  Search,
  ShieldAlert,
  Sparkles,
  Sun,
  Wind,
} from "lucide-react";

/**
 * Renders the AI's plan as colour-coded section cards.
 *
 * The backend prompt (`ANSWER_PROMPT`) always emits six `**bold**` headings —
 * Root Cause, Changes To Make, Yoga & Breathing, Food Chart, Daily Routine, When
 * To See A Doctor — and this maps each to an icon and palette. Extracted from
 * the consult page unchanged so the answer styling is exactly as before.
 */

const PALETTE = {
  amber: { iconCls: "bg-amber-500/15 text-amber-600 dark:text-amber-400", titleCls: "text-amber-700 dark:text-amber-300", cardCls: "border-amber-500/20 bg-amber-50/60 dark:bg-amber-500/[0.06]" },
  emerald: { iconCls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400", titleCls: "text-emerald-700 dark:text-emerald-300", cardCls: "border-emerald-500/20 bg-emerald-50/60 dark:bg-emerald-500/[0.06]" },
  sky: { iconCls: "bg-sky-500/15 text-sky-600 dark:text-sky-400", titleCls: "text-sky-700 dark:text-sky-300", cardCls: "border-sky-500/20 bg-sky-50/60 dark:bg-sky-500/[0.06]" },
  lime: { iconCls: "bg-lime-500/15 text-lime-600 dark:text-lime-400", titleCls: "text-lime-700 dark:text-lime-300", cardCls: "border-lime-500/20 bg-lime-50/60 dark:bg-lime-500/[0.06]" },
  violet: { iconCls: "bg-violet-500/15 text-violet-600 dark:text-violet-400", titleCls: "text-violet-700 dark:text-violet-300", cardCls: "border-violet-500/20 bg-violet-50/60 dark:bg-violet-500/[0.06]" },
  rose: { iconCls: "bg-rose-500/15 text-rose-600 dark:text-rose-400", titleCls: "text-rose-700 dark:text-rose-300", cardCls: "border-rose-500/20 bg-rose-50/60 dark:bg-rose-500/[0.06]" },
};

function styleFor(title: string) {
  const t = title.toLowerCase();
  if (t.includes("cause")) return { Icon: Search, ...PALETTE.amber };
  if (t.includes("change") || t.includes("do") || t.includes("avoid") || t.includes("lifestyle")) return { Icon: ClipboardCheck, ...PALETTE.emerald };
  if (t.includes("yoga") || t.includes("breath") || t.includes("pranayam") || t.includes("asana")) return { Icon: Wind, ...PALETTE.sky };
  if (t.includes("food") || t.includes("diet") || t.includes("eat")) return { Icon: Apple, ...PALETTE.lime };
  if (t.includes("routine") || t.includes("daily") || t.includes("dinacharya")) return { Icon: Sun, ...PALETTE.violet };
  if (t.includes("doctor") || t.includes("serious") || t.includes("emergency") || t.includes("see a")) return { Icon: ShieldAlert, ...PALETTE.rose };
  return { Icon: Sparkles, ...PALETTE.emerald };
}

function inline(text: string) {
  return text.split(/(\*\*.+?\*\*)/g).map((p, j) =>
    p.startsWith("**") && p.endsWith("**") ? <strong key={j} className="font-semibold text-primary">{p.slice(2, -2)}</strong> : <span key={j}>{p}</span>,
  );
}

function parseSections(text: string) {
  const out: { title: string | null; body: string[] }[] = [];
  let cur: { title: string | null; body: string[] } | null = null;
  for (const line of text.split("\n")) {
    const h = line.match(/^\s*\*\*(.+?)\*\*\s*$/);
    if (h) { cur = { title: h[1] ?? "", body: [] }; out.push(cur); }
    else { if (!cur) { cur = { title: null, body: [] }; out.push(cur); } cur.body.push(line); }
  }
  return out;
}

function Body({ lines }: { lines: string[] }) {
  return (
    <>
      {lines.map((line, i) => {
        const t = line.trim();
        if (!t) return <div key={i} className="h-1.5" />;
        if (/^[-*•]\s+/.test(t))
          return (
            <div key={i} className="flex gap-2 text-sm leading-relaxed text-primary/80">
              <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-current opacity-40" />
              <span>{inline(t.replace(/^[-*•]\s+/, ""))}</span>
            </div>
          );
        return <p key={i} className="text-sm leading-relaxed text-primary/80">{inline(t)}</p>;
      })}
    </>
  );
}

export function AnswerSections({ text }: { text: string }) {
  return (
    <div className="space-y-2.5">
      {parseSections(text).map((s, i) => {
        if (!s.title) return <div key={i} className="space-y-0.5"><Body lines={s.body} /></div>;
        const st = styleFor(s.title);
        return (
          <div key={i} className={`rounded-xl border p-3 ${st.cardCls}`}>
            <div className={`mb-1.5 flex items-center gap-2 text-sm font-semibold ${st.titleCls}`}>
              <span className={`grid h-6 w-6 place-items-center rounded-lg ${st.iconCls}`}><st.Icon className="h-3.5 w-3.5" /></span>
              {s.title}
            </div>
            <div className="space-y-0.5 pl-0.5"><Body lines={s.body} /></div>
          </div>
        );
      })}
    </div>
  );
}
