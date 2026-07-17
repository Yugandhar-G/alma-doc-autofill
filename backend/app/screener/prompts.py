"""Screener prompt builders. All regulatory framing interpolates from
criteria.py; the citation rules mirror the extraction contract (null over
guessing → here: not_met over uncited optimism).

Graded design artifact — change only with explicit approval.
"""
from app.screener.criteria import CriterionSpec

_CITATION_RULES = """CITATION RULES (non-negotiable):
1. Every factual claim you rely on MUST carry a source reference:
   - kind="answer", ref=<answer_id> for intake answers (the ids in [brackets]);
   - kind="doc", ref=<sha256>, excerpt=<VERBATIM quote> for uploaded documents;
   - kind="web", ref=<url> only for URLS listed under WEB FINDINGS (if any).
2. Doc excerpts must be copied verbatim from the evidence — they are
   substring-checked by a deterministic audit; paraphrases will be stripped.
3. Never invent evidence. If the record does not support a criterion, the
   correct verdict is "not_met" with gaps describing what evidence would help.
   An unsupported positive verdict is a defect; not_met is a correct answer.
4. This is decision support for an attorney, not a legal determination."""


def _criterion_block(spec: CriterionSpec) -> str:
    refs = ", ".join(
        ref for ref in (
            f"O-1A: {spec.o1a_ref}" if spec.o1a_ref else None,
            f"EB-1A: {spec.eb1a_ref}" if spec.eb1a_ref else None,
        ) if ref
    )
    strong = "\n".join(f"  - {item}" for item in spec.strong_evidence)
    rfe = "\n".join(f"  - {item}" for item in spec.rfe_patterns)
    return (
        f'CRITERION "{spec.id}" — {spec.title} ({refs})\n'
        f"{spec.description}\n"
        f"Evidence adjudicators accept:\n{strong}\n"
        f"Common RFE triggers:\n{rfe}"
    )


def _evidence_section(intake_rendered: str, matrix_rendered: str | None,
                      verification_rendered: str | None) -> str:
    parts = [f"INTAKE ANSWERS (cite by [answer_id]):\n{intake_rendered}"]
    if matrix_rendered:
        parts.append(f"REVIEWED EVIDENCE MATRIX (doc claims, cite by hash + verbatim excerpt):\n{matrix_rendered}")
    if verification_rendered:
        parts.append(
            "ONLINE VERIFICATION (an agent searched the public web for these "
            "claims; cite confirming sources by url). A contradicted claim "
            "cannot support met/likely; unverified claims carry less weight "
            "than verified ones:\n" + verification_rendered
        )
    return "\n\n".join(parts)


def compile_prompt(intake_rendered: str, docs_rendered: str) -> str:
    return f"""You are compiling an EVIDENCE MATRIX for a USCIS extraordinary-ability
screening (O-1A / EB-1A): every probative claim in the record, mapped to the
criteria it could support, with verifiable sources. A human will review and
edit this matrix before any criterion is assessed.

CRITERION IDS: awards, membership, published_material, judging,
original_contributions, scholarly_articles, critical_capacity, high_salary,
exhibitions, commercial_success.

INTAKE ANSWERS (cite by [answer_id]):
{intake_rendered}

UPLOADED DOCUMENTS (cite by sha256 + verbatim excerpt):
{docs_rendered}

{_CITATION_RULES}

Return an EvidenceMatrix JSON:
- items: one entry per distinct probative claim. claim = one factual sentence;
  criterion_ids = every criterion it could plausibly support; sources = the
  answer_ids and/or documents (hash + VERBATIM excerpt copied from the
  document facts above) backing it.
- unmapped_docs: sha256 hashes of documents containing nothing probative.
Do not invent claims the sources do not state."""


def assess_prompt(
    spec: CriterionSpec,
    intake_rendered: str,
    matrix_rendered: str | None = None,
    verification_rendered: str | None = None,
) -> str:
    return f"""You are screening a candidate's evidence against ONE USCIS criterion
for extraordinary-ability classification. Assess only this criterion.

{_criterion_block(spec)}

{_evidence_section(intake_rendered, matrix_rendered, verification_rendered)}

{_CITATION_RULES}

Return a CriterionAssessment JSON:
- criterion_id: "{spec.id}"
- verdict: "met" (evidence squarely satisfies the regulatory language),
  "likely" (satisfies it with modest additional documentation),
  "weak" (some relevant evidence, substantial gaps), or
  "not_met" (no qualifying evidence in this record).
- reasoning: how the cited evidence maps (or fails to map) onto the
  regulatory language above. Weigh the RFE triggers explicitly.
- citations: every source you relied on, per the citation rules.
- gaps: the specific documents or facts that would strengthen this criterion.
- rfe_risks: which of the RFE triggers above this record is exposed to."""


def merits_prompt(
    assessments_rendered: str,
    intake_rendered: str,
) -> str:
    return f"""You are performing the Kazarian step-two FINAL MERITS determination for
an EB-1A petition (8 CFR 204.5(h)). Meeting three criteria is necessary but
not sufficient: decide whether the totality of the record shows SUSTAINED
national or international acclaim and that the person is among the SMALL
PERCENTAGE at the very top of the field.

PER-CRITERION ASSESSMENTS (already adjudicated):
{assessments_rendered}

INTAKE ANSWERS (cite by [answer_id]):
{intake_rendered}

{_CITATION_RULES}

Return a FinalMeritsAssessment JSON:
- conclusion: "favorable", "uncertain", or "unfavorable"
- reasoning: totality analysis — sustained acclaim over time (not one spike),
  top-of-field standing relative to peers, and consistency of the record.
- citations: the strongest record evidence your conclusion rests on."""


def summary_prompt(
    intake_rendered: str,
    assessments_rendered: str,
    verification_rendered: str,
    verdicts_rendered: str,
) -> str:
    return f"""Write the candidate-facing profile summary for an extraordinary-ability
screening. Everything below is already adjudicated — synthesize it; do not
re-decide criteria or invent facts not present in the record.

INTAKE:
{intake_rendered}

PER-CRITERION ASSESSMENTS:
{assessments_rendered}

ONLINE VERIFICATION (what an agent could and could not confirm publicly):
{verification_rendered}

VISA VERDICTS:
{verdicts_rendered}

Return a ProfileSummary JSON:
- headline: one sentence an attorney would use to describe this case.
- strengths: what this candidate is genuinely good at, grounded in the record.
- eligibility_drivers: the concrete facts that carry the eligibility case,
  each tied to the criterion it serves.
- risks: what will draw an RFE or bounce back — unverifiable claims, thin
  documentation, criteria that look close but are not, weak public footprint.
  Be direct; the candidate is better served by candor.
- verification_note: how the online verification changed (or should change)
  their confidence — claims confirmed, claims nothing could be found for."""


def verdict_prompt(
    visa: str,
    threshold: int,
    criteria_summary: str,
    assessments_rendered: str,
    merits_rendered: str | None,
    one_time_award_claim: str | None,
) -> str:
    merits_block = (
        f"\nFINAL MERITS DETERMINATION:\n{merits_rendered}\n" if merits_rendered else ""
    )
    award_block = (
        "\nONE-TIME MAJOR AWARD CLAIMED (Nobel-class; if genuinely major and "
        f"internationally recognized it satisfies the classification without "
        f"the criteria count): {one_time_award_claim}\n"
        if one_time_award_claim
        else ""
    )
    return f"""You are writing the overall {visa} recommendation from completed
per-criterion assessments. Do not re-adjudicate criteria; synthesize.

REGULATORY BAR: at least {threshold} criteria satisfied out of: {criteria_summary}.
{award_block}
PER-CRITERION ASSESSMENTS:
{assessments_rendered}
{merits_block}
{_CITATION_RULES}

Return a VisaVerdict JSON:
- visa: "{visa}"
- recommendation: "strong" (clearly exceeds the bar), "possible" (plausibly
  meets it with focused evidence-gathering), "weak" (material gaps against
  the bar), or "not_recommended" (record does not support pursuing {visa}).
- confidence: how firmly the record supports the recommendation.
- criteria_met / criteria_likely: counts from the assessments above.
- summary: 3-6 sentences an attorney can read first.
- next_steps: the highest-leverage evidence-gathering actions, most
  impactful first."""
