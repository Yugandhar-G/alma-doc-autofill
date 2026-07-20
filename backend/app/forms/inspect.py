"""Field inspector — dump a library PDF's widget inventory for map authoring.

Run: cd backend && python -m app.forms.inspect I-129
Prints page, type, fully-qualified field name, and checkbox on-states /
combobox choices, so a field map can be authored against verified names
instead of guesses.
"""
import sys

import fitz

from app.forms.fill import library_pdf_path


def main(form_id: str) -> int:
    path = library_pdf_path(form_id)
    doc = fitz.open(path)
    print(f"# {path.name} — {doc.page_count} pages")
    count = 0
    for pno, page in enumerate(doc, start=1):
        for w in page.widgets() or []:
            count += 1
            extra = ""
            if w.field_type_string == "CheckBox":
                extra = f"  on={w.on_state()!r}"
            elif w.field_type_string == "ComboBox":
                choices = [v for v, _ in (w.choice_values or [])][:10]
                extra = f"  choices={choices}"
            print(f"p{pno:<3} [{w.field_type_string:<8}] {w.field_name}{extra}")
    print(f"# {count} fields")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m app.forms.inspect <FORM-ID>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
