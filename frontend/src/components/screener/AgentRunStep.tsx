"use client";

import { ActivityFeed } from "@/components/screener/ActivityFeed";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import type { ActivityEvent } from "@/lib/screener/types";

/** Display stages in graph order; a stage is done once any of its nodes has
 * finished (online verification can be skipped entirely — it completes by
 * being passed over). */
const STAGES: { id: string; label: string; detail: string; nodes: string[] }[] = [
  {
    id: "compile",
    label: "Compile evidence matrix",
    detail: "Claims mapped to criteria, every one with sources",
    nodes: ["compile_matrix"],
  },
  {
    id: "review",
    label: "Human review",
    detail: "The run pauses for your edits",
    nodes: ["review_gate"],
  },
  {
    id: "verify",
    label: "Online verification",
    detail: "The agent searches the web and validates your claims",
    nodes: ["verify_profile"],
  },
  {
    id: "assess",
    label: "Criterion assessments",
    detail: "One structured call per criterion, in parallel",
    nodes: ["plan_assessments", "assess_one"],
  },
  {
    id: "merits",
    label: "Final merits (EB-1A)",
    detail: "Kazarian step 2 — the totality of the record",
    nodes: ["merits_gate", "final_merits"],
  },
  {
    id: "verdict",
    label: "Visa verdicts",
    detail: "Recommendation per targeted visa",
    nodes: ["verdict"],
  },
  {
    id: "summary",
    label: "Profile summary",
    detail: "Strengths, eligibility drivers, and the bounce-backs",
    nodes: ["profile_summary"],
  },
  {
    id: "report",
    label: "Assemble report",
    detail: "Citations audited; unverifiable ones stripped",
    nodes: ["assemble_report"],
  },
];

type StageState = "done" | "current" | "todo";

function stageStates(finishedNodes: readonly string[], isLive: boolean): StageState[] {
  const finished = new Set(finishedNodes);
  let lastDone = -1;
  STAGES.forEach((stage, i) => {
    if (stage.nodes.some((n) => finished.has(n))) lastDone = i;
  });
  return STAGES.map((_, i) => {
    if (i <= lastDone) return "done";
    if (isLive && i === lastDone + 1) return "current";
    return "todo";
  });
}

function StageRow({ stage, state }: { stage: (typeof STAGES)[number]; state: StageState }) {
  return (
    <li className="flex items-start gap-3 py-2">
      {state === "done" ? (
        <span
          aria-hidden
          className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full bg-accent text-white"
        >
          <svg className="size-2.5" viewBox="0 0 20 20" fill="currentColor">
            <path
              fillRule="evenodd"
              d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.79 6.8-6.8a1 1 0 0 1 1.4 0Z"
              clipRule="evenodd"
            />
          </svg>
        </span>
      ) : state === "current" ? (
        <span
          aria-hidden
          className="mt-0.5 size-4 shrink-0 animate-spin rounded-full border-2 border-accent border-t-transparent"
        />
      ) : (
        <span
          aria-hidden
          className="mt-0.5 size-4 shrink-0 rounded-full border border-line-strong"
        />
      )}
      <div>
        <p
          className={`text-sm ${
            state === "current"
              ? "font-medium text-ink"
              : state === "done"
                ? "text-ink-soft"
                : "text-ink-faint"
          }`}
        >
          {stage.label}
        </p>
        <p className="text-xs text-ink-faint">{stage.detail}</p>
      </div>
    </li>
  );
}

type Props = {
  /** Which stream segment is (or was) running. */
  phase: "compiling" | "assessing";
  finishedNodes: string[];
  feed: ActivityEvent[];
  isLive: boolean;
  /** Stream/SSE failure — retry restarts the failed segment. */
  error: string | null;
  onRetry: () => void;
};

export function AgentRunStep({ phase, finishedNodes, feed, isLive, error, onRetry }: Props) {
  const states = stageStates(finishedNodes, isLive);

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">
          {phase === "compiling" ? "The agent is reading the record." : "Assessing the criteria."}
        </h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          {phase === "compiling"
            ? "Your answers and documents are being compiled into an evidence matrix — claims mapped to USCIS criteria, each with verifiable sources. You review every claim before anything is assessed."
            : "Your approved matrix drives one structured assessment per criterion, then the visa verdicts. Every citation is audited against what you actually provided before the report is assembled."}
        </p>
      </header>

      {error && (
        <Banner tone="danger">
          <span className="flex flex-wrap items-center justify-between gap-3">
            <span>{error}</span>
            <Button variant="secondary" onClick={onRetry}>
              Retry this step
            </Button>
          </span>
        </Banner>
      )}

      <div className="grid gap-6 lg:grid-cols-[2fr_3fr]">
        <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
            Run progress
          </p>
          <ol className="mt-2 divide-y divide-line">
            {STAGES.map((stage, i) => (
              <StageRow key={stage.id} stage={stage} state={states[i]} />
            ))}
          </ol>
        </div>

        <ActivityFeed feed={feed} isLive={isLive} />
      </div>
    </section>
  );
}
