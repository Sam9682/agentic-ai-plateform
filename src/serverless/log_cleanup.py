"""Serverless Docker Execution Service - Log Cleanup.

This module provides the cleanup_old_logs function that purges old job logs
and completed jobs from the database. Intended to be called on a daily
schedule from the worker service.
"""

import logging
from typing import Any, Dict, Tuple

import psycopg2

logger = logging.getLogger(__name__)


def cleanup_old_logs(db_config: Dict[str, Any]) -> Tuple[int, int]:
    """Delete old job logs and completed jobs older than 30 days.

    Removes entries from serverless_job_logs where created_at is older than
    30 days, and removes entries from serverless_jobs where completed_at is
    older than 30 days and the job is in a terminal state.

    Args:
        db_config: Database connection parameters with keys:
            host, port, database, user, password.

    Returns:
        A tuple of (logs_deleted, jobs_deleted) counts.

    Raises:
        Exception: Re-raises any database connection or execution errors
            after logging them.
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=db_config['host'],
            port=db_config['port'],
            dbname=db_config['database'],
            user=db_config['user'],
            password=db_config['password'],
        )
        conn.autocommit = False
        with conn.cursor() as cur:
            # Delete old job logs
            cur.execute(
                """DELETE FROM serverless_job_logs
                   WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '30 days'"""
            )
            logs_deleted = cur.rowcount

            # Delete old completed/terminal jobs
            cur.execute(
                """DELETE FROM serverless_jobs
                   WHERE completed_at < CURRENT_TIMESTAMP - INTERVAL '30 days'
                   AND status IN ('completed', 'failed', 'timeout', 'cancelled')"""
            )
            jobs_deleted = cur.rowcount

        conn.commit()
        logger.info(
            "Log cleanup completed: %d log entries deleted, %d jobs deleted",
            logs_deleted,
            jobs_deleted,
        )
        return (logs_deleted, jobs_deleted)
    except Exception as e:
        logger.error("Log cleanup failed: %s", e)
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()
