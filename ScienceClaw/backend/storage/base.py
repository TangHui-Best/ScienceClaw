"""Repository abstract base class — the storage contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class Repository(ABC):
    """One instance per collection. All methods are async."""

    def __init__(self, collection_name: str):
        self.collection_name = collection_name

    @abstractmethod
    async def find_one(
        self, filter: dict, projection: dict | None = None
    ) -> Optional[dict]:
        ...

    @abstractmethod
    async def find_many(
        self,
        filter: dict,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        ...

    @abstractmethod
    async def insert_one(self, document: dict) -> str:
        """Insert document, return _id (auto-generated if missing)."""
        ...

    @abstractmethod
    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> int:
        """Return modified_count (0 or 1). Supports $set, $push, $setOnInsert."""
        ...

    @abstractmethod
    async def update_many(self, filter: dict, update: dict) -> int:
        """Return modified_count."""
        ...

    @abstractmethod
    async def delete_one(self, filter: dict) -> int:
        """Return deleted_count (0 or 1)."""
        ...

    @abstractmethod
    async def delete_many(self, filter: dict) -> int:
        """Return deleted_count."""
        ...

    @abstractmethod
    async def count(self, filter: dict) -> int:
        ...
