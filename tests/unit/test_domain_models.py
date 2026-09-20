"""Unit tests for domain models. DEV-004, DEV-006, DEV-045."""

import dataclasses

import pytest

from qbank.domain.models import (
    Chunk,
    Course,
    Department,
    Document,
    DocumentType,
    DocumentVersion,
    ExtractionStatus,
    Language,
    Provenance,
    Question,
    Source,
    SourceType,
    SyncRun,
)


@pytest.mark.unit
class TestDomainModelsInstantiation:
    """All domain models should instantiate with defaults."""

    def test_department_defaults(self) -> None:
        dept = Department(code="CSE", name="Computer Science and Engineering")
        assert dept.code == "CSE"
        assert dept.tenant_id == "IUT"
        assert dept.department_id != ""

    def test_course_defaults(self) -> None:
        course = Course(course_code="CSE3101", title="Database Systems")
        assert course.course_code == "CSE3101"
        assert course.aliases == []
        assert course.tenant_id == "IUT"

    def test_source_defaults(self) -> None:
        source = Source(
            source_type=SourceType.DSPACE,
            name="IUT DSpace",
            base_url="https://repository.iutoic-dhaka.edu",
        )
        assert source.is_active is True
        assert source.last_synced_at is None

    def test_document_defaults(self) -> None:
        doc = Document(title="CSE3101 Final 2024")
        assert doc.document_type == DocumentType.OTHER
        assert doc.language == Language.ENGLISH
        assert doc.tenant_id == "IUT"

    def test_document_version_defaults(self) -> None:
        version = DocumentVersion(document_id="doc-1", version_hash="abc123")
        assert version.extraction_status == ExtractionStatus.PENDING
        assert version.extraction_method is None

    def test_chunk_defaults(self) -> None:
        chunk = Chunk(document_id="doc-1", version_id="v-1", text="Q1. What is...")
        assert chunk.chunk_index == 0
        assert chunk.provenance is None

    def test_question_defaults(self) -> None:
        q = Question(question_number="3(a)", text="Explain normalization.")
        assert q.marks is None
        assert q.provenance is None

    def test_sync_run_defaults(self) -> None:
        run = SyncRun(source_id="src-1")
        assert run.status == "running"
        assert run.documents_discovered == 0


@pytest.mark.unit
class TestProvenance:
    """Provenance is a frozen value object — DEV-006."""

    def test_provenance_is_immutable(self) -> None:
        prov = Provenance(
            source_id="s1",
            source_type=SourceType.DSPACE,
            source_url="https://repository.iutoic-dhaka.edu",
            document_id="d1",
            document_url="https://repository.iutoic-dhaka.edu/handle/123",
            document_title="CSE3101 Final 2024",
            version_id="v1",
            version_hash="sha256abc",
            page=2,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            prov.page = 3  # type: ignore[misc]

    def test_provenance_equality(self) -> None:
        prov1 = Provenance(
            source_id="s1",
            source_type=SourceType.DSPACE,
            source_url="https://example.com",
            document_id="d1",
            document_url="https://example.com/d1",
            document_title="Title",
            version_id="v1",
            version_hash="hash1",
        )
        prov2 = Provenance(
            source_id="s1",
            source_type=SourceType.DSPACE,
            source_url="https://example.com",
            document_id="d1",
            document_url="https://example.com/d1",
            document_title="Title",
            version_id="v1",
            version_hash="hash1",
        )
        assert prov1 == prov2


@pytest.mark.unit
class TestUniqueIds:
    """Each domain object should auto-generate a unique ID."""

    def test_documents_have_unique_ids(self) -> None:
        ids = {Document().document_id for _ in range(100)}
        assert len(ids) == 100

    def test_chunks_have_unique_ids(self) -> None:
        ids = {Chunk().chunk_id for _ in range(100)}
        assert len(ids) == 100
