#!/usr/bin/env python3
"""
Run this once to create the initial admin user.

Usage:
    python scripts/create_admin.py --username admin --password yourpassword
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal, init_db
from app.core.security import hash_password
from app.models.user import User


async def create_admin(username: str, password: str):
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        if result.scalar_one_or_none():
            print(f"❌ User '{username}' already exists.")
            return

        user = User(
            username=username,
            hashed_password=hash_password(password),
            is_admin=True,
        )
        db.add(user)
        await db.commit()
        print(f"✅ Admin user '{username}' created successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create admin user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    asyncio.run(create_admin(args.username, args.password))
