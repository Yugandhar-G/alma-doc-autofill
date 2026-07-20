import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: ReactNode;
  /** Cell renderer for a row. */
  cell: (row: T) => ReactNode;
  /** Optional extra classes for the cell/header (e.g. width, alignment). */
  className?: string;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** When set, rows become buttons and fire this on activation. */
  onRowClick?: (row: T) => void;
  caption?: string;
};

/**
 * A process table styled to the firm-paper visual language: hairline rows,
 * paper-tinted header, hover affordance when rows are clickable. Presentational
 * only — data loading and empty states live in the caller.
 */
export function Table<T>({ columns, rows, rowKey, onRowClick, caption }: Props<T>) {
  const clickable = onRowClick !== undefined;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)]">
      <table className="w-full border-collapse text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-line bg-paper/50">
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-soft ${col.className ?? ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={clickable ? () => onRowClick(row) : undefined}
              tabIndex={clickable ? 0 : undefined}
              onKeyDown={
                clickable
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
              className={
                clickable
                  ? "cursor-pointer transition-colors hover:bg-accent-wash/40 focus-visible:bg-accent-wash/50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
                  : ""
              }
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-5 py-3.5 align-middle ${col.className ?? ""}`}>
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
