from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    DateTime,
    Text,
    func,
    JSON,
    Boolean,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Float
)
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector



class Base(DeclarativeBase):
    pass



class DiscordGuild(Base):
    __tablename__ = "discord_servers"

    id = Column(BigInteger, primary_key=True)
    name = Column(String)
    create_at = Column(DateTime, index=True)  # fecha de creacion del server
    inserted_at = Column(DateTime, server_default=func.now())



class DiscordUser(Base):
    __tablename__ = "discord_users"

    id = Column(BigInteger, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey("discord_servers.id"), primary_key=True)
    is_bot = Column(Boolean, default=False, index=True)
    global_name = Column(String)  # El username real/único de Discord
    display_name = Column(String) # El apodo en ese servidor específico
    joined_at = Column(DateTime, index=True)
    inserted_at = Column(DateTime, server_default=func.now())



class DiscordChannel(Base):
    __tablename__ = "discord_channels"

    id = Column(BigInteger, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey("discord_servers.id"))
    name = Column(String)
    channel_type = Column(String)
    parent_channel_id = Column(BigInteger)  # Si es un hilo, cual es el canal del hilo
    create_at = Column(DateTime, index=True)
    last_messages_at = Column(DateTime, index=True)  # Fecha del ultimo mensaje
    inserted_at = Column(DateTime, server_default=func.now())
    # summary = Column(Text, nullable=True)
    channel_metadata = Column(JSONB)



# author.display_name
class DiscordMessage(Base):
    __tablename__ = "discord_messages"

    id = Column(BigInteger, unique=True, index=True, primary_key=True)
    guild_id = Column(BigInteger, ForeignKey("discord_servers.id"), index=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"), index=True)
    # user_id y user_name no son claves foraneas dado que pueden haver DiscordUser que no estan en DiscordMessage
    user_id = Column(BigInteger, index=True)  # Autor del mensaje
    user_name = Column(String)
    user_display_name = Column(String)

    content = Column(Text, nullable=True)
    reply_to = Column(BigInteger, nullable=True)
    attachments = Column(JSON)
    attachments_explanation = Column(Text, nullable=True) # explicacion de attachments en lenguaje natural, ej si es una imagen, descripcion de esta
    message_create_at = Column(DateTime, index=True)
    inserted_at = Column(DateTime, server_default=func.now())




class DiscordChannelChronologicalSummary(Base):
    __tablename__="discord_chronological_summary"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    number_messages = Column(Integer)
    summary = Column(Text, nullable=True)
    # status = Column(Enum('in_lightrag', 'ready', name='summary_status'), nullable=True)
    # 'metadata' es un atributo reservado por SQLAlchemy Declarative; el atributo se
    # llama chunk_metadata pero la columna en la BD sigue siendo "metadata".
    # chunk_metadata = Column("metadata", JSON, nullable=True)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    model = Column(String)
    inserted_at = Column(DateTime, server_default=func.now())

    status = Column(Boolean) # Estado que indica cuando un chunk está lo suficionete "maduro" para ser inmutable en el proceso de chunkenizar nuevos mensajes

    # Cobertura de alertas: True = ya se extrajeron alertas para el contenido actual
    # del chunk (aunque hayan sido 0). Se invalida (False) cuando el chunk cambia,
    # análogo a summary=None. Lo consume src/services/v1/DiscordAlerts/spam_alerts.py.
    alerts_done = Column(Boolean, nullable=False, server_default="false")




class DiscordSummaryStatus(Base):
    __tablename__="discord_summary_state"

    summary_id = Column(
            Integer,
            ForeignKey("discord_chronological_summary.id"),
            primary_key=True
        )
    lightrag_status = Column(Enum('in_lightrag', 'ready', name='summary_status'), nullable=True)
    naive_rag_status = Column(Enum('embeded', 'ready', name='summary_status'), nullable=True)
    graphiti_status = Column(Enum('in_graphiti', 'ready', name='summary_status'), nullable=True)






class DiscordChunkEmbeddings(Base):
    __tablename__ ="discord_chunk_embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    summary_id = Column(Integer, ForeignKey("discord_chronological_summary.id"))
    chunk = Column(Text)
    embedding = Column(Vector[3072]) 
    input_tokens = Column(Integer)
    embedding_model = Column(String)
    inserted_at = Column(DateTime, server_default=func.now())




class DiscordAlert(Base):
    __tablename__ = "discord_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"), nullable=False, index=True)
    # Chunk del que se extrajo la alerta. ON DELETE CASCADE: si se borra el chunk,
    # sus alertas se borran con él (no quedan huérfanas).
    summary_id = Column(
        Integer,
        ForeignKey("discord_chronological_summary.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    severity = Column(Integer, nullable=False, index=True)
    type = Column(JSON)
    description = Column(Text, nullable=False)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    model = Column(String)
    # Estado de procesamiento downstream de la alerta (análogo a DiscordSummaryStatus):
    # 'pending' detectada/sin enviar → 'sent' enviada/ingerida → 'ready' confirmada.
    alert_status = Column(
        Enum("pending", "sent", "ready", name="alert_status"),
        nullable=False,
        server_default="pending",
    )
    inserted_at = Column(DateTime, server_default=func.now())
    
    



class DiscordChannelPermission(Base):
    __tablename__ = "discord_channel_permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"), nullable=False, index=True)
    target_id = Column(BigInteger, nullable=False, index=True)
    target_name = Column(String, nullable=False)
    target_type = Column(String, nullable=False)  # "role" or "member"
    allow = Column(BigInteger, nullable=False)   # bitmask de permisos permitidos
    deny = Column(BigInteger, nullable=False)    # bitmask de permisos denegados
    inserted_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("channel_id", "target_id", name="uq_channel_target"),
    )


class DiscordMessageExtractionLog(Base):
    __tablename__ = "discord_message_extraction_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"), index=True, nullable=False)
    messages_extracted = Column(Integer, nullable=False)
    extracted_at = Column(DateTime, server_default=func.now(), index=True)




class DiscordChannelContext(Base):
    __tablename__ = "discord_channel_context"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(BigInteger, ForeignKey("discord_channels.id"))
    summary_context = Column(Text, nullable=True)





class LightRagDocs(Base):
    __tablename__ = "discord_lightrag_docs"

    summary_id = Column(
        Integer,
        ForeignKey("discord_chronological_summary.id"),
        primary_key=True
    )
    lightrag_doc_id = Column(String(255), nullable=True, unique=True, index=True)
    pending_deletion = Column(Boolean, default=False, nullable=False)
    lightrag_track_id = Column(String(255), nullable=True, index=True)




class ModelsProvider(Base):
    __tablename__ = "models_provider"

    id = Column(Integer, primary_key=True)
    model_name = Column(String, unique=True)
    model_provider = Column(String)
    pricing_input_tokens = Column(Float)
    pricing_output_tokens = Column(Float)




class GraphitiTokenUsage(Base):
    """Consumo de tokens (LLM y embedding) por cada resumen ingerido en Graphiti.

    Se escriben DOS filas por summary_id procesado:
      - kind='llm'       -> tokens reales de extracción/dedup (usage de vLLM).
      - kind='embedding' -> tokens aproximados del texto embebido; output_tokens
                            siempre 0 (los modelos de embedding no generan salida).

    Los nombres de modelo provienen de conf.LLM_MODEL / conf.EMBED_MODEL
    (src/services/v1/Graphiti/conf.py). Los tokens del LLM incluyen los reintentos
    transitorios (= coste real consumido), no solo el intento exitoso.
    """

    __tablename__ = "graphiti_token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    summary_id = Column(Integer, nullable=False, index=True)
    channel_id = Column(BigInteger, index=True)
    kind = Column(String(16), nullable=False)  # 'llm' | 'embedding'
    model_name = Column(String(255), nullable=False)
    input_tokens = Column(Integer, nullable=False, server_default="0")
    output_tokens = Column(Integer, nullable=False, server_default="0")
    # Nº de textos enviados a embeber (solo relevante para kind='embedding').
    embed_calls = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())








class LightragTokenUsage(Base):
    """Consumo de tokens (LLM y embedding) por cada resumen ingerido en LightRAG.

    Se escriben DOS filas por summary_id procesado:
      - kind='llm'       -> tokens reales de extracción de entidades/relaciones
                            (usage devuelto por vLLM, incluye reintentos).
      - kind='embedding' -> tokens aproximados del texto embebido (contados
                            localmente con tiktoken); output_tokens siempre 0,
                            los modelos de embedding no generan salida.

    Los nombres de modelo provienen de conf.LLM_MODEL / conf.EMBED_MODEL
    (src/services/v1/LightRag/conf.py). Las llamadas servidas desde la caché de
    LightRAG no consumen tokens nuevos, por lo que se registran como 0.
    """

    __tablename__ = "lightrag_token_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    summary_id = Column(Integer, nullable=False, index=True)
    channel_id = Column(BigInteger, index=True)
    kind = Column(String(16), nullable=False)  # 'llm' | 'embedding'
    model_name = Column(String(255), nullable=False)
    input_tokens = Column(Integer, nullable=False, server_default="0")
    output_tokens = Column(Integer, nullable=False, server_default="0")
    # Nº de textos enviados a embeber (solo relevante para kind='embedding').
    embed_calls = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())


