"use client";

import { useState } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import {
  CRITERION_IDS,
  criterionLabel,
  type EvidenceItem,
  type EvidenceMatrix,
  type SourceRef,
} from "@/lib/screener/types";

const MAX_CLAIM_CHARS = 1000;

const SOURCE_KIND_CLASS: Record<SourceRef["kind"], string> = {
  answer: "border-accent/30 bg-accent-wash text-accent-deep",
  doc: "border-line-strong bg-paper text-ink-soft",
  web: "border-good/30 bg-good-wash text-good",
};

function refPreview(source: SourceRef): string {
  if (source.kind === "doc") return source.ref.slice(0, 12);
  if (source.ref.length > 64) return `${source.ref.slice(0, 64)}…`;
  return source.ref;
}

function SourceLine({ source }: { source: SourceRef }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      <span
        className={`rounded-full border px-1.5 py-px text-[10px] font-semibold uppercase tracking-[0.1em] ${SOURCE_KIND_CLASS[source.kind]}`}
      >
        {source.kind}
      </span>
      <span className="font-mono text-xs text-ink-soft" title={source.ref}>
        {refPreview(source)}
      </span>
      {source.excerpt && (
        <span className="w-full text-xs italic leading-relaxed text-ink-faint">
          &ldquo;{source.excerpt}&rdquo;
        </span>
      )}
    </li>
  );
}

function CriterionChips({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {CRITERION_IDS.map((id) => {
        const isOn = selected.includes(id);
        return (
          <button
            key={id}
            type="button"
            aria-pressed={isOn}
            onClick={() => onToggle(id)}
            className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
              isOn
                ? "border-accent bg-accent text-white"
                : "border-line text-ink-soft hover:border-accent/60 hover:text-accent-deep"
            }`}
          >
            {criterionLabel(id)}
          </button>
        );
      })}
    </div>
  );
}

function ClaimCard({
  item,
  index,
  onChange,
  onDelete,
}: {
  item: EvidenceItem;
  index: number;
  onChange: (next: EvidenceItem) => void;
  onDelete: () => void;
}) {
  const isOver = item.claim.length > MAX_CLAIM_CHARS;
  const isEmpty = item.claim.trim() === "";
  return (
    <li className="rounded-xl border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <div className="flex items-start gap-3">
        <span className="mt-1 font-mono text-xs text-ink-faint">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <textarea
            rows={2}
            aria-label={`Claim ${index + 1}`}
            value={item.claim}
            onChange={(e) => onChange({ ...item, claim: e.target.value })}
            className={`w-full resize-y rounded-md border bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20 ${
              isOver || isEmpty ? "border-danger/50" : "border-line"
            }`}
          />
          {(isOver || isEmpty) && (
            <p className="mt-0.5 text-xs font-medium text-danger" role="alert">
              {isEmpty
                ? "A claim cannot be empty — edit it or delete the row."
                : `Claims are capped at ${MAX_CLAIM_CHARS} characters (${item.claim.length}).`}
            </p>
          )}
          <div className="mt-2.5">
            <CriterionChips
              selected={item.criterion_ids}
              onToggle={(id) =>
                onChange({
                  ...item,
                  criterion_ids: item.criterion_ids.includes(id)
                    ? item.criterion_ids.filter((c) => c !== id)
                    : [...item.criterion_ids, id],
                })
              }
            />
          </div>
          <ul className="mt-2.5 space-y-1 border-t border-line pt-2.5">
            {item.sources.map((source, i) => (
              <SourceLine key={`${source.kind}-${source.ref}-${i}`} source={source} />
            ))}
          </ul>
        </div>
        <button
          type="button"
          onClick={onDelete}
          className="shrink-0 rounded px-2 py-1 text-xs font-medium text-ink-soft transition-colors hover:bg-line/50 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
        >
          Delete
        </button>
      </div>
    </li>
  );
}

function AddClaimForm({
  answerIds,
  onAdd,
}: {
  answerIds: Record<string, string>;
  onAdd: (item: EvidenceItem) => void;
}) {
  const [claim, setClaim] = useState("");
  const [criterionIds, setCriterionIds] = useState<string[]>([]);
  const [answerRef, setAnswerRef] = useState("");

  const answerOptions = Object.entries(answerIds);
  const canAdd =
    claim.trim() !== "" && claim.length <= MAX_CLAIM_CHARS && answerRef !== "";

  const handleAdd = () => {
    onAdd({
      claim: claim.trim(),
      criterion_ids: criterionIds,
      // The UI can only mint answer citations — pointers at what the user
      // actually typed. Doc/web citations come solely from the agent.
      sources: [{ kind: "answer", ref: answerRef, excerpt: null }],
    });
    setClaim("");
    setCriterionIds([]);
    setAnswerRef("");
  };

  if (answerOptions.length === 0) {
    return (
      <p className="rounded-lg border border-line bg-paper/60 px-4 py-3 text-xs leading-relaxed text-ink-faint">
        New claims must cite an intake answer, and none were provided — go back later and add
        answers if the matrix is missing something.
      </p>
    );
  }

  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-paper/40 p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
        Add a claim
      </p>
      <p className="mt-1 text-xs text-ink-faint">
        Every claim needs a verifiable source. From here you can only cite one of your own intake
        answers — document and web citations are never fabricated in the UI.
      </p>
      <textarea
        rows={2}
        aria-label="New claim"
        placeholder="State one specific, checkable claim"
        value={claim}
        onChange={(e) => setClaim(e.target.value)}
        className="mt-2.5 w-full resize-y rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:italic placeholder:text-ink-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
      />
      {claim.length > MAX_CLAIM_CHARS && (
        <p className="mt-0.5 text-xs font-medium text-danger">
          Claims are capped at {MAX_CLAIM_CHARS} characters ({claim.length}).
        </p>
      )}
      <div className="mt-2.5">
        <CriterionChips
          selected={criterionIds}
          onToggle={(id) =>
            setCriterionIds((prev) =>
              prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
            )
          }
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label htmlFor="new-claim-source" className="text-xs text-ink-soft">
          Cites intake answer
        </label>
        <select
          id="new-claim-source"
          value={answerRef}
          onChange={(e) => setAnswerRef(e.target.value)}
          className="min-w-0 flex-1 rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
        >
          <option value="">— choose an answer —</option>
          {answerOptions.map(([id, text]) => (
            <option key={id} value={id}>
              {id} · {text.length > 60 ? `${text.slice(0, 60)}…` : text}
            </option>
          ))}
        </select>
        <Button variant="secondary" onClick={handleAdd} disabled={!canAdd}>
          Add claim
        </Button>
      </div>
    </div>
  );
}

type Props = {
  matrix: EvidenceMatrix;
  /** answer_id → answer text; the only citations the UI may create. */
  answerIds: Record<string, string>;
  isSubmitting: boolean;
  error: string | null;
  onChange: (next: EvidenceMatrix) => void;
  onConfirm: () => void;
};

export function MatrixReviewStep({
  matrix,
  answerIds,
  isSubmitting,
  error,
  onChange,
  onConfirm,
}: Props) {
  const setItem = (index: number, next: EvidenceItem) =>
    onChange({ ...matrix, items: matrix.items.map((it, i) => (i === index ? next : it)) });
  const deleteItem = (index: number) =>
    onChange({ ...matrix, items: matrix.items.filter((_, i) => i !== index) });

  const hasInvalidClaim = matrix.items.some(
    (item) => item.claim.trim() === "" || item.claim.length > MAX_CLAIM_CHARS,
  );

  return (
    <section className="flex flex-col gap-6">
      <header className="max-w-2xl">
        <h2 className="font-display text-3xl tracking-tight">Review the evidence matrix.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">
          The run is paused. These are the claims the agent believes your answers and documents
          support — every one carries its sources. Edit, re-map, delete, or add before the
          criterion assessments proceed; nothing downstream uses a claim you did not approve.
        </p>
      </header>

      {matrix.items.length === 0 ? (
        <Banner tone="warn">
          The agent could not compile any citable claims. Add claims below from your intake
          answers, or confirm with an empty matrix — the assessments will then lean on the raw
          intake alone.
        </Banner>
      ) : (
        <ul className="flex flex-col gap-3">
          {matrix.items.map((item, i) => (
            <ClaimCard
              key={i}
              item={item}
              index={i}
              onChange={(next) => setItem(i, next)}
              onDelete={() => deleteItem(i)}
            />
          ))}
        </ul>
      )}

      <AddClaimForm
        answerIds={answerIds}
        onAdd={(item) => onChange({ ...matrix, items: [...matrix.items, item] })}
      />

      {matrix.unmapped_docs.length > 0 && (
        <div className="rounded-xl border border-line bg-surface p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-soft">
            Documents with no criterion fit
          </p>
          <p className="mt-1 text-xs text-ink-faint">
            These uploads produced no claim the agent could map to a criterion. They stay in the
            record but nothing will be cited from them.
          </p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {matrix.unmapped_docs.map((hash) => (
              <li key={hash} className="rounded-md border border-line bg-paper px-2 py-1 font-mono text-xs text-ink-soft">
                {hash.slice(0, 12)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <Banner tone="danger">{error}</Banner>}

      <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-5">
        <Button onClick={onConfirm} disabled={hasInvalidClaim} isBusy={isSubmitting}>
          {isSubmitting ? "Resuming the run…" : "Confirm & continue"}
        </Button>
      </footer>
    </section>
  );
}
