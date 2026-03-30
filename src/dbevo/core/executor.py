# dbevo/core/executor.py
# -*- coding: utf-8 -*-
"""
Database executor for applying migrations.

Uses asyncpg for async PostgreSQL operations.
Applies migrations in GLOBAL order by migration_number.
"""

import asyncpg
import time
from datetime import datetime
from pathlib import Path

from dbevo.config import Settings
from dbevo.core.parser import MigrationParser


class MigrationExecutor:
    """Execute migrations against PostgreSQL database."""

    def __init__(self, settings: Settings, debug: bool = False):
        self.settings = settings
        self.parser = MigrationParser()
        self._connection: asyncpg.Connection | None = None
        self.debug = debug

    def _debug(self, message: str) -> None:
        """Print debug message if debug mode is enabled."""
        if self.debug:
            print(f"[DEBUG] {message}")

    async def connect(self) -> None:
        """Establish database connection."""
        self._connection = await asyncpg.connect(self.settings.database_url)
        self._debug(f"Connected to {self.settings.database_url}")

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            self._debug("Connection closed")

    async def execute_sql(self, sql: str, timeout: float = 30.0) -> None:
        """Execute raw SQL, handling multiple statements."""
        if not self._connection:
            await self.connect()

        statements = self._split_statements(sql)
        self._debug(f"Executing {len(statements)} statement(s)")

        async with self._connection.transaction():
            for i, statement in enumerate(statements, 1):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    self._debug(f"  [{i}/{len(statements)}] {statement[:60]}...")
                    await self._connection.execute(statement, timeout=timeout)

    def _split_statements(self, sql: str) -> list[str]:
        """
        Split SQL into individual statements.

        Handles:
        - Semicolon-terminated statements
        - $$ ... $$ dollar quoting (functions)
        - Decorative comment lines (---)
        """
        statements = []
        current = []
        in_dollar = False
        in_multiline_comment = False

        for line in sql.split('\n'):
            stripped = line.strip()

            # Skip pure decorative lines (only dashes) and pure comment lines
            if stripped.startswith('---') or (stripped.startswith('--') and ';' not in stripped):
                if current and not in_dollar:
                    # If we have accumulated SQL, finalize it before skipping
                    stmt = '\n'.join(current).strip()
                    if stmt and stmt.endswith(';'):
                        statements.append(stmt)
                        current = []
                continue

            # Track dollar quoting for functions: $$ ... $$
            if '$$' in stripped and not stripped.startswith('--'):
                # Count $$ occurrences (simple heuristic)
                in_dollar = not in_dollar

            # Track C-style multiline comments: /* ... */
            if '/*' in stripped:
                in_multiline_comment = True
            if '*/' in stripped:
                in_multiline_comment = False
                continue
            if in_multiline_comment:
                continue

            current.append(line)

            # Split on semicolon only if not inside $$ or /* */
            if not in_dollar and not in_multiline_comment and stripped.endswith(';'):
                stmt = '\n'.join(current).strip()
                if stmt:
                    statements.append(stmt)
                current = []

        # Don't forget any remaining statement
        if current:
            stmt = '\n'.join(current).strip()
            if stmt and stmt.endswith(';'):
                statements.append(stmt)

        # Debug output
        if self.debug:
            print(f"\n[DEBUG _split_statements] Found {len(statements)} statements:")
            for i, stmt in enumerate(statements[:5], 1):
                first_line = stmt.split('\n')[0][:80]
                print(f"  [{i}] {first_line}...")
            if len(statements) > 5:
                print(f"  ... and {len(statements) - 5} more")
            print()

        return statements

    async def get_applied_migrations(self) -> list[dict]:
        """Fetch applied migrations from dbevo.migrations table."""
        if not self._connection:
            await self.connect()

        self._debug("Fetching applied migrations from DB")

        # Сортировка ПО ГЛОБАЛЬНОМУ НОМЕРУ (без sort_order!)
        query = """
            SELECT
                g.name AS group_name,
                m.migration_number,
                m.migration_hash,
                m.description,
                m.status,
                m.applied_at
            FROM dbevo.migrations m
            JOIN dbevo.migration_groups g ON g.id = m.group_id
            ORDER BY m.migration_number
        """

        rows = await self._connection.fetch(query)
        result = [dict(row) for row in rows]
        self._debug(f"Found {len(result)} applied migration(s)")
        return result

    async def apply_migration(self, migration_path: Path) -> dict:
        """
        Apply a migration and record it in dbevo.migrations.

        Returns:
            dict with execution stats
        """
        self._debug(f"Applying migration: {migration_path}")

        migration = self.parser.parse(migration_path)

        if not migration.ups:
            raise ValueError("Migration missing !Ups section")

        errors = self.parser.validate(migration)
        for error in errors:
            if not error.startswith("Warning"):
                raise ValueError(error)

        group_id = await self._get_or_create_group(
            migration.migration_group,
            migration.migration_group
        )

        start_time = time.time()

        async with self._connection.transaction():
            self._debug(f"Executing !Ups SQL ({len(migration.ups.sql)} chars)")
            await self._connection.execute(migration.ups.sql)

            self._debug("Recording in dbevo.migrations")
            await self._connection.execute(
                """
                INSERT INTO dbevo.migrations (
                    group_id, migration_number, migration_hash, description,
                    status, applied_at, applied_by, execution_time_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (group_id, migration_number)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    applied_at = EXCLUDED.applied_at,
                    execution_time_ms = EXCLUDED.execution_time_ms
                """,
                group_id,
                migration.migration_number,
                migration.ups_hash,
                migration.description,
                'applied',
                datetime.now(),
                self.settings.author or 'dbevo',
                int((time.time() - start_time) * 1000),
            )

            self._debug("Recording in dbevo.migration_history")
            await self._connection.execute(
                """
                INSERT INTO dbevo.migration_history (
                    group_id, migration_number, action, new_hash,
                    executed_at, executed_by, execution_time_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                group_id,
                migration.migration_number,
                'applied',
                migration.ups_hash,
                datetime.now(),
                self.settings.author or 'dbevo',
                int((time.time() - start_time) * 1000),
            )

        execution_time_ms = int((time.time() - start_time) * 1000)
        self._debug(f"Migration applied in {execution_time_ms}ms")

        return {
            'migration_number': migration.migration_number,
            'description': migration.description,
            'execution_time_ms': execution_time_ms,
        }

    async def revert_to(self, target_number: int) -> list[dict]:
        """
        Revert all migrations newer than target_number (GLOBAL order).

        Args:
            target_number: Stop reverting when reaching this number

        Returns:
            List of reverted migration stats
        """
        self._debug(f"Reverting migrations newer than {target_number:06d}")

        if not self._connection:
            await self.connect()

        # Get applied migrations newer than target, sorted DESC (LIFO)
        # GLOBAL order by migration_number only!
        query = """
            SELECT
                g.name AS group_name,
                g.id AS group_id,
                m.migration_number,
                m.migration_hash,
                m.description,
                m.status
            FROM dbevo.migrations m
            JOIN dbevo.migration_groups g ON g.id = m.group_id
            WHERE m.migration_number > $1
              AND m.status = 'applied'
            ORDER BY m.migration_number DESC
        """
        rows = await self._connection.fetch(query, target_number)

        if not rows:
            self._debug("No migrations to revert")
            return []

        self._debug(f"Found {len(rows)} migration(s) to revert")
        reverted = []

        for row in rows:
            group_name = row['group_name']
            migration_number = row['migration_number']
            stored_hash = row['migration_hash']

            self._debug(f"  Reverting {migration_number:06d}__* ({group_name})")

            migration_file = self._find_migration_file(group_name, migration_number)

            if not migration_file:
                raise FileNotFoundError(
                    f"Migration file not found: {migration_number:06d}__* in {group_name}"
                )

            migration = self.parser.parse(migration_file)

            if not migration.downs:
                raise ValueError(
                    f"Migration {migration_number:06d}__{migration.description} "
                    f"missing !Downs section (cannot revert)"
                )

            current_hash = migration.ups_hash
            hash_mismatch = stored_hash != current_hash

            if hash_mismatch:
                self._debug(f"    ⚠️  Hash mismatch! Stored: {stored_hash[:16]}... Current: {current_hash[:16]}...")

            start_time = time.time()

            async with self._connection.transaction():
                self._debug("    Executing !Downs SQL")
                await self._connection.execute(migration.downs.sql)

                self._debug("    Updating dbevo.migrations status")
                await self._connection.execute(
                    """
                    UPDATE dbevo.migrations
                    SET status = 'reverted',
                        applied_at = NOW(),
                        execution_time_ms = $1
                    WHERE group_id = $2 AND migration_number = $3
                    """,
                    int((time.time() - start_time) * 1000),
                    row['group_id'],
                    migration_number,
                )

                self._debug("    Recording in dbevo.migration_history")
                await self._connection.execute(
                    """
                    INSERT INTO dbevo.migration_history (
                        group_id, migration_number, action, previous_hash,
                        executed_at, executed_by, execution_time_ms, error_message
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    row['group_id'],
                    migration_number,
                    'reverted',
                    stored_hash,
                    datetime.now(),
                    self.settings.author or 'dbevo',
                    int((time.time() - start_time) * 1000),
                    'hash_mismatch' if hash_mismatch else None,
                )

            execution_time_ms = int((time.time() - start_time) * 1000)

            reverted.append({
                'migration_number': migration_number,
                'description': migration.description,
                'group': group_name,
                'execution_time_ms': execution_time_ms,
                'hash_mismatch': hash_mismatch,
            })

        self._debug(f"Reverted {len(reverted)} migration(s)")
        return reverted

    def _find_migration_file(self, group: str, number: int) -> Path | None:
        """Find migration file by group and number."""
        migrations_path = self.settings.migrations_path

        if not migrations_path.exists():
            self._debug(f"Migrations path not found: {migrations_path}")
            return None

        # Search in group folder (clean name: core/, utils/)
        group_path = migrations_path / group
        if group_path.exists():
            pattern = f"{number:06d}__*.sql"
            for f in group_path.glob(pattern):
                if not f.name.endswith('.j2'):
                    self._debug(f"  Found: {f}")
                    return f

        # Search recursively if not found
        for f in migrations_path.rglob(f"{number:06d}__*.sql"):
            if not f.name.endswith('.j2'):
                self._debug(f"  Found (recursive): {f}")
                return f

        self._debug(f"  Not found: {number:06d}__* in {group}")
        return None

    async def _get_or_create_group(self, name: str, description: str) -> int:
        """Get or create a migration group, return its ID."""
        if not self._connection:
            await self.connect()

        self._debug(f"Looking up group: {name}")
        row = await self._connection.fetchrow(
            "SELECT id FROM dbevo.migration_groups WHERE name = $1",
            name
        )

        if row:
            self._debug(f"  Group exists: id={row['id']}")
            return row['id']

        # Create new (no sort_order needed!)
        self._debug("  Creating new group")
        result = await self._connection.fetchrow(
            """
            INSERT INTO dbevo.migration_groups (name, description)
            VALUES ($1, $2)
            RETURNING id
            """,
            name,
            description,
        )

        self._debug(f"  Group created: id={result['id']}")
        return result['id']

    async def init_schema(self) -> None:
        """Initialize dbevo tracking schema."""
        possible_paths = [
            Path("src/dbevo/schema/000000__init_dbevo_schema.sql"),
            Path("dbevo/schema/000000__init_dbevo_schema.sql"),
            Path("schema/000000__init_dbevo_schema.sql"),
        ]

        init_file = None
        for path in possible_paths:
            if path.exists():
                init_file = path
                break

        if not init_file:
            raise FileNotFoundError(
                f"Init migration not found. Tried: {possible_paths}"
            )

        self._debug(f"Found init file: {init_file.resolve()}")
        self._debug(f"File size: {init_file.stat().st_size} bytes")

        migration = self.parser.parse(init_file)

        self._debug(f"Parsed: number={migration.migration_number}, group={migration.migration_group}")
        self._debug(f"Ups section: {len(migration.ups.sql) if migration.ups else 0} chars")

        if not migration.ups:
            raise ValueError("Init migration missing !Ups section")

        if not self._connection:
            await self.connect()

        # === ИСПОЛЬЗУЕМ _split_statements для выполнения ===
        statements = self._split_statements(migration.ups.sql)

        self._debug(f"Found {len(statements)} statements to execute")

        async with self._connection.transaction():
            for i, stmt in enumerate(statements, 1):
                stmt = stmt.strip()
                if stmt and not stmt.startswith('--'):
                    self._debug(f"Executing statement {i}: {stmt[:50]}...")
                    try:
                        await self._connection.execute(stmt)
                        self._debug(f"✓ Statement {i} OK")
                    except Exception as e:
                        self._debug(f"❌ Statement {i} FAILED: {e}")
                        self._debug(f"Full SQL: {stmt[:500]}")
                        raise

        self._debug(f"All {len(statements)} statements executed successfully!")
