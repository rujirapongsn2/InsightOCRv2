from datetime import datetime, timezone
from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.api import deps
from app.api.permissions import ensure_document_access, ensure_job_access, is_admin_user
from app.api.v1.endpoints import documents as documents_endpoint
from app.api.v1.endpoints import integrations as integrations_endpoint
from app.models.document import Document
from app.models.integration import Integration, IntegrationStatus
from app.models.job import Job
from app.models.schema import DocumentSchema
from app.models.user import User
from app.schemas.external import (
    ExternalDocumentDecisionRequest,
    ExternalDocumentDetail,
    ExternalDocumentReviewRequest,
    ExternalDocumentStatusResponse,
    ExternalDocumentSummary,
    ExternalIntegrationResponse,
    ExternalJobCreate,
    ExternalJobResponse,
    ExternalProcessRequest,
    ExternalProgressInfo,
    ExternalSchemaResponse,
    ExternalSendToIntegrationRequest,
)
from app.utils.activity_logger import Actions, log_activity
from app.utils.job_logger import get_job_logger

router = APIRouter()


def _serialize_job(job: Job) -> ExternalJobResponse:
    return ExternalJobResponse(
        id=job.id,
        name=job.name,
        description=job.description,
        schema_id=job.schema_id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        document_count=len(job.documents or []),
    )


def _serialize_document_summary(document: Document) -> ExternalDocumentSummary:
    return ExternalDocumentSummary(
        id=document.id,
        job_id=document.job_id,
        filename=document.filename,
        mime_type=document.mime_type,
        status=document.status,
        schema_id=document.schema_id,
        review_decision=document.review_decision,
        uploaded_at=document.uploaded_at,
        reviewed_at=document.reviewed_at,
        page_count=document.page_count,
        processing_error=document.processing_error,
    )


def _serialize_document_detail(document: Document) -> ExternalDocumentDetail:
    return ExternalDocumentDetail(
        **_serialize_document_summary(document).model_dump(),
        ocr_text=document.ocr_text,
        extracted_data=document.extracted_data,
        reviewed_data=document.reviewed_data,
    )


def _get_job_or_404(db: Session, job_id: UUID) -> Job:
    job = (
        db.query(Job)
        .options(selectinload(Job.documents))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def _get_document_or_404(db: Session, document_id: UUID) -> Document:
    document = (
        db.query(Document)
        .options(selectinload(Document.job))
        .filter(Document.id == document_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def _serialize_document_status(document: Document, task_status: Any) -> ExternalDocumentStatusResponse:
    progress = None
    if task_status.progress is not None:
        progress = ExternalProgressInfo(
            percent=task_status.progress.percent,
            stage=task_status.progress.stage,
            message=task_status.progress.message,
        )

    return ExternalDocumentStatusResponse(
        document_id=document.id,
        status=task_status.status,
        review_decision=document.review_decision,
        extracted_data=task_status.extracted_data,
        reviewed_data=document.reviewed_data,
        processing_error=task_status.processing_error,
        page_count=task_status.page_count,
        progress=progress,
    )


@router.get("/jobs", response_model=List[ExternalJobResponse])
def list_external_jobs(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    query = db.query(Job).options(selectinload(Job.documents))
    if not is_admin_user(current_user):
        query = query.filter(Job.user_id == current_user.id)
    jobs = query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()
    return [_serialize_job(job) for job in jobs]


@router.post("/jobs", response_model=ExternalJobResponse, status_code=status.HTTP_201_CREATED)
def create_external_job(
    payload: ExternalJobCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    job = Job(
        name=payload.name.strip(),
        description=payload.description,
        schema_id=payload.schema_id,
        status="draft",
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_JOB,
        resource_type="job",
        resource_id=job.id,
        details={"job_name": job.name, "source": "external_api"},
    )
    try:
        job_logger = get_job_logger(str(job.id))
        job_logger.info(
            f"Job created via external API by user {current_user.email} (ID: {current_user.id}). "
            f"Name: {job.name}"
        )
    except Exception:
        pass

    job = _get_job_or_404(db, job.id)
    return _serialize_job(job)


@router.get("/jobs/{job_id}", response_model=ExternalJobResponse)
def get_external_job(
    job_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    job = _get_job_or_404(db, job_id)
    ensure_job_access(current_user, job)
    return _serialize_job(job)


@router.get("/jobs/{job_id}/documents", response_model=List[ExternalDocumentSummary])
def list_external_job_documents(
    job_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    job = _get_job_or_404(db, job_id)
    ensure_job_access(current_user, job)
    documents = (
        db.query(Document)
        .filter(Document.job_id == job.id)
        .order_by(Document.uploaded_at.asc())
        .all()
    )
    return [_serialize_document_summary(document) for document in documents]


@router.post("/jobs/{job_id}/documents", response_model=ExternalDocumentSummary, status_code=status.HTTP_201_CREATED)
async def upload_external_document(
    job_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    document = await documents_endpoint.upload_document(
        db=db,
        job_id=str(job_id),
        file=file,
        current_user=current_user,
    )
    stored_document = _get_document_or_404(db, document.id)
    return _serialize_document_summary(stored_document)


@router.get("/documents/{document_id}", response_model=ExternalDocumentDetail)
def get_external_document(
    document_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    document = _get_document_or_404(db, document_id)
    ensure_document_access(current_user, document)
    return _serialize_document_detail(document)


@router.post("/documents/{document_id}/process", response_model=documents_endpoint.ProcessResponse)
def process_external_document(
    document_id: UUID,
    payload: ExternalProcessRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    return documents_endpoint.process_document(
        db=db,
        document_id=str(document_id),
        process_request=documents_endpoint.ProcessRequest(schema_id=payload.schema_id),
        current_user=current_user,
    )


@router.get("/documents/{document_id}/status", response_model=ExternalDocumentStatusResponse)
def get_external_document_status(
    document_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    document = _get_document_or_404(db, document_id)
    ensure_document_access(current_user, document)
    task_status = documents_endpoint.get_task_status(
        db=db,
        document_id=str(document_id),
        current_user=current_user,
    )
    return _serialize_document_status(document, task_status)


@router.put("/documents/{document_id}/review", response_model=ExternalDocumentDetail)
def review_external_document(
    document_id: UUID,
    payload: ExternalDocumentReviewRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    document = _get_document_or_404(db, document_id)
    ensure_document_access(current_user, document)

    document.reviewed_data = payload.reviewed_data
    document.reviewed_by = current_user.id
    document.reviewed_at = datetime.now(timezone.utc)
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        job_logger = get_job_logger(str(document.job_id))
        job_logger.info(
            f"Document {document.filename} (ID: {document.id}) review data updated via external API "
            f"by user {current_user.email}"
        )
    except Exception:
        pass

    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_DOCUMENT,
        resource_type="document",
        resource_id=document.id,
        details={"filename": document.filename, "source": "external_api_review"},
    )

    return _serialize_document_detail(document)


@router.post("/documents/{document_id}/decision", response_model=ExternalDocumentDetail)
def decide_external_document(
    document_id: UUID,
    payload: ExternalDocumentDecisionRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    document = documents_endpoint.set_document_review_decision(
        db=db,
        document_id=str(document_id),
        payload=documents_endpoint.ReviewDecisionRequest(
            decision=payload.decision,
            reviewed_data=payload.reviewed_data,
        ),
        current_user=current_user,
    )
    stored_document = _get_document_or_404(db, document.id)
    return _serialize_document_detail(stored_document)


@router.get("/schemas", response_model=List[ExternalSchemaResponse])
def list_external_schemas(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    del current_user
    schemas = db.query(DocumentSchema).order_by(DocumentSchema.created_at.desc()).all()
    return [
        ExternalSchemaResponse(
            id=schema.id,
            name=schema.name,
            description=schema.description,
            document_type=schema.document_type,
            field_count=len(schema.fields or []),
            fields=schema.fields or [],
        )
        for schema in schemas
    ]


@router.get("/integrations", response_model=List[ExternalIntegrationResponse])
def list_external_integrations(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    del current_user
    integrations = (
        db.query(Integration)
        .filter(Integration.status == IntegrationStatus.ACTIVE)
        .order_by(Integration.name.asc())
        .all()
    )
    return [
        ExternalIntegrationResponse(
            id=integration.id,
            name=integration.name,
            type=integration.type.value if hasattr(integration.type, "value") else str(integration.type),
            description=integration.description,
            status=integration.status.value if hasattr(integration.status, "value") else str(integration.status),
        )
        for integration in integrations
    ]


@router.post(
    "/jobs/{job_id}/send-integration",
    response_model=integrations_endpoint.SendToIntegrationResponse,
)
async def send_external_job_to_integration(
    job_id: UUID,
    payload: ExternalSendToIntegrationRequest,
    http_request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    job = _get_job_or_404(db, job_id)
    ensure_job_access(current_user, job)

    query = db.query(Document).filter(Document.job_id == job.id)
    if payload.document_ids:
        query = query.filter(Document.id.in_(payload.document_ids))
    documents = query.order_by(Document.uploaded_at.asc()).all()
    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No documents found for this job")

    outbound_documents = []
    for document in documents:
        ensure_document_access(current_user, document)
        if not payload.include_unconfirmed and document.review_decision != "confirmed":
            continue

        document_data = document.reviewed_data if document.reviewed_data is not None else document.extracted_data
        if document_data is None:
            continue

        outbound_documents.append(
            integrations_endpoint.DocumentInput(
                id=str(document.id),
                filename=document.filename,
                data=document_data,
            )
        )

    if not outbound_documents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No eligible documents to send. Confirm documents first or set include_unconfirmed=true.",
        )

    send_request = integrations_endpoint.SendToIntegrationRequest(
        integration_id=payload.integration_id,
        integration_name=payload.integration_name,
        job_id=job.id,
        job_name=job.name or str(job.id),
        documents=outbound_documents,
    )
    return await integrations_endpoint.send_to_integration(
        request=send_request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )
