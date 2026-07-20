"""USCIS criteria registry — the regulatory knowledge as data, not prose.

Every prompt that mentions a criterion interpolates from this registry, so
the legal framing lives in exactly one reviewable place. Refs verified
against 8 CFR 214.2(o)(3)(iii) (O-1A), 8 CFR 204.5(h)(3) (EB-1A), and — for
the national-interest waiver — INA 203(b)(2)(B)(i) / 8 CFR 204.5(k) as read
through Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016).

Registry-as-data proof: NIW plugs in as three more CriterionSpec rows with a
new niw_ref channel and NO new branching. There is no Kazarian two-step for
NIW — its arithmetic (all three Dhanasar prongs required) lives in the report
cap, and routing (route_merits) stays EB-1A-only.
"""
from dataclasses import dataclass

VisaType = str  # "O1A" | "EB1A" | "NIW" (Literal lives in schemas; this module stays stdlib-only)

O1A_THRESHOLD = 3
EB1A_THRESHOLD = 3
# NIW is not a "3 of N" count: all three Dhanasar prongs are required. The
# threshold equals the number of prongs so the shared cap arithmetic collapses
# to "any prong short of met/likely caps the recommendation".
NIW_THRESHOLD = 3


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    title: str
    o1a_ref: str | None      # 8 CFR 214.2(o)(3)(iii)(B)(n), None if O-1A lacks it
    eb1a_ref: str | None     # 8 CFR 204.5(h)(3)(n), None if EB-1A lacks it
    description: str         # regulatory language, paraphrased
    strong_evidence: tuple[str, ...]   # what adjudicators actually accept
    rfe_patterns: tuple[str, ...]      # common RFE triggers for this criterion
    niw_ref: str | None = None  # NIW (Dhanasar prong) basis, None for O-1A/EB-1A rows

    @property
    def applies_to(self) -> frozenset[str]:
        visas = set()
        if self.o1a_ref:
            visas.add("O1A")
        if self.eb1a_ref:
            visas.add("EB1A")
        if self.niw_ref:
            visas.add("NIW")
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
    # --- NIW (EB-2 national-interest waiver) — the three Matter of Dhanasar
    # prongs. All three are REQUIRED (not "3 of N"); there is no Kazarian
    # two-step and no one-time-award bypass. Basis: INA 203(b)(2)(B)(i),
    # 8 CFR 204.5(k), Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016). ---
    CriterionSpec(
        id="niw_merit_importance",
        title="Substantial merit and national importance of the proposed endeavor",
        o1a_ref=None,
        eb1a_ref=None,
        niw_ref="INA 203(b)(2)(B)(i); 8 CFR 204.5(k); Matter of Dhanasar prong 1",
        description=(
            "The proposed endeavor has both substantial merit and national "
            "importance. Merit may be shown in business, science, technology, "
            "culture, health, or education; importance turns on the endeavor's "
            "prospective impact broadly, not merely on the petitioner's employer "
            "or immediate locality."
        ),
        strong_evidence=(
            "A specific, articulated endeavor (not just a job title) with a defined problem it addresses",
            "Evidence the endeavor's impact reaches beyond one employer or region — national scope",
            "Government, industry, or funding-body statements that the work addresses a recognized priority",
            "Metrics, adoption, or third-party analysis showing the field-level significance of the endeavor",
        ),
        rfe_patterns=(
            "Endeavor described as ordinary duties of an occupation rather than a defined undertaking",
            "Merit shown but national importance argued only from the employer's or a locality's benefit",
            "Prospective-impact claims with no evidence beyond the petitioner's assertions",
        ),
    ),
    CriterionSpec(
        id="niw_well_positioned",
        title="Well positioned to advance the proposed endeavor",
        o1a_ref=None,
        eb1a_ref=None,
        niw_ref="INA 203(b)(2)(B)(i); 8 CFR 204.5(k); Matter of Dhanasar prong 2",
        description=(
            "The petitioner is well positioned to advance the proposed endeavor, "
            "assessed from their education, skills, record of success, a model or "
            "plan for future activity, progress toward the endeavor, and the "
            "interest of relevant parties. This prong does not require a "
            "guarantee of ultimate success."
        ),
        strong_evidence=(
            "Record of prior success in the same or a closely related endeavor (traction, results, adoption)",
            "Advanced degree or demonstrated expertise directly tied to the endeavor",
            "A concrete plan or model for future activity with evidence of progress already made",
            "Letters or commitments from users, funders, agencies, or collaborators showing interest and reliance",
        ),
        rfe_patterns=(
            "Qualifications listed with no link to the specific endeavor being advanced",
            "A plan asserted with no evidence of prior progress or independent interest",
            "Reliance on generic praise letters that do not speak to the petitioner's positioning",
        ),
    ),
    CriterionSpec(
        id="niw_benefit_waiver",
        title="On balance, beneficial to waive the job offer and labor certification",
        o1a_ref=None,
        eb1a_ref=None,
        niw_ref="INA 203(b)(2)(B)(i); 8 CFR 204.5(k); Matter of Dhanasar prong 3",
        description=(
            "On balance, it would be beneficial to the United States to waive the "
            "job-offer requirement and thus the labor certification. Factors "
            "include impracticality of labor certification, the national benefit "
            "even if qualified U.S. workers are available, and whether the "
            "endeavor's urgency or the petitioner's contributions make the waiver "
            "worthwhile despite the protective purpose of labor certification."
        ),
        strong_evidence=(
            "Reasons a labor certification is impractical for this endeavor (self-employment, entrepreneurship, evolving work)",
            "Evidence the national benefit is significant enough to outweigh the protective aim of labor certification",
            "Urgency or time-sensitivity of the endeavor that a labor-certification process would frustrate",
            "Petitioner's demonstrated contributions supporting that the U.S. benefits from waiving the offer",
        ),
        rfe_patterns=(
            "Prongs 1 and 2 argued but prong 3 left as a bare conclusion",
            "No explanation why labor certification is impractical or why the benefit outweighs it",
            "Waiver argued solely from the petitioner's convenience rather than national benefit",
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
