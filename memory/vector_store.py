import uuid
from pathlib import Path
from typing import Any, Optional
import chromadb
from chromadb.utils import embedding_functions


class VectorStore:
    def __init__(self, persist_dir: Optional[Path] = None, openai_api_key: Optional[str] = None, 
                 openai_base_url: Optional[str] = None, embedding_model: str = "text-embedding-3-small"):
        self.persist_dir = persist_dir
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(persist_dir))
        else:
            self.client = chromadb.Client()
        
        if openai_api_key:
            self.ef = embedding_functions.OpenAIEmbeddingFunction(
                api_key=openai_api_key,
                api_base=openai_base_url,
                model_name=embedding_model
            )
        else:
            self.ef = embedding_functions.DefaultEmbeddingFunction()
        
        self.collections = {}
    
    def get_or_create_collection(self, name: str):
        if name not in self.collections:
            try:
                self.collections[name] = self.client.get_collection(name=name, embedding_function=self.ef)
            except:
                self.collections[name] = self.client.create_collection(name=name, embedding_function=self.ef)
        return self.collections[name]
    
    def add(self, collection_name: str, texts: list[str], metadatas: Optional[list[dict]] = None, 
            ids: Optional[list[str]] = None) -> list[str]:
        collection = self.get_or_create_collection(collection_name)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        collection.add(documents=texts, metadatas=metadatas, ids=ids)
        return ids
    
    def search(self, collection_name: str, query: str, top_k: int = 5, 
               filter: Optional[dict] = None) -> list[dict[str, Any]]:
        collection = self.get_or_create_collection(collection_name)
        results = collection.query(query_texts=[query], n_results=top_k, where=filter)
        items = []
        for i in range(len(results["ids"][0])):
            items.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else None,
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
                "score": 1.0 - (results["distances"][0][i] if results["distances"] else 0.0)
            })
        return items
    
    def delete(self, collection_name: str, ids: list[str]):
        collection = self.get_or_create_collection(collection_name)
        collection.delete(ids=ids)
    
    def delete_all(self, collection_name: str):
        try:
            self.client.delete_collection(name=collection_name)
            if collection_name in self.collections:
                del self.collections[collection_name]
        except:
            pass
    
    def count(self, collection_name: str) -> int:
        collection = self.get_or_create_collection(collection_name)
        return collection.count()
