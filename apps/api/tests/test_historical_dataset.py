import csv
from datetime import date
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database.session import Base
from app.models.historical_case import HistoricalCase
from app.services.dataset import HistoricalDatasetIngestor, load_dataset, normalize_record


def test_normalization_and_empty_values():
    case = normalize_record({"case_id":" HC-1 ","title":"  Missing   person ","summary":" none ","description":" last seen near station ","date":"2020/01/02","location":"  Pune ","unknown_field":"source detail"})
    assert case.external_id == "HC-1"
    assert case.title == "Missing person"
    assert case.summary is None
    assert case.case_date == date(2020,1,2)
    assert "Description" in case.text_content and "Location" in case.text_content
    assert case.metadata["source_fields"]["unknown_field"] == "source detail"

def test_dataset_image_references_are_preserved_without_fabrication():
    case = normalize_record({"title":"Archive case", "description":"Source notes", "image_path":"photos/source.webp", "image_url":"https://archive.example/image.webp", "source_url":"https://archive.example/case"})
    assert case.images == [{"path":"photos/source.webp", "url":None, "source_name":None, "source_url":None}, {"path":None, "url":"https://archive.example/image.webp", "source_name":None, "source_url":None}]

def test_validation_rejects_missing_and_malformed_data():
    try:
        normalize_record({"title":"Empty case"})
        assert False, "empty records must be rejected"
    except ValueError as exc:
        assert "descriptive fields" in str(exc)
    try:
        normalize_record({"title":"Case","description":"Details","date":"yesterday"})
        assert False, "malformed dates must be rejected"
    except ValueError as exc:
        assert "Malformed date" in str(exc)

def test_csv_json_and_jsonl_loaders(tmp_path):
    csv_path=tmp_path/"cases.csv"
    csv_path.write_text("external_id,title,description\n1,Case one,Details\n",encoding="utf-8")
    assert load_dataset(csv_path)[0][1]["title"] == "Case one"
    json_path=tmp_path/"cases.json"
    json_path.write_text('[{"title":"One"}]',encoding="utf-8")
    assert load_dataset(json_path)[0][1]["title"] == "One"
    jsonl_path=tmp_path/"cases.jsonl"
    jsonl_path.write_text('{"title":"One"}\nnot-json\n',encoding="utf-8")
    records=load_dataset(jsonl_path)
    assert records[0][1]["title"] == "One"
    assert "__invalid_record__" in records[1][1]
    empty_path=tmp_path/"empty.json"
    empty_path.write_text("[]",encoding="utf-8")
    assert load_dataset(empty_path)==[]

def test_ingestion_reports_invalid_and_duplicate_rows_and_is_idempotent(tmp_path, monkeypatch):
    engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.services.dataset.HistoricalIndexService.rebuild",lambda self,**kwargs:{"status":"READY","indexed_count":1})
    monkeypatch.setattr("app.services.dataset.HistoricalImageIndexService.rebuild",lambda self,**kwargs:{"status":"NO_CORPUS","indexed_count":0})
    path=tmp_path/"cases.csv"
    path.write_text("external_id,title,description,date\nX,Case X,Found near river,2020-01-02\nX,Duplicate case,Found near river,2020-01-02\n,Missing title,description,\nY,Malformed date,Details,bad\n",encoding="utf-8")
    with Session(engine) as session:
        report=HistoricalDatasetIngestor(session).ingest(path)
        assert report.total_records==4 and report.valid_records==2 and report.duplicates==0 and report.invalid_records==2
        repeated=HistoricalDatasetIngestor(session).ingest(path)
        count=session.scalar(select(func.count()).select_from(HistoricalCase))
        assert repeated.valid_records==2 and count==2
    Base.metadata.drop_all(engine)
