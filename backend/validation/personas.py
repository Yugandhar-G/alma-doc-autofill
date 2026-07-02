"""20 synthetic G-28 personas for the validation harness.

Each persona lists (printed_value, expected_extraction) per varied field —
printed is what gets stamped into the PDF, expected is what the pipeline
must return after normalization (e.g. "TX" printed → "Texas" extracted,
"N/A" printed → None). Unvaried fields inherit BASE_EXPECTED.

All names/values are synthetic. Diacritics, apostrophes, and hyphens are
deliberate: transcribe-exactly-as-printed is part of the contract.
"""

# Ground truth of the unmodified Example_G-28.pdf, keyed by dotted schema path.
BASE_EXPECTED: dict[str, object] = {
    "attorney.online_account_number": None,
    "attorney.family_name": "Smith",
    "attorney.given_name": "Barbara",
    "attorney.middle_name": None,
    "attorney.street_number_and_name": "545 Bryant Street",
    "attorney.apt_ste_flr": None,
    "attorney.apt_ste_flr_number": None,
    "attorney.city": "Palo Alto",
    "attorney.state": "California",
    "attorney.zip_code": "94301",
    "attorney.country": "United States of America",
    "attorney.daytime_phone": None,
    "attorney.mobile_phone": None,
    "attorney.email": "immigration@tryalma.ai",
    "eligibility.is_attorney": True,
    "eligibility.licensing_authority": "State Bar of California",
    "eligibility.bar_number": "12083456",
    "eligibility.subject_to_discipline": False,
    "eligibility.law_firm": "Alma Legal Services PC",
    "beneficiary.family_name": "Jonas",
    "beneficiary.given_name": "Joe",
    "beneficiary.middle_name": None,
}

# Unchecked-checkbox booleans where None and False are both acceptable.
LENIENT_FIELDS: dict[str, tuple] = {
    "eligibility.is_accredited_representative": (None, False),
    "eligibility.is_associated": (None, False),
    "eligibility.is_law_student": (None, False),
    "eligibility.recognized_organization": (None,),
    "eligibility.accreditation_date": (None,),
    "eligibility.associated_with_name": (None,),
    "eligibility.law_student_name": (None,),
}

# Varied-field key → (printed value, expected extraction).
# Keys map 1:1 to generator.FIELD_SPECS.
Persona = dict[str, tuple[str, object]]

PERSONAS: dict[str, Persona] = {
    "01-baseline-texas": {
        "family": ("Ramírez", "Ramírez"),
        "given": ("Elena", "Elena"),
        "state": ("TX", "Texas"),
        "city": ("Austin", "Austin"),
        "zip": ("73301", "73301"),
        "bar": ("24011223", "24011223"),
        "licensing": ("State Bar of Texas", "State Bar of Texas"),
    },
    "02-apostrophe-newyork": {
        "family": ("O'Brien", "O'Brien"),
        "given": ("Seán", "Seán"),
        "state": ("NY", "New York"),
        "city": ("Brooklyn", "Brooklyn"),
        "zip": ("11201", "11201"),
        "email": ("sean.obrien@obrienlaw.com", "sean.obrien@obrienlaw.com"),
    },
    "03-hyphenated-florida": {
        "family": ("García-Muñoz", "García-Muñoz"),
        "given": ("José", "José"),
        "state": ("FL", "Florida"),
        "city": ("Miami", "Miami"),
        "zip": ("33101", "33101"),
        "law_firm": ("García-Muñoz & Partners LLP", "García-Muñoz & Partners LLP"),
    },
    "04-na-email-illinois": {
        "family": ("Kowalski", "Kowalski"),
        "state": ("IL", "Illinois"),
        "city": ("Chicago", "Chicago"),
        "zip": ("60601", "60601"),
        "email": ("N/A", None),  # N/A trap on a normally-filled field
    },
    "05-mobile-filled-washington": {
        "family": ("Nakamura", "Nakamura"),
        "given": ("Kenji", "Kenji"),
        "state": ("WA", "Washington"),
        "city": ("Seattle", "Seattle"),
        "zip": ("98101", "98101"),
        "mobile": ("6502223344", "6502223344"),  # normally-N/A field gets a value
    },
    "06-diacritics-massachusetts": {
        "family": ("Müller", "Müller"),
        "given": ("Sørine", "Sørine"),
        "state": ("MA", "Massachusetts"),
        "city": ("Cambridge", "Cambridge"),
        "zip": ("02139", "02139"),
        "beneficiary_family": ("Nguyễn", "Nguyễn"),
        "beneficiary_given": ("Thi Minh", "Thi Minh"),
    },
    "07-dc-district": {
        "family": ("Washington", "Washington"),
        "state": ("DC", "District of Columbia"),
        "city": ("Washington", "Washington"),
        "zip": ("20001", "20001"),
        "licensing": ("DC Bar", "DC Bar"),
    },
    "08-long-firm-georgia": {
        "family": ("Abernathy", "Abernathy"),
        "state": ("GA", "Georgia"),
        "city": ("Atlanta", "Atlanta"),
        "zip": ("30301", "30301"),
        "law_firm": (
            "Abernathy Immigration Advocates of Greater Atlanta PC",
            "Abernathy Immigration Advocates of Greater Atlanta PC",
        ),
    },
    "09-na-bar-arizona": {
        "family": ("Slessor", "Slessor"),
        "state": ("AZ", "Arizona"),
        "city": ("Phoenix", "Phoenix"),
        "zip": ("85001", "85001"),
        "bar": ("N/A", None),  # N/A trap on bar number
    },
    "10-colorado-street": {
        "family": ("Petrov", "Petrov"),
        "given": ("Anastasiya", "Anastasiya"),
        "state": ("CO", "Colorado"),
        "city": ("Denver", "Denver"),
        "zip": ("80014", "80014"),
        "street": ("1234 Colfax Avenue Unit 9", "1234 Colfax Avenue Unit 9"),
    },
    "11-oregon-email-plus": {
        "family": ("van der Berg", "van der Berg"),
        "state": ("OR", "Oregon"),
        "city": ("Portland", "Portland"),
        "zip": ("97201", "97201"),
        "email": ("t.vdberg+g28@bergimmigration.org", "t.vdberg+g28@bergimmigration.org"),
    },
    "12-michigan-beneficiary": {
        "family": ("Haddad", "Haddad"),
        "state": ("MI", "Michigan"),
        "city": ("Dearborn", "Dearborn"),
        "zip": ("48120", "48120"),
        "beneficiary_family": ("Al-Rashid", "Al-Rashid"),
        "beneficiary_given": ("Layla", "Layla"),
    },
    "13-northcarolina-numbers": {
        "family": ("Whitfield", "Whitfield"),
        "state": ("NC", "North Carolina"),
        "city": ("Charlotte", "Charlotte"),
        "zip": ("28201", "28201"),
        "bar": ("55501", "55501"),
    },
    "14-newjersey-country": {
        "family": ("Rossi", "Rossi"),
        "given": ("Giulia", "Giulia"),
        "state": ("NJ", "New Jersey"),
        "city": ("Newark", "Newark"),
        "zip": ("07101", "07101"),
        "country": ("USA", "United States of America"),  # abbreviation → normalized
    },
    "15-virginia-licensing": {
        "family": ("Thompson", "Thompson"),
        "state": ("VA", "Virginia"),
        "city": ("Arlington", "Arlington"),
        "zip": ("22201", "22201"),
        "licensing": ("Virginia State Bar", "Virginia State Bar"),
    },
    "16-pennsylvania-all-caps": {
        "family": ("KAMINSKI", "KAMINSKI"),  # printed caps → transcribed as printed
        "given": ("PIOTR", "PIOTR"),
        "state": ("PA", "Pennsylvania"),
        "city": ("Philadelphia", "Philadelphia"),
        "zip": ("19101", "19101"),
    },
    "17-minnesota-short-names": {
        "family": ("Ng", "Ng"),
        "given": ("Bo", "Bo"),
        "state": ("MN", "Minnesota"),
        "city": ("St. Paul", "St. Paul"),
        "zip": ("55101", "55101"),
        "beneficiary_family": ("Xu", "Xu"),
        "beneficiary_given": ("Li", "Li"),
    },
    "18-nevada-email-na-mobile": {
        "family": ("Delacroix-Beaumont", "Delacroix-Beaumont"),
        "given": ("Anaïs", "Anaïs"),
        "state": ("NV", "Nevada"),
        "city": ("Las Vegas", "Las Vegas"),
        "zip": ("89101", "89101"),
        "mobile": ("7025551234", "7025551234"),
    },
    "19-ohio-firm-punctuation": {
        "family": ("Esposito", "Esposito"),
        "state": ("OH", "Ohio"),
        "city": ("Columbus", "Columbus"),
        "zip": ("43004", "43004"),
        "law_firm": ("Esposito, Reyes & Chen, L.L.C.", "Esposito, Reyes & Chen, L.L.C."),
    },
    "20-california-control": {
        # control: nothing varied except beneficiary — near-original document
        "beneficiary_family": ("Okafor", "Okafor"),
        "beneficiary_given": ("Chidi", "Chidi"),
    },
}

# printed-field key → dotted schema path (for computing expected ground truth)
KEY_TO_PATH: dict[str, str] = {
    "family": "attorney.family_name",
    "given": "attorney.given_name",
    "street": "attorney.street_number_and_name",
    "city": "attorney.city",
    "state": "attorney.state",
    "zip": "attorney.zip_code",
    "country": "attorney.country",
    "mobile": "attorney.mobile_phone",
    "email": "attorney.email",
    "licensing": "eligibility.licensing_authority",
    "bar": "eligibility.bar_number",
    "law_firm": "eligibility.law_firm",
    "beneficiary_family": "beneficiary.family_name",
    "beneficiary_given": "beneficiary.given_name",
}


def expected_for(persona: Persona) -> dict[str, object]:
    """Ground truth for one persona: base document + overridden expectations."""
    expected = dict(BASE_EXPECTED)
    for key, (_printed, expected_value) in persona.items():
        expected[KEY_TO_PATH[key]] = expected_value
    return expected
