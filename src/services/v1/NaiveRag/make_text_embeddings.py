from sqlalchemy.orm import Session
from src import discord_models as models
from langchain_core.embeddings.embeddings import Embeddings
#from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_text_splitters.base import TextSplitter
#from langchain_core.documents.base import Document
from tokenizers import Tokenizer
from src.logging_config import get_logger
import time



logger = get_logger(module_name="make_text_embeddings", DIR="NaiveRag", to_db=True)


def _approx_tokens(text: str, tokenizer: Tokenizer | None) -> int:
    """Tokens aproximados del texto.

    Si se pasa un tokenizer (huggingface `tokenizers.Tokenizer`), usa su conteo real;
    si no, cae a la heurística ~1 token cada 4 caracteres.
    """
    if tokenizer is not None:
        return len(tokenizer.encode(text).ids)
    return len(text) // 4


def make_text_embeddings(
    session: Session,
    embedding: Embeddings,
    embedding_model: str,
    text_spliter: TextSplitter | None = None,
    tokenizer: Tokenizer | None = None,
):

    # Chunks pendientes de (re)embeber: naive_rag_status IS NULL (lo pone chunking.py /
    # force_merge.py cuando el contenido del chunk cambia, o arranca NULL en chunks
    # nuevos). Hacemos JOIN a la tabla de resúmenes para traer el texto y exigimos que
    # el resumen ya exista (summary_chunks.py debe haber corrido antes).
    # Una fila por chunk: summary_id es PK de DiscordSummaryStatus y el join al resumen
    # es 1-a-1, así que no hay duplicados.
    records = (
        session.query(
            models.DiscordSummaryStatus.summary_id,
            models.DiscordChannelChronologicalSummary.summary,
        )
        .join(
            models.DiscordChannelChronologicalSummary,
            models.DiscordChannelChronologicalSummary.id == models.DiscordSummaryStatus.summary_id,
        )
        .filter(
            models.DiscordSummaryStatus.naive_rag_status.is_(None),
            models.DiscordChannelChronologicalSummary.summary.is_not(None),
        )
        .all()
    )

    # Borramos los embeddings previos de esos chunks: si el chunk mutó, eran obsoletos;
    # si es nuevo, no hay nada que borrar. Un único DELETE masivo por todos los
    # summary_id pendientes (evita el bug de borrar de uno en uno / con una lista).
    summary_ids = {r.summary_id for r in records}
    if summary_ids:
        session.query(models.DiscordChunkEmbeddings).filter(
            models.DiscordChunkEmbeddings.summary_id.in_(summary_ids)
        ).delete(synchronize_session=False)
        session.commit()


    for r in records:
        time.sleep(0.5)
        try:
            if text_spliter:
                # Sub chunkenizamos el chunk
                text = r.summary
                chunks = text_spliter.split_text(text)
                vectors = embedding.embed_documents(chunks)

                for n, c in enumerate(chunks):
                    aprox_tokens = _approx_tokens(c, tokenizer)
                    if aprox_tokens <= 5:
                        logger.warning(f"La cantidad de tokens de un sub chunk de un chunk con id {r.summary_id} es muy baja")
                    embedding_record = models.DiscordChunkEmbeddings(
                        summary_id=r.summary_id,
                        chunk=c,
                        embedding=vectors[n],
                        input_tokens=aprox_tokens,
                        embedding_model=embedding_model
                    )
                    session.add(embedding_record)
            else:
                # En este caso no se sub chunkeniza el chunk, se embebe completamente
                text =  r.summary
                aprox_tokens = _approx_tokens(text, tokenizer)
                if aprox_tokens <= 5:
                    logger.warning(f"La cantidad de tokens de un sub chunk de un chunk con id {r.summary_id} es muy baja")
                vector = embedding.embed_query(text)
                embedding_record = models.DiscordChunkEmbeddings(
                    summary_id=r.summary_id,
                    chunk=text,
                    embedding=vector,
                    input_tokens=aprox_tokens,
                    embedding_model=embedding_model
                )
                session.add(embedding_record)
        except Exception as e:
            logger.error(f"Error: {e}")

        # Embeddings (re)creados → esta rutina es el paso final del pipeline NaiveRag,
        # así que marcamos el chunk como 'ready' para que la próxima corrida no lo
        # vuelva a capturar (filtro naive_rag_status IS NULL).
        session.query(models.DiscordSummaryStatus).filter_by(
            summary_id=r.summary_id
        ).update(
            {models.DiscordSummaryStatus.naive_rag_status: "ready"},
            synchronize_session=False,
        )
        session.commit()
            


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from src import settings

    engine = create_engine(settings.THE_EDUBOT_DB_CONN_STRING)
    MySession = sessionmaker(bind=engine)
    session = MySession()

    model = "models/gemini-embedding-2"
    embedding = GoogleGenerativeAIEmbeddings(model=model, google_api_key=settings.GOOGLE_API_KEY)
    # Tokenizer de Gemma (misma familia SentencePiece que Gemini, vocab 256k) como
    # mejor proxy para contar tokens que la heurística chars/4.
    # Usamos el mirror de unsloth porque NO es gated (carga sin login). El oficial
    # "google/gemma-2-2b" es idéntico pero requiere aceptar licencia + huggingface-cli login.
    tokenizer = Tokenizer.from_pretrained("unsloth/gemma-2-2b")

    make_text_embeddings(
        session=session,
        embedding=embedding,
        embedding_model=model,
        tokenizer=tokenizer,
    )



    

