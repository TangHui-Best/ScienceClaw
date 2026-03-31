"""MongoRepository — thin wrapper around Motor collections."""
from __future__ import annotations

from typing import Optional

from backend.storage.base import Repository


class MongoRepository(Repository):
    """Delegates to Motor AsyncIOMotorCollection."""

    def _get_col(self):
        from backend.mongodb.db import db
        return db.get_collection(self.collection_name)

    async def find_one(
        self, filter: dict, projection: dict | None = None
    ) -> Optional[dict]:
        return await self._get_col().find_one(filter, projection)

    async def find_many(
        self,
        filter: dict,
        projection: dict | None = None,
        sort: list[tuple[str, int]] | None = None,
        skip: int = 0,
        limit: int = 0,
    ) -> list[dict]:
        cursor = self._get_col().find(filter, projection)
        if sort:
            cursor = cursor.sort(sort)
        if skip:
            cursor = cursor.skip(skip)
        if limit:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit or None)

    async def insert_one(self, document: dict) -> str:
        result = await self._get_col().insert_one(document)
        return str(result.inserted_id)

    async def update_one(
        self, filter: dict, update: dict, upsert: bool = False
    ) -> int:
        result = await self._get_col().update_one(filter, update, upsert=upsert)
        return result.modified_count

    async def update_many(self, filter: dict, update: dict) -> int:
        result = await self._get_col().update_many(filter, update)
        return result.modified_count

    async def delete_one(self, filter: dict) -> int:
        result = await self._get_col().delete_one(filter)
        return result.deleted_count

    async def delete_many(self, filter: dict) -> int:
        result = await self._get_col().delete_many(filter)
        return result.deleted_count

    async def count(self, filter: dict) -> int:
        return await self._get_col().count_documents(filter)
