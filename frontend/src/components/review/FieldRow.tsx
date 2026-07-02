"use client";

import type { FieldDef } from "@/lib/fields";

export type FieldValue = string | boolean | null;

type Props = {
  def: FieldDef;
  value: FieldValue;
  warning?: string;
  onChange: (value: FieldValue) => void;
};

const INPUT_CLASS =
  "w-full rounded-md border border-line bg-surface px-3 py-1.5 text-sm text-ink " +
  "placeholder:italic placeholder:text-ink-faint focus:border-accent focus:outline-none " +
  "focus:ring-2 focus:ring-accent/20";

function TriSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <select className={INPUT_CLASS} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">— not set —</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function FieldRow({ def, value, warning, onChange }: Props) {
  const isMissing = value === null || value === "";

  const input = (() => {
    switch (def.kind) {
      case "date":
        return (
          <input
            type="date"
            className={INPUT_CLASS}
            value={typeof value === "string" ? value : ""}
            onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
          />
        );
      case "sex":
        return (
          <TriSelect
            value={typeof value === "string" ? value : ""}
            options={[
              { value: "M", label: "M" },
              { value: "F", label: "F" },
              { value: "X", label: "X" },
            ]}
            onChange={(v) => onChange(v === "" ? null : v)}
          />
        );
      case "unit":
        return (
          <TriSelect
            value={typeof value === "string" ? value : ""}
            options={[
              { value: "apt", label: "Apartment" },
              { value: "ste", label: "Suite" },
              { value: "flr", label: "Floor" },
            ]}
            onChange={(v) => onChange(v === "" ? null : v)}
          />
        );
      case "bool":
        return (
          <TriSelect
            value={value === true ? "yes" : value === false ? "no" : ""}
            options={[
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]}
            onChange={(v) => onChange(v === "" ? null : v === "yes")}
          />
        );
      default:
        return (
          <input
            type="text"
            className={INPUT_CLASS}
            value={typeof value === "string" ? value : ""}
            placeholder="Not found on document"
            onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
          />
        );
    }
  })();

  return (
    <div className="grid grid-cols-1 items-center gap-1 py-2.5 sm:grid-cols-[minmax(0,15rem)_1fr] sm:gap-4">
      <div>
        <span className="text-sm text-ink-soft">{def.label}</span>
        {isMissing && (
          <span className="ml-2 rounded-full bg-line/60 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-faint">
            missing
          </span>
        )}
        {def.hint && <p className="text-xs text-ink-faint">{def.hint}</p>}
      </div>
      <div>
        {input}
        {warning && <p className="mt-1 text-xs text-warn">{warning}</p>}
      </div>
    </div>
  );
}
