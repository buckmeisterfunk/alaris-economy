# Alaris_EconomyBot_v010
# Full replacement for main.py
# Purpose: standalone Alaris Economy Bot using shared Postgres.
# v010: Immediate safety fix. Disables economy-triggered character-card refresh queueing to prevent duplicate Alaris character showcase posts until AlarisBot has an edit-only refresh path.
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
import json
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


APP_VERSION = "Alaris_EconomyBot_v010"
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
# Currency conversion, base unit = Ember.
# 100 Embers = 1 Crown; 100 Crowns = 1 Sovereign; 100 Sovereigns = 1 Throne; 100 Thrones = 1 Astral.
CURRENCY_UNITS: list[tuple[int, str, str]] = [
    (100_000_000, "Astral", "Astrals"),
    (1_000_000, "Throne", "Thrones"),
    (10_000, "Sovereign", "Sovereigns"),
    (100, "Crown", "Crowns"),
    (1, "Ember", "Embers"),
]

# Predefined asset catalog recovered from the prior economy bot.
# Values are stored in Embers. Tier labels intentionally retain their in-world tier names.
# Noble titles are intentionally omitted from player purchase/upgrade flows for now.
ASSET_DEFINITIONS_SEED: list[tuple[str, str, int, int]] = [
    ("Guild Trade Workshop", "(1) Guild Apprentice", 300, 50),
    ("Guild Trade Workshop", "(2) Guild Journeyman", 600, 100),
    ("Guild Trade Workshop", "(3) Leased Workshop", 1200, 150),
    ("Guild Trade Workshop", "(4) Small Workshop", 2000, 200),
    ("Guild Trade Workshop", "(5) Large Workshop", 3000, 250),
    ("Market Stall", "(1) Consignment Arrangement", 300, 50),
    ("Market Stall", "(2) Small Alley Stand", 600, 100),
    ("Market Stall", "(3) Market Stall", 1200, 150),
    ("Market Stall", "(4) Small Shop", 2000, 200),
    ("Market Stall", "(5) Large Shop", 3000, 250),
    ("Farm/Ranch", "(1) Subsistence Surplus", 300, 50),
    ("Farm/Ranch", "(2) Leased Fields", 600, 100),
    ("Farm/Ranch", "(3) Owned Acre", 1200, 150),
    ("Farm/Ranch", "(4) Small Fields and Barn", 2000, 200),
    ("Farm/Ranch", "(5) Large Fields and Barn", 3000, 250),
    ("Tavern/Inn", "(1) One-Room Flophouse", 300, 50),
    ("Tavern/Inn", "(2) Leased Establishment", 600, 100),
    ("Tavern/Inn", "(3) Small Tavern", 1200, 150),
    ("Tavern/Inn", "(4) Large Tavern", 2000, 200),
    ("Tavern/Inn", "(5) Large Tavern and Inn", 3000, 250),
    ("Warehouse/Trade House", "(1) Small Storage Shed", 300, 50),
    ("Warehouse/Trade House", "(2) Large Storage Shed", 600, 100),
    ("Warehouse/Trade House", "(3) Small Trading Post", 1200, 150),
    ("Warehouse/Trade House", "(4) Large Trading Post", 2000, 200),
    ("Warehouse/Trade House", "(5) Large Warehouse and Trading Post", 3000, 250),
    ("House", "(1) Shack", 600, 0),
    ("House", "(2) Hut", 1200, 0),
    ("House", "(3) House", 2000, 0),
    ("House", "(4) Lodge", 3000, 0),
    ("House", "(5) Mansion", 5000, 0),
    ("Village", "(1) Chartered Assembly", 1200, 100),
    ("Village", "(2) Hamlet", 2400, 200),
    ("Village", "(3) Village", 4800, 300),
    ("Village", "(4) Town", 9600, 400),
    ("Village", "(5) Small City", 15000, 500),
    ("Weapons", "(1) Hit +1 / Dmg +1d4", 300, 0),
    ("Weapons", "(2) Hit +1 / Dmg +1d6", 600, 0),
    ("Weapons", "(3) Hit +2 / Dmg +1d8", 1200, 0),
    ("Weapons", "(4) Hit +2 / Dmg +1d10", 2400, 0),
    ("Weapons", "(5) Hit +2 / Dmg +1d12", 4800, 0),
    ("Armor", "(1) AC +1", 300, 0),
    ("Armor", "(2) AC +2", 600, 0),
    ("Armor", "(3) AC +2 / Adv Magic Atk", 1200, 0),
    ("Armor", "(4) AC +2 / Adv Magic and Melee Atk", 2400, 0),
    ("Armor", "(5) AC +3 / Adv Magic and Melee Atk", 4800, 0),
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


DEFAULT_DAILY_INCOME_EMBERS = _get_int_env("DAILY_INCOME_EMBERS", 100) or 100  # 1 Crown default; tune via Railway env later.

DISCORD_TOKEN = _get_env("DISCORD_TOKEN")
DATABASE_URL = _get_env("DATABASE_URL")
GUILD_ID = _get_int_env("GUILD_ID")
STAFF_ROLE_IDS = _get_int_list_env("STAFF_ROLE_IDS")
ECON_LOG_CHANNEL_ID = _get_int_env("ECON_LOG_CHANNEL_ID", 1504528860237136022)
ASSET_REQUEST_CHANNEL_ID = _get_int_env("ASSET_REQUEST_CHANNEL_ID", 1504610669800980532)
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
    """Additive-only schema setup for EconomyBot v003."""
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
                CREATE TABLE IF NOT EXISTS econ.asset_requests (
                    id BIGSERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    request_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    character_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    asset_id BIGINT,
                    asset_type TEXT NOT NULL,
                    from_tier_code TEXT,
                    to_tier_code TEXT NOT NULL,
                    asset_name TEXT NOT NULL,
                    kingdom TEXT,
                    cost_embers BIGINT NOT NULL DEFAULT 0,
                    income_embers BIGINT NOT NULL DEFAULT 0,
                    request_channel_id BIGINT,
                    request_message_id BIGINT,
                    decided_by_user_id BIGINT,
                    decision_note TEXT,
                    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    decided_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

            # Ensure asset definition columns exist if this table was created by an earlier build.
            cur.execute("ALTER TABLE econ.asset_definitions ADD COLUMN IF NOT EXISTS display_name TEXT;")
            cur.execute("ALTER TABLE econ.asset_definitions ADD COLUMN IF NOT EXISTS cost_embers BIGINT NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE econ.asset_definitions ADD COLUMN IF NOT EXISTS income_embers BIGINT NOT NULL DEFAULT 0;")
            cur.execute("ALTER TABLE econ.asset_definitions ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;")
            cur.execute("ALTER TABLE econ.assets ADD COLUMN IF NOT EXISTS asset_id BIGINT;")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS asset_definitions_asset_type_tier_code_uidx ON econ.asset_definitions (asset_type, tier_code);")

            for asset_type, tier_code, cost_embers, income_embers in ASSET_DEFINITIONS_SEED:
                cur.execute(
                    """
                    INSERT INTO econ.asset_definitions (asset_type, tier_code, display_name, cost_embers, income_embers, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, %s, TRUE, NOW())
                    ON CONFLICT (asset_type, tier_code)
                    DO UPDATE SET display_name = EXCLUDED.display_name,
                                  cost_embers = EXCLUDED.cost_embers,
                                  income_embers = EXCLUDED.income_embers,
                                  is_active = TRUE,
                                  updated_at = NOW();
                    """,
                    (asset_type, tier_code, tier_code, int(cost_embers), int(income_embers)),
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


def transfer_balance_sync(
    guild_id: int,
    source_character_id: int,
    target_character_id: int,
    amount_embers: int,
) -> dict[str, int | bool | str]:
    """Atomically transfer currency between two character balances.

    Returns a dict with ok/source_balance/target_balance or ok=False and a reason.
    Never allows the source balance to go negative.
    """
    amount = int(amount_embers or 0)
    if amount <= 0:
        return {"ok": False, "reason": "amount_must_be_positive"}
    if int(source_character_id) == int(target_character_id):
        return {"ok": False, "reason": "same_character"}

    with db_connect() as conn:
        with conn.cursor() as cur:
            # Ensure both balance rows exist before locking.
            cur.execute(
                """
                INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                VALUES (%s, %s, 0, NOW())
                ON CONFLICT (guild_id, character_id) DO NOTHING;
                """,
                (guild_id, source_character_id),
            )
            cur.execute(
                """
                INSERT INTO econ.balances (guild_id, character_id, balance_embers, updated_at)
                VALUES (%s, %s, 0, NOW())
                ON CONFLICT (guild_id, character_id) DO NOTHING;
                """,
                (guild_id, target_character_id),
            )

            # Lock in a deterministic order to avoid deadlocks.
            first_id, second_id = sorted([int(source_character_id), int(target_character_id)])
            cur.execute(
                """
                SELECT character_id, balance_embers
                FROM econ.balances
                WHERE guild_id = %s AND character_id IN (%s, %s)
                ORDER BY character_id
                FOR UPDATE;
                """,
                (guild_id, first_id, second_id),
            )
            locked = {int(row["character_id"]): int(row["balance_embers"]) for row in cur.fetchall()}
            source_balance = int(locked.get(int(source_character_id), 0))
            target_balance = int(locked.get(int(target_character_id), 0))

            if source_balance < amount:
                conn.rollback()
                return {
                    "ok": False,
                    "reason": "insufficient_funds",
                    "source_balance": source_balance,
                    "target_balance": target_balance,
                }

            new_source = source_balance - amount
            new_target = target_balance + amount
            cur.execute(
                """
                UPDATE econ.balances
                SET balance_embers = %s, updated_at = NOW()
                WHERE guild_id = %s AND character_id = %s;
                """,
                (new_source, guild_id, source_character_id),
            )
            cur.execute(
                """
                UPDATE econ.balances
                SET balance_embers = %s, updated_at = NOW()
                WHERE guild_id = %s AND character_id = %s;
                """,
                (new_target, guild_id, target_character_id),
            )
        conn.commit()

    return {
        "ok": True,
        "source_balance": new_source,
        "target_balance": new_target,
    }


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
    """
    v010 safety guard: intentionally do NOT enqueue character-card refreshes.

    The AlarisBot card refresh path can create a new showcase post when an
    existing alaris_character_posts mapping is missing. Economy-triggered
    refresh requests are therefore disabled until AlarisBot provides an
    edit-only refresh worker that never creates new character posts.
    """
    return None


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
    """Set a character kingdom in both the compatibility table and native Alaris table.

    This intentionally avoids parameterized DO blocks. PostgreSQL can fail to infer
    parameter types inside DO/PLPGSQL bodies, which caused the v008 crash on
    /econ-set-character-kingdom. Direct UPDATE statements are safe here because
    ensure_schema_sync() already creates/patches the needed columns and tables.
    """
    kingdom_text = str(kingdom or "").strip()
    with db_connect() as conn:
        with conn.cursor() as cur:
            # Ensure the compatibility table has the column, then update it.
            cur.execute("ALTER TABLE public.characters ADD COLUMN IF NOT EXISTS kingdom TEXT;")
            cur.execute(
                """
                UPDATE public.characters
                SET kingdom = %s::text, updated_at = NOW()
                WHERE guild_id = %s AND character_id = %s;
                """,
                (kingdom_text, guild_id, character_id),
            )

            # If the native clean Alaris table exists, keep it in sync too.
            cur.execute("SELECT to_regclass('public.alaris_characters') AS table_name;")
            has_alaris = cur.fetchone()
            if has_alaris and has_alaris.get("table_name"):
                cur.execute("ALTER TABLE public.alaris_characters ADD COLUMN IF NOT EXISTS kingdom TEXT;")
                cur.execute(
                    """
                    UPDATE public.alaris_characters
                    SET kingdom = %s::text, updated_at = NOW()
                    WHERE guild_id = %s AND id = %s;
                    """,
                    (kingdom_text, guild_id, character_id),
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
# Asset helpers and approval workflow database functions
# -----------------------------------------------------------------------------


def tier_rank(tier_code: str | None) -> Optional[int]:
    if not tier_code:
        return None
    m = re.match(r"^\(\s*(\d+)\s*\)", str(tier_code).strip())
    if not m:
        m = re.match(r"^(\d+)", str(tier_code).strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def fetch_owned_characters_sync(guild_id: int, user_id: int) -> list[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT character_id, name, kingdom
                FROM public.characters
                WHERE guild_id = %s AND user_id = %s AND archived = FALSE
                ORDER BY name ASC
                LIMIT 25;
                """,
                (guild_id, user_id),
            )
            rows = [dict(r) for r in cur.fetchall()]
            if rows:
                return rows
            cur.execute(
                """
                SELECT id AS character_id, name, kingdom
                FROM public.alaris_characters
                WHERE guild_id = %s AND user_id = %s AND archived = FALSE
                ORDER BY name ASC
                LIMIT 25;
                """,
                (guild_id, user_id),
            )
            return [dict(r) for r in cur.fetchall()]


def fetch_character_by_id_sync(guild_id: int, character_id: int) -> Optional[CharacterRef]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT character_id, user_id, name, kingdom
                FROM public.characters
                WHERE guild_id = %s AND character_id = %s AND archived = FALSE
                LIMIT 1;
                """,
                (guild_id, character_id),
            )
            row = cur.fetchone()
            if row:
                return CharacterRef(guild_id, int(row["character_id"]), int(row["user_id"]), str(row["name"]), str(row["kingdom"]).strip() if row.get("kingdom") else None, "public.characters")
            cur.execute(
                """
                SELECT id AS character_id, user_id, name, kingdom
                FROM public.alaris_characters
                WHERE guild_id = %s AND id = %s AND archived = FALSE
                LIMIT 1;
                """,
                (guild_id, character_id),
            )
            row = cur.fetchone()
            if row:
                return CharacterRef(guild_id, int(row["character_id"]), int(row["user_id"]), str(row["name"]), str(row["kingdom"]).strip() if row.get("kingdom") else None, "public.alaris_characters")
    return None


def fetch_asset_types_sync() -> list[str]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT asset_type
                FROM econ.asset_definitions
                WHERE is_active = TRUE AND asset_type <> 'Noble Title'
                ORDER BY asset_type ASC;
                """
            )
            return [str(r["asset_type"]) for r in cur.fetchall()]


def fetch_tiers_for_type_sync(asset_type: str) -> list[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_type, tier_code, display_name, cost_embers, income_embers
                FROM econ.asset_definitions
                WHERE asset_type = %s AND is_active = TRUE
                ORDER BY tier_code ASC;
                """,
                (asset_type,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    rows.sort(key=lambda r: (tier_rank(r.get("tier_code")) or 999, str(r.get("tier_code") or "")))
    return rows


def fetch_asset_definition_sync(asset_type: str, tier_code: str) -> Optional[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT asset_type, tier_code, display_name, cost_embers, income_embers
                FROM econ.asset_definitions
                WHERE asset_type = %s AND tier_code = %s AND is_active = TRUE
                LIMIT 1;
                """,
                (asset_type, tier_code),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def cumulative_cost_to_tier_sync(asset_type: str, target_tier_code: str) -> Optional[int]:
    target_rank = tier_rank(target_tier_code)
    tiers = fetch_tiers_for_type_sync(asset_type)
    if not tiers:
        return None
    if target_rank is not None:
        total = 0
        found = False
        for row in tiers:
            rk = tier_rank(row.get("tier_code"))
            if rk is not None and rk <= target_rank:
                total += int(row.get("cost_embers") or 0)
                found = True
        if found:
            return total
    for row in tiers:
        if str(row.get("tier_code")) == str(target_tier_code):
            return int(row.get("cost_embers") or 0)
    return None


def incremental_cost_between_tiers_sync(asset_type: str, current_tier_code: str, target_tier_code: str) -> Optional[int]:
    current_rank = tier_rank(current_tier_code)
    target_rank = tier_rank(target_tier_code)
    if target_rank is None:
        return None
    tiers = fetch_tiers_for_type_sync(asset_type)
    if not tiers:
        return None
    if current_rank is not None:
        total = 0
        found = False
        for row in tiers:
            rk = tier_rank(row.get("tier_code"))
            if rk is not None and current_rank < rk <= target_rank:
                total += int(row.get("cost_embers") or 0)
                found = True
        if found:
            return total
    c_target = cumulative_cost_to_tier_sync(asset_type, target_tier_code)
    c_current = cumulative_cost_to_tier_sync(asset_type, current_tier_code)
    if c_target is None or c_current is None:
        return None
    return max(0, int(c_target) - int(c_current))


def fetch_owned_assets_for_upgrade_sync(guild_id: int, character_id: int) -> list[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, asset_type, tier_code, asset_name, kingdom, income_embers
                FROM econ.assets
                WHERE guild_id = %s
                  AND character_id = %s
                  AND asset_type <> 'Noble Title'
                ORDER BY asset_type ASC, asset_name ASC;
                """,
                (guild_id, character_id),
            )
            return [dict(r) for r in cur.fetchall()]


def fetch_asset_by_id_sync(guild_id: int, asset_id: int) -> Optional[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, guild_id, character_id, asset_type, tier_code, asset_name, kingdom, income_embers
                FROM econ.assets
                WHERE guild_id = %s AND id = %s
                LIMIT 1;
                """,
                (guild_id, asset_id),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def create_asset_request_sync(
    guild_id: int,
    request_type: str,
    character_id: int,
    user_id: int,
    asset_type: str,
    to_tier_code: str,
    asset_name: str,
    kingdom: Optional[str],
    cost_embers: int,
    income_embers: int,
    asset_id: Optional[int] = None,
    from_tier_code: Optional[str] = None,
) -> int:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO econ.asset_requests (
                    guild_id, request_type, status, character_id, user_id, asset_id, asset_type,
                    from_tier_code, to_tier_code, asset_name, kingdom, cost_embers, income_embers
                ) VALUES (%s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (guild_id, request_type, character_id, user_id, asset_id, asset_type, from_tier_code, to_tier_code, asset_name, kingdom, int(cost_embers), int(income_embers)),
            )
            request_id = int(cur.fetchone()["id"])
        conn.commit()
    return request_id


def update_asset_request_message_sync(guild_id: int, request_id: int, channel_id: int, message_id: int) -> None:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE econ.asset_requests
                SET request_channel_id = %s, request_message_id = %s, updated_at = NOW()
                WHERE guild_id = %s AND id = %s;
                """,
                (channel_id, message_id, guild_id, request_id),
            )
        conn.commit()


def fetch_asset_request_sync(guild_id: int, request_id: int) -> Optional[dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.*, c.name AS character_name
                FROM econ.asset_requests r
                LEFT JOIN public.characters c ON c.guild_id = r.guild_id AND c.character_id = r.character_id
                WHERE r.guild_id = %s AND r.id = %s
                LIMIT 1;
                """,
                (guild_id, request_id),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
    return None


def approve_asset_request_sync(guild_id: int, request_id: int, staff_user_id: int) -> dict[str, Any]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM econ.asset_requests
                WHERE guild_id = %s AND id = %s
                FOR UPDATE;
                """,
                (guild_id, request_id),
            )
            req = cur.fetchone()
            if not req:
                conn.rollback()
                return {"ok": False, "reason": "request_not_found"}
            req = dict(req)
            if req.get("status") != "pending":
                conn.rollback()
                return {"ok": False, "reason": "not_pending", "status": req.get("status")}

            character_id = int(req["character_id"])
            cost = int(req.get("cost_embers") or 0)
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
                SELECT balance_embers
                FROM econ.balances
                WHERE guild_id = %s AND character_id = %s
                FOR UPDATE;
                """,
                (guild_id, character_id),
            )
            bal_row = cur.fetchone()
            balance = int(bal_row["balance_embers"] if bal_row else 0)
            if balance < cost:
                conn.rollback()
                return {"ok": False, "reason": "insufficient_funds", "balance": balance, "cost": cost}

            if req["request_type"] == "purchase":
                cur.execute(
                    """
                    SELECT 1
                    FROM econ.assets
                    WHERE guild_id = %s AND character_id = %s AND asset_type = %s AND asset_name = %s
                    LIMIT 1;
                    """,
                    (guild_id, character_id, req["asset_type"], req["asset_name"]),
                )
                if cur.fetchone():
                    conn.rollback()
                    return {"ok": False, "reason": "duplicate_asset"}
                cur.execute(
                    """
                    INSERT INTO econ.assets (
                        guild_id, character_id, asset_type, tier_code, asset_name, kingdom,
                        income_embers, created_by_user_id, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING id;
                    """,
                    (guild_id, character_id, req["asset_type"], req["to_tier_code"], req["asset_name"], req.get("kingdom"), int(req.get("income_embers") or 0), staff_user_id),
                )
                asset_id = int(cur.fetchone()["id"])
            elif req["request_type"] == "upgrade":
                asset_id = int(req.get("asset_id") or 0)
                cur.execute(
                    """
                    SELECT id, asset_type, tier_code, asset_name
                    FROM econ.assets
                    WHERE guild_id = %s AND id = %s AND character_id = %s
                    FOR UPDATE;
                    """,
                    (guild_id, asset_id, character_id),
                )
                asset = cur.fetchone()
                if not asset:
                    conn.rollback()
                    return {"ok": False, "reason": "asset_not_found"}
                if str(asset["asset_type"]) != str(req["asset_type"]):
                    conn.rollback()
                    return {"ok": False, "reason": "asset_type_mismatch"}
                cur_rank = tier_rank(str(asset["tier_code"]))
                tgt_rank = tier_rank(str(req["to_tier_code"]))
                if cur_rank is not None and tgt_rank is not None and tgt_rank <= cur_rank:
                    conn.rollback()
                    return {"ok": False, "reason": "invalid_upgrade_target"}
                cur.execute(
                    """
                    UPDATE econ.assets
                    SET tier_code = %s,
                        kingdom = COALESCE(NULLIF(kingdom, ''), %s),
                        income_embers = %s,
                        updated_at = NOW()
                    WHERE guild_id = %s AND id = %s;
                    """,
                    (req["to_tier_code"], req.get("kingdom"), int(req.get("income_embers") or 0), guild_id, asset_id),
                )
            else:
                conn.rollback()
                return {"ok": False, "reason": "unknown_request_type"}

            new_balance = balance - cost
            cur.execute(
                """
                UPDATE econ.balances
                SET balance_embers = %s, updated_at = NOW()
                WHERE guild_id = %s AND character_id = %s;
                """,
                (new_balance, guild_id, character_id),
            )
            cur.execute(
                """
                UPDATE econ.asset_requests
                SET status = 'approved', decided_by_user_id = %s, decided_at = NOW(), updated_at = NOW()
                WHERE guild_id = %s AND id = %s;
                """,
                (staff_user_id, guild_id, request_id),
            )
            cur.execute(
                """
                INSERT INTO econ.transactions (guild_id, character_id, actor_user_id, action, amount_embers, details_json)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb);
                """,
                (
                    guild_id,
                    character_id,
                    staff_user_id,
                    f"asset_{req['request_type']}_approved",
                    -cost,
                    json.dumps({"request_id": request_id, "asset_id": asset_id, "asset_type": req["asset_type"], "to_tier_code": req["to_tier_code"], "asset_name": req["asset_name"]}),
                ),
            )
            # v010 safety: do not enqueue Alaris character-card refreshes here.
            # Asset data is committed in econ.assets; AlarisBot will receive an
            # edit-only refresh integration in a later version.
        conn.commit()
    return {"ok": True, "request": req, "asset_id": asset_id, "new_balance": new_balance}


def deny_asset_request_sync(guild_id: int, request_id: int, staff_user_id: int, reason: str = "") -> dict[str, Any]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM econ.asset_requests
                WHERE guild_id = %s AND id = %s
                FOR UPDATE;
                """,
                (guild_id, request_id),
            )
            req = cur.fetchone()
            if not req:
                conn.rollback()
                return {"ok": False, "reason": "request_not_found"}
            req = dict(req)
            if req.get("status") != "pending":
                conn.rollback()
                return {"ok": False, "reason": "not_pending", "status": req.get("status")}
            cur.execute(
                """
                UPDATE econ.asset_requests
                SET status = 'denied', decided_by_user_id = %s, decision_note = %s, decided_at = NOW(), updated_at = NOW()
                WHERE guild_id = %s AND id = %s;
                """,
                (staff_user_id, reason, guild_id, request_id),
            )
            cur.execute(
                """
                INSERT INTO econ.transactions (guild_id, character_id, actor_user_id, action, amount_embers, details_json)
                VALUES (%s, %s, %s, 'asset_request_denied', 0, %s::jsonb);
                """,
                (guild_id, int(req["character_id"]), staff_user_id, json.dumps({"request_id": request_id, "reason": reason, "asset_type": req.get("asset_type"), "asset_name": req.get("asset_name")})),
            )
        conn.commit()
    return {"ok": True, "request": req}


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
    """Best-effort audit logging.

    Economy commands must never fail only because the configured log channel is
    missing, private to the bot, or temporarily unavailable. The database action
    should still complete and the command should still return a useful response.
    """
    if not ECON_LOG_CHANNEL_ID:
        return
    try:
        channel = client.get_channel(int(ECON_LOG_CHANNEL_ID))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(ECON_LOG_CHANNEL_ID))
            except (discord.Forbidden, discord.NotFound) as exc:
                print(f"[warn] Economy log channel unavailable ({ECON_LOG_CHANNEL_ID}): {exc}")
                return
            except Exception as exc:
                print(f"[warn] Could not fetch economy log channel ({ECON_LOG_CHANNEL_ID}): {exc}")
                return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            print(f"[warn] Economy log target is not a text channel/thread: {ECON_LOG_CHANNEL_ID}")
            return
        text = f"**ECON LOG:** `{action}`\n" + "\n".join(lines)
        await channel.send(text[:1900], allowed_mentions=discord.AllowedMentions.none())
    except discord.Forbidden as exc:
        print(f"[warn] Missing access/send permission for economy log channel {ECON_LOG_CHANNEL_ID}: {exc}")
    except discord.HTTPException as exc:
        print(f"[warn] Failed to send economy log message to {ECON_LOG_CHANNEL_ID}: {exc}")
    except Exception as exc:
        print(f"[warn] Unexpected economy log failure for {ECON_LOG_CHANNEL_ID}: {exc}")


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
        "• `/econ-transfer` - transfer currency from one of your characters to another character",
        "• `/purchase-asset` - request to purchase an asset, routed to staff approval",
        "• `/upgrade-asset` - request to upgrade an owned asset, routed to staff approval",
        "• `/treasuries` - view kingdom treasury/tax status",
        "",
        "**Staff**" if staff else "**Staff commands hidden**",
    ]
    if staff:
        lines.extend(
            [
                "• `/econ-set-balance` - set a character balance exactly",
                "• `/econ-adjust` - adjust a character balance by an amount",
                "• `/econ-payout` - staff payout for quests, combat, events, or corrections",
                "• `/econ-grant-all` - grant all active characters currency",
                "• `/econ-set-character-kingdom` - associate a character with a kingdom/land",
                "• `/econ-set-kingdom-tax` - set a kingdom tax rate",
                "• `/econ-set-kingdom-treasury` - set a kingdom treasury exactly",
                "• `/econ-schema-status` - confirm economy schema/bootstrap status",
                "• `/econ-sync-characters` - backfill the economy character mirror from Alaris",
                "• `/econ-asset-request-action` - fallback approve/deny for pending asset requests",
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


@tree.command(name="econ-transfer", description="Transfer currency from one of your characters to another character.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    source_character="One of your characters sending the currency",
    target_character="The character receiving the currency",
    amount_embers="Amount to transfer in Embers/base units",
)
@app_commands.autocomplete(source_character=character_autocomplete, target_character=character_autocomplete)
async def econ_transfer(interaction: discord.Interaction, source_character: str, target_character: str, amount_embers: int):
    await interaction.response.defer(ephemeral=True)
    if amount_embers <= 0:
        await interaction.followup.send("Transfer amount must be greater than 0 Embers.", ephemeral=True)
        return

    source_ref = await resolve_character_or_reply(interaction, source_character)
    if not source_ref:
        return
    target_ref = await resolve_character_or_reply(interaction, target_character)
    if not target_ref:
        return

    if int(source_ref.user_id) != int(interaction.user.id):
        await interaction.followup.send("You may only transfer currency from a character you own.", ephemeral=True)
        return
    if int(source_ref.character_id) == int(target_ref.character_id):
        await interaction.followup.send("Source and target character must be different.", ephemeral=True)
        return

    result = await run_db(
        transfer_balance_sync,
        source_ref.guild_id,
        source_ref.character_id,
        target_ref.character_id,
        int(amount_embers),
    )

    if not result.get("ok"):
        reason = result.get("reason")
        if reason == "insufficient_funds":
            await interaction.followup.send(
                f"Insufficient funds. **{clean_text(source_ref.name)}** has **{format_currency(int(result.get('source_balance', 0)))}**.",
                ephemeral=True,
            )
            return
        await interaction.followup.send("Transfer could not be completed.", ephemeral=True)
        return

    details = {
        "source_character_id": source_ref.character_id,
        "source_character": source_ref.name,
        "target_character_id": target_ref.character_id,
        "target_character": target_ref.name,
        "source_new_balance": int(result["source_balance"]),
        "target_new_balance": int(result["target_balance"]),
    }
    await run_db(log_transaction_sync, source_ref.guild_id, source_ref.character_id, interaction.user.id, "transfer_out", -int(amount_embers), details)
    await run_db(log_transaction_sync, target_ref.guild_id, target_ref.character_id, interaction.user.id, "transfer_in", int(amount_embers), details)
    await run_db(enqueue_character_refresh_sync, source_ref.guild_id, source_ref.character_id, "economy_transfer_out")
    await run_db(enqueue_character_refresh_sync, target_ref.guild_id, target_ref.character_id, "economy_transfer_in")

    await log_to_channel(
        "transfer",
        [
            f"From: **{clean_text(source_ref.name)}**",
            f"To: **{clean_text(target_ref.name)}**",
            f"Amount: **{format_currency(int(amount_embers))}**",
            f"Performed by: **{clean_text(getattr(interaction.user, 'display_name', interaction.user.name))}** (`{interaction.user.id}`)",
            f"Source new balance: **{format_currency(int(result['source_balance']))}**",
            f"Target new balance: **{format_currency(int(result['target_balance']))}**",
        ],
    )

    await interaction.followup.send(
        "\n".join(
            [
                f"Transferred **{format_currency(int(amount_embers))}** from **{clean_text(source_ref.name)}** to **{clean_text(target_ref.name)}**.",
                f"{clean_text(source_ref.name)} balance: **{format_currency(int(result['source_balance']))}**",
                f"{clean_text(target_ref.name)} balance: **{format_currency(int(result['target_balance']))}**",
            ]
        ),
        ephemeral=True,
    )


@tree.command(name="econ-payout", description="Staff: pay a character for quests, combat, events, or other rewards.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.describe(
    character="Character receiving the payout",
    amount_embers="Payout amount in Embers/base units",
    payout_type="Short payout category, such as combat, quest, event, or other",
    reason="Brief reason for the payout",
)
@app_commands.autocomplete(character=character_autocomplete)
async def econ_payout(interaction: discord.Interaction, character: str, amount_embers: int, payout_type: str = "other", reason: str = ""):
    await interaction.response.defer(ephemeral=True)
    if amount_embers <= 0:
        await interaction.followup.send("Payout amount must be greater than 0 Embers.", ephemeral=True)
        return
    ref = await resolve_character_or_reply(interaction, character)
    if not ref:
        return

    payout_type_clean = clean_text(payout_type or "other")[:40] or "other"
    reason_clean = clean_text(reason or "")[:300]

    new_balance = await run_db(adjust_balance_sync, ref.guild_id, ref.character_id, int(amount_embers))
    await run_db(
        log_transaction_sync,
        ref.guild_id,
        ref.character_id,
        interaction.user.id,
        f"payout_{payout_type_clean.lower().replace(' ', '_')}",
        int(amount_embers),
        {"character": ref.name, "payout_type": payout_type_clean, "reason": reason_clean},
    )
    await run_db(enqueue_character_refresh_sync, ref.guild_id, ref.character_id, "economy_payout")
    await log_to_channel(
        "payout",
        [
            f"Character: **{clean_text(ref.name)}**",
            f"Type: **{payout_type_clean}**",
            f"Amount: **{format_currency(int(amount_embers))}**",
            f"Reason: {reason_clean or '—'}",
            f"Performed by: **{clean_text(getattr(interaction.user, 'display_name', interaction.user.name))}** (`{interaction.user.id}`)",
            f"New balance: **{format_currency(new_balance)}**",
        ],
    )
    await interaction.followup.send(
        f"Paid **{format_currency(int(amount_embers))}** to **{clean_text(ref.name)}**. New balance: **{format_currency(new_balance)}**.",
        ephemeral=True,
    )


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
                    # v010 safety: do not enqueue Alaris character-card refreshes here.
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



# -----------------------------------------------------------------------------
# Asset request views and commands
# -----------------------------------------------------------------------------


def build_asset_request_embed(req: dict[str, Any], character_name: str | None = None) -> discord.Embed:
    status = clean_text(req.get("status") or "pending").title()
    request_type = clean_text(req.get("request_type") or "asset")
    title = f"Asset {request_type.title()} Request #{req.get('id')} — {status}"
    color = discord.Color.gold() if status == "Pending" else discord.Color.green() if status == "Approved" else discord.Color.red()
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Character", value=f"**{clean_text(character_name or req.get('character_name') or req.get('character_id'))}**", inline=False)
    embed.add_field(name="Requested By", value=f"<@{int(req.get('user_id') or 0)}>", inline=True)
    embed.add_field(name="Asset Type", value=clean_text(req.get("asset_type")), inline=True)
    if req.get("request_type") == "upgrade":
        embed.add_field(name="Current Tier", value=clean_text(req.get("from_tier_code")), inline=True)
        embed.add_field(name="Target Tier", value=clean_text(req.get("to_tier_code")), inline=True)
    else:
        embed.add_field(name="Tier", value=clean_text(req.get("to_tier_code")), inline=True)
    embed.add_field(name="Asset Name", value=clean_text(req.get("asset_name")), inline=False)
    embed.add_field(name="Kingdom/Land", value=clean_text(req.get("kingdom")) or "—", inline=True)
    embed.add_field(name="Cost", value=f"**{format_currency(int(req.get('cost_embers') or 0))}**", inline=True)
    income = int(req.get("income_embers") or 0)
    embed.add_field(name="Daily Income", value=format_currency(income, show_base_total=False), inline=True)
    embed.set_footer(text="Staff should approve only after reviewing the request. Balance is re-checked at approval.")
    return embed


class AssetApprovalView(discord.ui.View):
    def __init__(self, request_id: int):
        super().__init__(timeout=None)
        self.request_id = int(request_id)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(interaction):
            await interaction.response.send_message("Only staff may approve economy asset requests.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = int(interaction.guild_id or GUILD_ID)
        result = await run_db(approve_asset_request_sync, guild_id, self.request_id, interaction.user.id)
        if not result.get("ok"):
            reason = result.get("reason")
            if reason == "insufficient_funds":
                await interaction.followup.send(
                    f"Cannot approve. Character balance is **{format_currency(int(result.get('balance', 0)))}**, but cost is **{format_currency(int(result.get('cost', 0)))}**.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(f"Cannot approve request: `{clean_text(reason)}`.", ephemeral=True)
            return

        req = result["request"]
        ref = await run_db(fetch_character_by_id_sync, guild_id, int(req["character_id"]))
        await log_to_channel(
            f"asset_{req['request_type']}_approved",
            [
                f"Request ID: **{self.request_id}**",
                f"Character: **{clean_text(ref.name if ref else req.get('character_id'))}**",
                f"Asset: **{clean_text(req['asset_name'])}** — {clean_text(req['asset_type'])}",
                f"Tier: **{clean_text(req['to_tier_code'])}**",
                f"Cost: **{format_currency(int(req['cost_embers']))}**",
                f"Approved by: **{clean_text(getattr(interaction.user, 'display_name', interaction.user.name))}** (`{interaction.user.id}`)",
                f"New balance: **{format_currency(int(result['new_balance']))}**",
            ],
        )
        fresh = await run_db(fetch_asset_request_sync, guild_id, self.request_id)
        if fresh and interaction.message:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(embed=build_asset_request_embed(fresh, ref.name if ref else None), view=self)
        await interaction.followup.send(f"Approved asset request #{self.request_id}.", ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_staff(interaction):
            await interaction.response.send_message("Only staff may deny economy asset requests.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = int(interaction.guild_id or GUILD_ID)
        result = await run_db(deny_asset_request_sync, guild_id, self.request_id, interaction.user.id, "Denied by staff button")
        if not result.get("ok"):
            await interaction.followup.send(f"Cannot deny request: `{clean_text(result.get('reason'))}`.", ephemeral=True)
            return
        req = result["request"]
        ref = await run_db(fetch_character_by_id_sync, guild_id, int(req["character_id"]))
        await log_to_channel(
            "asset_request_denied",
            [
                f"Request ID: **{self.request_id}**",
                f"Character: **{clean_text(ref.name if ref else req.get('character_id'))}**",
                f"Asset: **{clean_text(req['asset_name'])}** — {clean_text(req['asset_type'])}",
                f"Denied by: **{clean_text(getattr(interaction.user, 'display_name', interaction.user.name))}** (`{interaction.user.id}`)",
            ],
        )
        fresh = await run_db(fetch_asset_request_sync, guild_id, self.request_id)
        if fresh and interaction.message:
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(embed=build_asset_request_embed(fresh, ref.name if ref else None), view=self)
        await interaction.followup.send(f"Denied asset request #{self.request_id}.", ephemeral=True)


async def post_asset_request_to_staff_channel(guild_id: int, request_id: int, character_name: str):
    if not ASSET_REQUEST_CHANNEL_ID:
        return None
    req = await run_db(fetch_asset_request_sync, guild_id, request_id)
    if not req:
        return None
    channel = client.get_channel(int(ASSET_REQUEST_CHANNEL_ID))
    if channel is None:
        try:
            channel = await client.fetch_channel(int(ASSET_REQUEST_CHANNEL_ID))
        except Exception:
            channel = None
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return None
    msg = await channel.send(embed=build_asset_request_embed(req, character_name), view=AssetApprovalView(request_id), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
    await run_db(update_asset_request_message_sync, guild_id, request_id, channel.id, msg.id)
    return msg


class PurchaseAssetNameModal(discord.ui.Modal, title="Name This Asset"):
    asset_name = discord.ui.TextInput(label="Asset Name", placeholder="Example: The Silver Stag", max_length=80)

    def __init__(self, character_id: int, asset_type: str, tier_code: str):
        super().__init__()
        self.character_id = int(character_id)
        self.asset_type = str(asset_type)
        self.tier_code = str(tier_code)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = int(interaction.guild_id or GUILD_ID)
        ref = await run_db(fetch_character_by_id_sync, guild_id, self.character_id)
        if not ref:
            await interaction.followup.send("That character no longer exists.", ephemeral=True)
            return
        if int(ref.user_id) != int(interaction.user.id):
            await interaction.followup.send("You may only purchase assets for characters you own.", ephemeral=True)
            return
        if not ref.kingdom:
            await interaction.followup.send("This character has no kingdom/land assigned yet. Ask staff to set one before purchasing assets.", ephemeral=True)
            return
        asset_def = await run_db(fetch_asset_definition_sync, self.asset_type, self.tier_code)
        if not asset_def:
            await interaction.followup.send("That asset tier is no longer available.", ephemeral=True)
            return
        cost = await run_db(cumulative_cost_to_tier_sync, self.asset_type, self.tier_code)
        if cost is None or cost <= 0:
            await interaction.followup.send("Unable to calculate the purchase cost for that asset.", ephemeral=True)
            return
        balance = await run_db(get_balance_sync, guild_id, ref.character_id)
        if balance < int(cost):
            await interaction.followup.send(f"Insufficient funds. Balance: **{format_currency(balance)}**. Cost: **{format_currency(int(cost))}**.", ephemeral=True)
            return
        clean_name = clean_text(str(self.asset_name.value))[:80]
        if not clean_name:
            await interaction.followup.send("Asset name cannot be blank.", ephemeral=True)
            return
        request_id = await run_db(
            create_asset_request_sync,
            guild_id,
            "purchase",
            ref.character_id,
            interaction.user.id,
            self.asset_type,
            self.tier_code,
            clean_name,
            ref.kingdom,
            int(cost),
            int(asset_def.get("income_embers") or 0),
            None,
            None,
        )
        await post_asset_request_to_staff_channel(guild_id, request_id, ref.name)
        await log_to_channel("asset_purchase_requested", [f"Request ID: **{request_id}**", f"Character: **{clean_text(ref.name)}**", f"Asset: **{clean_name}** — {self.asset_type}", f"Tier: **{self.tier_code}**", f"Cost: **{format_currency(int(cost))}**"])
        await interaction.followup.send(f"Purchase request #{request_id} submitted for staff approval.", ephemeral=True)


class PurchaseAssetView(discord.ui.View):
    def __init__(self, owner_id: int, characters: list[dict[str, Any]], asset_types: list[str]):
        super().__init__(timeout=900)
        self.owner_id = int(owner_id)
        self.characters = characters
        self.asset_types = asset_types
        self.character_id: Optional[int] = None
        self.asset_type: Optional[str] = None
        self.tier_code: Optional[str] = None
        self.refresh_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("Only the player who opened this purchase flow may use it.", ephemeral=True)
            return False
        return True

    def refresh_items(self):
        self.clear_items()
        char_options = []
        for c in self.characters[:25]:
            label = clean_text(c.get("name"))[:100]
            desc = clean_text(c.get("kingdom"))[:100] or "No kingdom assigned"
            char_options.append(discord.SelectOption(label=label, value=str(c["character_id"]), description=desc, default=(self.character_id == int(c["character_id"]))))
        if char_options:
            self.add_item(PurchaseCharacterSelect(char_options))
        type_options = [discord.SelectOption(label=t[:100], value=t[:100], default=(self.asset_type == t)) for t in self.asset_types[:25]]
        if type_options:
            self.add_item(PurchaseAssetTypeSelect(type_options))
        if self.asset_type:
            # Placeholder tier selector is populated asynchronously by callback response rebuild.
            pass
        submit = discord.ui.Button(label="Continue", style=discord.ButtonStyle.success, disabled=not (self.character_id and self.asset_type and self.tier_code))
        async def submit_cb(interaction: discord.Interaction):
            if not (self.character_id and self.asset_type and self.tier_code):
                await interaction.response.send_message("Choose a character, asset type, and tier first.", ephemeral=True)
                return
            await interaction.response.send_modal(PurchaseAssetNameModal(self.character_id, self.asset_type, self.tier_code))
        submit.callback = submit_cb
        self.add_item(submit)

    async def rebuild(self, interaction: discord.Interaction, status: str = ""):
        self.refresh_items()
        if self.asset_type:
            tiers = await run_db(fetch_tiers_for_type_sync, self.asset_type)
            tier_options = []
            for t in tiers[:25]:
                cost = await run_db(cumulative_cost_to_tier_sync, self.asset_type, str(t["tier_code"]))
                desc = f"Cost: {format_currency(int(cost or 0), show_base_total=False)}"
                income = int(t.get("income_embers") or 0)
                if income:
                    desc += f" | Income: {format_currency(income, show_base_total=False)}/day"
                tier_options.append(discord.SelectOption(label=str(t["tier_code"])[:100], value=str(t["tier_code"])[:100], description=desc[:100], default=(self.tier_code == str(t["tier_code"]))))
            if tier_options:
                # Insert before continue button by rebuilding manually.
                old_submit = self.children[-1]
                self.remove_item(old_submit)
                self.add_item(PurchaseTierSelect(tier_options))
                self.add_item(old_submit)
        embed = discord.Embed(title="Purchase Asset", description="Choose one of your characters, an asset type, and a tier name. The bot will check your balance, then send the request to staff for approval.", color=discord.Color.gold())
        if status:
            embed.add_field(name="Status", value=status, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)


class PurchaseCharacterSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose one of your characters", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, PurchaseAssetView):
            view.character_id = int(self.values[0])
            await view.rebuild(interaction, "Character selected.")


class PurchaseAssetTypeSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose asset type", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, PurchaseAssetView):
            view.asset_type = str(self.values[0])
            view.tier_code = None
            await view.rebuild(interaction, "Asset type selected. Now choose a tier name.")


class PurchaseTierSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose tier name", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, PurchaseAssetView):
            view.tier_code = str(self.values[0])
            await view.rebuild(interaction, "Tier selected. Press Continue to name the asset and submit.")


@tree.command(name="purchase-asset", description="Request to purchase an asset for one of your characters.", guild=discord.Object(id=GUILD_ID))
async def purchase_asset(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = int(interaction.guild_id or GUILD_ID)
    characters = await run_db(fetch_owned_characters_sync, guild_id, interaction.user.id)
    if not characters:
        await interaction.followup.send("You do not have any active synced Alaris characters.", ephemeral=True)
        return
    asset_types = await run_db(fetch_asset_types_sync)
    if not asset_types:
        await interaction.followup.send("No asset definitions are available yet. Ask staff to check `/econ-schema-status` after redeploy.", ephemeral=True)
        return
    view = PurchaseAssetView(interaction.user.id, characters, asset_types)
    embed = discord.Embed(title="Purchase Asset", description="Choose one of your characters, an asset type, and a tier name. After you name the asset, staff will receive an approval request.", color=discord.Color.gold())
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class UpgradeAssetView(discord.ui.View):
    def __init__(self, owner_id: int, characters: list[dict[str, Any]]):
        super().__init__(timeout=900)
        self.owner_id = int(owner_id)
        self.characters = characters
        self.character_id: Optional[int] = None
        self.asset_id: Optional[int] = None
        self.target_tier: Optional[str] = None
        self.owned_assets: list[dict[str, Any]] = []
        self.refresh_base_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("Only the player who opened this upgrade flow may use it.", ephemeral=True)
            return False
        return True

    def refresh_base_items(self):
        self.clear_items()
        char_options = [discord.SelectOption(label=clean_text(c.get("name"))[:100], value=str(c["character_id"]), description=(clean_text(c.get("kingdom")) or "No kingdom assigned")[:100], default=(self.character_id == int(c["character_id"]))) for c in self.characters[:25]]
        if char_options:
            self.add_item(UpgradeCharacterSelect(char_options))
        submit = discord.ui.Button(label="Submit Upgrade Request", style=discord.ButtonStyle.success, disabled=not (self.character_id and self.asset_id and self.target_tier))
        async def submit_cb(interaction: discord.Interaction):
            await self.submit_request(interaction)
        submit.callback = submit_cb
        self.add_item(submit)

    async def rebuild(self, interaction: discord.Interaction, status: str = ""):
        self.refresh_base_items()
        if self.character_id:
            self.owned_assets = await run_db(fetch_owned_assets_for_upgrade_sync, int(interaction.guild_id or GUILD_ID), self.character_id)
            if self.owned_assets:
                asset_options = []
                for a in self.owned_assets[:25]:
                    label = f"{a['asset_name']} — {a['asset_type']}"
                    asset_options.append(discord.SelectOption(label=clean_text(label)[:100], value=str(a["id"]), description=clean_text(a.get("tier_code"))[:100], default=(self.asset_id == int(a["id"]))))
                old_submit = self.children[-1]
                self.remove_item(old_submit)
                self.add_item(UpgradeOwnedAssetSelect(asset_options))
                if self.asset_id:
                    selected = next((a for a in self.owned_assets if int(a["id"]) == int(self.asset_id)), None)
                    if selected:
                        tiers = await run_db(fetch_tiers_for_type_sync, selected["asset_type"])
                        cur_rank = tier_rank(selected.get("tier_code"))
                        tier_options = []
                        for t in tiers:
                            tr = tier_rank(t.get("tier_code"))
                            if cur_rank is not None and tr is not None and tr <= cur_rank:
                                continue
                            cost = await run_db(incremental_cost_between_tiers_sync, selected["asset_type"], selected["tier_code"], str(t["tier_code"]))
                            desc = f"Upgrade cost: {format_currency(int(cost or 0), show_base_total=False)}"
                            tier_options.append(discord.SelectOption(label=str(t["tier_code"])[:100], value=str(t["tier_code"])[:100], description=desc[:100], default=(self.target_tier == str(t["tier_code"]))))
                        if tier_options:
                            self.add_item(UpgradeTargetTierSelect(tier_options[:25]))
                self.add_item(old_submit)
        embed = discord.Embed(title="Upgrade Asset", description="Choose one of your characters, then one owned asset, then the higher tier name you want. Staff will receive an approval request.", color=discord.Color.gold())
        if status:
            embed.add_field(name="Status", value=status, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def submit_request(self, interaction: discord.Interaction):
        if not (self.character_id and self.asset_id and self.target_tier):
            await interaction.response.send_message("Choose a character, asset, and target tier first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = int(interaction.guild_id or GUILD_ID)
        ref = await run_db(fetch_character_by_id_sync, guild_id, self.character_id)
        if not ref or int(ref.user_id) != int(interaction.user.id):
            await interaction.followup.send("You may only upgrade assets for characters you own.", ephemeral=True)
            return
        asset = await run_db(fetch_asset_by_id_sync, guild_id, self.asset_id)
        if not asset or int(asset["character_id"]) != int(ref.character_id):
            await interaction.followup.send("That asset no longer exists on this character.", ephemeral=True)
            return
        cost = await run_db(incremental_cost_between_tiers_sync, asset["asset_type"], asset["tier_code"], self.target_tier)
        if cost is None or cost <= 0:
            await interaction.followup.send("Unable to calculate the upgrade cost for that target tier.", ephemeral=True)
            return
        balance = await run_db(get_balance_sync, guild_id, ref.character_id)
        if balance < int(cost):
            await interaction.followup.send(f"Insufficient funds. Balance: **{format_currency(balance)}**. Upgrade cost: **{format_currency(int(cost))}**.", ephemeral=True)
            return
        target_def = await run_db(fetch_asset_definition_sync, asset["asset_type"], self.target_tier)
        if not target_def:
            await interaction.followup.send("That target tier is no longer available.", ephemeral=True)
            return
        request_id = await run_db(
            create_asset_request_sync,
            guild_id,
            "upgrade",
            ref.character_id,
            interaction.user.id,
            asset["asset_type"],
            self.target_tier,
            asset["asset_name"],
            asset.get("kingdom") or ref.kingdom,
            int(cost),
            int(target_def.get("income_embers") or 0),
            int(asset["id"]),
            asset.get("tier_code"),
        )
        await post_asset_request_to_staff_channel(guild_id, request_id, ref.name)
        await log_to_channel("asset_upgrade_requested", [f"Request ID: **{request_id}**", f"Character: **{clean_text(ref.name)}**", f"Asset: **{clean_text(asset['asset_name'])}** — {clean_text(asset['asset_type'])}", f"From: **{clean_text(asset['tier_code'])}**", f"To: **{clean_text(self.target_tier)}**", f"Cost: **{format_currency(int(cost))}**"])
        await interaction.followup.send(f"Upgrade request #{request_id} submitted for staff approval.", ephemeral=True)


class UpgradeCharacterSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose one of your characters", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, UpgradeAssetView):
            view.character_id = int(self.values[0])
            view.asset_id = None
            view.target_tier = None
            await view.rebuild(interaction, "Character selected. Now choose an owned asset.")


class UpgradeOwnedAssetSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose owned asset", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, UpgradeAssetView):
            view.asset_id = int(self.values[0])
            view.target_tier = None
            await view.rebuild(interaction, "Asset selected. Now choose the target tier name.")


class UpgradeTargetTierSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose target tier name", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if isinstance(view, UpgradeAssetView):
            view.target_tier = str(self.values[0])
            await view.rebuild(interaction, "Target tier selected. Press Submit Upgrade Request.")


@tree.command(name="upgrade-asset", description="Request to upgrade one of your character's assets.", guild=discord.Object(id=GUILD_ID))
async def upgrade_asset(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild_id = int(interaction.guild_id or GUILD_ID)
    characters = await run_db(fetch_owned_characters_sync, guild_id, interaction.user.id)
    if not characters:
        await interaction.followup.send("You do not have any active synced Alaris characters.", ephemeral=True)
        return
    view = UpgradeAssetView(interaction.user.id, characters)
    embed = discord.Embed(title="Upgrade Asset", description="Choose one of your characters, then an owned asset, then the higher tier name you want. Staff will receive an approval request.", color=discord.Color.gold())
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


@tree.command(name="econ-asset-request-action", description="Staff fallback: approve or deny a pending asset request by ID.", guild=discord.Object(id=GUILD_ID))
@staff_only()
@app_commands.choices(action=[app_commands.Choice(name="Approve", value="approve"), app_commands.Choice(name="Deny", value="deny")])
async def econ_asset_request_action(interaction: discord.Interaction, request_id: int, action: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    guild_id = int(interaction.guild_id or GUILD_ID)
    if action.value == "approve":
        result = await run_db(approve_asset_request_sync, guild_id, int(request_id), interaction.user.id)
    else:
        result = await run_db(deny_asset_request_sync, guild_id, int(request_id), interaction.user.id, "Denied by fallback command")
    if not result.get("ok"):
        await interaction.followup.send(f"Could not apply action: `{clean_text(result.get('reason'))}`.", ephemeral=True)
        return
    await interaction.followup.send(f"Request #{request_id} marked `{action.value}`.", ephemeral=True)


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
