# dbevo/cli/main.py
# -*- coding: utf-8 -*-
"""
dbevo CLI - Database Evolutions for Python.

Inspired by Play Framework Evolutions.
"""

import asyncio
import click
import asyncpg

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ..config import get_settings
from ..core import MigrationGenerator
from ..core import MigrationExecutor
from ..core import MigrationParser

console = Console()


# ==============================================================================
# Декоратор для добавления --debug в любую команду
# ==============================================================================
def debug_option():
    """Decorator to add --debug option to commands."""
    def decorator(f):
        return click.option(
            "--debug",
            is_flag=True,
            default=None,
            help="Enable debug output"
        )(f)
    return decorator


# ==============================================================================
# Хелпер для получения debug флага (из контекста ИЛИ из параметра команды)
# ==============================================================================
def _get_debug(debug: bool | None = None) -> bool:
    """
    Get debug flag from command parameter OR from parent context.

    This allows --debug to work in both positions:
        dbevo --debug init    (context)
        dbevo init --debug    (parameter)
    """
    # Если флаг явно передан в команду (True/False) — используем его
    if debug is not None:
        return debug

    # Иначе идём вверх по цепочке контекстов (команда → группа)
    ctx = click.get_current_context(silent=True)
    while ctx:
        if ctx.obj and ctx.obj.get('debug') is True:
            return True
        ctx = ctx.parent  # ← Переходим к родительскому контексту!

    return False


# ==============================================================================
# CLI Group (с --debug на уровне группы!)
# ==============================================================================
@click.group()
@click.version_option(version="0.0.1", prog_name="dbevo")
@click.option("--debug", is_flag=True, help="Enable debug output")
@click.pass_context
def app(ctx, debug: bool):
    """
    dbevo - Database schema migrations for Python.

    Inspired by Play Framework Evolutions.

    Configuration is loaded from:
        1. OS environment variables (DBEVO_*)
        2. .env file
        3. Default values

    Required: DBEVO_DATABASE_URL
    """
    # Сохраняем в контекст для доступа из команд
    ctx.ensure_object(dict)
    ctx.obj['debug'] = debug


# ==============================================================================
# Command: status
# ==============================================================================
@app.command()
@debug_option()
@click.pass_context
def status(ctx, debug: bool):
    """Show current migration status."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo status[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_url}[/cyan]")
    console.print(f"Migrations path: [cyan]{settings.migrations_path}[/cyan]\n")

    async def _run():
        parser = MigrationParser()
        executor = MigrationExecutor(settings, debug=debug_flag)

        try:
            await executor.connect()

            # 1. Get applied migrations from DB (sorted by global number)
            applied = await executor.get_applied_migrations()
            applied_map = {
                m['migration_number']: m
                for m in applied
            }

            # 2. Scan migration files
            migrations = _scan_migrations(settings.migrations_path, parser)

            # 3. Build status table (sorted by global number)
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Migration", style="cyan", width=40)
            table.add_column("Group", style="blue", width=15)
            table.add_column("Status", style="green", width=10)
            table.add_column("Applied At", style="yellow", width=20)

            pending_count = 0
            applied_count = 0
            reverted_count = 0

            # Сортируем ПО ГЛОБАЛЬНОМУ НОМЕРУ
            for mig in sorted(migrations, key=lambda x: x['number']):
                key = mig['number']

                if key in applied_map:
                    db_mig = applied_map[key]

                    # ✅ Проверяем реальный статус из БД
                    db_status = db_mig['status']

                    if db_status == 'reverted':
                        status = "[yellow]reverted[/yellow]"
                        reverted_count += 1
                    elif db_mig['migration_hash'] != mig['hash']:
                        status = "[red]modified[/red] ⚠️"
                    else:
                        status = "[green]applied[/green]"
                        applied_count += 1

                    applied_at = db_mig['applied_at'].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    status = "[yellow]pending[/yellow]"
                    applied_at = "-"
                    pending_count += 1

                table.add_row(
                    f"{mig['number']:06d}__{mig['description']}",
                    mig['group'],
                    status,
                    applied_at,
                )

            console.print(table)

            # ✅ Обновлённая итоговая строка с reverted
            total_parts = []
            if pending_count:
                total_parts.append(f"{pending_count} pending")
            if applied_count:
                total_parts.append(f"{applied_count} applied")
            if reverted_count:
                total_parts.append(f"{reverted_count} reverted")

            total_str = ", ".join(total_parts) if total_parts else "0 migrations"
            console.print(f"\n[bold]Total:[/bold] {total_str}")

        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: apply
# ==============================================================================
@app.command()
@debug_option()
@click.option("--auto-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
@click.pass_context
def apply(ctx, debug: bool, auto_confirm: bool, dry_run: bool):
    """Apply pending migrations."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo apply[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_url}[/cyan]")
    console.print(f"Migrations path: [cyan]{settings.migrations_path}[/cyan]\n")

    if dry_run:
        console.print("[yellow]Dry-run mode: no changes will be applied[/yellow]\n")

    async def _run():
        parser = MigrationParser()
        executor = MigrationExecutor(settings, debug=debug_flag)

        try:
            await executor.connect()

            # 1. Get applied migrations (by global number)
            applied = await executor.get_applied_migrations()

            # ✅ FIX: Только 'applied' считаем применёнными
            # 'reverted' = была применена, потом откатана → можно применить снова!
            applied_set = {
                m['migration_number']
                for m in applied
                if m['status'] == 'applied'  # ← КЛЮЧЕВОЕ: только applied!
            }

            # 2. Scan migration files
            migrations = _scan_migrations(settings.migrations_path, parser)

            # 3. Filter pending (by global number)
            # Миграции со статусом 'reverted' попадут сюда → можно apply!
            pending = [
                m for m in migrations
                if m['number'] not in applied_set
            ]

            if not pending:
                console.print("[green]✓[/green] No pending migrations!")
                return

            # 4. Show what will be applied (sorted by global number)
            console.print(f"[bold]Will apply {len(pending)} migration(s):[/bold]")
            for m in sorted(pending, key=lambda x: x['number']):
                console.print(f"  • {m['number']:06d}__{m['description']} ({m['group']})")
            console.print()

            # 5. Confirm
            if not auto_confirm and not dry_run:
                if not click.confirm("Proceed?", abort=True):
                    console.print("[yellow]Aborted[/yellow]")
                    return

            # 6. Apply each (sorted by global number)
            for m in sorted(pending, key=lambda x: x['number']):
                console.print(f"\n[bold]Applying:[/bold] {m['number']:06d}__{m['description']}")

                if dry_run:
                    parsed = parser.parse(m['file'])
                    if parsed.ups:
                        console.print(f"[dim]```sql\n{parsed.ups.sql}\n```[/dim]")
                    continue

                result = await executor.apply_migration(m['file'])

                console.print(
                    f"[green]✓[/green] Applied in {result['execution_time_ms']}ms"
                )

            console.print("\n[green]✓[/green] All migrations applied successfully!")

        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: revert
# ==============================================================================
@app.command()
@debug_option()
@click.option("--to", "target", type=int, required=True,
              help="Revert to specific migration number (all newer will be reverted)")
@click.option("--dry-run", is_flag=True, help="Show SQL without executing")
@click.option("--auto-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--force", is_flag=True, help="Proceed even if migration file modified")
@click.pass_context
def revert(ctx, debug: bool, target: int, dry_run: bool, auto_confirm: bool, force: bool):
    """Revert migrations to a specific version.

    All migrations newer than TARGET will be reverted in reverse order.
    Global order by migration_number.
    """
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo revert[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_url}[/cyan]")
    console.print(f"Target: [cyan]{target:06d}[/cyan]")
    console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode: no changes will be applied[/yellow]\n")

    async def _run():
        executor = MigrationExecutor(settings, debug=debug_flag)
        parser = MigrationParser()

        try:
            await executor.connect()

            # 1. Get migrations to revert (GLOBAL order)
            to_revert = await executor.revert_to(target)

            if not to_revert:
                console.print("[green]✓[/green] No migrations to revert!")
                console.print(f"[dim]Already at or before {target:06d}[/dim]")
                return

            # 2. Check for hash mismatches
            mismatches = [m for m in to_revert if m['hash_mismatch']]

            if mismatches:
                console.print("[bold red]⚠️  WARNING: Modified migrations detected![/bold red]\n")
                for m in mismatches:
                    console.print(
                        f"  • {m['migration_number']:06d}__{m['description']} "
                        f"([yellow]{m['group']}[/yellow])"
                    )
                console.print()

                if not force:
                    console.print(
                        "[yellow]Use --force to proceed anyway (not recommended)[/yellow]"
                    )
                    raise click.Abort()

            # 3. Show what will be reverted
            console.print(f"[bold]Will revert {len(to_revert)} migration(s):[/bold]")
            for m in to_revert:
                console.print(
                    f"  • {m['migration_number']:06d}__{m['description']} "
                    f"([yellow]{m['group']}[/yellow])"
                )
            console.print()

            # 4. Confirm
            if not auto_confirm and not dry_run:
                if not click.confirm("[red]Proceed with revert?[/red]", abort=True):
                    console.print("[yellow]Aborted[/yellow]")
                    return

            # 5. Execute or dry-run
            if dry_run:
                for m in to_revert:
                    migration_file = executor._find_migration_file(
                        m['group'], m['migration_number']
                    )
                    if migration_file:
                        parsed = parser.parse(migration_file)
                        console.print(
                            f"\n[bold]Would revert:[/bold] "
                            f"{m['migration_number']:06d}__{m['description']}"
                        )
                        if parsed.downs:
                            console.print(f"[dim]```sql\n{parsed.downs.sql}\n```[/dim]")

                console.print(
                    f"\n[yellow]✓[/yellow] Dry-run complete. "
                    f"{len(to_revert)} migration(s) would be reverted."
                )
            else:
                for m in to_revert:
                    status = "[yellow]⚠️  hash mismatch[/yellow]" if m['hash_mismatch'] else "[green]✓[/green]"
                    console.print(
                        f"{status} Reverted {m['migration_number']:06d}__{m['description']} "
                        f"in {m['execution_time_ms']}ms"
                    )

                console.print(
                    "\n[green]✓[/green] All migrations reverted successfully!"
                )

        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Command: new
# ==============================================================================
@app.command()
@click.argument("description")
@click.option("--schema", "schema_name", default="default", help="Schema folder name (clean: core, utils)")
def new(description: str, schema_name: str):
    """Create a new migration file.

    DESCRIPTION: Migration description (e.g., 'add_user_table')
    SCHEMA: Folder name without prefix (e.g., 'core', not '001__core')
    """
    settings = get_settings()

    console.print("[bold blue]dbevo new[/bold blue]\n")
    console.print(f"Description: [cyan]{description}[/cyan]")
    console.print(f"Schema: [cyan]{schema_name}[/cyan]")
    console.print(f"Template: [cyan]{settings.template_path}[/cyan]\n")

    try:
        generator = MigrationGenerator(settings)
        file_path = generator.generate(
            description=description,
            schema=schema_name,
        )

        console.print(f"[green]✓[/green] Created: [cyan]{file_path}[/cyan]")

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise click.Abort()


# ==============================================================================
# Command: generate
# ==============================================================================
@app.command()
@click.option("--output", default=None, help="Override output directory")
def generate(output: str | None):
    """Generate Pydantic models from database schema."""
    settings = get_settings()

    output_path = output or settings.generate_output

    console.print("[bold blue]dbevo generate models[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_url}[/cyan]")
    console.print(f"Output: [cyan]{output_path}[/cyan]\n")

    console.print(f"[green]✓[/green] Would generate models to: {output_path}")


# ==============================================================================
# Command: init
# ==============================================================================
@app.command()
@debug_option()
@click.pass_context
def init(ctx, debug: bool):
    """Initialize dbevo tracking schema and tables."""
    settings = get_settings()
    debug_flag = _get_debug(debug)

    console.print("[bold blue]dbevo init[/bold blue]\n")
    console.print(f"Database: [cyan]{settings.database_url}[/cyan]\n")

    async def _run():
        executor = MigrationExecutor(settings, debug=debug_flag)
        try:
            await executor.connect()
            await executor.init_schema()
            console.print("[green]✓[/green] dbevo schema initialized successfully!")
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise click.Abort()
        except asyncpg.PostgresError as e:
            console.print(f"[red]Database error:[/red] {e}")
            raise click.Abort()
        finally:
            await executor.close()

    asyncio.run(_run())


# ==============================================================================
# Helper Functions
# ==============================================================================
def _scan_migrations(migrations_path: Path, parser: MigrationParser) -> list[dict]:
    """Scan migrations directory and parse all .sql files."""
    migrations = []

    if not migrations_path.exists():
        return migrations

    for sql_file in migrations_path.rglob("*.sql"):
        if sql_file.name.endswith('.j2'):
            continue

        try:
            parsed = parser.parse(sql_file)
            migrations.append({
                'file': sql_file,
                'group': parsed.migration_group,
                'number': parsed.migration_number,
                'description': parsed.description,
                'hash': parsed.ups_hash,
            })
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to parse {sql_file}: {e}")

    return migrations


# ==============================================================================
# Entry Point
# ==============================================================================
if __name__ == "__main__":
    app()
