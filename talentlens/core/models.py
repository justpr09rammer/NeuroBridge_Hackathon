"""SQLAlchemy ORM models for TalentLens AI."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    department: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    employment_type: Mapped[str] = mapped_column(String(50), default="Full-time")
    salary_range: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    recruiter_notes: Mapped[str] = mapped_column(Text, default="")
    wording_flags: Mapped[list] = mapped_column(JSON, default=list)
    extraction_source: Mapped[str] = mapped_column(String(50), default="local")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    requirements: Mapped[list["Requirement"]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan", order_by="Requirement.position"
    )
    candidates: Mapped[list["Candidate"]] = relationship(
        back_populates="vacancy", cascade="all, delete-orphan"
    )


class Requirement(Base):
    __tablename__ = "requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    key: Mapped[str] = mapped_column(String(80))  # canonical skill key or slug
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50))
    priority: Mapped[str] = mapped_column(String(20), default="must")  # must | nice
    weight: Mapped[float] = mapped_column(Float, default=10.0)
    guidance: Mapped[str] = mapped_column(Text, default="")
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"min_years": 2}

    vacancy: Mapped[Vacancy] = relationship(back_populates="requirements")


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("vacancy_id", "content_hash", name="uq_candidate_doc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"))
    display_id: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(80), default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="new")  # new|assessed|needs_review|error
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vacancy: Mapped[Vacancy] = relationship(back_populates="candidates")
    documents: Mapped[list["CVDocument"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="Assessment.created_at"
    )
    reviews: Mapped[list["RecruiterReview"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="RecruiterReview.created_at"
    )
    reports: Mapped[list["CandidateReport"]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan", order_by="CandidateReport.created_at"
    )

    @property
    def latest_assessment(self) -> "Assessment | None":
        return self.assessments[-1] if self.assessments else None


class CVDocument(Base):
    __tablename__ = "cv_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(500), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    pages: Mapped[list] = mapped_column(JSON, default=list)
    hidden_text: Mapped[list] = mapped_column(JSON, default=list)
    readability: Mapped[str] = mapped_column(String(30), default="ok")  # ok|too_short|unreadable
    processing_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="documents")


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"))
    pipeline: Mapped[str] = mapped_column(String(80))  # local-rules-v1 or llm:<model>
    score: Mapped[float] = mapped_column(Float, default=0.0)
    category_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    security_flags: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    blind_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="assessments")
    items: Mapped[list["RequirementAssessment"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class RequirementAssessment(Base):
    __tablename__ = "requirement_assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))  # DEMONSTRATED|UNCLEAR|NOT_FOUND
    original_status: Mapped[str] = mapped_column(String(20))
    evidence: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    matched_terms: Mapped[list] = mapped_column(JSON, default=list)
    uncertainty: Mapped[str] = mapped_column(Text, default="")
    follow_up: Mapped[str] = mapped_column(Text, default="")
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    assessment: Mapped[Assessment] = relationship(back_populates="items")
    requirement: Mapped[Requirement] = relationship()


class RecruiterReview(Base):
    __tablename__ = "recruiter_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))  # note|correction|decision|flag
    decision: Mapped[str] = mapped_column(String(30), default="")  # advance|hold|rejected
    note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    author: Mapped[str] = mapped_column(String(100), default="Recruiter")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="reviews")


class CandidateReport(Base):
    __tablename__ = "candidate_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    markdown: Mapped[str] = mapped_column(Text)
    resource_urls: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(80), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    candidate: Mapped[Candidate] = relationship(back_populates="reports")


class LearningResource(Base):
    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(String(200))
    topic: Mapped[str] = mapped_column(String(100))
    skill: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(500), unique=True)
    difficulty: Mapped[str] = mapped_column(String(30))
    estimated_time: Mapped[str] = mapped_column(String(100), default="Not stated")
    verification_status: Mapped[str] = mapped_column(String(60), default="seed (not checked at runtime)")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cases: Mapped[list["EvaluationCase"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(60))
    case_name: Mapped[str] = mapped_column(String(300))
    passed: Mapped[bool] = mapped_column(Boolean)
    expected: Mapped[str] = mapped_column(Text, default="")
    actual: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[EvaluationRun] = relationship(back_populates="cases")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
