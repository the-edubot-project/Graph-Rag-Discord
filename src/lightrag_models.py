from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Text,
    func,
    ARRAY,
    PrimaryKeyConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector



class LightRagBase(DeclarativeBase):
    pass



class LightRagDocChunk(LightRagBase):
    __tablename__ = "lightrag_doc_chunks"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    full_doc_id = Column(String(256))
    chunk_order_index = Column(Integer)
    tokens = Column(Integer)
    content = Column(Text)
    file_path = Column(Text)
    llm_cache_list = Column(JSONB, server_default="[]")
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagDocFull(LightRagBase):
    __tablename__ = "lightrag_doc_full"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    doc_name = Column(String(1024))
    content = Column(Text)
    meta = Column(JSONB)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagDocStatus(LightRagBase):
    __tablename__ = "lightrag_doc_status" 
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    workspace = Column(String(255), nullable=False)
    id = Column(String(255), nullable=False, index=True)
    content_summary = Column(String(255))
    content_length = Column(Integer)
    chunks_count = Column(Integer)
    status = Column(String(64))
    file_path = Column(Text)
    chunks_list = Column(JSONB, server_default="[]")
    track_id = Column(String(255), index=True)
    doc_metadata = Column("metadata", JSONB, server_default="{}")
    error_msg = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())



class LightRagEntityChunk(LightRagBase):
    __tablename__ = "lightrag_entity_chunks"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(512), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    chunk_ids = Column(JSONB)
    count = Column(Integer)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagFullEntity(LightRagBase):
    __tablename__ = "lightrag_full_entities"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    entity_names = Column(JSONB)
    count = Column(Integer)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagFullRelation(LightRagBase):
    __tablename__ = "lightrag_full_relations"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    relation_pairs = Column(JSONB)
    count = Column(Integer)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagLlmCache(LightRagBase):
    __tablename__ = "lightrag_llm_cache"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    workspace = Column(String(255), nullable=False)
    id = Column(String(255), nullable=False, index=True)
    original_prompt = Column(Text)
    return_value = Column(Text)
    chunk_id = Column(String(255))
    cache_type = Column(String(32))
    queryparam = Column(JSONB)
    create_time = Column(DateTime, server_default=func.now())
    update_time = Column(DateTime, server_default=func.now())



class LightRagRelationChunk(LightRagBase):
    __tablename__ = "lightrag_relation_chunks"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(512), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    chunk_ids = Column(JSONB)
    count = Column(Integer)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagVdbChunk(LightRagBase):
    __tablename__ = "lightrag_vdb_chunks_gemini_embedding_001_1536d"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    full_doc_id = Column(String(256))
    chunk_order_index = Column(Integer)
    tokens = Column(Integer)
    content = Column(Text)
    content_vector = Column(Vector(1536))
    file_path = Column(Text)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagVdbEntity(LightRagBase):
    __tablename__ = "lightrag_vdb_entity_gemini_embedding_001_1536d"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    entity_name = Column(String(512))
    content = Column(Text)
    content_vector = Column(Vector(1536))
    chunk_ids = Column(ARRAY(String(255)))
    file_path = Column(Text)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())



class LightRagVdbRelation(LightRagBase):
    __tablename__ = "lightrag_vdb_relation_gemini_embedding_001_1536d"
    __table_args__ = (PrimaryKeyConstraint("workspace", "id"),)

    id = Column(String(255), nullable=False, index=True)
    workspace = Column(String(255), nullable=False)
    source_id = Column(String(512))
    target_id = Column(String(512))
    content = Column(Text)
    content_vector = Column(Vector(1536))
    chunk_ids = Column(ARRAY(String(255)))
    file_path = Column(Text)
    create_time = Column(DateTime(0), server_default=func.now())
    update_time = Column(DateTime(0), server_default=func.now())




# ===========================================================
# ==========================================================


