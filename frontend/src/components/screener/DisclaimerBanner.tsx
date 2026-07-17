import { SCREENER_DISCLAIMER } from "@/lib/screener/types";

type Props = {
  /** Report-provided disclaimer once one exists; the constant text before. */
  text?: string | null;
};

/**
 * Persistent legal framing for the screener route — visible on every step.
 * Decision support, not legal advice; attorney review required.
 */
export function DisclaimerBanner({ text }: Props) {
  return (
    <div
      role="note"
      className="rounded-lg border border-line bg-paper/70 px-4 py-2.5 text-xs leading-relaxed text-ink-soft"
    >
      <span className="mr-2 rounded-full border border-line-strong px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-soft">
        Not legal advice
      </span>
      {text ?? SCREENER_DISCLAIMER}
    </div>
  );
}
