# Alaris_EconomyBot_v002
# Full replacement for main.py
# Purpose: standalone Alaris Economy Bot scaffold using shared Postgres.
# v002: Adds safe character compatibility sync/backfill from alaris_characters.
# Safety rules:
# - Additive schema only.
# - No wipe/reset/destructive commands.
# - Character economy is keyed by character_id, not character name.
# - Uses canonical Alaris currency: Embers, Crowns, Sovereigns, Thrones, Astrals.
# - Uses canonical Alaris kingdoms/lands.

from __future__ import annotations

import asyncio
import os
import re
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

import discord
from discord import app_commands
import psycopg
from psycopg.rows import dict_row

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


APP_VERSION = "Alaris_EconomyBot_v002"
CHICAGO_TZ = ZoneInfo("America/Chicago") if ZoneInfo else timezone.utc

CANON_KINGDOMS: list[str] = [
    "Ephel Duath",
    "Galadon",
    "Mullaghmore",
    "Frerinn",
    "Vornladuhr",
    "Vidalia",
    "Idolea",
    "Chiron",
]

DEFAULT_TAX_BP = 1000  # 10.00%
DEFAULT_DAILY_INCOME_EMBERS = 100  # 1 Crown in base units; easy to tune later.

# Currency conversion, base unit = Ember.
# 100 Embers = 1 Crown; 100 Crowns = 1 Sovereign; 100 Sovereigns = 1 Throne; 100 Thrones = 1 Astral.
CURRENCY_UNITS: list[tuple[int, str, str]] = [
    (100_000_000, "Astral", "Astrals"),
    (1_000_000, "Throne", "Thrones"),
    (10_000, "Sovereign", "Sovereigns"),
    (100, "Crown", "Crowns"),
    (1, "Ember", "Embers"),
]


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw if raw else default


def _get_int_env(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = _get_env(name)
    if raw is None:
        return default
    cleaned = re.sub(r"[^0-9]", "", raw)
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except Exception:
        return default


def _get_int_list_env(name: str) -> set[int]:
    raw = _get_env(name, "") or ""
    out: set[int] = set()
    for part in raw.replace(";", ",").replace("\n", ",").split(","):
        cleaned = re.sub(r"[^0-9]", "", part.strip())
        if cleaned:
            try:
                out.add(int(cleaned))
            except Exception:
                pass
    return out


DISCORD_TOKEN = _get_env("DISCORD_TOKEN")
DATABASE_URL = _get_env("DATABASE_URL")
GUILD_ID = _get_int_env("GUILD_ID")
STAFF_ROLE_IDS = _get_int_list_env("STAFF_ROLE_IDS")
ECON_LOG_CHANNEL_ID = _get_int_env("ECON_LOG_CHANNEL_ID")
BANK_CHANNEL_ID = _get_int_env("BANK_CHANNEL_ID")

if not DISCORD_TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN")
if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL")
if not GUILD_ID:
    raise RuntimeError("Missing or invalid GUILD_ID")


intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@dataclass(frozen=True)
class CharacterRef:
    guild_id: int
    character_id: int
    user_id: int
    name: str
    kingdom: Optional[str]
    source_table: str


# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("`", "'").replace("@", "@\u200b")
    return text.replace("\r", " ").replace("\n", " ").strip()


def plural(qty: int, singular: str, plural_form: str) -> str:
    return singular if abs(int(qty)) == 1 else plural_form


def format_currency(amount_embers: int, *, show_base_total: bool = True) -> str:
    try:
        amount = int(amount_embers)
    except Exception:
        amount = 0

    sign = "-" if amount < 0 else ""
    remaining = abs(amount)
    parts: list[str] = []

    for value, singular, plural_form in CURRENCY_UNITS:
        qty, remaining = divmod(remaining, value)
        if qty:
            parts.append(f"{qty:,} {plural(qty, singular, plural_form)}")

    if not parts:
        parts.append("0 Embers")

    shown = sign + ", ".join(parts)
    if show_base_total:
        shown += f" ({amount:,} Embers)"
    return shown


def bp_to_percent(bp: int) -> str:
    try:
        bp = int(bp)
    except Exception:
        bp = 0
    pct = bp / 100
    if bp % 100 == 0:
        return f"{pct:.0f}%"
    return f"{pct:.2f}%"


def calc_tax(amount_embers: int, tax_bp: int) -> int:
    amount = max(0, int(amount_embers or 0))
    bp = max(0, int(tax_bp or 0))
    return (amount * bp) // 10000


def is_valid_kingdom(kingdom: str) -> bool:
    return kingdom in CANON_KINGDOMS


# -----------------------------------------------------------------------------
# Database helpers
# -----------------------------------------------------------------------------


def db_connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


async def run_db(fn, *args, **kwargs):
    """Run blocking psycopg work off the Discord event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def ensure_schema_sync() -> None:
    """Additive-only schema setup for EconomyBot v002."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS econ;")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.kingdoms (
                    guild_id BIGINT NOT NULL,
                    kingdom TEXT NOT NULL,
                    tax_rate_bp INTEGER NOT NULL DEFAULT 1000,
                    treasury_embers BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (guild_id, kingdom)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.balances (
                    guild_id BIGINT NOT NULL,
                    character_id BIGINT NOT NULL,
                    balance_embers BIGINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (guild_id, character_id)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.asset_definitions (
                    id BIGSERIAL PRIMARY KEY,
                    asset_type TEXT NOT NULL,
                    tier_code TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    cost_embers BIGINT NOT NULL DEFAULT 0,
                    income_embers BIGINT NOT NULL DEFAULT 0,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (asset_type, tier_code)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.assets (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    character_id BIGINT NOT NULL,
                    asset_type TEXT NOT NULL,
                    tier_code TEXT,
                    asset_name TEXT NOT NULL,
                    kingdom TEXT,
                    noble_title_family TEXT,
                    noble_title_option TEXT,
                    noble_realm_name TEXT,
                    income_embers BIGINT NOT NULL DEFAULT 0,
                    created_by_user_id BIGINT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (guild_id, character_id, asset_type, asset_name)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.income_claims (
                    guild_id BIGINT NOT NULL,
                    character_id BIGINT NOT NULL,
                    last_claim_date DATE NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (guild_id, character_id)
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.transactions (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    character_id BIGINT,
                    actor_user_id BIGINT,
                    action TEXT NOT NULL,
                    amount_embers BIGINT NOT NULL DEFAULT 0,
                    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS econ.bank_messages (
                    guild_id BIGINT NOT NULL,
                    idx INTEGER NOT NULL,
                    channel_id BIGINT NOT NULL,
                    message_id BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (guild_id, idx)
                );
                """
            )

            # Queue used by AlarisBot later to refresh character sheets after economy changes.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.alaris_character_refresh_queue (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    character_id BIGINT NOT NULL,
                    reason TEXT NOT NULL DEFAULT 'economy_update',
                    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    processed_at TIMESTAMPTZ
                );
                """
            )

            # Optional compatibility: if public.characters exists, ensure kingdom exists.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'characters'
                    ) THEN
                        ALTER TABLE public.characters ADD COLUMN IF NOT EXISTS kingdom TEXT;
                    END IF;
                END $$;
                """
            )

            # Optional compatibility: if public.alaris_characters exists, ensure kingdom exists.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'alaris_characters'
                    ) THEN
                        ALTER TABLE public.alaris_characters ADD COLUMN IF NOT EXISTS kingdom TEXT;
                    END IF;
                END $$;
                """
            )

            # Compatibility bridge used by EconomyBot/TournamentBot.
            # Clean Alaris canon remains public.alaris_characters; this table is a read/write mirror.
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.characters (
                    character_id BIGINT PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT,
                    species TEXT,
                    class_name TEXT,
                    kingdom TEXT,
                    level INTEGER NOT NULL DEFAULT 1,
                    xp_total BIGINT NOT NULL DEFAULT 0,
                    archived BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                ALTER TABLE public.characters
                    ADD COLUMN IF NOT EXISTS character_id BIGINT,
                    ADD COLUMN IF NOT EXISTS guild_id BIGINT,
                    ADD COLUMN IF NOT EXISTS user_id BIGINT,
                    ADD COLUMN IF NOT EXISTS name TEXT,
                    ADD COLUMN IF NOT EXISTS normalized_name TEXT,
                    ADD COLUMN IF NOT EXISTS species TEXT,
                    ADD COLUMN IF NOT EXISTS class_name TEXT,
                    ADD COLUMN IF NOT EXISTS kingdom TEXT,
                    ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS xp_total BIGINT NOT NULL DEFAULT 0,
                    ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
                """
            )
            cur.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS characters_guild_character_id_uidx
                ON public.characters (guild_id, character_id);
                """
            )

            for kingdom in CANON_KINGDOMS:
                cur.execute(
                    """
                    INSERT INTO econ.kingdoms (guild_id, kingdom, tax_rate_bp, treasury_embers)
                    VALUES (%s, %s, %s, 0)
                    ON CONFLICT (guild_id, kingdom) DO NOTHING;
                    """,
                    (GUILD_ID, kingdom, DEFAULT_TAX_BP),
                )

        conn.commit()


def sync_public_characters_from_alaris_sync(guild_id: int) -> dict[str, int]:
    """Backfill the public.characters compatibility mirror from public.alaris_characters.

    This is additive/non-destructive: it inserts missing compatibility rows and updates
    display metadata for existing rows, but it never deletes character or economy data.
    """
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'alaris_characters'
                ) AS has_alaris_characters;
                """
            )
            flags = cur.fetchone() or {}
            if not flags.get("has_alaris_characters"):
                return {"has_alaris_characters": 0, "alaris_found": 0, "synced": 0, "missing_kingdom": 0}

            cur.execute(
                """
                SELECT COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE COALESCE(kingdom, '') = '') AS missing_kingdom
                FROM public.alaris_characters
                WHERE guild_id = %s
                  AND COALESCE(status, 'active') = 'active';
                """,
                (guild_id,),
            )
            counts = cur.fetchone() or {}
            alaris_found = int(counts.get("n") or 0)
            missing_kingdom = int(counts.get("missing_kingdom") or 0)

            cur.execute(
                """
                INSERT INTO public.characters (
                    guild_id, character_id, user_id, name, normalized_name, species, class_name,
                    kingdom, level, xp_total, archived, created_at, updated_at
                )
                SELECT
                    guild_id,
                    id AS character_id,
                    user_id,
                    name,
                    COALESCE(normalized_name, lower(name)) AS normalized_name,
                    COALESCE(species, '') AS species,
                    COALESCE(class_name, '') AS class_name,
                    NULLIF(COALESCE(kingdom, ''), '') AS kingdom,
                    COALESCE(level, 1) AS level,
                    COALESCE(xp_total, 0) AS xp_total,
                    CASE WHEN COALESCE(status, 'active') = 'active' THEN FALSE ELSE TRUE END AS archived,
                    COALESCE(created_at, NOW()) AS created_at,
                    NOW() AS updated_at
                FROM public.alaris_characters
                WHERE guild_id = %s
                ON CONFLICT (guild_id, character_id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    name = EXCLUDED.name,
                    normalized_name = EXCLUDED.normalized_name,
                    species = EXCLUDED.species,
                    class_name = EXCLUDED.class_name,
                    kingdom = EXCLUDED.kingdom,
                    level = EXCLUDED.level,
                    xp_total = EXCLUDED.xp_total,
                    archived = EXCLUDED.archived,
                    updated_at = NOW();
                """,
                (guild_id,),
            )
            synced = int(cur.rowcount or 0)
        conn.commit()
    return {
        "has_alaris_characters": 1,
        "alaris_found": alaris_found,
        "synced": synced,
        "missing_kingdom": missing_kingdom,
    }


def fetch_character_by_name_sync(guild_id: int, character_name: str) -> Optional[CharacterRef]:
    name = character_name.strip()
    with db_connect() as conn:
        with conn.cursor() as cur:
            # Preferred compatibility table produced by AlarisBot v100+.
            cur.execute(
                """
                SELECT character_id, user_id, name, kingdom
                FROM public.characters
                WHERE guild_id = %s
                  AND archived = FALSE
                  AND name = %s
                LIMIT 1;
                """,
                (guild_id, name),
            )
            row = cur.fetchone()
            if row:
                return CharacterRef(
                    guild_id=guild_id,
                    character_id=int(row["character_id"]),
                    user_id=int(row["user_id"]),
                    name=str(row["name"]),
                    kingdom=str(row["kingdom"]).strip() if row.get("kingdom") else None,
                    source_table="public.characters",
                )

            # Fallback for clean Alaris table if bridge is not present.
            cur.execute(
                """
                SELECT id AS character_id, user_id, name, kingdom
                FROM public.alaris_characters
                WHERE guild_id = %s
                  AND archived = FALSE
                  AND name = %s
                LIMIT 1;
                """,
                (guild_id, name),
            )
            row = cur.fetchone()
            if row:
                return CharacterRef(
                    guild_id=guild_id,
                    character_id=int(row["character_id"]),
                    user_id=int(row["user_id"]),
                    name=str(row["name"]),
                    kingdom=str(row["kingdom"]).strip() if row.get("kingdom") else None,
                    source_table="public.alaris_characters",
                )
    return None


def search_characters_sync(guild_id: int, current: str) -> list[app_commands.Choice[str]]:
    needle = f"%{current.strip()}%"
    choices: list[app_commands.Choice[str]] = []
    seen: set[str] = set()
    with db_connect() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT name
                    FROM public.characters
                    WHERE guild_id = %s AND archived = FALSE AND name ILIKE %s
                    ORDER BY name ASC
                    LIMIT 25;
                    """,
                    (guild_id, needle),
                )
                for row in cur.fetchall():
                    nm = clean_text(row["name"])
                    if nm and nm not in seen:
                        seen.add(nm)
                        choices.append(app_commands.Choice(name=nm[:100], value=nm[:100]))
            except Exception:
                pass

            if len(choices) < 25:
                try:
                    cur.execute(
                        """
                        SELECT name
                        FROM public.alaris_characters
                        WHERE guild_id = %s AND archived = FALSE AND name ILIKE %s
                        ORDER BY name ASC
                        LIMIT 25;
                        """,
                        (guild_id, needle),
                    )
                    for row in cur.fetchall():
                        nm = clean_text(row["name"])
                        if nm and nm not in seen:
                            seen.add(nm)
                            choices.append(app_commands.Choice(name=nm[:100], value=nm[:100]))
                            if len(choices) >= 25:
                                break
                except Exception:
                    pass
    return choices[:25]


def get_balance_sync(guild_id: int, character_id: int) -> int:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance_embers FROM econ.balances WHERE guild_id = %s AND character_id = %s LIMIT 1;",
                (guild_id, character_id),
            )
            row = cur.fetchone()
            return int(row["balance_embers"]) if row else 0


def set_balance_sync(guild_id: int, character_id: int, value_embers: int) -> int:
    value = max(0, int(value_embers))
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (guild_id, character_id)
                DO UPDATE SET balance_embers = EXCLUDED.balance_embers, updated_at = NOW();
                """,
                (guild_id, character_id, value),
            )
        conn.commit()
    return value


def adjust_balance_sync(guild_id: int, character_id: int, delta_embers: int) -> int:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                VALUES (%s, %s, 0, NOW())
                ON CONFLICT (guild_id, character_id) DO NOTHING;
                """,
                (guild_id, character_id),
            )
            cur.execute(
                """
                UPDATE econ.balances
                SET balance_embers = GREATEST(0, balance_embers + %s), updated_at = NOW()
                WHERE guild_id = %s AND character_id = %s
                RETURNING balance_embers;
                """,
                (int(delta_embers), guild_id, character_id),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["balance_embers"])


def log_transaction_sync(
    guild_id: int,
    character_id: Optional[int],
    actor_user_id: Optional[int],
    action: str,
    amount_embers: int = 0,
    details: Optional[dict[str, Any]] = None,
) -> None:
    import json

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.transactions (guild_id, character_id, actor_user_id, action, amount_embers, details_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb);
                """,
                (guild_id, character_id, actor_user_id, action, int(amount_embers), json.dumps(details or {})),
            )
        conn.commit()


def enqueue_character_refresh_sync(guild_id: int, character_id: int, reason: str = "economy_update") -> None:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.alaris_character_refresh_queue (guild_id, character_id, reason)
                VALUES (%s, %s, %s);
                """,
                (guild_id, character_id, reason),
            )
        conn.commit()


def fetch_assets_sync(guild_id: int, character_id: int) -> list[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_type, tier_code, asset_name, kingdom,
                       noble_title_family, noble_title_option, noble_realm_name,
                       income_embers
                FROM econ.assets
                WHERE guild_id = %s AND character_id = %s
                ORDER BY asset_type ASC, tier_code ASC NULLS LAST, asset_name ASC;
                """,
                (guild_id, character_id),
            )
            return [dict(row) for row in cur.fetchall()]


def total_asset_income_sync(guild_id: int, character_id: int) -> int:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(income_embers), 0) AS income
                FROM econ.assets
                WHERE guild_id = %s AND character_id = %s;
                """,
                (guild_id, character_id),
            )
            row = cur.fetchone()
            return int(row["income"] or 0)


def set_character_kingdom_sync(guild_id: int, character_id: int, kingdom: str) -> None:
    with db_connect() as conn:
        with conn.cursor() as cur:
            # Update compatibility/public table when present.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'characters'
                    ) THEN
                        UPDATE public.characters
                        SET kingdom = $3
                        WHERE guild_id = $1 AND character_id = $2;
                    END IF;
                END $$;
                """.replace("$1", "%s").replace("$2", "%s").replace("$3", "%s"),
                (guild_id, character_id, kingdom),
            )
            # Update native Alaris table when present.
            cur.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'alaris_characters'
                    ) THEN
                        UPDATE public.alaris_characters
                        SET kingdom = $3
                        WHERE guild_id = $1 AND id = $2;
                    END IF;
                END $$;
                """.replace("$1", "%s").replace("$2", "%s").replace("$3", "%s"),
                (guild_id, character_id, kingdom),
            )
        conn.commit()


def fetch_kingdoms_sync(guild_id: int) -> list[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kingdom, tax_rate_bp, treasury_embers
                FROM econ.kingdoms
                WHERE guild_id = %s
                ORDER BY kingdom ASC;
                """,
                (guild_id,),
            )
            return [dict(row) for row in cur.fetchall()]


def set_kingdom_tax_sync(guild_id: int, kingdom: str, tax_bp: int) -> None:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.kingdoms (guild_id, kingdom, tax_rate_bp, treasury_embers, updated_at)
                VALUES (%s, %s, %s, 0, NOW())
                ON CONFLICT (guild_id, kingdom)
                DO UPDATE SET tax_rate_bp = EXCLUDED.tax_rate_bp, updated_at = NOW();
                """,
                (guild_id, kingdom, int(tax_bp)),
            )
        conn.commit()


def set_kingdom_treasury_sync(guild_id: int, kingdom: str, amount_embers: int) -> None:
    amount = max(0, int(amount_embers))
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.kingdoms (guild_id, kingdom, tax_rate_bp, treasury_embers, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (guild_id, kingdom)
                DO UPDATE SET treasury_embers = EXCLUDED.treasury_embers, updated_at = NOW();
                """,
                (guild_id, kingdom, DEFAULT_TAX_BP, amount),
            )
        conn.commit()


def add_to_kingdom_treasury_sync(guild_id: int, kingdom: str, amount_embers: int) -> None:
    if amount_embers <= 0:
        return
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.kingdoms (guild_id, kingdom, tax_rate_bp, treasury_embers, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (guild_id, kingdom)
                DO UPDATE SET treasury_embers = econ.kingdoms.treasury_embers + EXCLUDED.treasury_embers,
                              updated_at = NOW();
                """,
                (guild_id, kingdom, DEFAULT_TAX_BP, int(amount_embers)),
            )
        conn.commit()


# -----------------------------------------------------------------------------
# Discord helpers
# -----------------------------------------------------------------------------


async def is_staff(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    perms = member.guild_permissions
    if perms.administrator or perms.manage_guild or perms.manage_messages:
        return True
    if STAFF_ROLE_IDS:
        return any(role.id in STAFF_ROLE_IDS for role in member.roles)
    return False


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if await is_staff(interaction):
            return True
        msg = "You do not have permission to use this Economy staff command."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return False

    return app_commands.check(predicate)


async def character_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    guild_id = interaction.guild_id or GUILD_ID
    return await run_db(search_characters_sync, int(guild_id), current or "")


KINGDOM_CHOICES = [app_commands.Choice(name=k, value=k) for k in CANON_KINGDOMS]
TAX_CHOICES = [
    app_commands.Choice(name="0%", value=0),
    app_commands.Choice(name="5%", value=5),
    app_commands.Choice(name="10%", value=10),
    app_commands.Choice(name="15%", value=15),
    app_commands.Choice(name="20%", value=20),
    app_commands.Choice(name="25%", value=25),
    app_commands.Choice(name="30%", value=30),
    app_commands.Choice(name="40%", value=40),
    app_commands.Choice(name="50%", value=50),
]


async def log_to_channel(action: str, lines: list[str]) -> None:
    if not ECON_LOG_CHANNEL_ID:
        return
    channel = client.get_channel(int(ECON_LOG_CHANNEL_ID))
    if channel is None:
        try:
            channel = await client.fetch_channel(int(ECON_LOG_CHANNEL_ID))
        except Exception:
            return
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return
    text = f"**ECON LOG:** `{action}`\n" + "\n".join(lines)
    await channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())


async def resolve_character_or_reply(interaction: discord.Interaction, character: str) -> Optional[CharacterRef]:
    guild_id = interaction.guild_id or GUILD_ID
    ref = await run_db(fetch_character_by_name_sync, int(guild_id), character)
    if not ref:
        await interaction.followup.send("Character not found in the Alaris character database.", ephemeral=True)
        return None
    return ref


# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------


@tree.command(name="econ-ping", description="Check whether the Alaris Economy Bot is online.", guild=discord.Object(id=GUILD_ID))
async def econ_ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"{APP_VERSION} is online.", ephemeral=True)


@tree.command(name="econ-commands", description="Show Alaris Economy Bot commands.", guild=discord.Object(id=GUILD_ID))
async def econ_commands(interaction: discord.Interaction):
    staff = await is_staff(interaction)
    lines = [
        f"**Alaris Economy Bot Commands** ({APP_VERSION})",
        "",
        "**Player**",
        "• `/balance` - view a character's economy card",
        "• `/income` - claim daily income for one of your characters",
        "• `/treasuries` - view kingdom treasury/tax status",
        "",
        "**Staff**" if staff else "**Staff commands hidden**",
    ]
    if staff:
        lines.extend(
            [
                "• `/econ-set-balance` - set a character balance exactly",
                "• `/econ-adjust` - adjust a character balance by an amount",
                "• `/econ-grant-all` - grant all active characters currency",
                "• `/econ-set-character-kingdom` - associate a character with a kingdom/land",
                "• `/econ-set-kingdom-tax` - set a kingdom tax rate",
                "• `/econ-set-kingdom-treasury` - set a kingdom treasury exactly",
                "• `/econ-schema-status` - confirm economy schema/bootstrap status",
                "• `/econ-sync-characters` - backfill the economy character mirror from Alaris",
            ]
        )
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@tree.command(name="balance", description="View a character's Alaris economy balance.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(character="Character name")
@app_commands.autocomplete(character=character_autocomplete)
async def balance(interaction: discord.Interaction, character: str):
    await interaction.response.defer(ephemeral=True)
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return

    balance_embers = await run_db(get_balance_sync, ref.guild_id, ref.character_id)
    assets = await run_db(fetch_assets_sync, ref.guild_id, ref.character_id)
    asset_income = await run_db(total_asset_income_sync, ref.guild_id, ref.character_id)
    kingdom = ref.kingdom or "Unassigned"

    business_lines: list[str] = []
    property_lines: list[str] = []
    title_lines: list[str] = []
    other_lines: list[str] = []

    for asset in assets:
        asset_type = clean_text(asset.get("asset_type"))
        asset_name = clean_text(asset.get("asset_name"))
        k = clean_text(asset.get("kingdom")) or kingdom
        income = int(asset.get("income_embers") or 0)
        line = f"• **{asset_name}** — {asset_type} — {k}"
        if income:
            line += f" — +{format_currency(income, show_base_total=False)}/day"
        if asset_type.lower() in {"business", "business/property", "guild trade workshop", "market stall", "tavern/inn", "warehouse/trade house", "farm/ranch"}:
            business_lines.append(line)
        elif asset_type.lower() in {"property", "house", "village", "estate", "land"}:
            property_lines.append(line)
        elif asset_type.lower() == "noble title":
            option = clean_text(asset.get("noble_title_option")) or asset_name
            realm = clean_text(asset.get("noble_realm_name"))
            title_kingdom = clean_text(asset.get("kingdom")) or kingdom
            if realm:
                title_lines.append(f"• **{option} of {realm}** | {title_kingdom}")
            else:
                title_lines.append(f"• **{option}** | {title_kingdom}")
        else:
            other_lines.append(line)

    embed = discord.Embed(
        title=f"{clean_text(ref.name)} — Economy",
        color=discord.Color.gold(),
        description=f"**Kingdom/Land:** {clean_text(kingdom)}\n**Balance:** {format_currency(balance_embers)}\n**Asset Income:** {format_currency(asset_income)}",
    )
    embed.add_field(name="Businesses", value="\n".join(business_lines) if business_lines else "None recorded", inline=False)
    embed.add_field(name="Properties", value="\n".join(property_lines) if property_lines else "None recorded", inline=False)
    embed.add_field(name="Noble Titles", value="\n".join(title_lines) if title_lines else "None recorded", inline=False)
    if other_lines:
        embed.add_field(name="Other Holdings", value="\n".join(other_lines)[:1024], inline=False)
    embed.set_footer(text="Alaris currency: Embers, Crowns, Sovereigns, Thrones, Astrals")
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="income", description="Claim daily income for one of your characters.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(character="Character name")
@app_commands.autocomplete(character=character_autocomplete)
async def income(interaction: discord.Interaction, character: str):
    await interaction.response.defer(ephemeral=True)
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return
    if int(ref.user_id) != int(interaction.user.id):
        await interaction.followup.send("You may only claim income for a character you own.", ephemeral=True)
        return
    if not ref.kingdom:
        await interaction.followup.send("This character does not have a kingdom/land assigned yet. Ask staff to set it first.", ephemeral=True)
        return

    today = datetime.now(CHICAGO_TZ).date()

    def claim_sync() -> dict[str, Any]:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT last_claim_date
                    FROM econ.income_claims
                    WHERE guild_id = %s AND character_id = %s
                    LIMIT 1;
                    """,
                    (ref.guild_id, ref.character_id),
                )
                row = cur.fetchone()
                if row and row["last_claim_date"] == today:
                    return {"ok": False, "reason": "already_claimed"}

                cur.execute(
                    """
                    SELECT COALESCE(SUM(income_embers), 0) AS asset_income
                    FROM econ.assets
                    WHERE guild_id = %s AND character_id = %s;
                    """,
                    (ref.guild_id, ref.character_id),
                )
                asset_income = int(cur.fetchone()["asset_income"] or 0)
                gross = DEFAULT_DAILY_INCOME_EMBERS + asset_income

                cur.execute(
                    "SELECT tax_rate_bp FROM econ.kingdoms WHERE guild_id = %s AND kingdom = %s LIMIT 1;",
                    (ref.guild_id, ref.kingdom),
                )
                tax_row = cur.fetchone()
                tax_bp = int(tax_row["tax_rate_bp"] if tax_row else DEFAULT_TAX_BP)
                tax = calc_tax(gross, tax_bp)
                net = max(0, gross - tax)

                cur.execute(
                    """
                    INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (guild_id, character_id)
                    DO UPDATE SET balance_embers = econ.balances.balance_embers + EXCLUDED.balance_embers,
                                  updated_at = NOW()
                    RETURNING balance_embers;
                    """,
                    (ref.guild_id, ref.character_id, net),
                )
                new_balance = int(cur.fetchone()["balance_embers"])

                cur.execute(
                    """
                    INSERT INTO econ.kingdoms (guild_id, kingdom, tax_rate_bp, treasury_embers, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (guild_id, kingdom)
                    DO UPDATE SET treasury_embers = econ.kingdoms.treasury_embers + EXCLUDED.treasury_embers,
                                  updated_at = NOW();
                    """,
                    (ref.guild_id, ref.kingdom, DEFAULT_TAX_BP, tax),
                )

                cur.execute(
                    """
                    INSERT INTO econ.income_claims (guild_id, character_id, last_claim_date, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (guild_id, character_id)
                    DO UPDATE SET last_claim_date = EXCLUDED.last_claim_date, updated_at = NOW();
                    """,
                    (ref.guild_id, ref.character_id, today),
                )
            conn.commit()
        log_transaction_sync(ref.guild_id, ref.character_id, interaction.user.id, "income_claim", net, {"gross": gross, "tax": tax, "tax_bp": tax_bp, "kingdom": ref.kingdom})
        enqueue_character_refresh_sync(ref.guild_id, ref.character_id, "economy_income_claim")
        return {"ok": True, "base": DEFAULT_DAILY_INCOME_EMBERS, "asset_income": asset_income, "gross": gross, "tax": tax, "net": net, "new_balance": new_balance, "tax_bp": tax_bp}

    result = await run_db(claim_sync)
    if not result.get("ok"):
        await interaction.followup.send("Daily income already claimed today.", ephemeral=True)
        return

    await log_to_channel(
        "income_claim",
        [
            f"Character: **{clean_text(ref.name)}**",
            f"Kingdom: **{clean_text(ref.kingdom)}**",
            f"Gross: **{format_currency(result['gross'])}**",
            f"Tax: **{format_currency(result['tax'])}** ({bp_to_percent(result['tax_bp'])})",
            f"Net: **{format_currency(result['net'])}**",
        ],
    )

    await interaction.followup.send(
        "\n".join(
            [
                f"Claimed daily income for **{clean_text(ref.name)}**.",
                f"Base income: **{format_currency(result['base'])}**",
                f"Asset income: **{format_currency(result['asset_income'])}**",
                f"Gross: **{format_currency(result['gross'])}**",
                f"Tax to {clean_text(ref.kingdom)}: **{format_currency(result['tax'])}**",
                f"Net received: **{format_currency(result['net'])}**",
                f"New balance: **{format_currency(result['new_balance'])}**",
            ]
        ),
        ephemeral=True,
    )


@tree.command(name="treasuries", description="View Alaris kingdom treasury and tax status.", guild=discord.Object(id=GUILD_ID))
async def treasuries(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    rows = await run_db(fetch_kingdoms_sync, int(interaction.guild_id or GUILD_ID))
    embed = discord.Embed(title="Alaris Kingdom Treasuries", color=discord.Color.blurple())
    for row in rows:
        embed.add_field(
            name=clean_text(row["kingdom"]),
            value=f"Treasury: **{format_currency(int(row['treasury_embers']))}**\nTax: **{bp_to_percent(int(row['tax_rate_bp']))}**",
            inline=False,
        )
    await interaction.followup.send(embed=embed, ephemeral=True)


@tree.command(name="econ-set-balance", description="Staff: set a character balance exactly.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(character="Character name", amount_embers="Amount in Embers/base units")
@app_commands.autocomplete(character=character_autocomplete)
async def econ_set_balance(interaction: discord.Interaction, character: str, amount_embers: int):
    await interaction.response.defer(ephemeral=True)
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return
    if amount_embers < 0:
        await interaction.followup.send("Amount cannot be negative.", ephemeral=True)
        return
    new_balance = await run_db(set_balance_sync, ref.guild_id, ref.character_id, int(amount_embers))
    await run_db(log_transaction_sync, ref.guild_id, ref.character_id, interaction.user.id, "set_balance", int(amount_embers), {"character": ref.name})
    await run_db(enqueue_character_refresh_sync, ref.guild_id, ref.character_id, "economy_set_balance")
    await log_to_channel("set_balance", [f"Character: **{clean_text(ref.name)}**", f"New balance: **{format_currency(new_balance)}**"])
    await interaction.followup.send(f"Set **{clean_text(ref.name)}** balance to **{format_currency(new_balance)}**.", ephemeral=True)


@tree.command(name="econ-adjust", description="Staff: adjust a character balance by an amount.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(character="Character name", delta_embers="Positive or negative amount in Embers/base units")
@app_commands.autocomplete(character=character_autocomplete)
async def econ_adjust(interaction: discord.Interaction, character: str, delta_embers: int):
    await interaction.response.defer(ephemeral=True)
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return
    new_balance = await run_db(adjust_balance_sync, ref.guild_id, ref.character_id, int(delta_embers))
    await run_db(log_transaction_sync, ref.guild_id, ref.character_id, interaction.user.id, "adjust_balance", int(delta_embers), {"character": ref.name})
    await run_db(enqueue_character_refresh_sync, ref.guild_id, ref.character_id, "economy_adjust_balance")
    await log_to_channel("adjust_balance", [f"Character: **{clean_text(ref.name)}**", f"Delta: **{format_currency(delta_embers)}**", f"New balance: **{format_currency(new_balance)}**"])
    await interaction.followup.send(f"Adjusted **{clean_text(ref.name)}** by **{format_currency(delta_embers)}**. New balance: **{format_currency(new_balance)}**.", ephemeral=True)


@tree.command(name="econ-grant-all", description="Staff: grant currency to every active character.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(amount_embers="Amount in Embers/base units to grant to every active character")
async def econ_grant_all(interaction: discord.Interaction, amount_embers: int):
    await interaction.response.defer(ephemeral=True)
    if amount_embers <= 0:
        await interaction.followup.send("Amount must be greater than 0.", ephemeral=True)
        return

    def grant_sync() -> int:
        with db_connect() as conn:
            with conn.cursor() as cur:
                # Prefer public.characters compatibility table.
                cur.execute(
                    """
                    SELECT character_id
                    FROM public.characters
                    WHERE guild_id = %s AND archived = FALSE;
                    """,
                    (int(interaction.guild_id or GUILD_ID),),
                )
                ids = [int(row["character_id"]) for row in cur.fetchall()]
                if not ids:
                    cur.execute(
                        """
                        SELECT id AS character_id
                        FROM public.alaris_characters
                        WHERE guild_id = %s AND archived = FALSE;
                        """,
                        (int(interaction.guild_id or GUILD_ID),),
                    )
                    ids = [int(row["character_id"]) for row in cur.fetchall()]
                for cid in ids:
                    cur.execute(
                        """
                        INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (guild_id, character_id)
                        DO UPDATE SET balance_embers = econ.balances.balance_embers + EXCLUDED.balance_embers,
                                      updated_at = NOW();
                        """,
                        (int(interaction.guild_id or GUILD_ID), cid, int(amount_embers)),
                    )
                    cur.execute(
                        """
                        INSERT INTO public.alaris_character_refresh_queue (guild_id, character_id, reason)
                        VALUES (%s, %s, 'economy_grant_all');
                        """,
                        (int(interaction.guild_id or GUILD_ID), cid),
                    )
            conn.commit()
        return len(ids)

    count = await run_db(grant_sync)
    await run_db(log_transaction_sync, int(interaction.guild_id or GUILD_ID), None, interaction.user.id, "grant_all", int(amount_embers), {"count": count})
    await log_to_channel("grant_all", [f"Amount: **{format_currency(amount_embers)}**", f"Characters affected: **{count:,}**"])
    await interaction.followup.send(f"Granted **{format_currency(amount_embers)}** to **{count:,}** active character(s).", ephemeral=True)


@tree.command(name="econ-set-character-kingdom", description="Staff: associate a character with a kingdom/land.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(character="Character name", kingdom="Canonical Alaris kingdom/land")
@app_commands.autocomplete(character=character_autocomplete)
@app_commands.choices(kingdom=KINGDOM_CHOICES)
async def econ_set_character_kingdom(interaction: discord.Interaction, character: str, kingdom: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return
    if not is_valid_kingdom(kingdom.value):
        await interaction.followup.send("Invalid kingdom/land.", ephemeral=True)
        return
    await run_db(set_character_kingdom_sync, ref.guild_id, ref.character_id, kingdom.value)
    await run_db(log_transaction_sync, ref.guild_id, ref.character_id, interaction.user.id, "set_character_kingdom", 0, {"character": ref.name, "kingdom": kingdom.value})
    await run_db(enqueue_character_refresh_sync, ref.guild_id, ref.character_id, "economy_set_character_kingdom")
    await log_to_channel("set_character_kingdom", [f"Character: **{clean_text(ref.name)}**", f"Kingdom/Land: **{clean_text(kingdom.value)}**"])
    await interaction.followup.send(f"Set **{clean_text(ref.name)}** kingdom/land to **{clean_text(kingdom.value)}**.", ephemeral=True)


@tree.command(name="econ-set-kingdom-tax", description="Staff: set a kingdom tax rate.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(kingdom="Canonical Alaris kingdom/land", rate_percent="Tax rate")
@app_commands.choices(kingdom=KINGDOM_CHOICES, rate_percent=TAX_CHOICES)
async def econ_set_kingdom_tax(interaction: discord.Interaction, kingdom: app_commands.Choice[str], rate_percent: app_commands.Choice[int]):
    await interaction.response.defer(ephemeral=True)
    tax_bp = int(rate_percent.value) * 100
    await run_db(set_kingdom_tax_sync, int(interaction.guild_id or GUILD_ID), kingdom.value, tax_bp)
    await run_db(log_transaction_sync, int(interaction.guild_id or GUILD_ID), None, interaction.user.id, "set_kingdom_tax", 0, {"kingdom": kingdom.value, "tax_bp": tax_bp})
    await log_to_channel("set_kingdom_tax", [f"Kingdom/Land: **{clean_text(kingdom.value)}**", f"Tax: **{bp_to_percent(tax_bp)}**"])
    await interaction.followup.send(f"Set **{clean_text(kingdom.value)}** tax rate to **{bp_to_percent(tax_bp)}**.", ephemeral=True)


@tree.command(name="econ-set-kingdom-treasury", description="Staff: set a kingdom treasury exactly.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(kingdom="Canonical Alaris kingdom/land", amount_embers="Treasury amount in Embers/base units")
@app_commands.choices(kingdom=KINGDOM_CHOICES)
async def econ_set_kingdom_treasury(interaction: discord.Interaction, kingdom: app_commands.Choice[str], amount_embers: int):
    await interaction.response.defer(ephemeral=True)
    if amount_embers < 0:
        await interaction.followup.send("Treasury amount cannot be negative.", ephemeral=True)
        return
    await run_db(set_kingdom_treasury_sync, int(interaction.guild_id or GUILD_ID), kingdom.value, int(amount_embers))
    await run_db(log_transaction_sync, int(interaction.guild_id or GUILD_ID), None, interaction.user.id, "set_kingdom_treasury", int(amount_embers), {"kingdom": kingdom.value})
    await log_to_channel("set_kingdom_treasury", [f"Kingdom/Land: **{clean_text(kingdom.value)}**", f"Treasury: **{format_currency(amount_embers)}**"])
    await interaction.followup.send(f"Set **{clean_text(kingdom.value)}** treasury to **{format_currency(amount_embers)}**.", ephemeral=True)


@tree.command(name="econ-sync-characters", description="Staff: sync existing Alaris characters into the economy lookup mirror.", guild=discord.Object(id=GUILD_ID))
@staff_only()
async def econ_sync_characters(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    result = await run_db(sync_public_characters_from_alaris_sync, int(interaction.guild_id or GUILD_ID))
    await interaction.followup.send(
        "\n".join(
            [
                f"**{APP_VERSION} Character Sync**",
                f"Alaris character table present: **{bool(result['has_alaris_characters'])}**",
                f"Active Alaris characters found: **{result['alaris_found']}**",
                f"Compatibility rows inserted/updated: **{result['synced']}**",
                f"Characters missing kingdom: **{result['missing_kingdom']}**",
                "",
                "This command is additive only. It does not delete characters, balances, assets, or transactions.",
            ]
        ),
        ephemeral=True,
    )



@tree.command(name="econ-schema-status", description="Staff: check EconomyBot schema/bootstrap status.", guild=discord.Object(id=GUILD_ID))
@staff_only()
async def econ_schema_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    def status_sync() -> dict[str, Any]:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM econ.kingdoms WHERE guild_id = %s;", (int(interaction.guild_id or GUILD_ID),))
                kingdoms = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM public.characters WHERE guild_id = %s AND archived = FALSE;", (int(interaction.guild_id or GUILD_ID),))
                compat_chars = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM public.alaris_characters WHERE guild_id = %s AND COALESCE(status, 'active') = 'active';", (int(interaction.guild_id or GUILD_ID),))
                alaris_chars = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM econ.balances WHERE guild_id = %s;", (int(interaction.guild_id or GUILD_ID),))
                balances = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM econ.assets WHERE guild_id = %s;", (int(interaction.guild_id or GUILD_ID),))
                assets = int(cur.fetchone()["n"])
                cur.execute("SELECT COUNT(*) AS n FROM public.alaris_character_refresh_queue WHERE guild_id = %s AND processed_at IS NULL;", (int(interaction.guild_id or GUILD_ID),))
                queue = int(cur.fetchone()["n"])
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'characters'
                    ) AS has_public_characters,
                    EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'alaris_characters'
                    ) AS has_alaris_characters;
                    """
                )
                flags = cur.fetchone()
        return {"kingdoms": kingdoms, "alaris_chars": alaris_chars, "compat_chars": compat_chars, "balances": balances, "assets": assets, "queue": queue, **dict(flags)}

    s = await run_db(status_sync)
    await interaction.followup.send(
        "\n".join(
            [
                f"**{APP_VERSION} Schema Status**",
                f"Canonical kingdoms seeded: **{s['kingdoms']} / {len(CANON_KINGDOMS)}**",
                f"Active Alaris characters: **{s['alaris_chars']}**",
                f"Economy compatibility characters: **{s['compat_chars']}**",
                f"Balance rows: **{s['balances']}**",
                f"Asset rows: **{s['assets']}**",
                f"Pending character refresh rows: **{s['queue']}**",
                f"public.characters present: **{s['has_public_characters']}**",
                f"public.alaris_characters present: **{s['has_alaris_characters']}**",
            ]
        ),
        ephemeral=True,
    )


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    traceback.print_exception(type(error), error, error.__traceback__)
    msg = "EconomyBot hit an internal error. Check Railway logs for details."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


@client.event
async def on_ready():
    print(f"[startup] {APP_VERSION} logged in as {client.user}")
    print(f"[startup] Guild ID: {GUILD_ID}")
    try:
        await run_db(ensure_schema_sync)
        print("[startup] Economy schema ensured.")
        sync_result = await run_db(sync_public_characters_from_alaris_sync, GUILD_ID)
        print(f"[startup] Character sync result: {sync_result}")
    except Exception as exc:
        print(f"[startup][ERROR] ensure_schema failed: {exc}")
        traceback.print_exc()

    try:
        guild_obj = discord.Object(id=GUILD_ID)
        synced = await tree.sync(guild=guild_obj)
        print(f"[startup] Synced {len(synced)} guild command(s).")
        print("[startup] Commands:", sorted(c.name for c in synced))
    except Exception as exc:
        print(f"[startup][ERROR] command sync failed: {exc}")
        traceback.print_exc()


def main():
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
