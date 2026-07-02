"""Offline tests for the extraction engine: guardrail ordering, loud
missing-key failure, and the escalation/wrapper helpers. No network calls."""
import pytest

from app.config import Settings
from app.extraction import engine
from app.extraction.engine import _all_fields_null, _wrapper_model, extract_document
from app.schemas import G28Data, PassportData
from tests.conftest import image_bytes, make_flat_image, make_noise_image


@pytest.fixture(autouse=True)
def keyless_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Force key-absent, env-isolated settings so no test can hit the API."""
    settings = Settings(_env_file=None, gemini_api_key=None)
    monkeypatch.setattr(engine, "get_settings", lambda: settings)
    return settings


class TestGuardrailOrdering:
    async def test_unknown_format_rejected_before_any_model_concern(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized file format"):
            await extract_document(b"not a document", "junk.txt", "passport")

    async def test_blurry_image_rejected_before_key_is_needed(self) -> None:
        blurry = image_bytes(make_flat_image(900, 900), "JPEG")
        with pytest.raises(ValueError, match="too blurry"):
            await extract_document(blurry, "scan.jpg", "passport")

    async def test_good_image_without_key_fails_loud(self) -> None:
        sharp = image_bytes(make_noise_image(900, 900), "PNG")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
            await extract_document(sharp, "scan.png", "passport")


class TestWrapperModel:
    @pytest.mark.parametrize(
        ("doc_type", "data_model"), [("passport", PassportData), ("g28", G28Data)]
    )
    def test_wrapper_shape(self, doc_type: str, data_model: type) -> None:
        wrapper = _wrapper_model(doc_type)
        instance = wrapper(document_type_detected="other", data=data_model())
        assert instance.document_type_detected == "other"
        assert isinstance(instance.data, data_model)

    def test_wrapper_rejects_unknown_detected_type(self) -> None:
        wrapper = _wrapper_model("passport")
        with pytest.raises(Exception):
            wrapper(document_type_detected="invoice", data=PassportData())


class TestAllFieldsNull:
    def test_fresh_models_are_all_null(self) -> None:
        assert _all_fields_null(PassportData().model_dump())
        assert _all_fields_null(G28Data().model_dump())

    def test_single_populated_leaf_flips_it(self) -> None:
        g28 = G28Data()
        g28 = g28.model_copy(
            update={"beneficiary": g28.beneficiary.model_copy(
                update={"family_name": "Jonas"})}
        )
        assert not _all_fields_null(g28.model_dump())

    def test_false_is_a_value_not_a_null(self) -> None:
        assert not _all_fields_null({"subject_to_discipline": False})
