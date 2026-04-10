from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from app.core.security import get_current_user
from app.models.user import User
from app.services.scheduler import job_scrape_and_store, scheduler

router = APIRouter(prefix="/scraper", tags=["scraper"])


class JobStatus(BaseModel):
    job_id: str
    next_run_time: str | None
    status: str


@router.post("/trigger", status_code=202)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    _: User = Depends(get_current_user),
):
    """Manually trigger a scrape job immediately (runs in background)."""
    background_tasks.add_task(job_scrape_and_store)
    return {"message": "Scrape job triggered", "status": "queued"}


@router.get("/jobs", response_model=list[JobStatus])
async def list_jobs(_: User = Depends(get_current_user)):
    """List all scheduled jobs and their next run times."""
    jobs = scheduler.get_jobs()
    return [
        JobStatus(
            job_id=job.id,
            next_run_time=str(job.next_run_time) if job.next_run_time else None,
            status="scheduled" if job.next_run_time else "paused",
        )
        for job in jobs
    ]
