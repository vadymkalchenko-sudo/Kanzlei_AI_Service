"""
E-Mail Parser Service
"""
import email
from email import policy
from email.parser import BytesParser
import logging

logger = logging.getLogger(__name__)


class EmailParser:
    """Parser for email files (.eml, .msg)"""
    
    async def parse_email(self, email_bytes: bytes) -> dict:
        """
        Parst E-Mail Datei
        
        Args:
            email_bytes: E-Mail als Bytes
            
        Returns:
            Dictionary mit E-Mail Daten
        """
        try:
            # Parse .eml format
            msg = BytesParser(policy=policy.default).parsebytes(email_bytes)
            
            # Extract basic info
            result = {
                "from": self._extract_email_address(msg.get("From", "")),
                "to": self._extract_email_address(msg.get("To", "")),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
                "body": self._extract_body(msg),
                "attachments": []
            }
            
            logger.info(f"Email parsed: {result['subject']}")
            return result
            
        except Exception as e:
            logger.error(f"Email parsing error: {str(e)}")
            raise
    
    def _extract_email_address(self, email_str: str) -> str:
        """Extrahiert E-Mail Adresse aus String"""
        # Simple extraction, can be improved
        if "<" in email_str and ">" in email_str:
            return email_str.split("<")[1].split(">")[0]
        return email_str.strip()
    
    def _extract_body(self, msg) -> str:
        """Extrahiert E-Mail Body (Text)"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode()
                        break
                    except:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode()
            except:
                body = str(msg.get_payload())
        
        return body.strip()


# Global instance
email_parser = EmailParser()
