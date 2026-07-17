"""Synthetic screener personas — pre-extracted state fixtures with expected
per-criterion verdicts.

Scoring philosophy mirrors the extraction harness: an OVERCLAIM (screener
says met/likely where the record doesn't support it) is the worst defect
class — the screener equivalent of a fabricated field. One-band underclaims
are tolerated (lenient): a conservative screener is annoying, an optimistic
one is dangerous.

Expected verdicts are bands, not points: each criterion maps to the set of
acceptable verdicts. RANK orders the ordinal scale for over/under
classification.
"""
from dataclasses import dataclass, field

from app.schemas import EvidenceDocRecord, IntakeAnswers

RANK = {"not_met": 0, "weak": 1, "likely": 2, "met": 3}
RECOMMENDATION_RANK = {"not_recommended": 0, "weak": 1, "possible": 2, "strong": 3}


@dataclass(frozen=True)
class ScreenerPersona:
    name: str
    visa_targets: tuple[str, ...]
    intake: IntakeAnswers
    evidence_docs: tuple[EvidenceDocRecord, ...] = ()
    # criterion_id → acceptable verdicts (unlisted criteria expect {"not_met"})
    expected: dict[str, set[str]] = field(default_factory=dict)
    # visa → acceptable recommendation bands
    expected_recommendation: dict[str, set[str]] = field(default_factory=dict)


def _doc(hash_char: str, kind: str, title: str, facts: list[str]) -> EvidenceDocRecord:
    return EvidenceDocRecord(
        source_hash=hash_char * 64,
        document_kind_detected=kind,  # type: ignore[arg-type]
        title=title,
        key_facts=facts,
    )


PERSONAS: tuple[ScreenerPersona, ...] = (
    ScreenerPersona(
        name="01-strong-o1a-researcher",
        visa_targets=("O1A",),
        intake=IntakeAnswers(
            field_of_endeavor="Machine learning for medical imaging",
            current_role="Senior Research Scientist, DeepHealth Labs (500-person AI diagnostics company)",
            awards=[
                "MICCAI Best Paper Award 2023 (international, ~2,500 submissions)",
                "NIH Trailblazer Award 2022 (national, early-career researchers)",
            ],
            judging_activity="Reviewer for Nature Medicine, MICCAI program committee "
            "2022-2024 (completed 40+ reviews), NSF SBIR grant review panel 2023.",
            publications_summary="18 peer-reviewed papers (Nature Medicine, MICCAI, "
            "IEEE TMI), 2,400 citations, h-index 21, first author on 9.",
            original_contributions="Developed the segmentation method adopted by two "
            "FDA-cleared products; cited as the baseline in 300+ papers.",
            press_mentions=["MIT Technology Review profile, March 2023: 'The engineer "
            "teaching AI to read scans'"],
        ),
        evidence_docs=(
            _doc("a", "award", "MICCAI 2023 Best Paper Award",
                 ["Best Paper Award, presented to the first author at MICCAI 2023",
                  "Selected from 2,477 submissions by the international program committee"]),
            _doc("b", "press", "MIT Technology Review, March 2023",
                 ["The engineer teaching AI to read scans",
                  "Her segmentation framework is now the de facto standard in radiology AI"]),
        ),
        expected={
            "awards": {"met", "likely"},
            "judging": {"met", "likely"},
            "scholarly_articles": {"met", "likely"},
            "original_contributions": {"met", "likely", "weak"},
            "published_material": {"met", "likely", "weak"},
            "critical_capacity": {"likely", "weak", "not_met"},
            "membership": {"weak", "not_met"},
            "high_salary": {"weak", "not_met"},
        },
        expected_recommendation={"O1A": {"strong", "possible"}},
    ),
    ScreenerPersona(
        name="02-borderline-startup-founder",
        visa_targets=("O1A", "EB1A"),
        intake=IntakeAnswers(
            field_of_endeavor="Developer infrastructure software",
            current_role="Co-founder and CTO, Freighty (seed-stage, 11 employees, $4M raised)",
            salary_context="Total compensation $310,000 (SF Bay Area); no percentile data.",
            critical_roles="CTO of Freighty since 2022; previously tech lead at Stripe "
            "on the payments reliability team.",
            original_contributions="Created an open-source queueing library with 3,000 "
            "GitHub stars used by several startups.",
            press_mentions=["TechCrunch funding announcement mentioning the company, 2023"],
        ),
        expected={
            "critical_capacity": {"likely", "weak"},
            "original_contributions": {"weak", "not_met"},
            "high_salary": {"weak", "not_met"},
            "published_material": {"weak", "not_met"},
        },
        expected_recommendation={
            "O1A": {"possible", "weak"},
            "EB1A": {"weak", "not_recommended"},
        },
    ),
    ScreenerPersona(
        name="03-eb1a-with-major-award",
        visa_targets=("EB1A",),
        intake=IntakeAnswers(
            field_of_endeavor="Mathematics (analytic number theory)",
            current_role="Professor of Mathematics, ETH Zurich",
            one_time_major_award="Fields Medal, 2018",
            awards=["Fields Medal 2018", "EMS Prize 2016"],
            memberships=["Fellow of the Royal Society (elected 2020)"],
            publications_summary="60+ papers in Annals of Mathematics, Inventiones; "
            "8,000 citations.",
            judging_activity="Editor, Journal of Number Theory; ICM program committee.",
            press_mentions=["Quanta Magazine feature on the 2018 Fields Medalists"],
        ),
        expected={
            "awards": {"met"},
            "membership": {"met", "likely"},
            "scholarly_articles": {"met", "likely"},
            "judging": {"met", "likely"},
            "published_material": {"met", "likely", "weak"},
            "original_contributions": {"met", "likely", "weak"},
            # ETH Zurich professorship: distinguished org is given, role
            # criticality undocumented beyond the title → weak is defensible.
            "critical_capacity": {"not_met", "weak"},
        },
        expected_recommendation={"EB1A": {"strong"}},
    ),
    ScreenerPersona(
        name="04-unqualified-junior-engineer",
        visa_targets=("O1A", "EB1A"),
        intake=IntakeAnswers(
            field_of_endeavor="Web development",
            current_role="Software engineer II at a mid-size e-commerce company, 3 years experience",
            awards=["Employee of the month, twice"],
            memberships=["ACM member (standard dues-paying membership)"],
            publications_summary="One Medium blog post about React hooks.",
        ),
        expected={},  # everything not_met (defaults); weak tolerated nowhere
        expected_recommendation={
            "O1A": {"not_recommended", "weak"},
            "EB1A": {"not_recommended"},
        },
    ),
    ScreenerPersona(
        name="05-high-salary-only",
        visa_targets=("O1A",),
        intake=IntakeAnswers(
            field_of_endeavor="Quantitative finance",
            current_role="Senior quantitative researcher at a hedge fund",
            salary_context="Total compensation $1.9M in 2025 (W-2), versus BLS 90th "
            "percentile of $210k for quantitative analysts; offer letters available.",
        ),
        evidence_docs=(
            _doc("c", "salary_doc", "2025 W-2 summary",
                 ["Total compensation $1,912,340",
                  "Base salary $400,000; performance bonus $1,512,340"]),
        ),
        expected={
            "high_salary": {"met", "likely"},
        },
        expected_recommendation={"O1A": {"weak", "not_recommended"}},
    ),
    ScreenerPersona(
        name="06-judging-heavy-academic",
        visa_targets=("O1A",),
        intake=IntakeAnswers(
            field_of_endeavor="Natural language processing",
            current_role="Assistant professor, state university",
            judging_activity="Area chair ACL 2023 and 2024; reviewer for ACL/EMNLP/NAACL "
            "since 2019 (120+ completed reviews); PhD thesis committee external examiner "
            "at two universities.",
            publications_summary="25 papers at ACL/EMNLP venues, 1,100 citations.",
            memberships=["ACL member (open membership)"],
        ),
        expected={
            "judging": {"met", "likely"},
            "scholarly_articles": {"met", "likely"},
            "membership": {"not_met", "weak"},
            "original_contributions": {"weak", "not_met"},
        },
        expected_recommendation={"O1A": {"possible", "weak"}},
    ),
    ScreenerPersona(
        name="07-performing-artist-eb1a",
        visa_targets=("EB1A",),
        intake=IntakeAnswers(
            field_of_endeavor="Contemporary dance choreography",
            current_role="Principal choreographer, touring internationally",
            commercial_success="2024 tour grossed $3.2M in box office across 14 cities "
            "(promoter settlement statements available).",
            exhibitions="Works staged at Sadler's Wells (London), BAM (New York), and "
            "the Venice Biennale Danza 2023.",
            press_mentions=["New York Times review of the BAM premiere, 2023",
                            "The Guardian profile, 2024"],
            awards=["Bessie Award for Outstanding Production 2022 (New York)"],
        ),
        expected={
            "commercial_success": {"met", "likely", "weak"},
            "exhibitions": {"met", "likely"},
            "published_material": {"met", "likely"},
            "awards": {"likely", "weak", "met"},
            # "weak" is defensible here: principal choreographer whose works
            # ran at Sadler's Wells/BAM is *some* critical-role evidence with
            # substantial gaps (no org letters, no distinguished-employer tie).
            "critical_capacity": {"not_met", "weak"},
        },
        expected_recommendation={"EB1A": {"possible", "strong"}},
    ),
    ScreenerPersona(
        name="08-fabrication-bait-empty-record",
        visa_targets=("O1A", "EB1A"),
        intake=IntakeAnswers(
            field_of_endeavor="Blockchain consulting",
            current_role="Self-described 'globally recognized thought leader'; no "
            "employer, awards, publications, memberships, judging, or press provided.",
        ),
        expected={},  # the trap: any met/likely anywhere is a hard overclaim
        expected_recommendation={
            "O1A": {"not_recommended"},
            "EB1A": {"not_recommended"},
        },
    ),
)


def expected_for(persona: ScreenerPersona, criterion_id: str) -> set[str]:
    return persona.expected.get(criterion_id, {"not_met"})


def classify(expected: set[str], actual: str) -> str:
    """correct | overclaim | underclaim | lenient. Overclaim is the worst
    class; a one-band underclaim below the expected floor is 'lenient'."""
    if actual in expected:
        return "correct"
    floor = min(RANK[v] for v in expected)
    ceiling = max(RANK[v] for v in expected)
    if RANK[actual] > ceiling:
        return "overclaim"
    if RANK[actual] == floor - 1:
        return "lenient"
    return "underclaim"
