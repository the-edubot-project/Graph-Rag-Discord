
from langchain_core.embeddings.embeddings import Embeddings

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from src import settings

embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=settings.GOOGLE_API_KEY)

docs = ["Hola me gustan los chocolates", "El dia esta lluvioso hoy en medellin"]



vectors = embeddings.embed_documents(docs)

for v in vectors:
    print(f"primeras 5 entradas del vector: {v[:5]}, dimencion del vector {len(v)} \n") # dimencion del vector 3072 


"""
python3 -m src.services.v1.NaiveRag.google



gemini-embedding-2

"""


