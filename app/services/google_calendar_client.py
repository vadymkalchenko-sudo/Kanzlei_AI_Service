import logging
import os
import httpx
from typing import Optional, List, Dict
from datetime import date, datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Constants
DJANGO_CALENDAR_TOKEN_URL = "http://host.docker.internal:8001/api/core/google/calendar/token/"
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

class GoogleCalendarClient:
    """
    Synchronisiert Fristen und Aufgaben aus Kanzlei V3 in Google Calendar.

    Nutzt OAuth2 User-Credentials (refresh_token aus Django SystemSettings).
    Ohne Credentials: Mock-Modus (tut nichts, gibt None zurück).

    Calendar-ID: "primary" (Hauptkalender des autorisierten Users)
    """
    
    def __init__(self):
        self.enabled = True
        self.creds = self._get_credentials()
        self.service = self._build_service()
        
    def _get_refresh_token(self) -> Optional[str]:
        """Holt den refresh_token vom Django Backend."""
        try:
            from app.services.hmac_auth import get_hmac_headers
            headers = get_hmac_headers()
            # 5 Sekunden Timeout, wichtig damit der Service beim Start nicht hängt
            response = httpx.get(DJANGO_CALENDAR_TOKEN_URL, headers=headers, timeout=5.0)
            
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
        """Initialisiert den Google Calendar API Client."""
        if not self.enabled or not self.creds:
            return None
            
        try:
            # Refresh automatically on first use
            if not self.creds.valid:
                self.creds.refresh(Request())
            return build('calendar', 'v3', credentials=self.creds, cache_discovery=False)
        except Exception as e:
            logger.error(f"Fehler beim Aufbau des Calendar Services: {e}")
            self.enabled = False
            return None

    def create_event(self, titel: str, datum: date, beschreibung: str = "", akte_id: Optional[int] = None) -> Optional[str]:
        """Erstellt ein Google Calendar Event (Ganztägiges Event). Returns: event_id oder None."""
        if not self.enabled or not self.service:
            logger.info(f"Mock-Modus (create_event): {titel} am {datum} (Akte: {akte_id})")
            return None
            
        try:
            event_body = {
                'summary': titel,
                'description': f"{beschreibung}\n\n[Erstellt via Kanzlei AI Service]" if beschreibung else "[Erstellt via Kanzlei AI Service]",
                'start': {
                    'date': datum.isoformat(),
                },
                'end': {
                    'date': datum.isoformat(),
                },
                'extendedProperties': {
                    'private': {
                        'origin': 'kanzlei_ai_service'
                    }
                }
            }
            if akte_id:
                event_body['extendedProperties']['private']['akte_id'] = str(akte_id)

            event = self.service.events().insert(calendarId='primary', body=event_body).execute()
            logger.info(f"Event erstellt: {event.get('htmlLink')}")
            return event.get('id')
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Events: {e}")
            return None

    def update_event(self, event_id: str, titel: str, datum: date) -> bool:
        """Aktualisiert ein bestehendes Event."""
        if not self.enabled or not self.service:
            logger.info(f"Mock-Modus (update_event): ID={event_id}, Titel={titel}, Datum={datum}")
            return False
            
        try:
            # First retrieve the existing event
            event = self.service.events().get(calendarId='primary', eventId=event_id).execute()
            
            # Update fields
            event['summary'] = titel
            event['start']['date'] = datum.isoformat()
            event['end']['date'] = datum.isoformat()
            
            updated_event = self.service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
            logger.info(f"Event aktualisiert: {updated_event.get('htmlLink')}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren des Events: {e}")
            return False

    def delete_event(self, event_id: str) -> bool:
        """Löscht ein Event."""
        if not self.enabled or not self.service:
            logger.info(f"Mock-Modus (delete_event): ID={event_id}")
            return False
            
        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            logger.info(f"Event gelöscht: {event_id}")
            return True
            
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Events: {e}")
            return False

    def get_upcoming_events(self, tage: int = 14) -> list[dict]:
        """Gibt Events der nächsten N Tage zurück."""
        if not self.enabled or not self.service:
            logger.info(f"Mock-Modus (get_upcoming_events): {tage} Tage")
            return []
            
        try:
            now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
            time_max = (datetime.utcnow() + timedelta(days=tage)).isoformat() + 'Z'
            
            events_result = self.service.events().list(
                calendarId='primary', 
                timeMin=now,
                timeMax=time_max,
                maxResults=50, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            return events
            
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Events: {e}")
            return []

# Singleton export
google_calendar_client = GoogleCalendarClient()
