"""
Backend API Client - Kommunikation mit Django Backend
"""
import httpx
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class BackendClient:
    """Client für Django Backend API"""
    
    def __init__(self):
        """Initialize Backend client"""
        self.base_url = settings.backend_url
        self.token = settings.backend_api_token
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        logger.info(f"Backend client initialized: {self.base_url}")
    
    async def create_akte(self, akte_data: dict) -> dict:
        """
        Erstellt eine neue Akte via Backend API
        
        Args:
            akte_data: Aktendaten
            
        Returns:
            Erstellte Akte
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/akten/",
                    json=akte_data,
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(f"Akte created: {result.get('id')}")
                return result
                
        except Exception as e:
            logger.error(f"Backend API error (create_akte): {str(e)}")
            raise
    
    async def create_mandant(self, mandant_data: dict) -> dict:
        """Erstellt einen neuen Mandanten"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/mandanten/",
                    json=mandant_data,
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"Backend API error (create_mandant): {str(e)}")
            raise
    
    async def create_gegner(self, gegner_data: dict) -> dict:
        """Erstellt einen neuen Gegner"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/gegner/",
                    json=gegner_data,
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"Backend API error (create_gegner): {str(e)}")
            raise
    
    async def upload_document(self, akte_id: int, file_data: bytes, filename: str, doc_type: str) -> dict:
        """
        Lädt ein Dokument zur Akte hoch
        
        Args:
            akte_id: Akten-ID
            file_data: Datei-Bytes
            filename: Dateiname
            doc_type: Dokumententyp
            
        Returns:
            Hochgeladenes Dokument
        """
        try:
            async with httpx.AsyncClient() as client:
                files = {"file": (filename, file_data)}
                data = {
                    "akte": akte_id,
                    "typ": doc_type
                }
                
                response = await client.post(
                    f"{self.base_url}/api/dokumente/",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"Backend API error (upload_document): {str(e)}")
            raise
    
    async def create_ticket(self, ticket_data: dict) -> dict:
        """Erstellt ein Ticket"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/tickets/",
                    json=ticket_data,
                    headers=self.headers,
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
                
        except Exception as e:
            logger.error(f"Backend API error (create_ticket): {str(e)}")
            raise


# Global instance
backend_client = BackendClient()
