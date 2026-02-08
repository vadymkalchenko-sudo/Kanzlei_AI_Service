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
import extract_msg  # New dependency

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
    async def process_email(self, file_data, filename: str) -> EmailContent:
        """Parse an email file (.eml or .msg)"""
        
        # Determine file type
        is_msg = filename.lower().endswith('.msg')
        
        # Read content bytes
        if hasattr(file_data, 'read'):
            content = await file_data.read()
            if hasattr(file_data, 'seek'):
                await file_data.seek(0)
        else:
            content = file_data

        if is_msg:
            return self._process_outlook_msg(content)
        else:
            return self._process_eml_content(content)

    def _process_eml_content(self, content: bytes) -> EmailContent:
        msg = email.message_from_bytes(content)
        
        email_data = EmailContent(
            subject=msg.get("subject", ""),
            sender=msg.get("from", ""),
            recipient=msg.get("to", ""),
            date=msg.get("date", "")
        )
        
        email_data.body = self._get_body(msg)
        email_data.attachments = self._get_attachments(msg)
        
        return email_data

    def _process_outlook_msg(self, content: bytes) -> EmailContent:
        """Parse Outlook .msg format"""
        try:
            msg = extract_msg.Message(content)
            
            email_data = EmailContent(
                subject=msg.subject or "",
                sender=msg.sender or "",
                recipient=msg.to or "",
                date=str(msg.date) if msg.date else "",
                body=msg.body or ""
            )

            # Attachments
            for att in msg.attachments:
                # generate filename if missing
                fname = att.longFilename or att.shortFilename or "unknown_attachment"
                
                # Get content type if available, else octet-stream
                # extract-msg attachments usually have 'data' property
                att_content = att.data
                
                # Content type guessing could be added here, currently defaulting
                ctype = "application/octet-stream"
                
                email_data.attachments.append(EmailAttachment(
                    filename=fname,
                    content=att_content,
                    content_type=ctype
                ))
                
            msg.close()
            return email_data
            
        except Exception as e:
            logger.error(f"Error parsing MSG file: {e}")
            raise ValueError(f"Failed to parse MSG file: {e}")

    def _get_body(self, msg: Message) -> str:
        """Extract plain text body from EML"""
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
        """Extract attachments from EML"""
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
