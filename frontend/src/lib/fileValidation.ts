/**
 * Client-side mirror of the backend upload guardrails: sniff by magic bytes
 * (never by extension) and cap size before anything leaves the browser.
 * The backend re-validates; this exists to fail fast with a friendly message.
 */
import { MAX_FILE_BYTES, MAX_FILE_MB } from "./config";

export type FileKind = "jpeg" | "png" | "pdf";

export type FileCheck =
  | { ok: true; kind: FileKind }
  | { ok: false; error: string };

function sniff(bytes: Uint8Array): FileKind | null {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "jpeg";
  }
  if (
    bytes.length >= 4 &&
    bytes[0] === 0x89 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x4e &&
    bytes[3] === 0x47
  ) {
    return "png";
  }
  if (
    bytes.length >= 4 &&
    bytes[0] === 0x25 && // %
    bytes[1] === 0x50 && // P
    bytes[2] === 0x44 && // D
    bytes[3] === 0x46 // F
  ) {
    return "pdf";
  }
  return null;
}

export async function validateFile(
  file: File,
  allowed: readonly FileKind[],
): Promise<FileCheck> {
  if (file.size === 0) {
    return { ok: false, error: "That file is empty." };
  }
  if (file.size > MAX_FILE_BYTES) {
    return {
      ok: false,
      error: `File is ${(file.size / 1024 / 1024).toFixed(1)} MB — the limit is ${MAX_FILE_MB} MB.`,
    };
  }

  const head = new Uint8Array(await file.slice(0, 8).arrayBuffer());
  const kind = sniff(head);
  if (kind === null) {
    return {
      ok: false,
      error: "Unrecognized file contents. Upload a JPEG, PNG, or PDF.",
    };
  }
  if (!allowed.includes(kind)) {
    return {
      ok: false,
      error: `This looks like a ${kind.toUpperCase()} file — expected ${allowed
        .map((k) => k.toUpperCase())
        .join(" or ")}.`,
    };
  }
  return { ok: true, kind };
}
