/**
 * TypeScript mirrors of the matter-store domain models and package manifest
 * wire forms. The Pydantic models are the source of truth:
 *   - backend/app/kernel/store/models.py (Matter, MatterDocument, WorkflowRun,
 *     RunArtifact, Interrupt)
 *   - backend/app/kernel/package.py (PackageManifest.summary / StageSpec)
 *   - backend/app/packages/preflight/schemas.py (PreflightReport / Finding)
 *   - backend/app/schemas/screener.py (SourceRef)
 *
 * Every field is hand-mirrored; nullable fields stay nullable. No codegen.
 */

export type MatterStatus = "open" | "closed";
export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_input"
  | "done"
  | "error";
export type ArtifactKind =
  | "report"
  | "population_pdf"
  | "population_png"
  | "transcript";
export type InterruptStatus = "pending" | "resolved" | "expired";

/** ISO-8601 timestamp string (backend sends tz-aware UTC). */
export type IsoTimestamp = string;

export interface Matter {
  id: string;
  firm_id: string;
  matter_type: string;
  title: string;
  client_ref: string | null;
  status: MatterStatus;
  created_by: string;
  created_at: IsoTimestamp;
}

export interface MatterDocument {
  id: string;
  matter_id: string;
  firm_id: string;
  doc_id: string;
  doc_type: string;
  filename: string;
  uploaded_by: string;
  created_at: IsoTimestamp;
}

export interface WorkflowRun {
  id: string;
  matter_id: string;
  firm_id: string;
  package_id: string;
  status: RunStatus;
  thread_id: string;
  started_by: string;
  created_at: IsoTimestamp;
  finished_at: IsoTimestamp | null;
  summary_json: Record<string, unknown>;
}

export interface RunArtifact {
  id: string;
  run_id: string;
  firm_id: string;
  kind: ArtifactKind;
  artifact_ref: string;
  created_at: IsoTimestamp;
}

export interface Interrupt {
  id: string;
  run_id: string;
  firm_id: string;
  kind: string;
  node: string;
  payload_json: Record<string, unknown>;
  status: InterruptStatus;
  created_at: IsoTimestamp;
  resolved_by: string | null;
  resolved_at: IsoTimestamp | null;
}

// --- Package manifests (wire form of PackageManifest.summary) --------------

export interface StageSummary {
  id: string;
  label: string;
  nodes: string[];
}

export interface PackageManifestSummary {
  package_id: string;
  version: string;
  title: string;
  description: string;
  matter_types: string[];
  stages: StageSummary[];
  interrupt_kinds: string[];
}

// --- Preflight report contracts (backend/app/packages/preflight/schemas.py) -

export type FindingSeverity = "critical" | "warning" | "info";
export type SourceRefKind = "answer" | "doc" | "web" | "memory";

export interface SourceRef {
  kind: SourceRefKind;
  ref: string;
  excerpt: string | null;
}

export interface PreflightFinding {
  check_id: string;
  severity: FindingSeverity;
  message: string;
  refs: SourceRef[];
}

export interface PreflightReport {
  case_type: string;
  findings: PreflightFinding[];
  checks_run: string[];
  docs_examined: number;
  ok: boolean;
}

// --- Response envelopes (data payloads under the ApiResponse envelope) ------

export interface MatterListData {
  matters: Matter[];
}

export interface MatterDetailData {
  matter: Matter;
  documents: MatterDocument[];
  runs: WorkflowRun[];
}

export interface DocumentUploadData {
  documents: MatterDocument[];
  rejected: string[];
}

export interface RunStatusData {
  run: WorkflowRun;
  artifacts: RunArtifact[];
}

export interface ResumeRunData {
  run: WorkflowRun | null;
  report: unknown;
}

export interface InboxData {
  interrupts: Interrupt[];
}

export interface PackageListData {
  packages: PackageManifestSummary[];
}

// --- Package-endpoint run payloads (autofill / preflight own routers) -------

/**
 * The autofill/preflight package endpoints (/api/packages/{pid}/runs) do NOT
 * mint matter-store WorkflowRun rows — they run standalone graph threads keyed
 * by run_id. Their POST response carries the parked interrupt's review payload
 * inline (extraction slots for autofill, a draft report for preflight); the
 * GET status only reports awaiting_review / done. See the reload note in the
 * run view for why the review payload is carried client-side.
 */
export type PackageRunStatus = "awaiting_review" | "done";

export interface PackageRunStatusData {
  run_id: string;
  status: PackageRunStatus;
  report?: unknown;
}
