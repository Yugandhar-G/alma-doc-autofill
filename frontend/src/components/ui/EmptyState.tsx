import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  /** Optional action (e.g. a button or link) rendered under the description. */
  action?: ReactNode;
};

export function EmptyState({ title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line-strong bg-surface/60 px-6 py-12 text-center">
      <p className="font-display text-lg text-ink">{title}</p>
      {description && (
        <p className="max-w-md text-sm leading-relaxed text-ink-soft">{description}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
