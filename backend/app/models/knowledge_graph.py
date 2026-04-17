"""Knowledge-graph models — entities extracted from documents and the inter-document
relations derived from shared entities.

Three tables form the two-layer graph:
    kg_entities             — normalized entity nodes (person / customer / project / ...)
    kg_document_entities    — edges: Document --MENTIONS/ABOUT/...--> Entity
    kg_document_relations   — edges: Document --RELATED_TO--> Document (shared entities)

Entity embeddings are stored as raw float32 bytes (SQLite-friendly). When deployed on
PostgreSQL with pgvector available, the BLOB column can be swapped for `vector(N)` in
a future migration; the service layer abstracts the cosine lookup so only the storage
representation changes.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Entity(Base):
    __tablename__ = "kg_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="other",
        comment="person | customer | project | product | org | contract | other",
    )
    aliases: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        comment="JSON array of alternative surface forms",
    )
    embedding: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        comment="float32 vector packed as bytes; None until first embed",
    )
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        Index("idx_entity_type", "entity_type"),
        Index("idx_entity_type_name", "entity_type", "name"),
    )


class DocumentEntity(Base):
    __tablename__ = "kg_document_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="mentions",
        comment="mentions | authored_by | about | belongs_to",
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "document_id", "entity_id", "relation_type",
            name="uq_doc_entity_rel",
        ),
        Index("idx_doc_entity_doc", "document_id"),
        Index("idx_doc_entity_ent", "entity_id"),
    )


class DocumentRelation(Base):
    __tablename__ = "kg_document_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    src_doc_id: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Smaller id in the undirected pair (src < dst)",
    )
    dst_doc_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="related",
        comment="same_project | same_customer | same_person | references | related",
    )
    weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0,
        comment="Count of shared entities or similarity score",
    )
    shared_entities: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="[]",
        comment="JSON array of shared entity_ids",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("src_doc_id", "dst_doc_id", name="uq_doc_relation_pair"),
        Index("idx_doc_rel_src", "src_doc_id"),
        Index("idx_doc_rel_dst", "dst_doc_id"),
    )
