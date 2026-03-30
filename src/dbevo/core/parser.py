# dbevo/core/parser.py
# -*- coding: utf-8 -*-
"""
SQL migration parser with !Ups/!Downs sections.

Supports explicit end markers for robust parsing:
    -- !Ups
    ... SQL ...
    -- !Ups end

    -- !Downs
    ... SQL ...
    -- !Downs end
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class MigrationSection:
    """Represents a single migration section (Ups or Downs)."""

    sql: str
    start_line: int
    end_line: int
    hash: Optional[str] = None


@dataclass
class ParsedMigration:
    """Represents a fully parsed migration file."""

    file_path: Path
    migration_number: int
    migration_group: str  # Clean name: "core", "utils"
    description: str
    ups: Optional[MigrationSection]
    downs: Optional[MigrationSection]
    header: str

    @property
    def ups_hash(self) -> Optional[str]:
        """Calculate SHA-256 hash of !Ups section."""
        if self.ups and self.ups.hash is None:
            self.ups.hash = hashlib.sha256(
                self.ups.sql.encode('utf-8')
            ).hexdigest()
        return self.ups.hash


class MigrationParser:
    """Parse SQL migration files with !Ups/!Downs sections."""

    # Маркеры секций
    UPS_START = "-- !Ups"
    UPS_END = "-- !Ups end"
    DOWNS_START = "-- !Downs"
    DOWNS_END = "-- !Downs end"

    # Pattern для имени файла: 000001__create_users_table.sql (6 digits)
    FILENAME_PATTERN = re.compile(r"^(\d{1,6})__(.+)\.sql$")

    def parse(self, file_path: Path) -> ParsedMigration:
        """Parse a migration file."""

        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Извлекаем метаданные из имени файла
        match = self.FILENAME_PATTERN.match(file_path.name)
        if not match:
            raise ValueError(f"Invalid migration filename: {file_path.name}")

        migration_number = int(match.group(1))
        description = match.group(2)

        # Определяем группу из родительской папки (ЧИСТОЕ имя)
        # Пример: dbevo/core/000001__init.sql → group = "core"
        migration_group = file_path.parent.name

        # Исключаем системные папки
        if migration_group in ("evolutions", "migrations", "dbevo", "schema"):
            migration_group = "default"

        # Парсим секции
        ups = self._parse_section(lines, self.UPS_START, self.UPS_END)
        downs = self._parse_section(lines, self.DOWNS_START, self.DOWNS_END)

        # Вычисляем хеш для !Ups
        if ups:
            ups.hash = hashlib.sha256(ups.sql.encode("utf-8")).hexdigest()

        # Извлекаем хедер (всё до !Ups)
        header = ""
        if ups:
            header = "\n".join(lines[: ups.start_line])

        return ParsedMigration(
            file_path=file_path,
            migration_number=migration_number,
            migration_group=migration_group,  # Clean name
            description=description,
            ups=ups,
            downs=downs,
            header=header,
        )

    def _parse_section(
        self,
        lines: list[str],
        start_marker: str,
        end_marker: str,
    ) -> Optional[MigrationSection]:
        """Parse a single section (Ups or Downs), skipping decorative headers."""

        start_idx: Optional[int] = None
        end_idx: Optional[int] = None

        for i, line in enumerate(lines):
            stripped = line.strip()

            if stripped == start_marker and start_idx is None:
                start_idx = i + 1  # SQL starts AFTER the marker
            elif stripped == end_marker and start_idx is not None:
                end_idx = i  # SQL ends BEFORE the marker
                break

        if start_idx is None:
            return None

        if end_idx is None:
            end_idx = len(lines)

        # Extract raw SQL
        raw_sql = "\n".join(lines[start_idx:end_idx])

        # === FIX: Skip decorative header (--- lines and -- comments) ===
        sql_lines = raw_sql.split('\n')
        cleaned_lines = []
        found_real_sql = False

        for line in sql_lines:
            stripped = line.strip()

            # Skip until we find a line that is NOT empty and NOT a comment
            if not found_real_sql:
                if not stripped or stripped.startswith('--'):
                    continue
                found_real_sql = True  # Found first real SQL statement

            cleaned_lines.append(line)

        sql = '\n'.join(cleaned_lines).strip()
        # === END FIX ===

        return MigrationSection(
            sql=sql,
            start_line=start_idx,
            end_line=end_idx,
        )

    def validate(self, migration: ParsedMigration) -> list[str]:
        """Validate migration structure."""

        errors: list[str] = []

        # !Ups обязательна
        if migration.ups is None:
            errors.append("Missing !Ups section")

        # !Downs желательна (предупреждение)
        if migration.downs is None:
            errors.append("Warning: Missing !Downs section (recommended for rollback)")

        return errors
