"""
Email Processing Service
Handles parsing of email files (.eml)
"""
import email
from email.message import Message
from typing import List, Optional, Tuple
from pydantic import BaseModel
import logging
from fastapi import UploadFile

logger = logging.getLogger(__name__)

class EmailAttachment(BaseModel):
    filename: str
    content: bytes
    content_type: str

class EmailContent(BaseModel):
    subject: str = ""
    sender: str = ""
    recipient: str = ""
    date: str = ""
    body: str = ""
    attachments: List[EmailAttachment] = []

class EmailProcessor:
    async def process_eml(self, file_data) -> EmailContent:
        """Parse an EML file (UploadFile or bytes)"""
        if hasattr(file_data, 'read'):
            content = await file_data.read()
            # Reset if it's an UploadFile that we might want to read again (though we shouldn't need to)
            if hasattr(file_data, 'seek'):
                await file_data.seek(0)
        else:
            content = file_data
            
        msg = email.message_from_bytes(content)
        
        email_data = EmailContent(
            subject=msg.get("subject", ""),
            sender=msg.get("from", ""),
            recipient=msg.get("to", ""),
            date=msg.get("date", "")
        )
        
        # Extract Body
        email_data.body = self._get_body(msg)
        
        # Extract Attachments
        email_data.attachments = self._get_attachments(msg)
        

        
        return email_data

    def _get_body(self, msg: Message) -> str:
        """Extract plain text body"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get('Content-Disposition'))

                # skip any text/plain (txt) attachments
                if ctype == 'text/plain' and 'attachment' not in cdispo:
                    try:
                        part_content = part.get_payload(decode=True)
                        if part_content:
                            body += part_content.decode('utf-8', errors='replace')
                    except Exception:
                        pass
        else:
            try:
                part_content = msg.get_payload(decode=True)
                if part_content:
                    body = part_content.decode('utf-8', errors='replace')
            except Exception:
                pass
                
        return body

    def _get_attachments(self, msg: Message) -> List[EmailAttachment]:
        """Extract attachments"""
        attachments = []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if part.get('Content-Disposition') is None:
                continue

            filename = part.get_filename()
            if filename:
                content = part.get_payload(decode=True)
                if content:
                    attachments.append(EmailAttachment(
                        filename=filename,
                        content=content,
                        content_type=part.get_content_type()
                    ))
        return attachments

email_processor = EmailProcessor()
