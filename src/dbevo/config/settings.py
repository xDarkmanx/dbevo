# config/settings.py
# -*- coding: utf-8 -*-
"""
dbevo configuration settings.

Loaded from environment variables or .env file.

Priority (highest to lowest):
    1. OS environment variables (export DBEVO_*)
    2. .env file
    3. Default values in code
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """dbevo configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DBEVO_",
        extra="ignore",
        case_sensitive=False,
    )

    # ========================================================================
    # Database (required)
    # ========================================================================
    database_url: str = Field(
        ...,
        description="PostgreSQL connection URL",
        examples=["postgresql://user:pass@localhost:5432/dbname"],
    )

    # ========================================================================
    # Migrations
    # ========================================================================
    migrations_path: Path = Field(
        default=Path("dbevo"),
        description="Path to migrations directory",
    )

    # ========================================================================
    # Template for new migrations
    # ========================================================================
    template_path: Path = Field(
        default=Path("src/dbevo/templates/migration.sql.j2"),
        description="Path to Jinja2 template for new migrations",
    )

    # ========================================================================
    # Metadata for templates
    # ========================================================================
    author: str = Field(
        default="",
        description="Author name for migration headers",
    )

    project: str = Field(
        default="dbevo",
        description="Project name for migration headers",
    )

    # ========================================================================
    # Behavior
    # ========================================================================
    auto_apply: bool = Field(
        default=False,
        description="Auto-apply migrations on startup",
    )

    dry_run: bool = Field(
        default=False,
        description="Show SQL without executing",
    )

    # ========================================================================
    # Schema generation (future)
    # ========================================================================
    generate_output: Path = Field(
        default=Path("src/dbevo/models/generated"),
        description="Output directory for generated Pydantic models",
    )

    # ========================================================================
    # ignore_tables: храним как str, парсим при использовании
    # ========================================================================
    ignore_tables_raw: str = Field(
        default="evolutions,pg_%",
        description="Tables to ignore during model generation (comma-separated)",
        alias="ignore_tables",
    )

    @property
    def ignore_tables(self) -> list[str]:
        """Parse comma-separated string to list."""
        return [item.strip() for item in self.ignore_tables_raw.split(',') if item.strip()]


# ============================================================================
# Global settings instance
# ============================================================================
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings instance (useful for testing)."""
    global _settings
    _settings = None
