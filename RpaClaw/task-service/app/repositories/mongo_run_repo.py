"""MongoDB-backed task run repository."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.db import db
from app.models.task import TaskRunOut, task_run_doc_to_out
from app.repositories.base import TaskRunRepository


class MongoRunRepository(TaskRunRepository):
    """MongoDB implementation of TaskRunRepository, delegating to the shared db object."""

    async def get_run(self, run_id: str) -> Optional[TaskRunOut]:
        """Retrieve a task run by ID.

        Args:
            run_id: The run identifier

        Returns:
            TaskRunOut if found, None otherwise
        """
        doc = await db.get_collection("task_runs").find_one({"_id": run_id})
        if not doc:
            return None
        return task_run_doc_to_out(doc)

    async def list_runs(
        self,
        task_id: str,
        skip: int = 0,
        limit: int = 20,
    ) -> List[TaskRunOut]:
        """List task runs for a specific task with pagination.

        Args:
            task_id: The task identifier
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of task runs sorted by start_time descending
        """
        cursor = (
            db.get_collection("task_runs")
            .find({"task_id": task_id})
            .sort("start_time", -1)
            .skip(skip)
            .limit(limit)
        )
        return [task_run_doc_to_out(doc) async for doc in cursor]

    async def create_run(
        self,
        task_id: str,
        status: str,
        chat_id: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> TaskRunOut:
        """Create a new task run record.

        Args:
            task_id: The task identifier
            status: Run status (success | failed | running)
            chat_id: Associated chat session ID
            result: Run result message
            error: Error message if failed

        Returns:
            The created task run
        """
        now = datetime.now(timezone.utc)
        doc: Dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "chat_id": chat_id,
            "start_time": now,
            "end_time": None,
            "result": result,
            "error": error,
        }
        ins = await db.get_collection("task_runs").insert_one(doc)
        # After insert_one, Motor adds _id to the doc dict in-place
        doc["_id"] = ins.inserted_id
        logger.debug(f"MongoRunRepository: run created {ins.inserted_id} for task {task_id}")
        return task_run_doc_to_out(doc)

    async def update_run(
        self,
        run_id: str,
        status: Optional[str] = None,
        chat_id: Optional[str] = None,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[TaskRunOut]:
        """Update an existing task run.

        Args:
            run_id: The run identifier
            status: New status
            chat_id: Associated chat session ID
            result: Run result message
            error: Error message

        Returns:
            The updated task run if found, None otherwise
        """
        doc = await db.get_collection("task_runs").find_one({"_id": run_id})
        if not doc:
            return None

        updates: Dict[str, Any] = {}

        if status is not None:
            updates["status"] = status
            # Set end_time when transitioning to a final state
            if status in ("success", "failed"):
                updates["end_time"] = datetime.now(timezone.utc)
        if chat_id is not None:
            updates["chat_id"] = chat_id
        if result is not None:
            updates["result"] = result
        if error is not None:
            updates["error"] = error

        if updates:
            await db.get_collection("task_runs").update_one(
                {"_id": run_id}, {"$set": updates}
            )

        updated_doc = await db.get_collection("task_runs").find_one({"_id": run_id})
        return task_run_doc_to_out(updated_doc)

    async def count_runs(self, task_id: str, status: Optional[str] = None) -> int:
        """Count runs for a task, optionally filtered by status.

        Args:
            task_id: The task identifier
            status: Optional status filter

        Returns:
            Number of matching runs
        """
        query = {"task_id": task_id}
        if status is not None:
            query["status"] = status
        return await db.get_collection("task_runs").count_documents(query)

    async def get_recent_run_statuses(self, task_id: str, limit: int = 7) -> List[str]:
        """Get recent run statuses for a task.

        Args:
            task_id: The task identifier
            limit: Number of recent runs to retrieve

        Returns:
            List of status strings in reverse chronological order
        """
        cursor = (
            db.get_collection("task_runs")
            .find({"task_id": task_id})
            .sort("start_time", -1)
            .limit(limit)
        )
        return [doc.get("status", "failed") async for doc in cursor]
