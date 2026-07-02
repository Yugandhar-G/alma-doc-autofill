"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";

import { FILE_ACCEPT, MAX_FILE_MB } from "@/lib/config";
import type { FileKind } from "@/lib/fileValidation";

type Props = {
  slotNumber: string;
  title: string;
  description: string;
  file: File | null;
  kind: FileKind | null;
  error: string | null;
  isDisabled: boolean;
  onSelect: (file: File) => void;
  onClear: () => void;
};

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Thumbnail for an image upload. Mounted with a key tied to the file so the
 * object URL is created once per file and revoked on unmount — no state
 * updates inside effects.
 */
function ImageThumbnail({ file }: { file: File }) {
  const [url] = useState(() => URL.createObjectURL(file));
  useEffect(() => () => URL.revokeObjectURL(url), [url]);
  return (
    // Plain <img>: the source is a session-local object URL, not an asset next/image can optimize.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url}
      alt={`Preview of ${file.name}`}
      className="size-16 shrink-0 rounded-md border border-line object-cover"
    />
  );
}

export function UploadSlot({
  slotNumber,
  title,
  description,
  file,
  kind,
  error,
  isDisabled,
  onSelect,
  onClear,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const isImage = kind === "jpeg" || kind === "png";

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (isDisabled) return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) onSelect(dropped);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        if (!isDisabled) setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
      className={`flex flex-col rounded-xl border bg-surface shadow-[0_1px_2px_rgba(28,39,51,0.04)] transition-colors duration-150 ${
        isDragOver ? "border-accent bg-accent-wash" : "border-line"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={FILE_ACCEPT}
        className="hidden"
        disabled={isDisabled}
        onChange={(e) => {
          const chosen = e.target.files?.[0];
          if (chosen) onSelect(chosen);
          e.target.value = ""; // allow re-selecting the same file after a fix
        }}
      />

      <div className="flex items-baseline gap-3 border-b border-line px-5 py-3.5">
        <span className="font-mono text-xs text-ink-faint">{slotNumber}</span>
        <h3 className="font-display text-lg">{title}</h3>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-5">
        {file === null ? (
          <button
            type="button"
            disabled={isDisabled}
            onClick={() => inputRef.current?.click()}
            className={`flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              isDragOver
                ? "border-accent"
                : "border-line-strong hover:border-accent/60 hover:bg-accent-wash/40"
            } ${isDisabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
          >
            <svg
              aria-hidden
              className="size-8 text-ink-faint"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
              />
            </svg>
            <span className="text-sm font-medium">Drop the file here or click to browse</span>
            <span className="text-xs text-ink-faint">
              PDF, JPG, or PNG · up to {MAX_FILE_MB} MB
            </span>
          </button>
        ) : (
          <div className="flex items-center gap-4 rounded-lg border border-line bg-paper/60 p-3">
            {isImage ? (
              <ImageThumbnail key={`${file.name}-${file.size}-${file.lastModified}`} file={file} />
            ) : (
              <span className="flex size-16 shrink-0 flex-col items-center justify-center rounded-md border border-line bg-surface">
                <span className="rounded bg-danger px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-white">
                  PDF
                </span>
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium" title={file.name}>
                {file.name}
              </p>
              <p className="text-xs text-ink-faint">
                {kind?.toUpperCase()} · {formatSize(file.size)}
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-1">
              <button
                type="button"
                disabled={isDisabled}
                onClick={() => inputRef.current?.click()}
                className="rounded px-2 py-1 text-xs font-medium text-accent-deep transition-colors hover:bg-accent-wash focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
              >
                Replace
              </button>
              <button
                type="button"
                disabled={isDisabled}
                onClick={onClear}
                className="rounded px-2 py-1 text-xs font-medium text-ink-soft transition-colors hover:bg-line/50 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
              >
                Remove
              </button>
            </div>
          </div>
        )}

        {error && (
          <p role="alert" className="text-xs leading-relaxed text-danger">
            {error}
          </p>
        )}
        <p className="text-xs leading-relaxed text-ink-faint">{description}</p>
      </div>
    </div>
  );
}
