# dbevo

**Database schema migrations for Python.**

Легковесный фреймворк для управления миграциями базы данных, вдохновленный [Play Framework Evolutions](https://www.playframework.com/documentation/latest/Evolutions).

[![Python Version](https://img.shields.io/pypi/pyversions/dbevo.svg)](https://pypi.org/project/dbevo/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📋 Содержание

- [Установка](#-установка)
- [Быстрый старт](#-быстрый-старт)
- [Конфигурация](#-конфигурация)
- [CLI Команды](#-cli-команды)
- [Структура миграций](#-структура-миграций)
- [Примеры](#-примеры)
- [Разработка](#-разработка)
- [Лицензия](#-лицензия)

---

## 🚀 Установка

```bash
git clone https://github.com/xDarkmanx/dbevo.git
cd dbevo
```

```bash
poetry install
```

---

## ⚡ Быстрый старт

### 1. Настройка окружения

Создайте файл `.env` в корне проекта:

```env
DBEVO_DATABASE_URL=postgresql://user:password@localhost:5432/mydb
DBEVO_MIGRATIONS_PATH=migrations
DBEVO_TEMPLATE_PATH=src/dbevo/templates/migration.sql.j2
```

### 2. Инициализация схемы отслеживания

```bash
dbevo init
```

Создаёт схему `dbevo` с таблицами для отслеживания применённых миграций.

### 3. Создание новой миграции

```bash
dbevo new add_user_table --schema core
```

Создаёт файл: `migrations/core/000001__add_user_table.sql`

### 4. Применение миграций

```bash
dbevo apply
```

### 5. Проверка статуса

```bash
dbevo status
```

---

## ⚙️ Конфигурация

Конфигурация загружается в следующем порядке (приорет сверху вниз):

1. **Переменные окружения** (префикс `DBEVO_`)
2. **Файл `.env`**
3. **Значения по умолчанию**

### Доступные переменные

| Переменная | Описание | По умолчанию |
| ---------- | -------- | ------------ |
| `DBEVO_DATABASE_URL` | PostgreSQL DSN | - |
| `DBEVO_MIGRATIONS_PATH` | Путь к миграциям | `migrations` |
| `DBEVO_TEMPLATE_PATH` | Шаблон миграции | `src/dbevo/templates/migration.sql.j2` |
| `DBEVO_SCHEMA_NAME` | Схема БД | `dbevo` |
| `DBEVO_GENERATE_OUTPUT` | Выходная директория для генерации моделей | `src/dbevo/models` |

---

## 🛠 CLI Команды

### `dbevo init`

Инициализирует схему отслеживания миграций в базе данных.

```bash
dbevo init [--debug]
```

### `dbevo status`

Показывает статус всех миграций.

```bash
dbevo status [--debug]
```

**Пример вывода:**

```text
dbevo status

Database: postgresql://localhost:5432/mydb
Migrations path: migrations

┌────────────────────────────────────┬─────────────┬──────────┬────────────────┐
│ Migration                          │ Group       │ Status   │ Applied At     │
├────────────────────────────────────┼─────────────┼──────────┼────────────────┤
│ 000001__init_core_schema           │ core        │ applied  │ 2026-03-30 10: │
│ 000002__init_utils_schema          │ utils       │ applied  │ 2026-03-30 10: │
│ 000003__create_update_trigger_func │ utils       │ pending  │ -              │
└────────────────────────────────────┴─────────────┴──────────┴────────────────┘

Total: 1 pending, 2 applied
```

### `dbevo apply`

Применяет все ожидающие миграции.

```bash
dbevo apply [--debug] [--auto-confirm] [--dry-run]
```

**Опции:**

| Опция | Описание |
| ----- | -------- |
| `--debug` | Включить debug вывод |
| `--auto-confirm` | Пропустить подтверждение |
| `--dry-run` | Показать SQL без выполнения |

### `dbevo revert`

Откатывает миграции до указанной версии.

```bash
dbevo revert --to 000002 [--debug] [--dry-run] [--auto-confirm] [--force]
```

**Опции:**

| Опция | Описание |
| ----- | -------- |
| `--to` | Номер миграции, к которой откатиться |
| `--dry-run` | Показать SQL без выполнения |
| `--auto-confirm` | Пропустить подтверждение |
| `--force` | Принудительно, даже если файл изменён |

### `dbevo new`

Создаёт новый файл миграции.

```bash
dbevo new <description> [--schema <schema_name>]
```

**Примеры:**

```bash
dbevo new add_user_table --schema core
dbevo new add_email_column --schema utils
```

### `dbevo generate`

Генерирует Pydantic-модели из схемы базы данных.

```bash
dbevo generate models [--output <path>]
```

---

## 📁 Структура миграций

Миграции организованы по **группам** (схемам) и имеют **глобальный номер**.

```text
migrations/
├── core/
│   ├── 000001__init_core_schema.sql
│   └── 000004__add_user_table.sql
└── utils/
    ├── 000002__init_utils_schema.sql
    ├── 000003__create_indexes.sql
    └── 000005__create_update_trigger_function.sql
```

### Формат имени файла

```text
<6-digit-number>__<description>.sql
```

- **Номер**: 6 цифр, глобальная нумерация
- **Описание**: snake_case, описывает изменения

### Формат миграции

```sql
------------------------------------------------------------------------------------------------------------------------
-- Author: Semenets Pavel <p.semenets@gmail.com>
-- Project: dbevo
-- Schema: utils
-- Create: Date: 2026-03-30
-- Migration: 000002__init_utils_schema
------------------------------------------------------------------------------------------------------------------------

-- !Ups
------------------------------------------------------------------------------------------------------------------------
-- Desc: init_utils_schema
------------------------------------------------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS "utils";
COMMENT ON SCHEMA "utils" IS 'core schema';


-- !Ups end

-- !Downs
------------------------------------------------------------------------------------------------------------------------
-- Desc: Rollback
------------------------------------------------------------------------------------------------------------------------
DROP SCHEMA IF EXISTS "utils";


-- !Downs end
```

**Секции:**

| Секция | Описание |
| ------ | -------- |
| `-- !Ups` | SQL для применения миграции |
| `-- !Downs` | SQL для отката миграции |

### Откат до конкретной версии

```bash
# Откат всех миграций после 000002
dbevo revert --to 2

# Откат с подтверждением
dbevo revert --to 000002 --auto-confirm
```

### Dry-run для проверки SQL

```bash
# Проверка перед применением
dbevo apply --dry-run

# Проверка перед откатом
dbevo revert --to 000002 --dry-run
```

---

## 🔧 Разработка

### Зависимости

```bash
poetry install --with lint,test,security
```

### Запуск тестов

```bash
poetry run pytest
```

### Linting

```bash
poetry run flake8 src/
poetry run bandit -r src/
```

---

## 📄 Лицензия

MIT License. См. [`LICENSE`](LICENSE) для деталей.

---

## 🤝 Вклад

Приветствуются Pull Requests! Пожалуйста, сначала обсудите изменения в issue.

---

## 📚 См. также

- [Play Framework Evolutions](https://www.playframework.com/documentation/latest/Evolutions)
- [Alembic](https://alembic.sqlalchemy.org/)
- [Flyway](https://flywaydb.org/)
- [Liquibase](https://www.liquibase.com/)
