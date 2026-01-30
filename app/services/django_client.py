"""
Django Client Service
Handles communication with the main Kanzlei Application
"""
import httpx
import logging
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)


class DjangoClient:
    def __init__(self):
        self.base_url = settings.backend_url.rstrip('/')
        self.api_token = settings.backend_api_token
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        self.timeout = 30.0

    async def _post_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generic POST request handler"""
        url = f"{self.base_url}/api/ai/{endpoint}"
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP Error calling {endpoint}: {e.response.text}")
                raise Exception(f"Backend API Error: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Connection Error calling {endpoint}: {str(e)}")
                raise Exception(f"Backend Connection Error: {str(e)}")

    async def create_mandant(self, mandant_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Mandant"""
        # Payload structure should match AIMandantCreateSerializer
        return await self._post_request("mandant/create", mandant_data)

    async def lookup_or_create_gegner(self, gegner_data: Dict[str, Any]) -> Dict[str, Any]:
        """Find or create a Gegner (Versicherung)"""
        return await self._post_request("gegner/lookup-or-create", gegner_data)

    async def create_akte(self, akte_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Akte"""
        # Payload: mandant_id, gegner_id, aktenzeichen (optional), etc.
        return await self._post_request("akte/create", akte_data)

    async def create_ticket(self, ticket_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new Ticket"""
        return await self._post_request("ticket/create", ticket_data)

    async def upload_dokument(self, akte_id: int, file_content: bytes, filename: str, titel: str) -> Dict[str, Any]:
        """Upload a document to an Akte"""
        url = f"{self.base_url}/api/ai/dokument/upload"
        
        # Multipart form data requires special handling
        files = {'file': (filename, file_content)}
        data = {
            'akte': str(akte_id),
            'titel': titel
        }
        
        # Don't set Content-Type header manually for multipart
        headers = {k: v for k, v in self.headers.items() if k != 'Content-Type'}
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, data=data, files=files, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.error(f"Error uploading document: {str(e)}")
                raise

# Global instance
django_client = DjangoClient()
