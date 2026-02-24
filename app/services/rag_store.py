import logging
import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class RAGStore:
    """
    Isolierter Vektor-Speicher für den AI Service.
    Nutzt ChromaDB als lokale, dateibasierte Datenbank.
    """
    def __init__(self, persist_directory: str = "./rag_storage"):
        self.persist_directory = persist_directory
        self._client = None
        self._collection = None
        
        # Stelle sicher, dass das Verzeichnis existiert
        if not os.path.exists(self.persist_directory):
            os.makedirs(self.persist_directory)
            
        self._init_db()

    def _init_db(self):
        """Initialisiert die Verbindung zu ChromaDB"""
        try:
            # Nutze pure persistente Speicherung (ohne Server)
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(allow_reset=True)
            )
            logger.info(f"✓ ChromaDB verbunden (Pfad: {self.persist_directory})")
            
            # Hole oder erstelle die Haupt-Collection für Kanzlei-Fälle
            self._collection = self._client.get_or_create_collection(
                name="kanzlei_wissen",
                metadata={"description": "Referenzschreiben und Fallwissen"}
            )
        except Exception as e:
            logger.error(f"✗ Fehler bei ChromaDB Initialisierung: {e}")
            self._client = None

    async def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """
        Fügt Text-Chunks zur Vektordatenbank hinzu.
        
        Args:
            documents: Liste von Rohtexten (Chunks)
            metadatas: Liste von Metadaten-Dicts (z.B. {"fall_typ": "auffahrunfall", "akte": "123"})
            ids: Eindeutige IDs für jeden Chunk (z.B. "akte_123_chunk_1")
        """
        if not self._collection:
            logger.error("RAG Store nicht initialisiert!")
            return False
            
        try:
            # Hole Embeddings via Vertex REST API (ohne SDK)
            embeddings = await self._get_vertex_embeddings(documents)
            
            if embeddings:
                self._collection.upsert(
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    ids=ids
                )
            else:
                # Fallback: ChromaDB Default Embeddings (all-MiniLM-L6-v2) 
                # Nur lokal für Development, wenn kein Vertex Key da ist
                self._collection.upsert(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                
            logger.info(f"✓ {len(documents)} Chunks erfolgreich in RAG Store gespeichert.")
            return True
        except Exception as e:
            logger.error(f"✗ Fehler beim Speichern im RAG Store: {e}")
            return False

    async def _get_vertex_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Holt Embeddings via reinem REST-Call an die Google Vertex API"""
        from app.config import settings
        import httpx
        
        # Falls in Dev kein Key vorliegt, nutze Chroma Defaults
        if not settings.gemini_api_key:
            return None
            
        # REST URL für Embeddings (text-embedding-004)
        # Für reine API-Key Nutzung (ohne OAuth2 Service Account) nutzen wir den Standard Gemini Endpunkt
        url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key={settings.gemini_api_key}"
        
        headers = {"Content-Type": "application/json"}
        
        # Aufbereiten für batchEmbedContents: [{ "model": "...", "content": { "parts": [{ "text": "..." }]}}]
        requests_payload = []
        for t in texts:
            requests_payload.append({
                "model": "models/text-embedding-004",
                "content": {
                    "parts": [{"text": t}]
                }
            })
            
        payload = {"requests": requests_payload}
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                embeddings = []
                for emb in data.get("embeddings", []):
                    embeddings.append(emb.get("values", []))
                    
                return embeddings if len(embeddings) == len(texts) else None
        except Exception as e:
            logger.error(f"Vertex Embedding API Fehler: {e}")
            return None

    def search_similar(self, query_text: str, n_results: int = 3, filter_dict: Optional[Dict] = None) -> List[Dict]:
        """
        Sucht nach ähnlichen Dokumenten basierend auf einem Suchtext.
        
        Args:
            query_text: Der Text, nach dem gesucht wird (z.B. Kontext des neuen Falls)
            n_results: Anzahl der gewünschten Treffer
            filter_dict: Optionaler Filter (z.B. {"fall_typ": "auffahrunfall"})
            
        Returns:
            Liste von Dictionaries mit den Chunks und Metadaten.
        """
        if not self._collection:
            logger.error("RAG Store nicht initialisiert!")
            return []
            
        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=filter_dict
            )
            
            # ChromaDB gibt Arrays von Arrays zurück, da mehrere Queries möglich sind.
            # Da wir nur 1 Query senden, nehmen wir Index [0].
            matches = []
            if results and results["documents"] and len(results["documents"]) > 0:
                docs = results["documents"][0]
                metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
                dists = results["distances"][0] if "distances" in results and results["distances"] else [0] * len(docs)
                
                for doc, meta, dist in zip(docs, metas, dists):
                    matches.append({
                        "text": doc,
                        "metadata": meta,
                        "distance": dist  # Niedriger = ähnlicher
                    })
                    
            return matches
        except Exception as e:
            logger.error(f"✗ Fehler bei der RAG Suche: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Gibt Statistiken über die ChromaDB Collection zurück.
        Berechnet auch eine 'Sättigung' (Füllstandsbalken), wie gut die KI trainiert ist.
        """
        if not self._collection:
            return {"status": "error", "message": "DB offline", "document_count": 0, "categories": {}, "saturation_percent": 0.0}
            
        try:
            # Bei ChromaDB können wir count() abrufen, um die Gesamtzahl der Chunks zu ermitteln
            total_chunks = self._collection.count()
            
            # Um die Kategorien zu ermitteln, laden wir die Metadaten
            # ACHTUNG: Das lädt alles in den RAM, bei großen DBs (Millionen Einträge) schlecht,
            # für unsere kleine Kanzlei-RAG-DB (einige Hundert Chunks) jedoch völlig okay.
            all_data = self._collection.get(include=["metadatas"])
            metadatas = all_data.get("metadatas", [])
            
            categories = {}
            unique_docs = set()
            documents_map = {}
            
            if metadatas:
                for meta in metadatas:
                    # Kategorien sammeln
                    cat = meta.get("fall_typ", "Unbekannt")
                    categories[cat] = categories.get(cat, 0) + 1
                    
                    # Da ein echtes Word-Dokument in z.B. 5 Chunks zerlegt wird,
                    # gucken wir, wie viele "echte" Dokuemnte es gibt (nach document_id)
                    doc_id = meta.get("document_id", "unknown")
                    if doc_id != "unknown":
                        unique_docs.add(doc_id)
                        if doc_id not in documents_map:
                            documents_map[doc_id] = {
                                "id": doc_id,
                                "source": meta.get("source", "Manuelle Texteingabe"),
                                "fall_typ": cat,
                                "notizen": meta.get("notizen", ""),
                                "chunk_count": 0
                            }
                        documents_map[doc_id]["chunk_count"] += 1
                    
            real_doc_count = len(unique_docs)
            
            # Füllstand der "Tank-Nadel" (Ziel: 100 Goldstandard-Dokumente)
            TARGET_DOCS = 100
            saturation = min(100.0, round((real_doc_count / TARGET_DOCS) * 100, 1))

            return {
                "status": "success",
                "chunk_count": total_chunks,
                "document_count": real_doc_count,
                "categories": categories,
                "saturation_percent": saturation,
                "target_docs": TARGET_DOCS,
                "documents": list(documents_map.values())
            }
        except Exception as e:
            logger.error(f"Fehler beim Lesen der RAG Stats: {e}")
            return {"status": "error", "error": str(e), "document_count": 0, "categories": {}, "saturation_percent": 0.0}

    def delete_document(self, document_id: str) -> bool:
        """
        Löscht alle Chunks (aus dem Vektor-Store), die zu einer bestimmten document_id gehören.
        """
        if not self._collection:
            logger.error("RAG Store nicht initialisiert!")
            return False
            
        try:
            # ChromaDB v0.4.x erlaubt das Löschen via Metadaten-Where-Klausel
            self._collection.delete(
                where={"document_id": document_id}
            )
            logger.info(f"✓ Dokument {document_id} erfolgreich aus RAG Store gelöscht.")
            return True
        except Exception as e:
            logger.error(f"✗ Fehler beim Löschen aus RAG Store: {e}")
            return False

# Singleton-Instanz für den Service
rag_store = RAGStore()
