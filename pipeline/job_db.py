"""
job_db.py – SQLite-backed job ledger with state machine semantics.

Every article goes through a fixed sequence of states.  The ledger
supports resumability (re-run picks up where it left off) and
provides a single source of truth for pipeline progress.

States:
    PENDING → HTML_SCRAPED → LINKS_EXTRACTED → FILES_DOWNLOADED
            → PDF_PROCESSED → TEXT_EXTRACTED → DONE
    Any state can also transition to FAILED (with an error message).
"""

from __future__ import annotations
import sqlite3
import logging
from pathlib import Path
from enum import Enum
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    PENDING          = "PENDING"
    HTML_SCRAPED     = "HTML_SCRAPED"
    LINKS_EXTRACTED  = "LINKS_EXTRACTED"
    FILES_DOWNLOADED = "FILES_DOWNLOADED"
    PDF_PROCESSED    = "PDF_PROCESSED"
    TEXT_EXTRACTED   = "TEXT_EXTRACTED"
    DONE             = "DONE"
    FAILED           = "FAILED"
    SKIPPED          = "SKIPPED"


# Allowed forward transitions (excluding FAILED, which is always allowed)
_TRANSITIONS = {
    JobStatus.PENDING:          JobStatus.HTML_SCRAPED,
    JobStatus.HTML_SCRAPED:     JobStatus.LINKS_EXTRACTED,
    JobStatus.LINKS_EXTRACTED:  JobStatus.FILES_DOWNLOADED,
    JobStatus.FILES_DOWNLOADED: JobStatus.PDF_PROCESSED,
    JobStatus.PDF_PROCESSED:    JobStatus.TEXT_EXTRACTED,
    JobStatus.TEXT_EXTRACTED:    JobStatus.DONE,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,          -- row index from CSV
    url         TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'PENDING',
    doi         TEXT,                          -- extracted DOI (e.g. 10.1021/jacs.4c07999)
    html_path   TEXT,
    si_links    TEXT,                          -- JSON list of download URLs
    error       TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id),
    url         TEXT    NOT NULL,
    local_path  TEXT,
    file_type   TEXT,                          -- pdf, xyz, cif, etc.
    processed   INTEGER NOT NULL DEFAULT 0,    -- 0=no, 1=yes
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_downloads_job ON downloads(job_id);
"""


class JobDB:
    """Thin wrapper around SQLite for the pipeline job ledger."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        # Migrate existing DBs: add doi column if missing
        try:
            self.conn.execute("SELECT doi FROM jobs LIMIT 1")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN doi TEXT")
        self.conn.commit()

    # ── Bulk-load jobs from a URL list ───────────────────────────────────
    def load_urls(self, urls: list[tuple[int, str]]) -> int:
        """Insert (index, url) pairs that don't already exist. Returns count added."""
        now = _now()
        added = 0
        for idx, url in urls:
            existing = self.conn.execute(
                "SELECT id FROM jobs WHERE id = ?", (idx,)
            ).fetchone()
            if not existing:
                self.conn.execute(
                    "INSERT INTO jobs (id, url, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (idx, url, JobStatus.PENDING, now, now),
                )
                added += 1
        self.conn.commit()
        return added

    # ── Query jobs by status ─────────────────────────────────────────────
    def get_jobs(
        self,
        status: JobStatus | list[JobStatus],
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        statuses = [status] if isinstance(status, JobStatus) else status
        placeholders = ",".join("?" for _ in statuses)
        q = f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY id"
        params: list = [s.value for s in statuses]
        if limit:
            q += " LIMIT ? OFFSET ?"
            params += [limit, offset]
        return self.conn.execute(q, params).fetchall()

    def get_job(self, job_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()

    # ── State transitions ────────────────────────────────────────────────
    def advance(self, job_id: int, new_status: JobStatus, **kwargs) -> None:
        """Move a job to the next state, with optional field updates."""
        sets = ["status = ?", "updated_at = ?"]
        vals: list = [new_status.value, _now()]
        for col in ("html_path", "si_links", "error", "doi"):
            if col in kwargs:
                sets.append(f"{col} = ?")
                vals.append(kwargs[col])
        vals.append(job_id)
        self.conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", vals
        )
        self.conn.commit()

    def fail(self, job_id: int, error: str) -> None:
        self.advance(job_id, JobStatus.FAILED, error=error)

    def skip(self, job_id: int, reason: str = "") -> None:
        self.advance(job_id, JobStatus.SKIPPED, error=reason)

    # ── Downloads sub-table ──────────────────────────────────────────────
    def add_download(self, job_id: int, url: str, local_path: str, file_type: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO downloads (job_id, url, local_path, file_type, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_id, url, local_path, file_type, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_downloads(self, job_id: int, file_type: Optional[str] = None) -> list[sqlite3.Row]:
        if file_type:
            return self.conn.execute(
                "SELECT * FROM downloads WHERE job_id = ? AND file_type = ?",
                (job_id, file_type),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM downloads WHERE job_id = ?", (job_id,)
        ).fetchall()

    def mark_download_processed(self, download_id: int) -> None:
        self.conn.execute(
            "UPDATE downloads SET processed = 1 WHERE id = ?", (download_id,)
        )
        self.conn.commit()

    # ── Reporting ────────────────────────────────────────────────────────
    def summary(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def close(self):
        self.conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
