"""
Job Tracker for AI Service
Tracks progress of AI jobs in-memory
"""
from typing import Dict, Optional
from datetime import datetime

class JobTracker:
    def __init__(self):
        self.jobs: Dict[str, dict] = {}
    
    def create_job(self, job_id: str):
        """Initialize a new job"""
        self.jobs[job_id] = {
            'job_id': job_id,
            'status': 'processing',
            'current_step': 'email_analysis',
            'steps': {
                'email_analysis': {'status': 'processing', 'message': 'E-Mail wird analysiert...'},
                'mandant_creation': {'status': 'pending', 'message': 'Mandant erstellen'},
                'akte_creation': {'status': 'pending', 'message': 'Akte erstellen'},
                'document_upload': {'status': 'pending', 'message': 'Dokumente hochladen'},
                'ticket_creation': {'status': 'pending', 'message': 'Ticket erstellen'}
            },
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
    
    def update_step(self, job_id: str, step: str, status: str, message: Optional[str] = None):
        """Update a specific step"""
        if job_id not in self.jobs:
            return
        
        self.jobs[job_id]['current_step'] = step
        self.jobs[job_id]['steps'][step]['status'] = status
        if message:
            self.jobs[job_id]['steps'][step]['message'] = message
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()
    
    def complete_job(self, job_id: str, akte_id: int, aktenzeichen: str):
        """Mark job as completed"""
        if job_id not in self.jobs:
            return
        
        self.jobs[job_id]['status'] = 'completed'
        self.jobs[job_id]['akte_id'] = akte_id
        self.jobs[job_id]['aktenzeichen'] = aktenzeichen
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()
    
    def fail_job(self, job_id: str, error: str):
        """Mark job as failed"""
        if job_id not in self.jobs:
            return
        
        self.jobs[job_id]['status'] = 'failed'
        self.jobs[job_id]['error'] = error
        self.jobs[job_id]['updated_at'] = datetime.utcnow().isoformat()
    
    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job status"""
        return self.jobs.get(job_id)

# Global instance
job_tracker = JobTracker()
