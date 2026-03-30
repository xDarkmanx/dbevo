# dbevo/core/generator.py
# -*- coding: utf-8 -*-
"""
Migration file generator with Jinja2 templates.

Generates new migration files from templates with context variables.
Uses GLOBAL numbering across all groups.
"""

import re

from pathlib import Path
from datetime import datetime

from jinja2 import Environment
from jinja2 import FileSystemLoader
from jinja2 import TemplateNotFound

from dbevo.config import Settings


class MigrationGenerator:
    """Generate new migration files from Jinja2 templates."""

    def __init__(self, settings: Settings):
        self.settings = settings

        # Setup Jinja2 environment
        template_dir = settings.template_path.parent

        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        description: str,
        schema: str = "default",
        migration_number: int | None = None,
        output_path: Path | None = None,
    ) -> Path:
        """
        Generate a new migration file with GLOBAL numbering.

        Args:
            description: Migration description (e.g., 'add_user_table')
            schema: Schema folder name (clean name: 'core', 'utils', not '001__core')
            migration_number: Optional migration number (auto-detect if None)
            output_path: Optional output directory (uses settings.migrations_path if None)

        Returns:
            Path to the created file
        """

        # Load template
        try:
            template = self.env.get_template(self.settings.template_path.name)
        except TemplateNotFound:
            raise FileNotFoundError(
                f"Template not found: {self.settings.template_path}"
            )

        # Auto-detect migration number if not provided (GLOBAL max+1)
        if migration_number is None:
            migration_number = self._get_next_global_number(output_path)

        # Build context for template
        context = {
            "author": self.settings.author,
            "project": self.settings.project,
            "schema": schema,  # Чистое имя группы для хедера
            "migration_name": f"{migration_number:06d}__{description}",
            "description": description,
            "created_at": datetime.now().strftime("%Y-%m-%d"),
        }

        # Render template
        content = template.render(**context).rstrip() + "\n"

        # Build output path: dbevo/{schema}/{number}__{desc}.sql
        base_path = output_path or self.settings.migrations_path
        schema_path = base_path / schema  # Чистое имя: core/, utils/
        schema_path.mkdir(parents=True, exist_ok=True)

        # Build filename: 000001__description.sql
        filename = f"{migration_number:06d}__{description}.sql"
        file_path = schema_path / filename

        # Write file
        file_path.write_text(content, encoding="utf-8")

        return file_path

    def _get_next_global_number(self, output_path: Path | None) -> int:
        """
        Get next migration number by scanning ALL groups.

        This ensures GLOBAL numbering across all folders.

        Returns:
            Global max + 1 (across all folders)
        """
        base_path = output_path or self.settings.migrations_path

        if not base_path.exists():
            return 1

        # Pattern: 1-6 digits __ *.sql
        pattern = re.compile(r"^(\d{1,6})__.+\.sql$")

        numbers = []
        # Recursively scan ALL subfolders for global numbering
        for sql_file in base_path.rglob("*.sql"):
            # Skip templates
            if sql_file.name.endswith('.j2'):
                continue

            match = pattern.match(sql_file.name)
            if match:
                numbers.append(int(match.group(1)))

        return max(numbers, default=0) + 1
