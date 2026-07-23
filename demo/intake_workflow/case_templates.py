"""Case-type templates. FROZEN data for parallel work.

The marriage AOS checklist mirrors the document list Yew Legal runs today
(30-50 items in production; trimmed here to a representative demo set).
Swap/extend per firm without touching domain or web code.
"""
from __future__ import annotations

from intake_workflow.schemas import (
    CaseTemplate,
    CategoryRule,
    ItemKind,
    PartyRole,
    QuestionField,
    TemplateItem,
)

P = PartyRole.petitioner
B = PartyRole.beneficiary
DOC = ItemKind.document
QS = ItemKind.question_section


MARRIAGE_AOS = CaseTemplate(
    name="marriage_aos",
    label="Marriage-based Adjustment of Status (I-130 / I-485)",
    min_categories=3,
    categories=[
        CategoryRule(category="financial", label="Financial commingling"),
        CategoryRule(category="cohabitation", label="Living together"),
        CategoryRule(category="insurance", label="Insurance & benefits"),
        CategoryRule(category="travel", label="Travel & life together"),
        CategoryRule(category="affidavits", label="Third-party affidavits"),
    ],
    items=[
        # ------------------------------------------------------ questionnaires
        TemplateItem(
            key="pet_bio", label="Petitioner — Biographic questionnaire",
            kind=QS, assignee=P,
            fields=[
                QuestionField(
                    key="full_name", label="Full legal name",
                    hint="Exactly as it appears on your passport or government ID.",
                ),
                QuestionField(
                    key="dob", label="Date of birth", type="date",
                    hint="The date on your passport or birth certificate.",
                ),
                QuestionField(
                    key="phone", label="Phone number",
                    hint="A number where we can reach you by text or call.",
                ),
                QuestionField(
                    key="address", label="Current home address", type="textarea",
                    hint="Street, unit, city, state, and ZIP.",
                ),
            ],
        ),
        TemplateItem(
            key="ben_bio", label="Beneficiary — Biographic questionnaire",
            kind=QS, assignee=B,
            fields=[
                QuestionField(
                    key="full_name", label="Full legal name",
                    hint="Exactly as it appears on your passport.",
                ),
                QuestionField(
                    key="dob", label="Date of birth", type="date",
                    hint="The date on your passport or birth certificate.",
                ),
                QuestionField(
                    key="a_number", label="A-number", required=False,
                    pattern=r"^A?\d{8,9}$",
                    hint="On your green card or any USCIS notice — the letter A "
                         "followed by 8 or 9 digits, e.g. A123456789. Leave blank "
                         "if you don't have one.",
                ),
                QuestionField(
                    key="i94_number", label="Most recent I-94 number", required=False,
                    pattern=r"^[0-9A-Za-z]{11}$",
                    hint="The 11-character number on your most recent I-94 record — "
                         "find it under 'Get Most Recent I-94' at i94.cbp.dhs.gov. "
                         "Leave blank if you're unsure.",
                ),
                QuestionField(
                    key="last_entry", label="Date of last U.S. entry", type="date",
                    hint="The date you most recently entered the U.S. — check the "
                         "stamp in your passport or your I-94. Leave blank if unsure.",
                ),
                QuestionField(
                    key="current_status", label="Current immigration status",
                    type="select", options=["F-1", "H-1B", "B-1/B-2", "Other"],
                ),
            ],
        ),
        TemplateItem(
            key="marriage_details", label="Marriage details",
            kind=QS, assignee=P,
            fields=[
                QuestionField(
                    key="marriage_date", label="Date of marriage", type="date",
                    hint="The date on your marriage certificate.",
                ),
                QuestionField(
                    key="marriage_place", label="City & state/country of marriage",
                    hint="Where the ceremony took place, e.g. Austin, Texas.",
                ),
                QuestionField(
                    key="prior_marriages", label="Any prior marriages?",
                    type="select", options=["None", "Petitioner", "Beneficiary", "Both"],
                ),
            ],
        ),
        TemplateItem(
            key="ben_address_history", label="Beneficiary — Address history (last 5 years)",
            kind=QS, assignee=B,
            fields=[
                QuestionField(
                    key="current_address", label="Current address", type="textarea",
                    hint="Street, unit, city, state, and ZIP where you live now.",
                ),
                QuestionField(
                    key="moved_in", label="Date moved in", type="date",
                    hint="Roughly when you moved to this address is fine.",
                ),
                QuestionField(
                    key="previous_address", label="Previous address", type="textarea",
                    required=False,
                    hint="Only if you moved within the last 5 years — leave blank otherwise.",
                ),
            ],
        ),
        TemplateItem(
            key="ben_eligibility", label="Beneficiary — Background questions",
            kind=QS, assignee=B,
            description="A few standard questions every applicant must answer.",
            fields=[
                QuestionField(
                    key="criminal_history",
                    label="Have you ever been arrested, charged, or convicted of "
                          "any crime anywhere in the world?",
                    type="select", options=["No", "Yes"],
                ),
                QuestionField(
                    key="criminal_details", label="If yes, briefly describe",
                    type="textarea", required=False,
                ),
                QuestionField(
                    key="immigration_violations",
                    label="Have you ever overstayed a visa, worked without "
                          "authorization, or been ordered removed?",
                    type="select", options=["No", "Yes"],
                ),
                QuestionField(
                    key="violation_details", label="If yes, briefly describe",
                    type="textarea", required=False,
                ),
                QuestionField(
                    key="prior_denials",
                    label="Have you ever been denied a visa or any immigration "
                          "benefit?",
                    type="select", options=["No", "Yes"],
                ),
                QuestionField(
                    key="denial_details", label="If yes, briefly describe",
                    type="textarea", required=False,
                ),
            ],
        ),
        # ------------------------------------------------------- core documents
        TemplateItem(key="marriage_cert", label="Marriage certificate", assignee=P),
        TemplateItem(
            key="pet_citizenship", assignee=P,
            label="Petitioner — Proof of U.S. citizenship",
            description="U.S. passport bio page or naturalization certificate.",
        ),
        TemplateItem(
            key="pet_tax_return", assignee=P,
            label="Petitioner — Most recent federal tax return",
            description="For the I-864 affidavit of support. All pages.",
        ),
        TemplateItem(
            key="pet_employment", assignee=P,
            label="Petitioner — Employment letter or two recent pay stubs",
        ),
        TemplateItem(key="ben_passport", label="Beneficiary — Passport bio page", assignee=B),
        TemplateItem(
            key="ben_birth_cert", assignee=B,
            label="Beneficiary — Birth certificate",
            description="With certified English translation if not in English.",
        ),
        TemplateItem(key="ben_i94", label="Beneficiary — Most recent I-94 record", assignee=B),
        TemplateItem(
            key="ben_photos", label="Beneficiary — Passport-style photos", assignee=B,
            description="Digital is fine; we will print to spec.",
        ),
        # ------------------------------------------- bona fide marriage evidence
        TemplateItem(
            key="joint_bank", assignee=P, category="financial",
            label="Joint bank statements — most recent 6 months",
            description="All pages, showing both names. Either spouse may upload.",
        ),
        TemplateItem(
            key="joint_tax", assignee=P, category="financial", required=False,
            label="Joint tax return or jointly-filed W-2s",
        ),
        TemplateItem(
            key="lease", assignee=B, category="cohabitation",
            label="Lease or deed with both names",
        ),
        TemplateItem(
            key="utility_bill", assignee=B, category="cohabitation", required=False,
            label="Utility bill at your shared address",
        ),
        TemplateItem(
            key="insurance", assignee=P, category="insurance",
            label="Insurance policy naming your spouse",
            description="Health, auto, life, or renters — any policy listing both of you.",
        ),
        TemplateItem(
            key="travel_photos", assignee=B, category="travel",
            label="Photos & travel receipts together over time",
            description="A handful spanning your relationship — trips, events, holidays.",
        ),
        TemplateItem(
            key="affidavits", assignee=B, category="affidavits", required=False,
            label="Affidavits from two people who know you as a couple",
        ),
    ],
)


TEMPLATES: dict[str, CaseTemplate] = {MARRIAGE_AOS.name: MARRIAGE_AOS}


def get_template(name: str) -> CaseTemplate:
    return TEMPLATES[name]
