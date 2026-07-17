"use client";

import { useEffect, useRef } from "react";

import {
  criterionLabel,
  type ActivityEvent,
  type CriterionVerdict,
  type VerificationStatus,
} from "@/lib/screener/types";

/**
 * Terminal-style live feed of the agent's real work: the excerpts it is
 * reading, its streamed reasoning, the findings it lands on, and the web
 * searches and page fetches it makes while verifying claims. Everything
 * rendered comes verbatim off the SSE stream — no synthetic progress copy.
 */

const NODE_TITLES: Record<string, string> = {
  compile_matrix: "Compile evidence matrix",
  review_gate: "Human review",
  verify_profile: "Online verification",
  plan_assessments: "Plan assessments",
  assess_one: "Criterion assessment",
  merits_gate: "Merits gate",
  final_merits: "Final merits (EB-1A)",
  verdict: "Visa verdicts",
  profile_summary: "Profile summary",
  assemble_report: "Assemble report",
};

function laneKey(event: ActivityEvent): string {
  return event.criterion_id ? `crit:${event.criterion_id}` : `node:${event.node}`;
}

function laneTitle(event: ActivityEvent): string {
  if (event.criterion_id) return criterionLabel(event.criterion_id);
  return NODE_TITLES[event.node] ?? event.node;
}

/**
 * Append one activity event, merging consecutive model_thinking chunks of the
 * same lane into a single streaming paragraph. Returns a new array (the
 * merged entry is replaced immutably).
 */
export function appendFeedEvent(feed: ActivityEvent[], event: ActivityEvent): ActivityEvent[] {
  if (event.type === "model_thinking") {
    const key = laneKey(event);
    for (let i = feed.length - 1; i >= 0; i--) {
      if (laneKey(feed[i]) !== key) continue;
      if (feed[i].type === "model_thinking") {
        const merged: ActivityEvent = {
          ...feed[i],
          text: `${feed[i].text ?? ""}${event.text ?? ""}`,
        };
        return [...feed.slice(0, i), merged, ...feed.slice(i + 1)];
      }
      break; // a non-thinking event of this lane arrived since — new paragraph
    }
  }
  return [...feed, event];
}

const VERDICT_CHIP: Record<CriterionVerdict, string> = {
  met: "bg-emerald-400/15 text-emerald-300",
  likely: "bg-teal-400/15 text-teal-300",
  weak: "bg-amber-400/15 text-amber-300",
  not_met: "bg-red-400/15 text-red-300",
};

const RECOMMENDATION_CHIP: Record<string, string> = {
  strong: "bg-emerald-400/15 text-emerald-300",
  possible: "bg-teal-400/15 text-teal-300",
  weak: "bg-amber-400/15 text-amber-300",
  not_recommended: "bg-red-400/15 text-red-300",
};

const STATUS_CHIP: Record<VerificationStatus, string> = {
  verified: "bg-emerald-400/15 text-emerald-300",
  partially_verified: "bg-amber-400/15 text-amber-300",
  unverified: "bg-white/10 text-white/60",
  contradicted: "bg-red-400/15 text-red-300",
};

const RESULT_SUMMARY_CHARS = 220;

function truncate(text: string, max = RESULT_SUMMARY_CHARS): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function Quote({ text }: { text: string }) {
  return (
    <p className="border-l border-white/20 pl-2 text-white/60">&ldquo;{text}&rdquo;</p>
  );
}

function ScanBody({ event }: { event: ActivityEvent }) {
  if (event.budget !== undefined) {
    const claims = (event.claims ?? []).map((c) => (typeof c === "string" ? c : c.claim));
    return (
      <div className="space-y-0.5">
        <p className="text-white/80">
          verifying <span className="text-teal-300">{claims.length}</span> claim
          {claims.length === 1 ? "" : "s"} against the public web
          <span className="text-white/50"> · budget {event.budget} tool calls</span>
        </p>
        {claims.map((claim, i) => (
          <Quote key={i} text={claim} />
        ))}
      </div>
    );
  }
  if (event.doc !== undefined) {
    return (
      <div className="space-y-0.5">
        <p className="text-white/80">
          reading doc <span className="text-teal-300">{event.doc}</span>
          {event.kind && <span className="text-white/50"> · {event.kind}</span>}
          {event.title && <span className="text-white/50"> · {event.title}</span>}
        </p>
        {(event.facts ?? []).map((fact, i) => (
          <Quote key={i} text={fact} />
        ))}
      </div>
    );
  }
  if (event.matrix_claims !== undefined) {
    return (
      <div className="space-y-0.5">
        {event.intake_answer_ids !== undefined && (
          <p className="text-white/80">
            intake answers on file:{" "}
            <span className="text-teal-300">{event.intake_answer_ids.join(", ") || "none"}</span>
          </p>
        )}
        {event.matrix_claims.length === 0 ? (
          <p className="text-white/50">no matrix claims mapped to this criterion</p>
        ) : (
          event.matrix_claims.map((claim, i) => (
            <div key={i}>
              <Quote text={claim.claim} />
              <p className="pl-2 text-white/40">sources: {claim.sources.join(", ")}</p>
            </div>
          ))
        )}
      </div>
    );
  }
  if (event.intake_answer_ids !== undefined) {
    return (
      <p className="text-white/80">
        reading intake answers:{" "}
        <span className="text-teal-300">{event.intake_answer_ids.join(", ") || "none"}</span>
      </p>
    );
  }
  if (event.visa !== undefined && event.threshold !== undefined) {
    return (
      <p className="text-white/80">
        counting {event.visa} criteria: <span className="text-emerald-300">{event.criteria_met} met</span>
        {", "}
        <span className="text-teal-300">{event.criteria_likely} likely</span>
        <span className="text-white/50"> · threshold {event.threshold}</span>
      </p>
    );
  }
  if (event.weighing !== undefined) {
    return (
      <p className="text-white/80">
        weighing totality:{" "}
        {event.weighing.map((w, i) => (
          <span key={w.criterion_id}>
            {i > 0 && <span className="text-white/40">, </span>}
            {w.criterion_id}=
            <span className={VERDICT_CHIP[w.verdict].split(" ")[1]}>{w.verdict}</span>
          </span>
        ))}
      </p>
    );
  }
  return <p className="text-white/60">scanning evidence…</p>;
}

function FindingBody({ event }: { event: ActivityEvent }) {
  if (event.verdict !== undefined) {
    return (
      <div className="space-y-0.5">
        <p>
          <span className={`rounded px-1.5 py-px font-semibold ${VERDICT_CHIP[event.verdict]}`}>
            {event.verdict.replace("_", " ")}
          </span>
          {event.citations !== undefined && (
            <span className="text-white/40">
              {" "}· {event.citations.length} citation{event.citations.length === 1 ? "" : "s"}
            </span>
          )}
        </p>
        {event.reasoning && <p className="text-white/70">{event.reasoning}</p>}
      </div>
    );
  }
  if (event.recommendation !== undefined) {
    return (
      <div className="space-y-0.5">
        <p>
          {event.visa && <span className="text-white/80">{event.visa}: </span>}
          <span
            className={`rounded px-1.5 py-px font-semibold ${RECOMMENDATION_CHIP[event.recommendation] ?? "bg-white/10 text-white/70"}`}
          >
            {event.recommendation.replace("_", " ")}
          </span>
          {event.confidence && (
            <span className="text-white/40"> · {event.confidence} confidence</span>
          )}
        </p>
        {event.summary && <p className="text-white/70">{event.summary}</p>}
      </div>
    );
  }
  if (event.identity_confidence !== undefined) {
    return (
      <div className="space-y-0.5">
        <p className="text-white/80">
          identity confidence <span className="text-teal-300">{event.identity_confidence}</span>
          {event.tool_calls_used !== undefined && (
            <span className="text-white/40">
              {" "}· {event.tool_calls_used} tool call{event.tool_calls_used === 1 ? "" : "s"} used
            </span>
          )}
        </p>
        {(event.verifications ?? []).map((v, i) => (
          <p key={i}>
            <span className={`rounded px-1.5 py-px font-semibold ${STATUS_CHIP[v.status]}`}>
              {v.status.replace("_", " ")}
            </span>{" "}
            <span className="text-white/70">{v.claim}</span>
            {v.urls.length > 0 && (
              <span className="text-white/40">
                {" "}· {v.urls.length} source{v.urls.length === 1 ? "" : "s"}
              </span>
            )}
          </p>
        ))}
        {event.searched_but_absent !== undefined && event.searched_but_absent.length > 0 && (
          <p className="text-white/40">
            searched but absent: {event.searched_but_absent.join("; ")}
          </p>
        )}
      </div>
    );
  }
  if (event.headline !== undefined) {
    return (
      <div className="space-y-0.5">
        <p className="text-white/80">{event.headline}</p>
        {(event.strengths ?? []).map((strength, i) => (
          <p key={`s-${i}`} className="text-emerald-300/80">+ {strength}</p>
        ))}
        {(event.risks ?? []).map((risk, i) => (
          <p key={`r-${i}`} className="text-amber-300/80">! {risk}</p>
        ))}
      </div>
    );
  }
  if (event.claims !== undefined) {
    return (
      <div className="space-y-0.5">
        <p className="text-white/80">
          compiled <span className="text-emerald-300">{event.claims.length}</span> claim
          {event.claims.length === 1 ? "" : "s"}
          {event.unmapped_docs !== undefined && event.unmapped_docs.length > 0 && (
            <span className="text-amber-300"> · {event.unmapped_docs.length} doc(s) unmapped</span>
          )}
        </p>
        {event.claims.map((entry, i) => {
          const claim = typeof entry === "string" ? { claim: entry, criteria: [] } : entry;
          return (
            <div key={i}>
              <Quote text={claim.claim} />
              <p className="pl-2 text-white/40">→ {claim.criteria.join(", ") || "(no criterion)"}</p>
            </div>
          );
        })}
      </div>
    );
  }
  if (event.audited_assessments !== undefined) {
    return (
      <p className="text-white/80">
        audited <span className="text-emerald-300">{event.audited_assessments}</span> assessments
        {event.citations_stripped_warnings !== undefined &&
          event.citations_stripped_warnings > 0 && (
            <span className="text-amber-300">
              {" "}· {event.citations_stripped_warnings} unverifiable citation(s) stripped
            </span>
          )}
      </p>
    );
  }
  return <p className="text-white/60">finding recorded</p>;
}

const TYPE_TAG: Record<
  Exclude<ActivityEvent["type"], "tool_call" | "tool_result">,
  { label: string; className: string }
> = {
  evidence_scan: { label: "scan", className: "text-teal-300/80" },
  model_thinking: { label: "think", className: "text-white/40" },
  finding: { label: "find", className: "text-emerald-300/80" },
};

/** tool_call gutters name the action (search/open); everything else is static. */
function typeTag(event: ActivityEvent): { label: string; className: string } {
  if (event.type === "tool_call") {
    return event.tool === "fetch_page"
      ? { label: "open", className: "text-sky-300/80" }
      : { label: "search", className: "text-sky-300/80" };
  }
  if (event.type === "tool_result") {
    return { label: "result", className: "text-sky-300/50" };
  }
  return TYPE_TAG[event.type];
}

function ToolCallBody({ event }: { event: ActivityEvent }) {
  if (event.tool === "fetch_page") {
    return (
      <p className="break-all text-white/70">
        <span className="select-none text-sky-300/80">→ </span>
        {event.url}
      </p>
    );
  }
  return (
    <p className="text-white/70">
      <span className="select-none text-sky-300/80">? </span>
      &ldquo;{event.query}&rdquo;
    </p>
  );
}

function ToolResultBody({ event }: { event: ActivityEvent }) {
  return (
    <div className="space-y-0.5">
      {event.summary !== undefined && event.summary !== "" && (
        <p className="text-white/60">{truncate(event.summary)}</p>
      )}
      {event.urls !== undefined && (
        <p className="text-white/40">
          {event.urls.length} source url{event.urls.length === 1 ? "" : "s"} returned
        </p>
      )}
      {event.url !== undefined && <p className="break-all text-teal-300/80">{event.url}</p>}
    </div>
  );
}

function FeedEntry({ event }: { event: ActivityEvent }) {
  const tag = typeTag(event);
  return (
    <div className="flex gap-2.5 py-1">
      <span className={`w-12 shrink-0 select-none text-right ${tag.className}`}>{tag.label}</span>
      <div className="min-w-0 flex-1">
        {event.type === "model_thinking" && (
          <p className="whitespace-pre-wrap italic text-white/55">{event.text}</p>
        )}
        {event.type === "evidence_scan" && <ScanBody event={event} />}
        {event.type === "finding" && <FindingBody event={event} />}
        {event.type === "tool_call" && <ToolCallBody event={event} />}
        {event.type === "tool_result" && <ToolResultBody event={event} />}
      </div>
    </div>
  );
}

type Lane = { key: string; title: string; events: ActivityEvent[] };

function groupIntoLanes(feed: ActivityEvent[]): Lane[] {
  const lanes: Lane[] = [];
  const byKey = new Map<string, Lane>();
  for (const event of feed) {
    const key = laneKey(event);
    let lane = byKey.get(key);
    if (lane === undefined) {
      lane = { key, title: laneTitle(event), events: [] };
      byKey.set(key, lane);
      lanes.push(lane);
    }
    lane.events.push(event);
  }
  return lanes;
}

type Props = {
  feed: ActivityEvent[];
  /** Streaming right now — shows the live cursor. */
  isLive: boolean;
};

export function ActivityFeed({ feed, isLive }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isPinnedRef = useRef(true);

  // Follow the stream while the user is at the bottom; stop when they scroll up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && isPinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [feed]);

  const lanes = groupIntoLanes(feed);

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-ink shadow-[0_1px_2px_rgba(28,39,51,0.08)]">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2.5">
        <span aria-hidden className={`size-2 rounded-full ${isLive ? "animate-pulse bg-emerald-400" : "bg-white/30"}`} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-white/60">
          Agent activity — live
        </span>
        <span className="ml-auto font-mono text-[11px] text-white/40">
          {feed.length} event{feed.length === 1 ? "" : "s"}
        </span>
      </div>
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          isPinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        role="log"
        aria-live="polite"
        className="max-h-[26rem] overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed"
      >
        {lanes.length === 0 && (
          <p className="text-white/40">
            Waiting for the first agent event…
            {isLive && <span className="ml-1 inline-block w-2 animate-pulse bg-white/50">&nbsp;</span>}
          </p>
        )}
        {lanes.map((lane) => (
          <section key={lane.key} className="mb-3 last:mb-0">
            <h4 className="mb-0.5 select-none text-white/40">
              <span className="text-white/25">›</span> {lane.title}
            </h4>
            <div className="border-l border-white/10 pl-2">
              {lane.events.map((event, i) => (
                <FeedEntry key={i} event={event} />
              ))}
            </div>
          </section>
        ))}
        {lanes.length > 0 && isLive && (
          <span aria-hidden className="inline-block h-3.5 w-2 animate-pulse bg-white/50" />
        )}
      </div>
    </div>
  );
}
