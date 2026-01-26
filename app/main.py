"""
FastAPI Main Application
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import logging

from app.config import settings

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Kanzlei AI Service",
    description="KI-gestützter Service für automatisierte Aktenanlage",
    version="0.1.0",
    debug=settings.debug
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Kanzlei AI Service",
        "version": "0.1.0",
        "status": "running",
        "provider": settings.llm_provider
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "provider": settings.llm_provider,
        "backend_url": settings.backend_url
    }


@app.post("/api/akte/create-from-email")
async def create_akte_from_email(
    email_file: UploadFile = File(...),
    attachments: List[UploadFile] = File(default=[])
):
    """
    Erstellt eine neue Akte aus E-Mail und Anhängen
    
    Args:
        email_file: E-Mail Datei (.eml oder .msg)
        attachments: Liste von Anhängen
        
    Returns:
        Job-ID für Status-Tracking
    """
    try:
        logger.info(f"Received email: {email_file.filename}")
        logger.info(f"Attachments: {len(attachments)}")
        
        # TODO: Implement actual processing
        # 1. Parse email
        # 2. Extract data with LLM
        # 3. Create Akte via Backend API
        # 4. Upload documents
        # 5. Create ticket
        
        return {
            "status": "processing",
            "job_id": "placeholder-123",
            "message": "E-Mail wird verarbeitet (noch nicht implementiert)"
        }
        
    except Exception as e:
        logger.error(f"Error processing email: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/job/{job_id}")
async def get_job_status(job_id: str):
    """
    Gibt den Status eines Jobs zurück
    
    Args:
        job_id: Job-ID
        
    Returns:
        Job-Status und Ergebnis
    """
    # TODO: Implement job tracking
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job-Tracking noch nicht implementiert"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug
    )
