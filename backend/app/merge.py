"""Server-side merge of passport front/back extractions.

The front side is authoritative; the back side only fills fields the front
left null (many passports carry no machine-readable data on the back, so a
sparse or non-passport back is a notice, not a failure).
"""
from app.schemas import ExtractionEnvelope, FieldWarning


def merge_passport_envelopes(
    front: ExtractionEnvelope, back: ExtractionEnvelope | None
) -> ExtractionEnvelope:
    if back is None:
        return front

    warnings = list(front.warnings) + [
        FieldWarning(field=f"back:{w.field}", message=w.message) for w in back.warnings
    ]

    merged_data = dict(front.data) if front.data is not None else None
    if back.document_type_detected != "passport":
        warnings.append(
            FieldWarning(
                field="back:document_type_detected",
                message=(
                    "The back-side image does not look like a passport "
                    f"(detected: {back.document_type_detected}). Its data was ignored — "
                    "re-upload the back side if you expected information from it."
                ),
            )
        )
    elif back.data is not None:
        if merged_data is None:
            merged_data = dict(back.data)
        else:
            filled_from_back = [
                key
                for key, value in back.data.items()
                if merged_data.get(key) is None and value is not None
            ]
            for key in filled_from_back:
                merged_data[key] = back.data[key]
            if filled_from_back:
                warnings.append(
                    FieldWarning(
                        field="back:merge",
                        message=(
                            "Filled from the back side: " + ", ".join(filled_from_back)
                        ),
                    )
                )

    return ExtractionEnvelope(
        document_type_requested=front.document_type_requested,
        document_type_detected=front.document_type_detected,
        data=merged_data,
        warnings=warnings,
        model_used=front.model_used,
        source_hash=front.source_hash,
    )
