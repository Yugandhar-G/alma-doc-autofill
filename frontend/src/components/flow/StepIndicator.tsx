export interface StepMeta {
  id: string;
  label: string;
}

type Props = {
  steps: readonly StepMeta[];
  currentIndex: number;
};

export function StepIndicator({ steps, currentIndex }: Props) {
  return (
    <nav aria-label="Progress">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
        {steps.map((step, i) => {
          const state = i < currentIndex ? "done" : i === currentIndex ? "current" : "todo";
          return (
            <li key={step.id} className="flex items-center gap-1">
              {i > 0 && (
                <span
                  aria-hidden
                  className={`mx-1 h-px w-4 sm:w-7 ${i <= currentIndex ? "bg-accent" : "bg-line-strong"}`}
                />
              )}
              <span
                aria-current={state === "current" ? "step" : undefined}
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                  state === "current"
                    ? "bg-accent text-white"
                    : state === "done"
                      ? "text-accent-deep"
                      : "text-ink-faint"
                }`}
              >
                {state === "done" ? (
                  <svg aria-hidden className="size-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path
                      fillRule="evenodd"
                      d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.79 6.8-6.8a1 1 0 0 1 1.4 0Z"
                      clipRule="evenodd"
                    />
                  </svg>
                ) : (
                  <span
                    className={`flex size-4 items-center justify-center rounded-full text-[10px] ${
                      state === "current" ? "bg-white/25" : "border border-line-strong"
                    }`}
                  >
                    {i + 1}
                  </span>
                )}
                <span className="hidden sm:inline">{step.label}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-1 text-xs text-ink-faint sm:hidden">
        Step {currentIndex + 1} of {steps.length}: {steps[currentIndex].label}
      </p>
    </nav>
  );
}
