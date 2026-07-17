"""USCIS criteria registry — the regulatory knowledge as data, not prose.

Every prompt that mentions a criterion interpolates from this registry, so
the legal framing lives in exactly one reviewable place. Refs verified
against 8 CFR 214.2(o)(3)(iii) (O-1A) and 8 CFR 204.5(h)(3) (EB-1A).
"""
from dataclasses import dataclass

VisaType = str  # "O1A" | "EB1A" (Literal lives in schemas; this module stays stdlib-only)

O1A_THRESHOLD = 3
EB1A_THRESHOLD = 3


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    title: str
    o1a_ref: str | None      # 8 CFR 214.2(o)(3)(iii)(B)(n), None if O-1A lacks it
    eb1a_ref: str | None     # 8 CFR 204.5(h)(3)(n), None if EB-1A lacks it
    description: str         # regulatory language, paraphrased
    strong_evidence: tuple[str, ...]   # what adjudicators actually accept
    rfe_patterns: tuple[str, ...]      # common RFE triggers for this criterion

    @property
    def applies_to(self) -> frozenset[str]:
        visas = set()
        if self.o1a_ref:
            visas.add("O1A")
        if self.eb1a_ref:
            visas.add("EB1A")
        return frozenset(visas)


CRITERIA: tuple[CriterionSpec, ...] = (
    CriterionSpec(
        id="awards",
        title="Nationally or internationally recognized prizes or awards",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(1)",
        eb1a_ref="8 CFR 204.5(h)(3)(i)",
        description=(
            "Receipt of nationally or internationally recognized prizes or "
            "awards for excellence in the field of endeavor."
        ),
        strong_evidence=(
            "Award certificate plus documentation of the award's national/international scope",
            "Selection criteria and pool size showing the award recognizes excellence",
            "Media coverage of the award itself (not just the recipient)",
        ),
        rfe_patterns=(
            "Award is institutional, local, or student-level (e.g. university-internal)",
            "No evidence of the award's recognition beyond the granting organization",
            "Team award without evidence of the individual's role",
        ),
    ),
    CriterionSpec(
        id="membership",
        title="Membership in associations requiring outstanding achievement",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(2)",
        eb1a_ref="8 CFR 204.5(h)(3)(ii)",
        description=(
            "Membership in associations in the field which require outstanding "
            "achievements of their members, as judged by recognized national or "
            "international experts."
        ),
        strong_evidence=(
            "Membership bylaws showing outstanding achievement is a condition of admission",
            "Evidence that admission is judged by recognized experts (e.g. elected fellowship)",
            "IEEE/ACM Fellow, National Academy membership, or equivalent selective grade",
        ),
        rfe_patterns=(
            "Membership obtainable by paying dues or by employment alone (e.g. ordinary IEEE member)",
            "No documentation of the association's admission standards",
        ),
    ),
    CriterionSpec(
        id="published_material",
        title="Published material about the person",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(3)",
        eb1a_ref="8 CFR 204.5(h)(3)(iii)",
        description=(
            "Published material in professional or major trade publications or "
            "major media about the person, relating to their work in the field."
        ),
        strong_evidence=(
            "Articles primarily about the person (not passing mentions), with title, date, author",
            "Circulation/readership evidence establishing the outlet as major media",
            "Trade-press profiles of the person's specific contribution",
        ),
        rfe_patterns=(
            "Material quotes the person but is not about them",
            "Blog or press-release reprints without evidence of the outlet's standing",
            "Coverage of the employer/product with only incidental mention of the person",
        ),
    ),
    CriterionSpec(
        id="judging",
        title="Judging the work of others in the field",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(4)",
        eb1a_ref="8 CFR 204.5(h)(3)(iv)",
        description=(
            "Participation, on a panel or individually, as a judge of the work "
            "of others in the same or an allied field."
        ),
        strong_evidence=(
            "Peer-review invitations and completed-review records from journals or conferences",
            "Program-committee or grant-review-panel appointment letters",
            "Judging documentation for recognized competitions or hackathons of standing",
        ),
        rfe_patterns=(
            "A single review with no evidence it was completed",
            "Internal code review or hiring interviews presented as 'judging'",
            "No evidence of the venue's standing in the field",
        ),
    ),
    CriterionSpec(
        id="original_contributions",
        title="Original contributions of major significance",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(5)",
        eb1a_ref="8 CFR 204.5(h)(3)(v)",
        description=(
            "Original scientific, scholarly, or business-related contributions "
            "of major significance in the field."
        ),
        strong_evidence=(
            "Citation record showing broad adoption of the person's specific work",
            "Expert letters tracing how the contribution changed practice in the field",
            "Patents with documented licensing/implementation by others",
            "Widely adopted open-source work with independent usage evidence",
        ),
        rfe_patterns=(
            "Originality shown but 'major significance' undocumented — the most common RFE",
            "Expert letters that assert impact without independent corroboration",
            "Patent filings with no evidence anyone uses the invention",
        ),
    ),
    CriterionSpec(
        id="scholarly_articles",
        title="Authorship of scholarly articles",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(6)",
        eb1a_ref="8 CFR 204.5(h)(3)(vi)",
        description=(
            "Authorship of scholarly articles in the field, in professional "
            "journals or other major media."
        ),
        strong_evidence=(
            "First-author publications in peer-reviewed venues with the venue's standing documented",
            "Citation counts contextualized against the field's norms",
            "Invited papers, keynotes, or book chapters in recognized outlets",
        ),
        rfe_patterns=(
            "Publications listed without evidence the venues are peer-reviewed or major",
            "Middle-author papers with no statement of the person's contribution",
        ),
    ),
    CriterionSpec(
        id="critical_capacity",
        title="Critical or essential role for distinguished organizations",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(7)",
        eb1a_ref="8 CFR 204.5(h)(3)(viii)",
        description=(
            "Employment in a critical or essential capacity (O-1A) or a leading "
            "or critical role (EB-1A) for organizations or establishments with "
            "a distinguished reputation."
        ),
        strong_evidence=(
            "Org charts and letters showing the role was critical to the organization's outcomes",
            "Evidence of the organization's distinguished reputation (funding, rankings, press)",
            "Founding-engineer/tech-lead roles tied to concrete shipped outcomes",
        ),
        rfe_patterns=(
            "Senior title without evidence the role itself was critical",
            "Distinguished employer but generic job duties",
            "Startup employer with no evidence of distinguished reputation",
        ),
    ),
    CriterionSpec(
        id="high_salary",
        title="High salary or remuneration",
        o1a_ref="8 CFR 214.2(o)(3)(iii)(B)(8)",
        eb1a_ref="8 CFR 204.5(h)(3)(ix)",
        description=(
            "Command of a high salary or other significantly high remuneration "
            "for services, in relation to others in the field."
        ),
        strong_evidence=(
            "W-2/offer letters plus BLS or survey percentile data for the same role and geography",
            "Equity valuations with documented methodology",
            "Evidence salary sits at/above the 90th percentile for the field",
        ),
        rfe_patterns=(
            "High absolute salary with no comparator data for role and geography",
            "Total-comp claims mixing unvested equity without valuation evidence",
        ),
    ),
    CriterionSpec(
        id="exhibitions",
        title="Display of work at artistic exhibitions or showcases",
        o1a_ref=None,
        eb1a_ref="8 CFR 204.5(h)(3)(vii)",
        description=(
            "Display of the person's work in the field at artistic exhibitions "
            "or showcases. (EB-1A only; USCIS reads this as artistic display, "
            "though comparable evidence may apply for non-artists.)"
        ),
        strong_evidence=(
            "Exhibition catalogs, invitations, and venue-standing documentation",
            "Juried-show selection records",
        ),
        rfe_patterns=(
            "Conference demos or trade-show booths presented as artistic exhibition",
            "Group shows with no evidence of the person's individual selection",
        ),
    ),
    CriterionSpec(
        id="commercial_success",
        title="Commercial success in the performing arts",
        o1a_ref=None,
        eb1a_ref="8 CFR 204.5(h)(3)(x)",
        description=(
            "Commercial success in the performing arts, as shown by box office "
            "receipts or record, cassette, compact disk, or video sales. (EB-1A only.)"
        ),
        strong_evidence=(
            "Box-office or sales figures from independent sources (not self-reported)",
            "Chart positions, streaming numbers with platform documentation",
        ),
        rfe_patterns=(
            "Self-reported revenue with no third-party corroboration",
            "Business revenue presented for a non-performing-arts field",
        ),
    ),
)

CRITERIA_BY_ID: dict[str, CriterionSpec] = {spec.id: spec for spec in CRITERIA}


def criteria_for(visa: str) -> tuple[CriterionSpec, ...]:
    """Applicable criteria for one visa type, registry order preserved."""
    return tuple(spec for spec in CRITERIA if visa in spec.applies_to)


def criteria_for_targets(visa_targets: list[str]) -> tuple[CriterionSpec, ...]:
    """Union of applicable criteria across the targeted visa types."""
    return tuple(
        spec for spec in CRITERIA
        if any(visa in spec.applies_to for visa in visa_targets)
    )
