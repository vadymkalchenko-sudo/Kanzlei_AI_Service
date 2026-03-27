import logging
import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

class DummyEmbeddingFunction(EmbeddingFunction):
    """Bypasses Chroma's default model download since we use Vertex/Gemini."""
    def __call__(self, input: Documents) -> Embeddings:
        return [[0.0] * 768 for _ in input]

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
        self._system_collection = None
        self._akte_collection = None
        
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
            
            # Nutze ein Dummy-Embedding, da wir via Vertex einbetten
            dummy_ef = DummyEmbeddingFunction()
            
            # Hole oder erstelle die Haupt-Collection für Kanzlei-Fälle
            self._collection = self._client.get_or_create_collection(
                name="kanzlei_wissen",
                embedding_function=dummy_ef,
                metadata={"description": "Referenzschreiben und Fallwissen"}
            )
            
            # Hole oder erstelle die Collection für das System-Wissen der Kanzlei
            self._system_collection = self._client.get_or_create_collection(
                name="system_wissen",
                embedding_function=dummy_ef,
                metadata={"description": "Dokumentation über das Kanzlei-Programm"}
            )

            # Neue Collection: Volltexte aller Akte-Dokumente (RAG Vollanalyse)
            self._akte_collection = self._client.get_or_create_collection(
                name="akte_dokumente",
                embedding_function=dummy_ef,
                metadata={"description": "Hochgeladene Dokumente pro Akte (indexiert für RAG-Analyse)"}
            )
            logger.info("✓ ChromaDB Collection 'akte_dokumente' bereit")
        except Exception as e:
            logger.error(f"✗ Fehler bei ChromaDB Initialisierung: {e}")
            self._client = None

    @staticmethod
    def _chunk_text_with_overlap(text: str, chunk_size_words: int = 400, overlap_words: int = 50) -> List[str]:
        """
        Teilt Text in Wort-basierte Chunks mit Overlap.

        Args:
            text: Eingabetext
            chunk_size_words: Zielgröße in Wörtern (~400 Wörter ≈ ~400 Tokens)
            overlap_words: Anzahl Wörter Überlappung zwischen Chunks

        Returns:
            Liste von Text-Chunks
        """
        if not text or not text.strip():
            return []

        words = text.split()
        if len(words) <= chunk_size_words:
            return [text.strip()]

        chunks: List[str] = []
        start = 0
        step = chunk_size_words - overlap_words  # Schrittweite mit Overlap

        while start < len(words):
            end = min(start + chunk_size_words, len(words))
            chunk = " ".join(words[start:end])
            if chunk.strip():
                chunks.append(chunk.strip())
            if end >= len(words):
                break
            start += step

        return chunks

    async def index_dokument(
        self,
        akte_id: int,
        dokument_id: int,
        titel: str,
        kategorie: str,
        text: str,
    ) -> int:
        """
        Indexiert ein Dokument in der 'akte_dokumente' Collection.

        Bestehende Chunks für diese dokument_id werden zuerst gelöscht
        (Re-Indexierung bei erneutem Upload). Dann wird der Text in
        ~400-Wort-Chunks mit 50-Wort-Overlap zerlegt und gespeichert.

        Args:
            akte_id: ID der zugehörigen Akte
            dokument_id: ID des Dokuments in Django
            titel: Dokumenttitel
            kategorie: Kategorie (z.B. "Gutachten", "Email")
            text: Extrahierter Volltext des Dokuments

        Returns:
            Anzahl der gespeicherten Chunks (0 bei Fehler oder leerem Text)
        """
        if not self._akte_collection:
            logger.error("RAG Store: 'akte_dokumente' Collection nicht initialisiert!")
            return 0

        if not text or not text.strip():
            logger.warning(f"index_dokument: Kein Text für Dokument {dokument_id} — übersprungen.")
            return 0

        doc_id_str = str(dokument_id)

        # 1. Alte Chunks für dieses Dokument löschen (Re-Indexierung)
        try:
            self._akte_collection.delete(where={"dokument_id": doc_id_str})
            logger.debug(f"index_dokument: Alte Chunks für Dokument {dokument_id} gelöscht.")
        except Exception as e:
            # Kann passieren wenn keine Chunks existieren — kein fataler Fehler
            logger.debug(f"index_dokument: Keine bestehenden Chunks zum Löschen für {dokument_id}: {e}")

        # 2. Text in Chunks aufteilen (~400 Wörter, 50 Wörter Overlap)
        chunks = self._chunk_text_with_overlap(text.strip())
        if not chunks:
            logger.warning(f"index_dokument: Chunking ergab leeres Ergebnis für Dokument {dokument_id}.")
            return 0

        # 3. IDs und Metadaten vorbereiten
        ids = [f"akte_{akte_id}_dok_{dokument_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "akte_id": str(akte_id),
                "dokument_id": doc_id_str,
                "titel": titel or "",
                "kategorie": kategorie or "",
            }
            for _ in chunks
        ]

        # 4. Embeddings via Vertex/Gemini API holen und speichern
        try:
            embeddings = await self._get_vertex_embeddings(chunks)

            if embeddings:
                self._akte_collection.upsert(
                    documents=chunks,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    ids=ids,
                )
            else:
                # Fallback: ChromaDB Default Embeddings (Development ohne API-Key)
                self._akte_collection.upsert(
                    documents=chunks,
                    metadatas=metadatas,
                    ids=ids,
                )

            logger.info(
                f"✓ Dokument {dokument_id} (Akte {akte_id}) indexiert: "
                f"{len(chunks)} Chunks in 'akte_dokumente'"
            )
            return len(chunks)

        except Exception as e:
            logger.error(f"✗ Fehler beim Indexieren von Dokument {dokument_id}: {e}")
            return 0

    async def search_akte_dokumente(
        self,
        query_text: str,
        akte_id: int,
        n_results: int = 8,
    ) -> List[Dict]:
        """
        Sucht in der 'akte_dokumente' Collection — gefiltert nach akte_id.

        Args:
            query_text: Suchtext (z.B. Schadenshergang)
            akte_id: Nur Chunks dieser Akte zurückgeben
            n_results: Max. Anzahl Treffer

        Returns:
            Liste von {text, metadata, distance} Dictionaries
        """
        if not self._akte_collection:
            logger.error("RAG Store: 'akte_dokumente' Collection nicht initialisiert!")
            return []

        filter_dict = {"akte_id": str(akte_id)}

        try:
            embeddings = await self._get_vertex_embeddings([query_text])

            if embeddings:
                results = self._akte_collection.query(
                    query_embeddings=embeddings,
                    n_results=n_results,
                    where=filter_dict,
                )
            else:
                results = self._akte_collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where=filter_dict,
                )

            matches: List[Dict] = []
            if results and results["documents"] and len(results["documents"]) > 0:
                docs = results["documents"][0]
                metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
                dists = results["distances"][0] if "distances" in results and results["distances"] else [0] * len(docs)
                for doc, meta, dist in zip(docs, metas, dists):
                    matches.append({"text": doc, "metadata": meta, "distance": dist})

            return matches

        except Exception as e:
            logger.error(f"✗ Fehler bei der akte_dokumente Suche (akte_id={akte_id}): {e}")
            return []

    def get_alle_akte_chunks(self, akte_id: int) -> List[Dict]:
        """
        Gibt ALLE indexierten Chunks einer Akte zurück — ungefiltert, vollständig.
        Sortiert nach Dokument-ID und Chunk-Index für logische Lesereihenfolge.

        Kein semantisches Filtern — Loki soll die gesamte Akte kennen,
        wie ein Anwalt der die Akte aufschlägt und alles liest.
        """
        if not self._akte_collection:
            logger.error("RAG Store: 'akte_dokumente' Collection nicht initialisiert!")
            return []
        try:
            results = self._akte_collection.get(
                where={"akte_id": str(akte_id)},
                include=["documents", "metadatas"],
            )
            chunks = []
            docs = results.get("documents") or []
            metas = results.get("metadatas") or []
            ids = results.get("ids") or []
            for doc, meta, cid in zip(docs, metas, ids):
                chunks.append({"text": doc, "metadata": meta, "id": cid})
            # Sortieren nach ID (akte_X_dok_Y_chunk_Z) → logische Lesereihenfolge
            chunks.sort(key=lambda c: c.get("id", ""))
            logger.info(f"get_alle_akte_chunks: {len(chunks)} Chunks für Akte {akte_id} geladen.")
            return chunks
        except Exception as e:
            logger.error(f"get_alle_akte_chunks Fehler (akte_id={akte_id}): {e}")
            return []

    def get_indexed_dokument_ids(self, akte_id: int | None = None) -> list[int]:
        """
        Gibt alle dokument_ids zurück, die bereits in 'akte_dokumente' indexiert sind.

        Args:
            akte_id: Nur IDs dieser Akte zurückgeben (None = alle Akten)

        Returns:
            Liste eindeutiger Dokument-IDs als Integer
        """
        if not self._akte_collection:
            return []
        try:
            kwargs: dict = {"include": ["metadatas"]}
            if akte_id is not None:
                kwargs["where"] = {"akte_id": str(akte_id)}
            results = self._akte_collection.get(**kwargs)
            ids: set[int] = set()
            metadatas_raw = results.get("metadatas") if results else None
            for meta in (metadatas_raw or []):
                if meta and meta.get("dokument_id"):
                    try:
                        ids.add(int(meta["dokument_id"]))
                    except (ValueError, TypeError):
                        pass
            return list(ids)
        except Exception as e:
            logger.error(f"get_indexed_dokument_ids Fehler: {e}")
            return []

    async def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str], collection_name: str = "kanzlei_wissen"):
        """
        Fügt Text-Chunks zur Vektordatenbank hinzu.
        
        Args:
            documents: Liste von Rohtexten (Chunks)
            metadatas: Liste von Metadaten-Dicts (z.B. {"fall_typ": "auffahrunfall", "akte": "123"})
            ids: Eindeutige IDs für jeden Chunk (z.B. "akte_123_chunk_1")
            collection_name: Name der Collection ('kanzlei_wissen' oder 'system_wissen')
        """
        target_collection = self._system_collection if collection_name == "system_wissen" else self._collection
        
        if not target_collection:
            logger.error(f"RAG Store Collection '{collection_name}' nicht initialisiert!")
            return False
            
        try:
            # Hole Embeddings via Vertex REST API (ohne SDK)
            embeddings = await self._get_vertex_embeddings(documents)
            
            if embeddings:
                target_collection.upsert(
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    ids=ids
                )
            else:
                # Fallback: ChromaDB Default Embeddings (all-MiniLM-L6-v2) 
                # Nur lokal für Development, wenn kein Vertex Key da ist
                target_collection.upsert(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
                
            logger.info(f"✓ {len(documents)} Chunks erfolgreich in RAG Store ({collection_name}) gespeichert.")
            return True
        except Exception as e:
            logger.error(f"✗ Fehler beim Speichern im RAG Store ({collection_name}): {e}")
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

    async def search_similar(self, query_text: str, n_results: int = 3, filter_dict: Optional[Dict] = None, collection_name: str = "kanzlei_wissen") -> List[Dict]:
        """
        Sucht nach ähnlichen Dokumenten basierend auf einem Suchtext.
        
        Args:
            query_text: Der Text, nach dem gesucht wird (z.B. Kontext des neuen Falls)
            n_results: Anzahl der gewünschten Treffer
            filter_dict: Optionaler Filter (z.B. {"fall_typ": "auffahrunfall"})
            collection_name: Name der Collection
            
        Returns:
            Liste von Dictionaries mit den Chunks und Metadaten.
        """
        target_collection = self._system_collection if collection_name == "system_wissen" else self._collection
        
        if not target_collection:
            logger.error(f"RAG Store Collection '{collection_name}' nicht initialisiert!")
            return []
            
        try:
            # Versuche zuerst die Vertex Embeddings zu holen
            embeddings = await self._get_vertex_embeddings([query_text]) if hasattr(self, '_get_vertex_embeddings') else None
            
            if embeddings:
                results = target_collection.query(
                    query_embeddings=embeddings,
                    n_results=n_results,
                    where=filter_dict
                )
            else:
                # Fallback
                results = target_collection.query(
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

    def get_health(self) -> Dict[str, Any]:
        """
        Gibt den Gesundheitszustand aller 3 ChromaDB-Collections zurück.
        Wird vom RAG-Dashboard als Übersicht angezeigt.
        """
        collections_info = []
        total_chunks = 0

        def _collection_stats(collection, id_field: str = "document_id") -> Dict:
            if not collection:
                return {"chunk_count": 0, "document_count": 0}
            count = collection.count()
            data = collection.get(include=["metadatas"])
            metadatas_list = data.get("metadatas") or []
            unique_docs = len(set(
                m.get(id_field, "") for m in metadatas_list if m and m.get(id_field)
            ))
            return {"chunk_count": count, "document_count": unique_docs}

        # 1. kanzlei_wissen (Goldstandard-Schreiben, manuell)
        kw = _collection_stats(self._collection, "document_id")
        total_chunks += kw["chunk_count"]
        collections_info.append({
            "name": "kanzlei_wissen",
            "label": "Goldstandard-Schreiben",
            "description": "Manuell kuratierte Referenzschreiben für die KI",
            **kw,
        })

        # 2. system_wissen (Programm-Dokumentation)
        sw = _collection_stats(self._system_collection, "document_id")
        total_chunks += sw["chunk_count"]
        collections_info.append({
            "name": "system_wissen",
            "label": "System-Wissen",
            "description": "Kanzlei-Programm-Dokumentation und Prozesse",
            **sw,
        })

        # 3. akte_dokumente (auto-indexiert)
        ad = _collection_stats(self._akte_collection, "dokument_id")
        total_chunks += ad["chunk_count"]
        # Anzahl eindeutiger Akten zusätzlich ermitteln
        akte_count = 0
        if self._akte_collection:
            try:
                data = self._akte_collection.get(include=["metadatas"]) or {}
                akte_count = len(set(
                    m.get("akte_id", "") for m in (data.get("metadatas") or []) if m and m.get("akte_id")
                ))
            except Exception:
                pass
        collections_info.append({
            "name": "akte_dokumente",
            "label": "Akte-Dokumente",
            "description": "Automatisch indexierte Dokumente aus allen Akten",
            "chunk_count": ad["chunk_count"],
            "document_count": ad["document_count"],
            "akte_count": akte_count,
        })

        return {
            "status": "ok",
            "total_chunks": total_chunks,
            "collections": collections_info,
        }

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
