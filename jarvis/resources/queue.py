"""Download queue status. Does not execute downloaded files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Status = Literal["queued", "running", "done", "failed"]


@dataclass
class DownloadJob:
    url: str
    status: Status = "queued"
    error: str = ""


@dataclass
class DownloadQueue:
    jobs: list[DownloadJob] = field(default_factory=list)

    def enqueue(self, url: str) -> DownloadJob:
        if not url.startswith("https://"):
            raise ValueError("https required")
        job = DownloadJob(url=url)
        self.jobs.append(job)
        return job

    def mark(self, job: DownloadJob, status: Status, error: str = "") -> None:
        job.status = status
        job.error = error[:200]

    def summary(self) -> dict:
        return {
            "queued": sum(1 for j in self.jobs if j.status == "queued"),
            "running": sum(1 for j in self.jobs if j.status == "running"),
            "done": sum(1 for j in self.jobs if j.status == "done"),
            "failed": sum(1 for j in self.jobs if j.status == "failed"),
        }
