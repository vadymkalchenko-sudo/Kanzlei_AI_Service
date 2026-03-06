import logging
import os
import httpx
import base64
from email.mime.text import MIMEText
from typing import Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Constants
DJANGO_GMAIL_TOKEN_URL = "http://host.docker.internal:8001/api/core/google/gmail/token/"
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

class GoogleGmailClient:
    """
    Google Gmail Client — Kanzlei AI Service

    Sendet E-Mails im Namen des autorisierten Users (OAuth2).
    Ohne Credentials: Mock-Modus (loggt nur, sendet nicht).

    Konfiguration:
        refresh_token: wird von Django geholt via GET /api/core/google/gmail/token/
        GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET: aus .env
        GOOGLE_DELEGATE_EMAIL: Absender-Adresse
    """
    
    def __init__(self):
        self.enabled = True
        self.creds = self._get_credentials()
        self.service = self._build_service()
        self.absender = os.getenv("GOOGLE_DELEGATE_EMAIL", "")

    def _get_refresh_token(self) -> Optional[str]:
        """Holt den refresh_token vom Django Backend."""
        try:
            from app.services.hmac_auth import get_hmac_headers
            headers = get_hmac_headers()
            response = httpx.get(DJANGO_GMAIL_TOKEN_URL, headers=headers, timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('refresh_token')
            elif response.status_code == 503:
                logger.warning("Mock-Modus: Token-Endpoint meldet 503 (oder leerer Token).")
                self.enabled = False
                return None
            else:
                logger.error(f"Fehler beim Abruf des refresh_tokens. Status: {response.status_code}")
                self.enabled = False
                return None
                
        except Exception as e:
            logger.error(f"Konnte refresh_token nicht abrufen: {e}")
            self.enabled = False
            return None

    def _get_credentials(self) -> Optional[Credentials]:
        """Erstellt Google Credentials aus dem refresh_token."""
        refresh_token = self._get_refresh_token()
        if not refresh_token:
            return None
            
        client_id = os.getenv("GOOGLE_CLIENT_ID")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.error("GOOGLE_CLIENT_ID oder GOOGLE_CLIENT_SECRET nicht gesetzt.")
            self.enabled = False
            return None
            
        try:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=SCOPES,
            )
            return creds
        except Exception as e:
            logger.error(f"Fehler bei Erstellung der Credentials: {e}")
            self.enabled = False
            return None

    def _build_service(self):
        """Initialisiert den Google Gmail API Client."""
        if not self.enabled or not self.creds:
            return None
            
        try:
            if not self.creds.valid:
                self.creds.refresh(Request())
            return build('gmail', 'v1', credentials=self.creds, cache_discovery=False)
        except Exception as e:
            logger.error(f"Fehler beim Aufbau des Gmail Services: {e}")
            self.enabled = False
            return None

    def _build_message(self, absender: str, an: str, betreff: str, text: str, cc: str = '', reply_to: str = '') -> dict:
        """Erstellt eine RFC 2822 base64url-encodierte Nachricht."""
        msg = MIMEText(text, 'plain', 'utf-8')
        msg['to'] = an
        msg['from'] = absender
        msg['subject'] = betreff
        if cc:
            msg['cc'] = cc
        if reply_to:
            msg['reply-to'] = reply_to
            
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return {'raw': raw}

    def send_email(
        self,
        an: str,             # Empfänger-E-Mail
        betreff: str,        # Betreff
        text: str,           # E-Mail-Body (Plaintext)
        cc: str = '',        # Optional CC
        reply_to: str = '',  # Optional Reply-To
    ) -> bool:
        """
        Sendet eine E-Mail.
        Returns: True bei Erfolg, False bei Fehler/Mock-Modus.
        """
        if not self.enabled or not self.service:
            logger.info(f"Mock-Modus (send_email): An={an}, Betreff='{betreff}'")
            return False
            
        if not self.absender:
            logger.error("GOOGLE_DELEGATE_EMAIL ist nicht gesetzt. Kann keine E-Mail senden.")
            return False
            
        try:
            body = self._build_message(self.absender, an, betreff, text, cc, reply_to)
            
            # Use 'me' to indicate the authenticated user
            sent_message = self.service.users().messages().send(userId='me', body=body).execute()
            logger.info(f"E-Mail gesendet an {an}: Message ID {sent_message.get('id')}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Senden der E-Mail an {an}: {e}")
            return False

# Singleton export
google_gmail_client = GoogleGmailClient()
