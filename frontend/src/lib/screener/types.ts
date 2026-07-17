/**
 * TypeScript mirrors of backend/app/schemas/screener.py — the Pydantic models
 * are the source of truth. Every claim carries at least one SourceRef; a
 * verdict without verifiable sources is a backend defect, not a UI concern.
 */

export type VisaType = "O1A" | "EB1A";
export type CriterionVerdict = "met" | "likely" | "weak" | "not_met";
export type SourceKind = "answer" | "doc" | "web";

export type EvidenceKind =
  | "resume"
  | "award"
  | "press"
  | "recommendation_letter"
  | "publication"
  | "salary_doc"
  | "membership_proof"
  | "patent"
  | "other";

/** Mirror of the backend DISCLAIMER constant — shown before a report exists. */
export const SCREENER_DISCLAIMER =
  "This screener is decision support, not a legal determination. It does not " +
  "constitute legal advice, does not create an attorney-client relationship, " +
  "and must be reviewed by a licensed immigration attorney before any filing " +
  "decision. USCIS adjudication outcomes depend on the full evidentiary " +
  "record and adjudicator discretion.";

export const INTAKE_MAX_CHARS = 2000;
export const INTAKE_MAX_LIST_ENTRIES = 20;
export const MAX_EVIDENCE_DOCS = 8;
/** USCIS regulatory floor: three criteria must be satisfied for both visas. */
export const CRITERIA_THRESHOLD = 3;

export interface SourceRef {
  kind: SourceKind;
  /** answer → intake answer_id (e.g. "awards[0]"); doc → SHA-256; web → URL. */
  ref: string;
  excerpt?: string | null;
}

export interface IntakeAnswers {
  field_of_endeavor: string | null;
  current_role: string | null;
  salary_context: string | null;
  awards: string[];
  memberships: string[];
  judging_activity: string | null;
  publications_summary: string | null;
  press_mentions: string[];
  original_contributions: string | null;
  critical_roles: string | null;
  exhibitions: string | null;
  commercial_success: string | null;
  one_time_major_award: string | null;
}

export const EMPTY_INTAKE: IntakeAnswers = {
  field_of_endeavor: null,
  current_role: null,
  salary_context: null,
  awards: [],
  memberships: [],
  judging_activity: null,
  publications_summary: null,
  press_mentions: [],
  original_contributions: null,
  critical_roles: null,
  exhibitions: null,
  commercial_success: null,
  one_time_major_award: null,
};

export interface FieldWarning {
  field: string;
  message: string;
}

export interface EvidenceDocRecord {
  source_hash: string;
  document_kind_detected: EvidenceKind;
  title: string | null;
  key_facts: string[];
  warnings: FieldWarning[];
}

export interface EvidenceItem {
  claim: string;
  criterion_ids: string[];
  sources: SourceRef[];
}

export interface EvidenceMatrix {
  items: EvidenceItem[];
  unmapped_docs: string[];
}

export type VerificationStatus =
  | "verified"
  | "partially_verified"
  | "unverified"
  | "contradicted";

/** The verification agent's judgment on one reviewed claim, backed by URLs
 * it actually visited (audited against the tool transcript backend-side). */
export interface ClaimVerification {
  claim: string;
  status: VerificationStatus;
  evidence_urls: string[];
  notes: string;
}

/** Output of the tool-loop verification agent. */
export interface ProfileVerification {
  identity_confidence: "high" | "medium" | "low";
  verifications: ClaimVerification[];
  /** Notable things that SHOULD be findable for a strong case but were not. */
  searched_but_absent: string[];
  tool_calls_used: number;
}

/** User-facing synthesis: the profile as an adjudicator would see it. */
export interface ProfileSummary {
  headline: string;
  strengths: string[];
  /** What concretely makes this candidate eligible, tied to criteria. */
  eligibility_drivers: string[];
  /** What will draw an RFE or denial — the bounce-backs. */
  risks: string[];
  /** How the online verification affected this picture. */
  verification_note: string;
}

export interface CriterionAssessment {
  criterion_id: string;
  verdict: CriterionVerdict;
  reasoning: string;
  citations: SourceRef[];
  gaps: string[];
  rfe_risks: string[];
}

export interface FinalMeritsAssessment {
  conclusion: "favorable" | "uncertain" | "unfavorable";
  reasoning: string;
  citations: SourceRef[];
}

export interface VisaVerdict {
  visa: VisaType;
  recommendation: "strong" | "possible" | "weak" | "not_recommended";
  confidence: "high" | "medium" | "low";
  criteria_met: number;
  criteria_likely: number;
  summary: string;
  next_steps: string[];
}

export interface ScreenerReport {
  session_id: string;
  visa_targets: VisaType[];
  profile_summary: ProfileSummary | null;
  verification: ProfileVerification | null;
  verdicts: VisaVerdict[];
  assessments: CriterionAssessment[];
  final_merits: FinalMeritsAssessment | null;
  warnings: FieldWarning[];
  disclaimer: string;
}

/** criterion_id → human title, in canonical display order. */
export const CRITERION_LABELS: Record<string, string> = {
  awards: "Prizes & Awards",
  membership: "Selective Memberships",
  published_material: "Published Material About You",
  judging: "Judging Others' Work",
  original_contributions: "Original Contributions",
  scholarly_articles: "Scholarly Articles",
  critical_capacity: "Critical Role at Distinguished Orgs",
  high_salary: "High Remuneration",
  exhibitions: "Exhibitions (EB-1A)",
  commercial_success: "Commercial Success (EB-1A)",
};

export const CRITERION_IDS = Object.keys(CRITERION_LABELS);

export function criterionLabel(id: string): string {
  return CRITERION_LABELS[id] ?? id;
}

/** Per-slot outcome of a /documents upload — rejections pin to their slot. */
export type EvidenceSlotResult =
  | { kind: "ok"; record: EvidenceDocRecord }
  | { kind: "rejected"; error: string };

export interface DocumentsUploadResult {
  resume: EvidenceSlotResult | null;
  evidence: EvidenceSlotResult[];
}

// ---------------------------------------------------------------------------
// SSE stream events (backend/app/screener/api.py + nodes/*.py emitters)
// ---------------------------------------------------------------------------

export type ActivityType =
  | "evidence_scan"
  | "model_thinking"
  | "finding"
  | "tool_call"
  | "tool_result";

/**
 * One activity event off the live agent feed. Payload keys vary by node —
 * every field below is exactly what some emitter sends; nothing is invented.
 */
export interface ActivityEvent {
  event: "activity";
  type: ActivityType;
  node: string;
  criterion_id?: string;
  // model_thinking
  text?: string;
  // evidence_scan (compile_matrix per-doc)
  doc?: string;
  kind?: string;
  title?: string | null;
  facts?: string[];
  // evidence_scan (compile_matrix intake / assess_one)
  intake_answer_ids?: string[];
  matrix_claims?: { claim: string; sources: string[] }[];
  // evidence_scan (verdict)
  visa?: VisaType;
  criteria_met?: number;
  criteria_likely?: number;
  threshold?: number;
  // evidence_scan (final_merits)
  weighing?: { criterion_id: string; verdict: CriterionVerdict }[];
  // evidence_scan (verify_profile) — plain claim strings on the same key
  // the compile_matrix finding uses for {claim, criteria} objects
  budget?: number;
  // tool_call / tool_result (verify_profile)
  tool?: "search_web" | "fetch_page";
  query?: string;
  url?: string;
  urls?: string[];
  // finding (compile_matrix) | evidence_scan (verify_profile)
  claims?: ({ claim: string; criteria: string[] } | string)[];
  unmapped_docs?: string[];
  // finding (assess_one)
  verdict?: CriterionVerdict;
  reasoning?: string;
  citations?: string[];
  // finding (verify_profile)
  identity_confidence?: ProfileVerification["identity_confidence"];
  verifications?: { claim: string; status: VerificationStatus; urls: string[] }[];
  searched_but_absent?: string[];
  tool_calls_used?: number;
  // finding (profile_summary)
  headline?: string;
  strengths?: string[];
  risks?: string[];
  // finding (verdict) — summary is also the tool_result payload text
  recommendation?: VisaVerdict["recommendation"];
  confidence?: VisaVerdict["confidence"];
  summary?: string;
  // finding (assemble_report)
  audited_assessments?: number;
  citations_stripped_warnings?: number;
}

export type ScreenerEvent =
  | { event: "run_started" }
  | { event: "node_finished"; node: string }
  | ActivityEvent
  | { event: "awaiting_review"; matrix: EvidenceMatrix | null }
  | { event: "done"; report: ScreenerReport }
  | { event: "error"; message: string };

/**
 * Mirror of backend answer_index(): answer_id → answer text for every
 * non-empty answer. These ids are the only citations the UI may fabricate —
 * they point at what the user actually typed.
 */
export function answerIndex(intake: IntakeAnswers): Record<string, string> {
  const index: Record<string, string> = {};
  for (const [name, value] of Object.entries(intake)) {
    if (Array.isArray(value)) {
      value.forEach((entry, i) => {
        if (entry.trim() !== "") index[`${name}[${i}]`] = entry;
      });
    } else if (value !== null && value.trim() !== "") {
      index[name] = value;
    }
  }
  return index;
}
