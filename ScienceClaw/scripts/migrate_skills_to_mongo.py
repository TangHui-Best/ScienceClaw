"""
One-time migration: import existing filesystem skills into MongoDB.

Usage:
    cd ScienceClaw/backend
    uv run python -m scripts.migrate_skills_to_mongo --skills-dir /app/Skills --default-user-id <user_id>

If --default-user-id is not provided, uses the first user found in MongoDB.
"""
import asyncio
import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from motor.motor_asyncio import AsyncIOMotorClient


async def main():
    parser = argparse.ArgumentParser(description="Migrate filesystem skills to MongoDB")
    parser.add_argument("--skills-dir", default="/app/Skills", help="Path to Skills directory")
    parser.add_argument("--default-user-id", default=None, help="User ID to assign skills to")
    parser.add_argument("--mongodb-uri", default=None, help="MongoDB URI (default: from env)")
    parser.add_argument("--db-name", default="scienceclaw", help="Database name")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done")
    args = parser.parse_args()

    # Connect to MongoDB
    uri = args.mongodb_uri or os.environ.get(
        "MONGODB_URI",
        f"mongodb://{os.environ.get('MONGODB_USER', 'scienceone')}:"
        f"{os.environ.get('MONGODB_PASSWORD', '')}@"
        f"{os.environ.get('MONGODB_HOST', 'localhost')}:"
        f"{os.environ.get('MONGODB_PORT', '27014')}/",
    )
    client = AsyncIOMotorClient(uri)
    db = client[args.db_name]

    # Resolve user_id
    user_id = args.default_user_id
    if not user_id:
        user = await db.users.find_one({}, {"_id": 1})
        if not user:
            print("ERROR: No users found in MongoDB. Use --default-user-id.")
            sys.exit(1)
        user_id = str(user["_id"])
        print(f"Using first user: {user_id}")

    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_dir():
        print(f"ERROR: Skills directory not found: {skills_dir}")
        sys.exit(1)

    # Migrate blocked_skills → set blocked=True on skill docs
    blocked_names = set()
    async for doc in db.blocked_skills.find({"user_id": user_id}, {"skill_name": 1}):
        if doc.get("skill_name"):
            blocked_names.add(doc["skill_name"])
    if blocked_names:
        print(f"Found {len(blocked_names)} blocked skills: {blocked_names}")

    # Scan and migrate skills
    migrated = 0
    skipped = 0
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not (child / "SKILL.md").is_file():
            continue

        skill_name = child.name

        # Check if already exists
        existing = await db.skills.find_one(
            {"user_id": user_id, "name": skill_name}, {"_id": 1}
        )
        if existing:
            print(f"  SKIP (exists): {skill_name}")
            skipped += 1
            continue

        # Read all files
        files = {}
        for fp in child.rglob("*"):
            if fp.is_file():
                rel = str(fp.relative_to(child))
                try:
                    files[rel] = fp.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    print(f"  WARN: Cannot read {fp}: {e}")

        # Parse description from SKILL.md
        description = ""
        skill_md = files.get("SKILL.md", "")
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", skill_md, re.DOTALL)
        if fm_match:
            try:
                fm = yaml.safe_load(fm_match.group(1))
                if isinstance(fm, dict):
                    description = fm.get("description", "")
            except Exception:
                pass

        now = datetime.now(timezone.utc)
        doc = {
            "user_id": user_id,
            "name": skill_name,
            "description": description,
            "source": "migrated",
            "blocked": skill_name in blocked_names,
            "files": files,
            "params": {},
            "created_at": now,
            "updated_at": now,
        }

        if args.dry_run:
            print(f"  DRY-RUN: {skill_name} ({len(files)} files, blocked={doc['blocked']})")
        else:
            await db.skills.insert_one(doc)
            print(f"  MIGRATED: {skill_name} ({len(files)} files, blocked={doc['blocked']})")
        migrated += 1

    print(f"\nDone. Migrated: {migrated}, Skipped: {skipped}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
