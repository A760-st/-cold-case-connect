from app.geospatial.normalizer import infer_precision, normalize_location


def test_location_normalization_preserves_raw_text_while_normalizing_aliases():
    assert normalize_location("  Bangalore, Karnataka  ") == "bengaluru, karnataka"
    assert normalize_location("Near  MG Road") == "near mg road"
    assert normalize_location("") == ""


def test_precision_inference_does_not_turn_approximate_text_into_exact_point():
    assert infer_precision("Near the old station").value == "APPROXIMATE"
    assert infer_precision("42 MG Road").value == "STREET"
    assert infer_precision("Bengaluru").value == "CITY"


def test_explicit_source_precision_takes_precedence():
    assert infer_precision("Bengaluru", {"precision": "REGION"}).value == "REGION"
