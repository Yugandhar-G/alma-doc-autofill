import type { StageSummary } from "@/lib/matters/types";

export type StageState = "done" | "active" | "pending";

type Props = {
  stages: StageSummary[];
  /** Per-stage state, keyed by stage id. Missing → "pending". */
  stateFor: (stageId: string) => StageState;
};

const DOT: Record<StageState, string> = {
  done: "border-good bg-good",
  active: "border-accent bg-accent-wash",
  pending: "border-line-strong bg-surface",
};

const TEXT: Record<StageState, string> = {
  done: "text-ink",
  active: "text-accent-deep font-medium",
  pending: "text-ink-faint",
};

/**
 * Stage checklist derived from the package manifest's stages[] — never from
 * hardcoded stage names. State is coarse in v1 (no per-node telemetry): the run
 * view marks stages done/active/pending from the run's overall status.
 */
export function StageChecklist({ stages, stateFor }: Props) {
  if (stages.length === 0) return null;
  return (
    <ol className="flex flex-col gap-0.5">
      {stages.map((stage, index) => {
        const state = stateFor(stage.id);
        const isLast = index === stages.length - 1;
        return (
          <li key={stage.id} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                aria-hidden
                className={`mt-0.5 flex size-4 items-center justify-center rounded-full border-2 ${DOT[state]}`}
              >
                {state === "done" && (
                  <svg viewBox="0 0 12 12" className="size-2.5 text-white" fill="none">
                    <path
                      d="M2.5 6.5l2 2 5-5"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </span>
              {!isLast && <span aria-hidden className="w-px flex-1 bg-line" />}
            </div>
            <span className={`pb-4 text-sm ${TEXT[state]}`}>{stage.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
