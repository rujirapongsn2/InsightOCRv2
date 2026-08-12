from app.schemas.document import DocumentUpdate


def test_document_update_accepts_edited_ocr_text():
    update = DocumentUpdate(ocr_text="Corrected document text", status="reviewed")

    assert update.ocr_text == "Corrected document text"
    assert update.model_dump(exclude_unset=True)["ocr_text"] == "Corrected document text"
