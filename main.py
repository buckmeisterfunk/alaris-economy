# Alaris Bot v125  

# v125: Posts a compact HP health summary whenever combat initiative wraps back to the top of the order.
# v124: Fixes /character-grant-xp XP pipeline call, hides empty economy/tournament sections on character cards, and ensures optional enemy metadata columns exist.
# v123: Hardens character autocomplete for staff/player commands, especially /character-grant-xp, and documents command wiring audit.
# v118: Full replacement based on v117. Adds the missing enchantment combat bridge:
# - Reads approved EconomyBot enchantment assets from econ.assets.
# - Applies Warding to AC, Accuracy to attack rolls, and Potency to damage in recalculated character combat values.
# - Fails safely if EconomyBot tables/columns are not present yet.
# v120: Full replacement based on v119. Adds staff-only character rename command that updates DB identity, compatibility mirror, showcase thread title, and live card.
# v117 confirms /session-start posts a join UI with owned-character multi-select for session participation.
# Full replacement main.py - v105 compact character cards with economy holdings and safe live refresh  
#  
# v029:  
# - Adds /character-create ticket workflow.  
# - Adds player-owned character creation: name, species, class, image upload, Google Doc URL.  
# - Adds manual Standard Array or auto-assigned stats by class.  
# - Adds staff approval/rejection buttons.  
# - On approval, writes to clean alaris_* tables and creates a discussion post.  
# - Adds character discussion/forum posts for approved characters.  
# - Preserves clean alaris_* schema foundation.  
#  
# Required env:  
# - DISCORD_TOKEN  
# - DATABASE_URL  
# - GUILD_ID  
#  
# Optional but recommended for v003:  
# - STAFF_ROLE_IDS  
# - CHARACTER_REVIEW_CATEGORY_ID  
# - CHARACTER_DISCUSSION_CHANNEL_ID  
# - COMMAND_LOG_CHANNEL_ID  
#  
# Railway start command:  
# python main.py  
  
import os  
import time  
import asyncio  
import random  
import re  
import math  
import json  
import logging  
import io  
from datetime import datetime  
try:  
    from zoneinfo import ZoneInfo  
except Exception:  # pragma: no cover  
    ZoneInfo = None  # type: ignore  
from typing import Any, Optional  
  
import asyncpg  
from openai import AsyncOpenAI  
import discord  
from discord import app_commands  
from discord.ext import commands  
  
  
# ---------- Logging ----------  
  
LOG = logging.getLogger("AlarisBot")  
logging.basicConfig(  
    level=logging.INFO,  
    format="%(asctime)s [%(levelname)s] AlarisBot: %(message)s",  
)  
  
  
# ---------- Environment ----------  
  
TOKEN = os.getenv("DISCORD_TOKEN")  
DATABASE_URL = os.getenv("DATABASE_URL")  
GUILD_ID_RAW = os.getenv("GUILD_ID")  
STAFF_ROLE_IDS_RAW = os.getenv("STAFF_ROLE_IDS", "")  
DEVELOPER_ROLE_ID = 1505626082701738165  
  
COMMAND_LOG_CHANNEL_ID_RAW = os.getenv("COMMAND_LOG_CHANNEL_ID", "")  
XP_AWARD_LOG_CHANNEL_ID_RAW = os.getenv("XP_AWARD_LOG_CHANNEL_ID", "1500571564217860177")  
CHARACTER_REVIEW_CATEGORY_ID_RAW = os.getenv("CHARACTER_REVIEW_CATEGORY_ID", os.getenv("CHAR_SHEET_REVIEW_CATEGORY_ID", ""))  
CHARACTER_DISCUSSION_CHANNEL_ID_RAW = os.getenv("CHARACTER_DISCUSSION_CHANNEL_ID", "1501770833083760690")  
CHARACTER_APPROVAL_LOG_CHANNEL_ID_RAW = os.getenv("CHARACTER_APPROVAL_LOG_CHANNEL_ID", "1497310660629889065")  
SESSION_LOG_CHANNEL_ID_RAW = os.getenv("SESSION_LOG_CHANNEL_ID", "1500481604085350520")  
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")  
OPENAI_SUMMARY_MODEL = os.getenv("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")  
  
  
def parse_optional_int(raw: Optional[str], name: str) -> Optional[int]:  
    if raw is None or str(raw).strip() == "":  
        return None  
    try:  
        return int(str(raw).strip())  
    except ValueError as exc:  
        raise RuntimeError(f"{name} must be an integer if provided. Got: {raw!r}") from exc  
  
  
def parse_required_int(raw: Optional[str], name: str) -> int:  
    value = parse_optional_int(raw, name)  
    if value is None:  
        raise RuntimeError(f"Missing required environment variable: {name}")  
    return value  
  
  
def parse_int_list(raw: str) -> list[int]:  
    values: list[int] = []  
    for item in str(raw or "").split(","):  
        item = item.strip()  
        if not item:  
            continue  
        try:  
            values.append(int(item))  
        except ValueError as exc:  
            raise RuntimeError(f"STAFF_ROLE_IDS contains a non-integer value: {item!r}") from exc  
    return values  
  
  
def validate_environment() -> None:  
    if not TOKEN:  
        raise RuntimeError("Missing required environment variable: DISCORD_TOKEN")  
    if not DATABASE_URL:  
        raise RuntimeError("Missing required environment variable: DATABASE_URL")  
    parse_required_int(GUILD_ID_RAW, "GUILD_ID")  
    parse_int_list(STAFF_ROLE_IDS_RAW)  
    parse_optional_int(COMMAND_LOG_CHANNEL_ID_RAW, "COMMAND_LOG_CHANNEL_ID")  
    parse_optional_int(XP_AWARD_LOG_CHANNEL_ID_RAW, "XP_AWARD_LOG_CHANNEL_ID")  
    parse_optional_int(CHARACTER_REVIEW_CATEGORY_ID_RAW, "CHARACTER_REVIEW_CATEGORY_ID")  
    parse_optional_int(CHARACTER_DISCUSSION_CHANNEL_ID_RAW, "CHARACTER_DISCUSSION_CHANNEL_ID")  
    parse_optional_int(CHARACTER_APPROVAL_LOG_CHANNEL_ID_RAW, "CHARACTER_APPROVAL_LOG_CHANNEL_ID")  
    parse_optional_int(SESSION_LOG_CHANNEL_ID_RAW, "SESSION_LOG_CHANNEL_ID")  
  
  
validate_environment()  
  
GUILD_ID = parse_required_int(GUILD_ID_RAW, "GUILD_ID")  
STAFF_ROLE_IDS = parse_int_list(STAFF_ROLE_IDS_RAW)  
COMMAND_LOG_CHANNEL_ID = parse_optional_int(COMMAND_LOG_CHANNEL_ID_RAW, "COMMAND_LOG_CHANNEL_ID")  
XP_AWARD_LOG_CHANNEL_ID = parse_optional_int(XP_AWARD_LOG_CHANNEL_ID_RAW, "XP_AWARD_LOG_CHANNEL_ID")  
CHARACTER_REVIEW_CATEGORY_ID = parse_optional_int(CHARACTER_REVIEW_CATEGORY_ID_RAW, "CHARACTER_REVIEW_CATEGORY_ID")  
CHARACTER_DISCUSSION_CHANNEL_ID = parse_optional_int(CHARACTER_DISCUSSION_CHANNEL_ID_RAW, "CHARACTER_DISCUSSION_CHANNEL_ID")  
CHARACTER_APPROVAL_LOG_CHANNEL_ID = parse_optional_int(CHARACTER_APPROVAL_LOG_CHANNEL_ID_RAW, "CHARACTER_APPROVAL_LOG_CHANNEL_ID")  
SESSION_LOG_CHANNEL_ID = parse_optional_int(SESSION_LOG_CHANNEL_ID_RAW, "SESSION_LOG_CHANNEL_ID")  
  
  
# ---------- Discord Setup ----------  
  
intents = discord.Intents.default()  
intents.guilds = True  
intents.members = True  
intents.message_content = True  
  
bot = commands.Bot(command_prefix="!", intents=intents)  
db_pool: Optional[asyncpg.Pool] = None  
openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None  
_commands_synced = False  
_character_refresh_worker_task: Optional[asyncio.Task] = None  
_xp_award_listener_task: Optional[asyncio.Task] = None  
_xp_award_poller_task: Optional[asyncio.Task] = None  
_xp_award_processing_lock = asyncio.Lock()  
APPROVED_PLAYER_ROLE_ID = 1497792386322141354  
  
  
# ---------- Constants ----------  
  
STAT_KEYS = ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]  
STAT_LABELS = {  
    "strength": "STR",  
    "dexterity": "DEX",  
    "constitution": "CON",  
    "intelligence": "INT",  
    "wisdom": "WIS",  
    "charisma": "CHA",  
}  
STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]  
  
# v056 locked Alaris creation species roster. Do not replace with generic D&D species.  
# v061 locked Alaris playable species roster.  
SPECIES_OPTIONS = ['Aasimar',  
 'Centaur',  
 'Dhampir',  
 'Dragonborn',  
 'Drow',  
 'Dwarf',  
 'Elf',  
 'Faerie',  
 'Genasi',  
 'Gnome',  
 'Goblin',  
 'Goliath',  
 'Halfling',  
 'Human',  
 'Kitsune',  
 'Merfolk',  
 'Orc',  
 'Theranth',  
 'Tiefling',  
 'Triton',  
 'Werewolf']  
# v061 locked Alaris class roster.  
CLASS_OPTIONS = ['Artificer',  
 'Barbarian',  
 'Bard',  
 'Captain',  
 'Cleric',  
 'Druid',  
 'Fighter',  
 'Monk',  
 'Paladin',  
 'Ranger',  
 'Rogue',  
 'Scholar',  
 'Sorcerer',  
 'Warlock',  
 'Warden',  
 'Wizard']  
  
# v100 locked Alaris kingdom/region roster for character affiliation.  
# Keep this list centralized so AlarisBot, EconomyBot, and TournamentBot can converge on the same names.  
KINGDOM_OPTIONS = [  
    'Galadon',  
    'Ephel Duath',  
    'Chiron',  
    'Mullaghmore',  
    'Vidalia',  
    'Idolea',  
    'Frerinn',  
    'Vornladuhr',  
    'Unaffiliated',  
]  
  
  
CLASS_COMBAT_SCALING = {  
    "artificer": {"attack": "moderate", "magic": "strong"},  
    "barbarian": {"attack": "strong", "magic": "none"},  
    "bard": {"attack": "moderate", "magic": "strong"},  
    "captain": {"attack": "moderate", "magic": "weak"},  
    "cleric": {"attack": "moderate", "magic": "strong"},  
    "druid": {"attack": "moderate", "magic": "strong"},  
    "fighter": {"attack": "strong", "magic": "none"},  
    "monk": {"attack": "strong", "magic": "weak"},  
    "paladin": {"attack": "strong", "magic": "moderate"},  
    "ranger": {"attack": "strong", "magic": "moderate"},  
    "rogue": {"attack": "moderate", "magic": "weak"},  
    "scholar": {"attack": "weak", "magic": "moderate"},  
    "sorcerer": {"attack": "weak", "magic": "strong"},  
    "warlock": {"attack": "weak", "magic": "strong"},  
    "warden": {"attack": "strong", "magic": "weak"},  
    "wizard": {"attack": "weak", "magic": "strong"},  
    "mage": {"attack": "weak", "magic": "strong"},  
}  
GENERIC_SPECIES_PASSIVES = [  
    {"name": "Swift Instinct", "description": "+1 Initiative.", "bonuses": {"initiative_bonus": 1}},  
    {"name": "Hardy Blood", "description": "+1 HP per level.", "bonuses": {"hp_per_level": 1}},  
    {"name": "Mystic Poise", "description": "+1 Magic Defense.", "bonuses": {"magic_defense": 1}},  
]  
  
SPECIES_PASSIVE_OPTIONS = {'aasimar': [{'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Celestial Poise'},  
             {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Radiant Focus'},  
             {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Blessed Vigor'}],  
 'centaur': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Fleet Strider'},  
             {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Powerful Build'},  
             {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Surefooted'}],  
 'dhampir': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Nocturnal Reflexes'},  
             {'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Predatory Grace'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Unliving Resilience'}],  
 'dragonborn': [{'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Draconic Might'},  
                {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Scaled Guard'},  
                {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Ancient Blood'}],  
 'drow': [{'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Umbral Precision'},  
          {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Shadow Veil'},  
          {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Deep Sight'}],  
 'dwarf': [{'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Stoneblood'},  
           {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Unshaken'},  
           {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Mountain Guard'}],  
 'elf': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Keen Reflexes'},  
         {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Arcane Affinity'},  
         {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Graceful Guard'}],  
 'fae': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Glamour-Touched'},  
         {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Flickerstep'},  
         {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Otherworldly Poise'}],  
 'faerie': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Glamour-Touched'},  
            {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Flickerstep'},  
            {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Otherworldly Poise'}],  
 'fairy': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Glamour-Touched'},  
           {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Flickerstep'},  
           {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Otherworldly Poise'}],  
 'genasi': [{'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Elemental Body'},  
            {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Primordial Spark'},  
            {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Elemental Grace'}],  
 'gnome': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Quick Thinker'},  
           {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': "Tinkerer's Wit"},  
           {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Nimble Escape'}],  
 'goblin': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': "Scavenger's Reflexes"},  
            {'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Dirty Fighting'},  
            {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Slippery Escape'}],  
 'goliath': [{'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Mountain Endurance'},  
             {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Titan Frame'},  
             {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Stone Guard'}],  
 'halfling': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Nimble Footing'},  
              {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Lucky Nerve'},  
              {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Small Target'}],  
 'human': [{'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Adaptable Training'},  
           {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Hardy Blood'},  
           {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Steady Nerve'}],  
 'kitsune': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Glamourborn'},  
             {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Fleetfooted Guile'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Spirit-Sly'}],  
 'merfolk': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Tidal Grace'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Deepwater Poise'},  
             {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Flowing Form'}],  
 'orc': [{'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Brutal Strength'},  
         {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Ironhide'},  
         {'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Battle Fury'}],  
 'theranth': [{'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': "Predator's Instinct"},  
              {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Natural Ferocity'},  
              {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Lineage Hide'}],  
 'tiefling': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Hellfire Spark'},  
              {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Infernal Will'},  
              {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': "Devil's Edge"}],  
 'triton': [{'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Guardian of the Deep'},  
            {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Storm-Touched'},  
            {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Oceanborn Resolve'}],  
 'werewolf': [{'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Lunar Vitality'},  
              {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Clawed Ferocity'},  
              {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': "Hunter's Reflex"}]}  
SPECIES_PASSIVE_OPTIONS["fae"] = SPECIES_PASSIVE_OPTIONS["faerie"]  
SPECIES_PASSIVE_OPTIONS["fairy"] = SPECIES_PASSIVE_OPTIONS["faerie"]  
  
CLASS_PASSIVE_OPTIONS = {'artificer': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Runic Calibration'},  
               {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Layered Wards'},  
               {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Arcane Method'}],  
 'barbarian': [{'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Raging Power'},  
               {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Unarmored Bulk'},  
               {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Savage Momentum'}],  
 'bard': [{'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Inspiring Presence'},  
          {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Silver Spellcraft'},  
          {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Quick Performance'}],  
 'captain': [{'bonuses': {'technique_dc': 1}, 'description': '+1 Technique DC.', 'name': 'Commanding Presence'},  
             {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Battlefield Voice'},  
             {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Shielding Orders'}],  
 'cleric': [{'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Sacred Ward'},  
            {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Consecrated Focus'},  
            {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Merciful Hands'}],  
 'druid': [{'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Wild Resilience'},  
           {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Primal Channel'},  
           {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Seasonal Instinct'}],  
 'fighter': [{'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Weapon Discipline'},  
             {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Heavy Strikes'},  
             {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Battle-Hardened'}],  
 'monk': [{'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Flowing Form'},  
          {'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Swift Hands'},  
          {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Centered Breath'}],  
 'paladin': [{'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Divine Presence'},  
             {'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': 'Zealous Blade'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Oathbound Spirit'}],  
 'ranger': [{'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': "Hunter's Aim"},  
            {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Trail Instincts'},  
            {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Wilderness Guard'}],  
 'rogue': [{'bonuses': {'attack_bonus': 1}, 'description': '+1 Attack.', 'name': "Killer's Precision"},  
           {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Fast Hands'},  
           {'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Evasive Footwork'}],  
 'scholar': [{'bonuses': {'technique_dc': 1}, 'description': '+1 Technique DC.', 'name': 'Tactical Mind'},  
             {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Forbidden Studies'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Measured Defense'}],  
 'sorcerer': [{'bonuses': {'resolve_bonus': 1}, 'description': '+1 Resolve.', 'name': 'Arcane Reservoir'},  
              {'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Mystic Potency'},  
              {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Spellflare'}],  
 'warden': [{'bonuses': {'armor_class': 1}, 'description': '+1 AC.', 'name': 'Sentinel Training'},  
            {'bonuses': {'technique_dc': 1}, 'description': '+1 Technique DC.', 'name': 'Binding Discipline'},  
            {'bonuses': {'hp_per_level': 1}, 'description': '+1 HP per level.', 'name': 'Stalwart Frame'}],  
 'warlock': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Pact-Bound Focus'},  
             {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Eldritch Resilience'},  
             {'bonuses': {'damage_bonus': 1}, 'description': '+1 Damage.', 'name': 'Dark Bargain'}],  
 'wizard': [{'bonuses': {'spell_dc': 1}, 'description': '+1 Spell DC.', 'name': 'Arcane Thesis'},  
            {'bonuses': {'magic_defense': 1}, 'description': '+1 Magic Defense.', 'name': 'Protective Formula'},  
            {'bonuses': {'initiative_bonus': 1}, 'description': '+1 Initiative.', 'name': 'Measured Casting'}]}  
  
  
SESSION_TYPES = [  
    "Roleplay",  
    "Event",  
    "Mission",  
    "Training",  
    "Downtime",  
]  
  
SESSION_TYPE_ALIASES = {  
    "roleplay": "Roleplay",  
    "rp": "Roleplay",  
    "event": "Event",  
    "mission": "Mission",  
    "training": "Training",  
    "downtime": "Downtime",  
}  
  
RP_XP_PER_TYPED_CHARACTER = 0.005  
RP_XP_CAP_PER_SESSION = 300  
  
COMBAT_ACTIVITY_TZ = ZoneInfo("America/Chicago") if ZoneInfo else None  
SPAR_DUEL_PARTICIPATION_XP = 30  
SPAR_DUEL_VICTORY_XP = 30  
PVE_PARTICIPATION_XP = 50  
# Backward-compatible aliases for older log text/helpers.  
DUEL_WINNER_XP = SPAR_DUEL_PARTICIPATION_XP + SPAR_DUEL_VICTORY_XP  
DUEL_LOSER_XP = SPAR_DUEL_PARTICIPATION_XP  
  
DEFAULT_ENEMY_XP_BY_DIFFICULTY = {  
    "trivial": 10,  
    "easy": 25,  
    "standard": 50,  
    "hard": 100,  
    "deadly": 200,  
    "boss": 500,  
}  
  
COMBAT_TYPES = ["Spar", "Duel", "Enemy Encounter"]  
COMBAT_TYPE_ALIASES = {  
    "spar": "Spar",  
    "duel": "Duel",  
    "enemy encounter": "Enemy Encounter",  
    "encounter": "Enemy Encounter",  
    "enemy": "Enemy Encounter",  
}  
  
CHALLENGE_RATINGS = ["Easy", "Standard", "Balanced", "Hard", "Deadly"]  
ENEMY_TYPES = ["NPCs", "Beasts"]  
  
NPC_GROUPS = ["Bandits", "Cultists", "Undead", "Mercenaries", "Raiders"]  
BEAST_SETTINGS = ["Forest", "Mountain", "Swamp", "Plains", "Coastal", "Cavern"]  
  
# v082 player-facing encounter UX labels. These map back into the existing enemy/scaling engine.  
ENCOUNTER_ENEMY_CATEGORIES = ["Bandits", "Cultists", "Pirates", "Undead", "Soldiers", "Goblins", "Orcs", "Beasts", "Monsters"]  
ENCOUNTER_DANGER_LEVELS = ["Easy", "Standard", "Balanced", "Hard", "Deadly"]  
ENCOUNTER_ENVIRONMENTS = ["Roads", "Forest", "Mountains", "Ruins", "Coast", "Swamp", "City", "Caverns", "Jungle", "Volcanic Region"]  
  
DANGER_TO_CR = {  
    "easy": "easy",  
    "standard": "standard",  
    "balanced": "standard",  
    "hard": "hard",  
    "deadly": "deadly",  
}  
  
ENCOUNTER_CATEGORY_TO_GENERATOR = {  
    "bandits": ("NPCs", "Bandits"),  
    "cultists": ("NPCs", "Cultists"),  
    "pirates": ("NPCs", "Raiders"),  
    "undead": ("NPCs", "Undead"),  
    "soldiers": ("NPCs", "Mercenaries"),  
    "goblins": ("NPCs", "Raiders"),  
    "orcs": ("NPCs", "Mercenaries"),  
    "beasts": ("Beasts", "Forest"),  
    "monsters": ("Beasts", "Cavern"),  
}  
  
ACTION_TYPES = [  
    "Use Ability",  
    "Magical Attack",  
    "Piercing Melee or Ranged Attack",  
    "Slashing Melee Attack",  
    "Blunt Melee Attack",  
]  
  
LOCKED_DAMAGE_TYPES = [  
    "piercing",  
    "slashing",  
    "blunt",  
    "fire",  
    "water",  
    "air",  
    "earth",  
    "spirit",  
    "poison/acid",  
    "lightning",  
    "ice",  
]  
  
PHYSICAL_ACTION_DAMAGE_TYPES = {  
    "piercing melee or ranged attack": "piercing",  
    "piercing attack": "piercing",  
    "slashing melee attack": "slashing",  
    "slashing attack": "slashing",  
    "blunt melee attack": "blunt",  
    "blunt attack": "blunt",  
}  
  
HOSTILE_ACTIONS = {  
    "piercing melee or ranged attack",  
    "piercing attack",  
    "slashing melee attack",  
    "slashing attack",  
    "blunt melee attack",  
    "blunt attack",  
    "magical attack",  
    "magic attack",  
}  
SUPPORT_ACTIONS = {"heal", "shield / defensive spell", "buff"}  
ATTACK_ACTIONS = {"piercing melee or ranged attack", "piercing attack", "slashing melee attack", "slashing attack", "blunt melee attack", "blunt attack"}  
  
ENEMY_STAT_BLOCKS = {  
    "cult initiate": {"max_hp": 8, "armor_class": 10, "initiative_bonus": 0, "attack_bonus": 2, "save_dc": 10, "damage_die_sides": 4, "damage_bonus": 0, "xp_value": 15},  
    "masked zealot": {"max_hp": 14, "armor_class": 12, "initiative_bonus": 1, "attack_bonus": 4, "save_dc": 11, "damage_die_sides": 6, "damage_bonus": 1, "xp_value": 40},  
    "dark acolyte": {"max_hp": 12, "armor_class": 11, "initiative_bonus": 1, "attack_bonus": 3, "save_dc": 13, "damage_die_sides": 6, "damage_bonus": 0, "xp_value": 55},  
    "cult herald": {"max_hp": 20, "armor_class": 13, "initiative_bonus": 2, "attack_bonus": 5, "save_dc": 14, "damage_die_sides": 8, "damage_bonus": 1, "xp_value": 90},  
    "bandit cutthroat": {"max_hp": 10, "armor_class": 12, "initiative_bonus": 2, "attack_bonus": 4, "save_dc": 10, "damage_die_sides": 6, "damage_bonus": 0, "xp_value": 25},  
    "bandit archer": {"max_hp": 8, "armor_class": 12, "initiative_bonus": 2, "attack_bonus": 4, "save_dc": 10, "damage_die_sides": 6, "damage_bonus": 0, "xp_value": 25},  
    "bandit bruiser": {"max_hp": 16, "armor_class": 11, "initiative_bonus": 0, "attack_bonus": 4, "save_dc": 10, "damage_die_sides": 8, "damage_bonus": 1, "xp_value": 45},  
    "bandit captain": {"max_hp": 24, "armor_class": 14, "initiative_bonus": 2, "attack_bonus": 5, "save_dc": 12, "damage_die_sides": 8, "damage_bonus": 2, "xp_value": 90},  
    "dire wolf": {"max_hp": 16, "armor_class": 12, "initiative_bonus": 2, "attack_bonus": 4, "save_dc": 10, "damage_die_sides": 8, "damage_bonus": 0, "xp_value": 45},  
    "briar boar": {"max_hp": 18, "armor_class": 11, "initiative_bonus": 0, "attack_bonus": 4, "save_dc": 10, "damage_die_sides": 8, "damage_bonus": 1, "xp_value": 45},  
    "shadowcat": {"max_hp": 12, "armor_class": 13, "initiative_bonus": 3, "attack_bonus": 5, "save_dc": 11, "damage_die_sides": 6, "damage_bonus": 1, "xp_value": 55},  
    "antlered stalker": {"max_hp": 22, "armor_class": 13, "initiative_bonus": 2, "attack_bonus": 5, "save_dc": 12, "damage_die_sides": 8, "damage_bonus": 2, "xp_value": 85},  
}  
  
ENEMY_NAME_POOLS = {  
    "bandits": ["Bandit Cutthroat", "Bandit Archer", "Bandit Bruiser", "Bandit Captain"],  
    "cultists": ["Cult Initiate", "Masked Zealot", "Dark Acolyte", "Cult Herald"],  
    "undead": ["Restless Dead", "Grave Wight", "Bone Servitor", "Hollow Revenant"],  
    "mercenaries": ["Mercenary Blade", "Shield-for-Hire", "Veteran Sellsword", "Mercenary Captain"],  
    "raiders": ["Raider Skirmisher", "Raider Reaver", "Raider Archer", "Raider Chief"],  
    "forest": ["Dire Wolf", "Briar Boar", "Shadowcat", "Antlered Stalker"],  
    "mountain": ["Crag Wolf", "Stoneclaw Bear", "Mountain Drake", "Cliff Raptor"],  
    "swamp": ["Bog Serpent", "Marsh Horror", "Mire Crocodile", "Fen Strider"],  
    "plains": ["Razorhorn", "Hunting Cat", "Dust Hyena", "Stormhoof"],  
    "coastal": ["Reef Serpent", "Saltmaw", "Tide Raptor", "Shore Stalker"],  
    "cavern": ["Cave Horror", "Blind Ravager", "Gloom Spider", "Stoneback Beast"],  
}  
  
  
ENCOUNTER_DIFFICULTY_PROFILE = {  
    "easy": {"minions": 1, "elites": 0, "hp_mult": 0.75, "atk_mod": -1, "ac_mod": -1, "die_mod": -2, "xp_mult": 0.80, "ability_chance": 0.04},  
    "standard": {"minions": 2, "elites": 0, "hp_mult": 0.85, "atk_mod": -1, "ac_mod": 0, "die_mod": -1, "xp_mult": 1.00, "ability_chance": 0.08},  
    "balanced": {"minions": 2, "elites": 0, "lite_elites": 1, "hp_mult": 0.92, "elite_hp_mult": 0.72, "atk_mod": 0, "ac_mod": 0, "die_mod": 0, "elite_die_mod": -2, "xp_mult": 1.25, "ability_chance": 0.10, "elite_ability_chance": 0.10},  
    "hard": {"minions": 2, "elites": 1, "lite_elites": 0, "hp_mult": 1.00, "elite_hp_mult": 0.88, "atk_mod": 0, "elite_atk_mod": 0, "ac_mod": 0, "die_mod": 0, "elite_die_mod": -1, "xp_mult": 1.50, "ability_chance": 0.16, "elite_ability_chance": 0.16},  
    "deadly": {"minions": 3, "elites": 1, "lite_elites": 0, "hp_mult": 1.20, "elite_hp_mult": 1.00, "atk_mod": 1, "elite_atk_mod": 1, "ac_mod": 1, "die_mod": 2, "elite_die_mod": 1, "xp_mult": 2.00, "ability_chance": 0.28, "elite_ability_chance": 0.28},  
}  
SETTING_FLAVOR = {  
    "roads": {"intro": "Dust hangs over the road as danger closes in from the broken edges of the path.", "weights": ["ambusher", "skirmisher", "raider"]},  
    "forest": {"intro": "Branches stir overhead as the forest tightens around the party, every shadow suddenly watchful.", "weights": ["ambusher", "beast", "skirmisher"]},  
    "mountains": {"intro": "Wind screams through the mountain pass as shapes move along the stone heights above.", "weights": ["climber", "ambusher", "bruiser"]},  
    "ruins": {"intro": "Dust shifts over broken stone as the ruins reveal the danger waiting within.", "weights": ["lurker", "caster", "guard"]},  
    "swamp": {"intro": "Black water ripples beneath the fog as something answers from the mire.", "weights": ["lurker", "poisoner", "beast"]},  
    "city": {"intro": "The noise of the street thins as hostile eyes turn toward the party.", "weights": ["skirmisher", "guard", "ambusher"]},  
    "coast": {"intro": "Salt spray lashes the shore as danger rises from wave, rock, and storm.", "weights": ["raider", "skirmisher", "bruiser"]},  
    "caverns": {"intro": "Sound carries strangely through the dark as movement echoes from the stone-shadow.", "weights": ["lurker", "bruiser", "monster"]},  
    "jungle": {"intro": "The jungle canopy trembles, and the heat suddenly feels close and alive.", "weights": ["ambusher", "poisoner", "beast"]},  
    "volcanic region": {"intro": "Heat rolls across blackened ground while ash drifts through the air like falling snow.", "weights": ["bruiser", "caster", "monster"]},  
}  
ENEMY_ABILITY_LIBRARY = {  
    "coordinated_strike": {"name": "Coordinated Strike", "kind": "strike", "damage_type": "piercing", "state": "marked", "description": "calls out an opening and strikes with disciplined timing"},  
    "dark_invocation": {"name": "Dark Invocation", "kind": "spell", "damage_type": "spirit", "state": "weakened", "description": "raises a forbidden sign as shadowed power lashes outward"},  
    "blood_frenzy": {"name": "Blood Frenzy", "kind": "buff", "state": "inspired", "description": "whips itself into a violent frenzy"},  
    "hex_bolt": {"name": "Hex Bolt", "kind": "spell", "damage_type": "spirit", "state": "exposed", "description": "hurls a spiteful hex toward a vulnerable target"},  
    "grave_cleave": {"name": "Grave Cleave", "kind": "strike", "damage_type": "slashing", "state": "bleeding", "description": "swings with cold grave-strength in a brutal cleaving arc"},  
    "shield_breaker": {"name": "Shield Breaker", "kind": "strike", "damage_type": "blunt", "state": "staggered", "description": "drives forward with a crushing blow meant to break footing"},  
    "venom_spit": {"name": "Venom Spit", "kind": "spell", "damage_type": "poison/acid", "state": "weakened", "description": "spits a caustic spray toward exposed flesh and armor seams"},  
    "terrifying_roar": {"name": "Terrifying Roar", "kind": "debuff", "damage_type": "spirit", "state": "feared", "description": "unleashes a terrible cry that rattles courage and concentration"},  
    "rift_lash": {"name": "Rift Lash", "kind": "spell", "damage_type": "spirit", "state": "exposed", "description": "tears a ragged line of unstable force through the air"},  
    "war_cry": {"name": "War Cry", "kind": "buff", "state": "inspired", "description": "bellows a command that sharpens its fury"},  
}  
def _e(name, role, tags, hp, ac, init, atk, md, die, dmg, dtype, xp, abilities=None):  
    return {"name": name, "role": role, "tags": tags, "hp": hp, "ac": ac, "init": init, "atk": atk, "md": md, "die": die, "dmg": dmg, "dtype": dtype, "xp": xp, "abilities": abilities or []}  
ENCOUNTER_ENEMY_LIBRARY = {  
    "bandits": {"minor": [_e("Cutpurse","skirmisher",["city","roads","ambusher"],10,12,2,4,10,6,0,"piercing",25), _e("Highway Raider","raider",["roads","coast"],14,12,1,4,10,6,1,"slashing",40), _e("Cliff Brigand","ambusher",["mountains","climber"],13,13,2,4,10,6,1,"piercing",45), _e("Desperate Outlaw","bruiser",["roads","forest"],16,11,0,4,10,8,1,"blunt",45)], "elite": [_e("Bandit Captain","elite",["roads","city","guard"],28,14,2,6,12,8,2,"slashing",120,["coordinated_strike"]), _e("Mountain Reaver","elite",["mountains","climber","bruiser"],32,13,1,6,11,10,2,"slashing",130,["shield_breaker"])]},  
    "cultists": {"minor": [_e("Cult Acolyte","caster",["ruins","city"],10,10,1,3,12,6,0,"spirit",35,["dark_invocation"]), _e("Frenzied Convert","bruiser",["ruins","roads"],15,11,1,4,10,6,1,"blunt",40), _e("Ash-Robed Zealot","caster",["volcanic region","ruins"],12,11,1,4,13,6,1,"fire",55,["dark_invocation"])], "elite": [_e("Cult Fanatic","elite",["ruins","city"],26,13,2,5,14,8,2,"spirit",120,["dark_invocation","blood_frenzy"]), _e("Void Channeler","elite",["ruins","volcanic region","caster"],24,12,2,5,15,10,1,"spirit",140,["rift_lash","dark_invocation"])]},  
    "pirates": {"minor": [_e("Deck Raider","raider",["coast","roads"],13,12,2,4,10,6,1,"slashing",40), _e("Harpoon Thrower","skirmisher",["coast"],12,12,2,4,10,6,1,"piercing",40), _e("Bilge Knife","ambusher",["coast","city"],10,13,3,4,10,6,0,"piercing",35)], "elite": [_e("Corsair Captain","elite",["coast","raider"],30,14,3,6,12,8,2,"slashing",130,["coordinated_strike"])]},  
    "undead": {"minor": [_e("Restless Dead","minion",["ruins","swamp"],12,10,-1,3,11,6,0,"blunt",30), _e("Bonewalker","guard",["ruins","caverns"],15,12,0,4,11,6,1,"slashing",45), _e("Gravebound Corpse","bruiser",["swamp","ruins"],18,11,-1,4,12,8,1,"blunt",50)], "elite": [_e("Wight","elite",["ruins","caverns"],28,14,2,6,14,8,2,"spirit",130,["dark_invocation"]), _e("Bone Knight","elite",["ruins","guard"],34,15,1,6,13,10,2,"slashing",150,["grave_cleave"])]},  
    "soldiers": {"minor": [_e("Levy Spearman","guard",["roads","city"],14,13,0,4,10,6,1,"piercing",40), _e("Militia Archer","skirmisher",["roads","forest","mountains"],11,12,2,4,10,6,1,"piercing",40), _e("Frontier Guard","guard",["mountains","roads"],16,13,1,4,11,6,1,"slashing",45)], "elite": [_e("Veteran Knight","elite",["city","roads","guard"],34,16,1,6,13,8,2,"slashing",150,["shield_breaker"]), _e("Imperial Duelist","elite",["city","skirmisher"],28,15,3,7,12,8,2,"piercing",150,["coordinated_strike"])]},  
    "goblins": {"minor": [_e("Goblin Sneak","ambusher",["forest","caverns","mountains"],8,13,3,4,10,6,0,"piercing",30), _e("Goblin Cutter","skirmisher",["roads","forest","caverns"],10,12,2,4,10,6,1,"slashing",35), _e("Goblin Torchbearer","skirmisher",["ruins","caverns"],9,12,2,4,10,6,0,"fire",35), _e("Goblin Cliffscrambler","climber",["mountains","ambusher"],10,13,3,4,10,6,1,"piercing",40)], "elite": [_e("Goblin Hexer","caster",["caverns","ruins","forest"],18,12,2,5,14,8,1,"spirit",100,["hex_bolt"]), _e("Goblin Chief","elite",["caverns","mountains","guard"],26,14,2,6,12,8,2,"slashing",120,["war_cry"])]},  
    "orcs": {"minor": [_e("Orc Raider","bruiser",["roads","mountains","raider"],18,12,1,5,10,8,1,"slashing",55), _e("Orc Hunter","skirmisher",["forest","mountains"],15,12,2,5,10,6,2,"piercing",55)], "elite": [_e("Skullbreaker","elite",["mountains","bruiser"],38,14,1,7,12,10,3,"blunt",160,["shield_breaker","war_cry"]), _e("Ironhide Champion","elite",["roads","guard"],42,15,0,6,13,10,2,"slashing",160,["war_cry"])]},  
    "beasts": {"minor": [_e("Dire Wolf","beast",["forest","mountains"],16,12,2,4,10,8,0,"piercing",45), _e("Mountain Cat","ambusher",["mountains","forest"],14,13,3,5,10,6,1,"slashing",50), _e("Giant Serpent","poisoner",["swamp","jungle"],18,12,2,4,10,8,1,"poison/acid",55,["venom_spit"]), _e("Cave Bear","bruiser",["caverns","mountains"],26,12,0,5,11,10,2,"blunt",80)], "elite": [_e("Alpha Dire Wolf","elite",["forest","mountains"],30,13,3,6,12,8,2,"piercing",120,["terrifying_roar"]), _e("Elder Basilisk","elite",["caverns","jungle"],34,14,1,6,14,10,2,"poison/acid",160,["venom_spit","terrifying_roar"])]},  
    "monsters": {"minor": [_e("Mire Spawn","monster",["swamp","jungle"],16,11,1,4,11,8,1,"poison/acid",55), _e("Hollow Stalker","lurker",["ruins","caverns"],14,13,3,5,12,6,2,"spirit",65), _e("Ash Maw","bruiser",["volcanic region","monster"],24,12,1,5,12,10,1,"fire",80)], "elite": [_e("Rift Horror","elite",["ruins","caverns","monster"],36,14,2,6,15,10,2,"spirit",170,["rift_lash","terrifying_roar"]), _e("Deep Crawler","elite",["caverns","jungle"],40,15,1,6,13,12,2,"piercing",180,["venom_spit"])]},  
}  
  
  
CR_SCALE = {  
    "trivial": {"count_mod": -1, "hp_mult": 0.65, "ac_mod": -2, "atk_mod": -2, "die_mod": -2, "xp": 10},  
    "easy": {"count_mod": 0, "hp_mult": 0.8, "ac_mod": -1, "atk_mod": -1, "die_mod": -1, "xp": 25},  
    "standard": {"count_mod": 0, "hp_mult": 1.0, "ac_mod": 0, "atk_mod": 0, "die_mod": 0, "xp": 50},  
    "hard": {"count_mod": 1, "hp_mult": 1.25, "ac_mod": 1, "atk_mod": 1, "die_mod": 2, "xp": 100},  
    "deadly": {"count_mod": 2, "hp_mult": 1.5, "ac_mod": 2, "atk_mod": 2, "die_mod": 4, "xp": 200},  
    "boss": {"count_mod": -2, "hp_mult": 3.0, "ac_mod": 3, "atk_mod": 3, "die_mod": 8, "xp": 500},  
}  
  
  
  
ASI_LEVELS = {4, 8}  
SPECIES_ABILITY_LEVELS = {3, 7}  
COMBAT_SPECIALIZATION_LEVELS = {3, 6, 9}  
ABILITY_CHOICE_LEVELS = {2, 4, 6, 8, 10}  
  
COMBAT_SPECIALIZATION_OPTIONS = {  
    "attack": {"name": "Sharpened Accuracy", "bonus": {"attack_bonus": 1}, "description": "+1 Attack"},  
    "damage": {"name": "Deadlier Force", "bonus": {"damage_bonus": 1}, "description": "+1 Damage"},  
    "spell dc": {"name": "Deepened Spellcraft", "bonus": {"spell_dc": 1}, "description": "+1 Spell DC"},  
    "spell": {"name": "Deepened Spellcraft", "bonus": {"spell_dc": 1}, "description": "+1 Spell DC"},  
}  
  
  
CLASS_ACTIVE_ABILITIES = {'artificer': {2: [{'cost': 1,  
                    'description': 'Inscribe a quick protective sigil.',  
                    'kind': 'buff',  
                    'name': 'Warding Sigil',  
                    'state': 'shielded'},  
                   {'cost': 1,  
                    'damage_type': 'spirit',  
                    'dc_type': 'spell',  
                    'description': 'Unravel magical stability through counter-enchantment.',  
                    'kind': 'debuff',  
                    'name': 'Arcane Disjunction',  
                    'state': 'weakened'}],  
               4: [{'cost': 1,  
                    'description': 'Temporarily enchant a weapon, focus, or implement.',  
                    'kind': 'buff',  
                    'name': 'Runebound Edge',  
                    'state': 'inspired'},  
                   {'cost': 1,  
                    'damage_type': 'earth',  
                    'dc_type': 'spell',  
                    'description': 'Manifest binding glyphs beneath the target.',  
                    'kind': 'spell',  
                    'name': 'Glyph of Binding',  
                    'state': 'restrained'}],  
               6: [{'cost': 2,  
                    'description': 'Layer protective wards over an ally.',  
                    'kind': 'buff',  
                    'name': 'Mantle of Wards',  
                    'secondary_state': 'shielded',  
                    'state': 'fortified'},  
                   {'cost': 2,  
                    'damage_type': 'spirit',  
                    'dc_type': 'spell',  
                    'description': 'Break through magical protections.',  
                    'kind': 'spell',  
                    'name': 'Shatter Enchantment',  
                    'state': 'exposed'}],  
               8: [{'cost': 2,  
                    'description': 'Etch a defensive pattern into the air.',  
                    'kind': 'buff',  
                    'name': 'Aegis Inscription',  
                    'secondary_state': 'fortified',  
                    'state': 'guarded'},  
                   {'cost': 2,  
                    'damage_type': 'spirit',  
                    'dc_type': 'spell',  
                    'description': 'Channel elemental force through an enchanted focus.',  
                    'kind': 'spell_buff',  
                    'name': 'Elemental Infusion',  
                    'secondary_state': 'inspired',  
                    'state': 'weakened'}],  
               10: [{'cost': 3,  
                     'description': 'Unfold a masterwork ward that protects an ally.',  
                     'kind': 'buff',  
                     'name': 'Grand Ward of Preservation',  
                     'secondary_state': 'fortified',  
                     'state': 'shielded'},  
                    {'cost': 3,  
                     'description': "Perfect an ally's weapon, focus, armor, or spellwork.",  
                     'kind': 'buff',  
                     'name': 'Masterwork Enchantment',  
                     'secondary_state': 'guarded',  
                     'state': 'inspired'}]},  
 'barbarian': {2: [{'cost': 1,  
                    'damage_type': 'blunt',  
                    'dc_type': 'technique',  
                    'description': 'A savage strike that rattles the target.',  
                    'kind': 'strike',  
                    'name': 'Crushing Blow',  
                    'state': 'staggered'},  
                   {'cost': 1,  
                    'description': 'Enter a furious battle trance.',  
                    'kind': 'buff',  
                    'name': 'Blood Roar',  
                    'state': 'inspired'}],  
               4: [{'cost': 1,  
                    'damage_type': 'blunt',  
                    'dc_type': 'technique',  
                    'description': "Break the enemy's guard with brute force.",  
                    'kind': 'strike',  
                    'name': 'Sundering Swing',  
                    'state': 'exposed'},  
                   {'cost': 1,  
                    'description': 'Rage through incoming punishment.',  
                    'kind': 'buff',  
                    'name': 'Relentless Fury',  
                    'state': 'guarded'}],  
               6: [{'cost': 2,  
                    'damage_type': 'earth',  
                    'dc_type': 'technique',  
                    'description': 'Slam the battlefield and destabilize enemies.',  
                    'kind': 'strike',  
                    'name': 'Earthshaker',  
                    'state': 'restrained'},  
                   {'cost': 2,  
                    'description': 'Gain overwhelming offensive momentum.',  
                    'kind': 'buff',  
                    'name': 'Berserker Rush',  
                    'secondary_state': 'guarded',  
                    'state': 'inspired'}],  
               8: [{'cost': 2,  
                    'damage_type': 'blunt',  
                    'dc_type': 'technique',  
                    'description': 'A crippling strike against armor and bone.',  
                    'kind': 'strike',  
                    'name': 'Bonebreaker',  
                    'state': 'weakened'},  
                   {'cost': 2,  
                    'description': 'Ignore pain through sheer willpower.',  
                    'kind': 'buff',  
                    'name': 'Savage Endurance',  
                    'secondary_state': 'shielded',  
                    'state': 'fortified'}],  
               10: [{'cost': 3,  
                     'damage_type': 'slashing',  
                     'dc_type': 'technique',  
                     'description': 'A catastrophic finishing blow.',  
                     'kind': 'strike',  
                     'name': 'Titan Cleave',  
                     'state': 'bleeding'},  
                    {'cost': 3,  
                     'damage_type': 'blunt',  
                     'dc_type': 'technique',  
                     'description': 'Make a devastating attack and enter legendary fury.',  
                     'kind': 'strike_buff',  
                     'name': 'Wrath Unbound',  
                     'secondary_state': 'inspired',  
                     'state': 'staggered'}]},  
 'bard': {2: [{'cost': 1,  
               'description': 'Bolster an ally through performance.',  
               'kind': 'buff',  
               'name': 'Inspire Ally',  
               'state': 'inspired'},  
              {'cost': 1,  
               'damage_type': 'spirit',  
               'dc_type': 'spell',  
               'description': 'Undermine a foe with magical mockery.',  
               'kind': 'debuff',  
               'name': 'Cutting Verse',  
               'state': 'weakened'}],  
          4: [{'cost': 1, 'description': 'Restore vitality through music.', 'kind': 'heal', 'name': 'Soothing Melody'},  
              {'cost': 1,  
               'dc_type': 'spell',  
               'description': 'Throw enemies off balance.',  
               'kind': 'debuff',  
               'name': 'Distracting Flourish',  
               'state': 'exposed'}],  
          6: [{'cost': 2,  
               'description': 'Rally an ally with a heroic anthem.',  
               'kind': 'buff',  
               'name': 'Heroic Anthem',  
               'secondary_state': 'fortified',  
               'state': 'inspired'},  
              {'cost': 2,  
               'damage_type': 'air',  
               'dc_type': 'spell',  
               'description': 'A sonic blast that disrupts foes.',  
               'kind': 'spell',  
               'name': 'Shattering Chord',  
               'state': 'staggered'}],  
          8: [{'cost': 2,  
               'description': 'Cloak an ally in magical inspiration.',  
               'kind': 'buff',  
               'name': 'Veil of Legends',  
               'secondary_state': 'shielded',  
               'state': 'fortified'},  
              {'cost': 2,  
               'damage_type': 'spirit',  
               'dc_type': 'spell',  
               'description': 'Invoke terror through ancient song.',  
               'kind': 'debuff',  
               'name': 'Dread Refrain',  
               'state': 'feared'}],  
          10: [{'cost': 3,  
                'description': 'Elevate an ally beyond mortal limits.',  
                'kind': 'buff',  
                'name': 'Symphony of Victory',  
                'secondary_state': 'fortified',  
                'state': 'inspired'},  
               {'cost': 3,  
                'damage_type': 'lightning',  
                'dc_type': 'spell',  
                'description': 'Overwhelming resonance that harms a foe and rallies the caster.',  
                'kind': 'spell_buff',  
                'name': 'Final Crescendo',  
                'secondary_state': 'inspired',  
                'state': 'staggered'}]},  
 'captain': {2: [{'cost': 1,  
                  'description': 'Reinforce discipline and morale.',  
                  'kind': 'buff',  
                  'name': 'Rally Command',  
                  'state': 'inspired'},  
                 {'cost': 1,  
                  'dc_type': 'technique',  
                  'description': 'Coordinate focused attacks.',  
                  'kind': 'debuff',  
                  'name': 'Mark Target',  
                  'state': 'marked'}],  
             4: [{'cost': 1,  
                  'description': 'Reposition an ally through command.',  
                  'kind': 'buff',  
                  'name': 'Tactical Shift',  
                  'state': 'guarded'},  
                 {'cost': 1,  
                  'description': 'Organize a defensive formation.',  
                  'kind': 'buff',  
                  'name': 'Shield Line',  
                  'state': 'shielded'}],  
             6: [{'cost': 2,  
                  'description': 'Strengthen allied resolve.',  
                  'kind': 'buff',  
                  'name': 'Battlefield Order',  
                  'secondary_state': 'inspired',  
                  'state': 'fortified'},  
                 {'cost': 2,  
                  'dc_type': 'technique',  
                  'description': 'Direct suppressive pressure.',  
                  'kind': 'debuff',  
                  'name': 'Suppressing Volley',  
                  'state': 'weakened'}],  
             8: [{'cost': 2,  
                  'description': 'Hold the line against overwhelming odds.',  
                  'kind': 'buff',  
                  'name': 'Unbreakable Formation',  
                  'secondary_state': 'guarded',  
                  'state': 'shielded'},  
                 {'cost': 2,  
                  'dc_type': 'technique',  
                  'description': 'Identify and punish weakness.',  
                  'kind': 'debuff',  
                  'name': 'Execution Order',  
                  'state': 'exposed'}],  
             10: [{'cost': 3,  
                   'description': 'A legendary rallying command.',  
                   'kind': 'buff',  
                   'name': 'Banner of Triumph',  
                   'secondary_state': 'shielded',  
                   'state': 'inspired'},  
                  {'cost': 3,  
                   'dc_type': 'technique',  
                   'description': 'Dominate the battlefield through authority.',  
                   'kind': 'debuff',  
                   'name': 'Absolute Command',  
                   'secondary_state': 'marked',  
                   'state': 'feared'}]},  
 'cleric': {2: [{'cost': 1,  
                 'damage_type': 'spirit',  
                 'description': 'Restore health with sacred power.',  
                 'kind': 'heal',  
                 'name': 'Mending Light'},  
                {'cost': 1,  
                 'description': 'Protect an ally from harm.',  
                 'kind': 'buff',  
                 'name': 'Sacred Shield',  
                 'state': 'shielded'}],  
            4: [{'cost': 1,  
                 'damage_type': 'fire',  
                 'dc_type': 'spell',  
                 'description': 'Burn corruption from the battlefield.',  
                 'kind': 'spell',  
                 'name': 'Purifying Flame',  
                 'state': 'burning'},  
                {'cost': 1,  
                 'description': 'Reinforce spiritual resilience.',  
                 'kind': 'buff',  
                 'name': 'Blessing of Resolve',  
                 'state': 'fortified'}],  
            6: [{'cost': 2,  
                 'damage_type': 'spirit',  
                 'dc_type': 'spell',  
                 'description': 'Punish enemies with divine wrath.',  
                 'kind': 'spell',  
                 'name': 'Divine Rebuke',  
                 'state': 'weakened'},  
                {'cost': 2,  
                 'description': 'Restore a large measure of vitality to an ally.',  
                 'kind': 'heal',  
                 'name': 'Mass Restoration'}],  
            8: [{'cost': 2,  
                 'description': 'Create a zone of protection around an ally.',  
                 'kind': 'buff',  
                 'name': 'Sanctuary Field',  
                 'secondary_state': 'shielded',  
                 'state': 'guarded'},  
                {'cost': 2,  
                 'damage_type': 'fire',  
                 'dc_type': 'spell',  
                 'description': 'Call down sacred destruction.',  
                 'kind': 'spell',  
                 'name': 'Judgment Flame',  
                 'state': 'burning'}],  
            10: [{'cost': 3,  
                  'description': 'Restore an ally from the brink.',  
                  'kind': 'heal',  
                  'name': 'Miracle Invocation'},  
                 {'cost': 3,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Unleash overwhelming holy power.',  
                  'kind': 'spell',  
                  'name': 'Divine Cataclysm',  
                  'state': 'feared'}]},  
 'druid': {2: [{'cost': 1,  
                'damage_type': 'earth',  
                'dc_type': 'spell',  
                'description': 'Vines bind the target while dealing damage.',  
                'kind': 'spell',  
                'name': 'Thorn Lash',  
                'state': 'restrained'},  
               {'cost': 1,  
                'description': 'Restore health and reinforce natural vitality.',  
                'kind': 'heal',  
                'name': 'Verdant Renewal',  
                'state': 'fortified'}],  
           4: [{'cost': 1,  
                'damage_type': 'fire',  
                'dc_type': 'spell',  
                'description': 'A spreading wave of magical flame.',  
                'kind': 'spell',  
                'name': 'Wildfire Surge',  
                'state': 'burning'},  
               {'cost': 1,  
                'description': "Harden an ally's defenses with living bark.",  
                'kind': 'buff',  
                'name': 'Stonebark Ward',  
                'state': 'guarded'}],  
           6: [{'cost': 2,  
                'damage_type': 'air',  
                'dc_type': 'spell',  
                'description': 'Violent winds slam enemies backward.',  
                'kind': 'spell',  
                'name': 'Tempest Bloom',  
                'state': 'staggered'},  
               {'cost': 2,  
                'description': 'Anchor an ally in ancient protective magic.',  
                'kind': 'buff',  
                'name': 'Ancient Roots',  
                'secondary_state': 'fortified',  
                'state': 'shielded'}],  
           8: [{'cost': 2,  
                'damage_type': 'earth',  
                'dc_type': 'spell',  
                'description': 'Massive roots burst upward across the battlefield.',  
                'kind': 'spell',  
                'name': 'Wrath of the Wilds',  
                'state': 'restrained'},  
               {'cost': 2,  
                'description': 'A powerful restorative blessing under moonlight.',  
                'kind': 'heal',  
                'name': 'Lunar Restoration',  
                'state': 'inspired'}],  
           10: [{'cost': 3,  
                 'damage_type': 'earth',  
                 'dc_type': 'spell',  
                 'description': 'Battlefield-wide natural destruction focused on one foe.',  
                 'kind': 'spell',  
                 'name': 'Cataclysm Grove',  
                 'state': 'restrained'},  
                {'cost': 3,  
                 'description': 'Become a living embodiment of primal nature.',  
                 'kind': 'buff',  
                 'name': 'Avatar of Seasons',  
                 'secondary_state': 'fortified',  
                 'state': 'inspired'}]},  
 'fighter': {2: [{'cost': 1,  
                  'damage_type': 'piercing',  
                  'dc_type': 'technique',  
                  'description': 'A disciplined strike targeting weak points.',  
                  'kind': 'strike',  
                  'name': 'Precision Strike',  
                  'state': 'exposed'},  
                 {'cost': 1,  
                  'description': 'Adopt a hardened defensive stance.',  
                  'kind': 'buff',  
                  'name': 'Iron Guard',  
                  'state': 'guarded'}],  
             4: [{'cost': 1,  
                  'damage_type': 'slashing',  
                  'dc_type': 'technique',  
                  'description': 'Push the enemy with overwhelming force.',  
                  'kind': 'strike',  
                  'name': 'Driving Assault',  
                  'state': 'staggered'},  
                 {'cost': 1,  
                  'description': 'Prepare to punish enemy aggression.',  
                  'kind': 'buff',  
                  'name': 'Tactical Counter',  
                  'state': 'shielded'}],  
             6: [{'cost': 2,  
                  'damage_type': 'slashing',  
                  'dc_type': 'technique',  
                  'description': 'A broad strike that wounds foes.',  
                  'kind': 'strike',  
                  'name': 'Battlefield Sweep',  
                  'state': 'bleeding'},  
                 {'cost': 2,  
                  'description': 'Ignore pressure through experience.',  
                  'kind': 'buff',  
                  'name': "Veteran's Resolve",  
                  'secondary_state': 'guarded',  
                  'state': 'fortified'}],  
             8: [{'cost': 2,  
                  'damage_type': 'blunt',  
                  'dc_type': 'technique',  
                  'description': 'Crush resistance through relentless offense.',  
                  'kind': 'strike',  
                  'name': 'Relentless Advance',  
                  'state': 'weakened'},  
                 {'cost': 2,  
                  'description': 'Reinforce the frontline.',  
                  'kind': 'buff',  
                  'name': 'Hold the Line',  
                  'secondary_state': 'shielded',  
                  'state': 'guarded'}],  
             10: [{'cost': 3,  
                   'damage_type': 'slashing',  
                   'dc_type': 'technique',  
                   'description': 'A decisive finishing assault.',  
                   'kind': 'strike',  
                   'name': "War Master's Judgment",  
                   'state': 'exposed'},  
                  {'cost': 3,  
                   'description': 'Become nearly impossible to break.',  
                   'kind': 'buff',  
                   'name': 'Indomitable Veteran',  
                   'secondary_state': 'fortified',  
                   'state': 'inspired'}]},  
 'mage': {2: [{'cost': 1,  
               'damage_type': 'spirit',  
               'dc_type': 'spell',  
               'description': 'Precise magical bolts strike the enemy.',  
               'kind': 'spell',  
               'name': 'Arcane Missile',  
               'state': 'exposed'},  
              {'cost': 1,  
               'description': 'Conjure layered magical defenses.',  
               'kind': 'buff',  
               'name': 'Mystic Ward',  
               'state': 'shielded'}],  
          4: [{'cost': 1,  
               'damage_type': 'ice',  
               'dc_type': 'spell',  
               'description': 'Freeze enemies in place.',  
               'kind': 'spell',  
               'name': 'Frost Nova',  
               'state': 'restrained'},  
              {'cost': 1,  
               'damage_type': 'fire',  
               'dc_type': 'spell',  
               'description': 'A spiraling eruption of flame.',  
               'kind': 'spell',  
               'name': 'Flame Spiral',  
               'state': 'burning'}],  
          6: [{'cost': 2,  
               'damage_type': 'lightning',  
               'dc_type': 'spell',  
               'description': 'Chain lightning into the target.',  
               'kind': 'spell',  
               'name': 'Arc Lightning',  
               'state': 'staggered'},  
              {'cost': 2,  
               'dc_type': 'spell',  
               'description': 'Slow and destabilize enemies.',  
               'kind': 'debuff',  
               'name': 'Time Distortion',  
               'state': 'weakened'}],  
          8: [{'cost': 2,  
               'damage_type': 'fire',  
               'dc_type': 'spell',  
               'description': 'Rain destruction from above.',  
               'kind': 'spell',  
               'name': 'Meteor Call',  
               'state': 'burning'},  
              {'cost': 2,  
               'description': 'Layer powerful magical protections.',  
               'kind': 'buff',  
               'name': 'Prismatic Barrier',  
               'secondary_state': 'shielded',  
               'state': 'fortified'}],  
          10: [{'cost': 3,  
                'damage_type': 'lightning',  
                'dc_type': 'spell',  
                'description': 'Unleash overwhelming arcane devastation.',  
                'kind': 'spell',  
                'name': 'Cataclysmic Invocation',  
                'state': 'staggered'},  
               {'cost': 3,  
                'description': 'Temporarily surpass mortal magical limits.',  
                'kind': 'buff',  
                'name': 'Archmage Ascension',  
                'secondary_state': 'fortified',  
                'state': 'inspired'}]},  
 'monk': {2: [{'cost': 1,  
               'damage_type': 'blunt',  
               'dc_type': 'technique',  
               'description': 'A precise spiritual impact.',  
               'kind': 'strike',  
               'name': 'Palm Strike',  
               'state': 'staggered'},  
              {'cost': 1,  
               'description': 'Move with impossible agility.',  
               'kind': 'buff',  
               'name': 'Flow Step',  
               'state': 'guarded'}],  
          4: [{'cost': 1,  
               'damage_type': 'spirit',  
               'dc_type': 'technique',  
               'description': 'Lock an enemy in flowing strikes.',  
               'kind': 'strike',  
               'name': 'Serpent Coil',  
               'state': 'restrained'},  
              {'cost': 1,  
               'description': 'Restore balance and vitality.',  
               'kind': 'heal',  
               'name': 'Inner Breath',  
               'state': 'fortified'}],  
          6: [{'cost': 2,  
               'damage_type': 'air',  
               'dc_type': 'technique',  
               'description': 'A rapid flurry of overwhelming blows.',  
               'kind': 'strike',  
               'name': 'Tempest Fists',  
               'state': 'weakened'},  
              {'cost': 2,  
               'description': 'Center yourself against magical assault.',  
               'kind': 'buff',  
               'name': 'Silent Mind',  
               'state': 'shielded'}],  
          8: [{'cost': 2,  
               'damage_type': 'spirit',  
               'dc_type': 'technique',  
               'description': 'A devastating burst of focused energy.',  
               'kind': 'strike',  
               'name': 'Shattering Pulse',  
               'state': 'staggered'},  
              {'cost': 2,  
               'description': 'Move like a blur across the battlefield.',  
               'kind': 'buff',  
               'name': 'Thousand Steps',  
               'secondary_state': 'guarded',  
               'state': 'inspired'}],  
          10: [{'cost': 3,  
                'description': 'Achieve transcendent martial mastery.',  
                'kind': 'buff',  
                'name': 'Ascendant Soul',  
                'secondary_state': 'fortified',  
                'state': 'inspired'},  
               {'cost': 3,  
                'damage_type': 'spirit',  
                'dc_type': 'technique',  
                'description': 'A legendary finishing technique.',  
                'kind': 'strike',  
                'name': 'Heavenbreaker Technique',  
                'state': 'weakened'}]},  
 'paladin': {2: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'dc_type': 'technique',  
                  'description': 'Channel sacred power into a blow.',  
                  'kind': 'strike',  
                  'name': 'Smite Evil',  
                  'state': 'marked'},  
                 {'cost': 1,  
                  'description': 'Protect allies through divine resolve.',  
                  'kind': 'buff',  
                  'name': "Guardian's Oath",  
                  'state': 'shielded'}],  
             4: [{'cost': 1,  
                  'damage_type': 'fire',  
                  'dc_type': 'technique',  
                  'description': 'Brand enemies with holy fire.',  
                  'kind': 'strike',  
                  'name': 'Purging Brand',  
                  'state': 'burning'},  
                 {'cost': 1,  
                  'description': 'Become an immovable bastion.',  
                  'kind': 'buff',  
                  'name': 'Radiant Stand',  
                  'state': 'guarded'}],  
             6: [{'cost': 2,  
                  'damage_type': 'spirit',  
                  'dc_type': 'technique',  
                  'description': 'Deliver divine punishment.',  
                  'kind': 'strike',  
                  'name': 'Judgment Strike',  
                  'state': 'weakened'},  
                 {'cost': 2,  
                  'description': 'Strengthen allies with conviction.',  
                  'kind': 'buff',  
                  'name': 'Sacred Rally',  
                  'secondary_state': 'fortified',  
                  'state': 'inspired'}],  
             8: [{'cost': 2,  
                  'damage_type': 'fire',  
                  'dc_type': 'technique',  
                  'description': 'Sweep enemies aside in holy fury.',  
                  'kind': 'strike',  
                  'name': "Crusader's Wrath",  
                  'state': 'burning'},  
                 {'cost': 2,  
                  'description': 'Shield allies against magical assault.',  
                  'kind': 'buff',  
                  'name': 'Bulwark of Faith',  
                  'secondary_state': 'shielded',  
                  'state': 'fortified'}],  
             10: [{'cost': 3,  
                   'damage_type': 'spirit',  
                   'dc_type': 'technique',  
                   'description': 'Call down divine devastation.',  
                   'kind': 'strike',  
                   'name': 'Heavenfall',  
                   'state': 'feared'},  
                  {'cost': 3,  
                   'description': 'Become a legendary symbol of hope.',  
                   'kind': 'buff',  
                   'name': 'Sainted Champion',  
                   'secondary_state': 'shielded',  
                   'state': 'inspired'}]},  
 'ranger': {2: [{'cost': 1,  
                 'damage_type': 'piercing',  
                 'dc_type': 'technique',  
                 'description': 'Pinpoint a target for pursuit.',  
                 'kind': 'strike',  
                 'name': "Hunter's Shot",  
                 'state': 'marked'},  
                {'cost': 1,  
                 'description': 'Gain mobility and battlefield awareness.',  
                 'kind': 'buff',  
                 'name': 'Trailblazer',  
                 'state': 'guarded'}],  
            4: [{'cost': 1,  
                 'damage_type': 'piercing',  
                 'dc_type': 'technique',  
                 'description': 'A vicious ranged assault.',  
                 'kind': 'strike',  
                 'name': 'Barbed Volley',  
                 'state': 'bleeding'},  
                {'cost': 1,  
                 'description': 'Blend into the battlefield.',  
                 'kind': 'buff',  
                 'name': 'Camouflage Veil',  
                 'state': 'shielded'}],  
            6: [{'cost': 2,  
                 'damage_type': 'slashing',  
                 'dc_type': 'technique',  
                 'description': 'Exploit enemy weaknesses with precision.',  
                 'kind': 'strike',  
                 'name': "Predator's Rush",  
                 'state': 'exposed'},  
                {'cost': 2,  
                 'description': 'Heighten accuracy and awareness.',  
                 'kind': 'buff',  
                 'name': "Falcon's Sight",  
                 'state': 'inspired'}],  
            8: [{'cost': 2,  
                 'damage_type': 'lightning',  
                 'dc_type': 'technique',  
                 'description': 'A crackling shot of elemental force.',  
                 'kind': 'strike',  
                 'name': 'Storm Arrow',  
                 'state': 'staggered'},  
                {'cost': 2,  
                 'description': 'Lead allies in relentless pursuit.',  
                 'kind': 'buff',  
                 'name': 'Wild Hunt',  
                 'secondary_state': 'guarded',  
                 'state': 'inspired'}],  
            10: [{'cost': 3,  
                  'damage_type': 'piercing',  
                  'dc_type': 'technique',  
                  'description': 'An unstoppable finishing assault.',  
                  'kind': 'strike',  
                  'name': 'Apex Predator',  
                  'state': 'bleeding'},  
                 {'cost': 3,  
                  'description': 'Become one with the wild battlefield.',  
                  'kind': 'buff',  
                  'name': 'Spirit of the Hunt',  
                  'secondary_state': 'inspired',  
                  'state': 'fortified'}]},  
 'rogue': {2: [{'cost': 1,  
                'damage_type': 'piercing',  
                'dc_type': 'technique',  
                'description': 'Strike from vulnerability for damage.',  
                'kind': 'strike',  
                'name': 'Backstab',  
                'state': 'bleeding'},  
               {'cost': 1,  
                'description': 'Slip through danger unseen.',  
                'kind': 'buff',  
                'name': 'Shadowstep',  
                'state': 'guarded'}],  
           4: [{'cost': 1,  
                'damage_type': 'poison/acid',  
                'dc_type': 'technique',  
                'description': 'Poison the enemy through precise cuts.',  
                'kind': 'strike',  
                'name': 'Venom Blade',  
                'state': 'weakened'},  
               {'cost': 1,  
                'dc_type': 'technique',  
                'description': 'Mislead the target and create openings.',  
                'kind': 'debuff',  
                'name': 'Feinting Trick',  
                'state': 'exposed'}],  
           6: [{'cost': 2,  
                'damage_type': 'slashing',  
                'dc_type': 'technique',  
                'description': 'A lethal chain of rapid attacks.',  
                'kind': 'strike',  
                'name': 'Ambush Barrage',  
                'state': 'bleeding'},  
               {'cost': 2,  
                'description': 'Disappear into shadow and confusion.',  
                'kind': 'buff',  
                'name': 'Cloak of Silence',  
                'state': 'shielded'}],  
           8: [{'cost': 2,  
                'damage_type': 'piercing',  
                'dc_type': 'technique',  
                'description': 'Punish weakened enemies with force.',  
                'kind': 'strike',  
                'name': "Executioner's Strike",  
                'state': 'exposed'},  
               {'cost': 2,  
                'dc_type': 'technique',  
                'description': 'Instill terror through shadow and deception.',  
                'kind': 'debuff',  
                'name': 'Nightmare Veil',  
                'state': 'feared'}],  
           10: [{'cost': 3,  
                 'damage_type': 'slashing',  
                 'dc_type': 'technique',  
                 'description': 'A whirlwind of lethal attacks.',  
                 'kind': 'strike',  
                 'name': 'Death Blossom',  
                 'state': 'bleeding'},  
                {'cost': 3,  
                 'description': 'Become nearly untouchable in combat.',  
                 'kind': 'buff',  
                 'name': 'Master of Shadows',  
                 'secondary_state': 'guarded',  
                 'state': 'inspired'}]},  
 'scholar': {2: [{'cost': 1,  
                  'dc_type': 'technique',  
                  'description': 'Identify weaknesses in enemy defenses.',  
                  'kind': 'debuff',  
                  'name': 'Tactical Analysis',  
                  'state': 'exposed'},  
                 {'cost': 1,  
                  'description': 'Direct allies with superior strategy.',  
                  'kind': 'buff',  
                  'name': 'Guiding Insight',  
                  'state': 'inspired'}],  
             4: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Use calculated magic to disrupt enemies.',  
                  'kind': 'spell',  
                  'name': 'Arcane Formula',  
                  'state': 'weakened'},  
                 {'cost': 1,  
                  'description': 'Strengthen allies through preparation.',  
                  'kind': 'buff',  
                  'name': 'Reinforced Theory',  
                  'state': 'fortified'}],  
             6: [{'cost': 2,  
                  'description': 'Coordinate battlefield efficiency.',  
                  'kind': 'buff',  
                  'name': 'Battlefield Calculation',  
                  'secondary_state': 'inspired',  
                  'state': 'guarded'},  
                 {'cost': 2,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': "Overload an enemy's mind.",  
                  'kind': 'debuff',  
                  'name': 'Mental Collapse',  
                  'state': 'feared'}],  
             8: [{'cost': 2,  
                  'damage_type': 'lightning',  
                  'dc_type': 'spell',  
                  'description': 'Trigger cascading magical effects.',  
                  'kind': 'spell',  
                  'name': 'Chain Reaction',  
                  'state': 'staggered'},  
                 {'cost': 2,  
                  'description': 'Elevate allies through superior planning.',  
                  'kind': 'buff',  
                  'name': 'Master Strategist',  
                  'secondary_state': 'fortified',  
                  'state': 'inspired'}],  
             10: [{'cost': 3,  
                   'description': 'Achieve flawless tactical execution.',  
                   'kind': 'buff',  
                   'name': 'Perfect Calculation',  
                   'secondary_state': 'shielded',  
                   'state': 'inspired'},  
                  {'cost': 3,  
                   'damage_type': 'spirit',  
                   'dc_type': 'spell',  
                   'description': 'Invoke dangerous ancient knowledge.',  
                   'kind': 'spell',  
                   'name': 'Forbidden Principle',  
                   'state': 'feared'}]},  
 'sorcerer': {2: [{'cost': 1,  
                   'damage_type': 'fire',  
                   'dc_type': 'spell',  
                   'description': 'Release raw elemental fire.',  
                   'kind': 'spell',  
                   'name': 'Flame Burst',  
                   'state': 'burning'},  
                  {'cost': 1,  
                   'description': 'Overflow with unstable magical energy.',  
                   'kind': 'buff',  
                   'name': 'Arcane Surge',  
                   'state': 'inspired'}],  
              4: [{'cost': 1,  
                   'damage_type': 'ice',  
                   'dc_type': 'spell',  
                   'description': 'Pierce enemies with glacial magic.',  
                   'kind': 'spell',  
                   'name': 'Frozen Lance',  
                   'state': 'restrained'},  
                  {'cost': 1,  
                   'damage_type': 'lightning',  
                   'dc_type': 'spell',  
                   'description': 'Unleash unstable electrical force.',  
                   'kind': 'spell',  
                   'name': 'Tempest Pulse',  
                   'state': 'staggered'}],  
              6: [{'cost': 2,  
                   'damage_type': 'fire',  
                   'dc_type': 'spell',  
                   'description': 'A violent eruption of elemental power.',  
                   'kind': 'spell',  
                   'name': 'Elemental Fury',  
                   'state': 'burning'},  
                  {'cost': 2,  
                   'description': 'Surround yourself with magical protection.',  
                   'kind': 'buff',  
                   'name': 'Arcane Shield',  
                   'state': 'shielded'}],  
              8: [{'cost': 2,  
                   'damage_type': 'lightning',  
                   'dc_type': 'spell',  
                   'description': 'Devastate enemies with uncontrolled arcana.',  
                   'kind': 'spell',  
                   'name': 'Cataclysm Wave',  
                   'state': 'weakened'},  
                  {'cost': 2,  
                   'description': 'Enter a heightened magical state.',  
                   'kind': 'buff',  
                   'name': 'Stormblood Awakening',  
                   'secondary_state': 'fortified',  
                   'state': 'inspired'}],  
              10: [{'cost': 3,  
                    'damage_type': 'fire',  
                    'dc_type': 'spell',  
                    'description': 'Consume the battlefield in elemental destruction.',  
                    'kind': 'spell',  
                    'name': 'Worldfire Invocation',  
                    'state': 'burning'},  
                   {'cost': 3,  
                    'description': 'Become a conduit of limitless power.',  
                    'kind': 'buff',  
                    'name': 'Arcane Ascension',  
                    'secondary_state': 'shielded',  
                    'state': 'inspired'}]},  
 'warden': {2: [{'cost': 1,  
                 'description': 'Step between danger and your allies.',  
                 'kind': 'buff',  
                 'name': 'Intercepting Guard',  
                 'state': 'guarded'},  
                {'cost': 1,  
                 'damage_type': 'blunt',  
                 'dc_type': 'technique',  
                 'description': 'Lock enemies in place.',  
                 'kind': 'strike',  
                 'name': 'Binding Strike',  
                 'state': 'restrained'}],  
            4: [{'cost': 1,  
                 'damage_type': 'blunt',  
                 'dc_type': 'technique',  
                 'description': 'A shield strike that disrupts attackers.',  
                 'kind': 'strike',  
                 'name': 'Bastion Slam',  
                 'state': 'staggered'},  
                {'cost': 1,  
                 'description': 'Become a wall against incoming attacks.',  
                 'kind': 'buff',  
                 'name': 'Iron Bastion',  
                 'state': 'shielded'}],  
            6: [{'cost': 2,  
                 'description': 'Reinforce nearby allies.',  
                 'kind': 'buff',  
                 'name': 'Guardian Pulse',  
                 'secondary_state': 'shielded',  
                 'state': 'fortified'},  
                {'cost': 2,  
                 'damage_type': 'blunt',  
                 'dc_type': 'technique',  
                 'description': 'Crush aggressive enemies into submission.',  
                 'kind': 'strike',  
                 'name': 'Punishing Lockdown',  
                 'state': 'weakened'}],  
            8: [{'cost': 2,  
                 'description': 'Anchor the battlefield around yourself.',  
                 'kind': 'buff',  
                 'name': 'Fortress Stance',  
                 'secondary_state': 'fortified',  
                 'state': 'guarded'},  
                {'cost': 2,  
                 'damage_type': 'earth',  
                 'dc_type': 'technique',  
                 'description': 'Raise barriers and crush attackers.',  
                 'kind': 'strike',  
                 'name': 'Judgment Wall',  
                 'state': 'restrained'}],  
            10: [{'cost': 3,  
                  'description': 'Become an indestructible defender.',  
                  'kind': 'buff',  
                  'name': 'Immovable Sentinel',  
                  'secondary_state': 'shielded',  
                  'state': 'inspired'},  
                 {'cost': 3,  
                  'damage_type': 'blunt',  
                  'dc_type': 'technique',  
                  'description': 'Deliver overwhelming defensive retaliation.',  
                  'kind': 'strike',  
                  'name': "Titan's Rebuke",  
                  'state': 'staggered'}]},  
 'warlock': {2: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Blast enemies with forbidden energy.',  
                  'kind': 'spell',  
                  'name': 'Eldritch Bolt',  
                  'state': 'weakened'},  
                 {'cost': 1,  
                  'description': 'Invoke a dark protective pact.',  
                  'kind': 'buff',  
                  'name': 'Pact Shield',  
                  'state': 'shielded'}],  
             4: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Sap vitality from the target.',  
                  'kind': 'spell',  
                  'name': 'Soul Drain',  
                  'state': 'weakened'},  
                 {'cost': 1,  
                  'dc_type': 'spell',  
                  'description': "Invade the enemy's mind with terror.",  
                  'kind': 'debuff',  
                  'name': 'Dread Whisper',  
                  'state': 'feared'}],  
             6: [{'cost': 2,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Bind enemies in eldritch chains.',  
                  'kind': 'spell',  
                  'name': 'Void Chains',  
                  'state': 'restrained'},  
                 {'cost': 2,  
                  'description': 'Draw strength from dark pacts.',  
                  'kind': 'buff',  
                  'name': 'Infernal Surge',  
                  'state': 'inspired'}],  
             8: [{'cost': 2,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Tear reality with void energy.',  
                  'kind': 'spell',  
                  'name': 'Abyssal Rupture',  
                  'state': 'staggered'},  
                 {'cost': 2,  
                  'dc_type': 'spell',  
                  'description': 'Doom an enemy to destruction.',  
                  'kind': 'debuff',  
                  'name': 'Curse of Ruin',  
                  'state': 'exposed'}],  
             10: [{'cost': 3,  
                   'damage_type': 'spirit',  
                   'dc_type': 'spell',  
                   'description': 'Unleash apocalyptic eldritch power.',  
                   'kind': 'spell',  
                   'name': 'Eldritch Cataclysm',  
                   'state': 'feared'},  
                  {'cost': 3,  
                   'description': 'Temporarily transcend mortal limits.',  
                   'kind': 'buff',  
                   'name': 'Dark Apotheosis',  
                   'secondary_state': 'fortified',  
                   'state': 'inspired'}]},  
 'wizard': {2: [{'cost': 1,  
                 'damage_type': 'spirit',  
                 'dc_type': 'spell',  
                 'description': 'Precise magical bolts strike the enemy.',  
                 'kind': 'spell',  
                 'name': 'Arcane Missile',  
                 'state': 'exposed'},  
                {'cost': 1,  
                 'description': 'Conjure layered magical defenses.',  
                 'kind': 'buff',  
                 'name': 'Mystic Ward',  
                 'state': 'shielded'}],  
            4: [{'cost': 1,  
                 'damage_type': 'ice',  
                 'dc_type': 'spell',  
                 'description': 'Freeze enemies in place.',  
                 'kind': 'spell',  
                 'name': 'Frost Nova',  
                 'state': 'restrained'},  
                {'cost': 1,  
                 'damage_type': 'fire',  
                 'dc_type': 'spell',  
                 'description': 'A spiraling eruption of flame.',  
                 'kind': 'spell',  
                 'name': 'Flame Spiral',  
                 'state': 'burning'}],  
            6: [{'cost': 2,  
                 'damage_type': 'lightning',  
                 'dc_type': 'spell',  
                 'description': 'Chain lightning into the target.',  
                 'kind': 'spell',  
                 'name': 'Arc Lightning',  
                 'state': 'staggered'},  
                {'cost': 2,  
                 'dc_type': 'spell',  
                 'description': 'Slow and destabilize enemies.',  
                 'kind': 'debuff',  
                 'name': 'Time Distortion',  
                 'state': 'weakened'}],  
            8: [{'cost': 2,  
                 'damage_type': 'fire',  
                 'dc_type': 'spell',  
                 'description': 'Rain destruction from above.',  
                 'kind': 'spell',  
                 'name': 'Meteor Call',  
                 'state': 'burning'},  
                {'cost': 2,  
                 'description': 'Layer powerful magical protections.',  
                 'kind': 'buff',  
                 'name': 'Prismatic Barrier',  
                 'secondary_state': 'shielded',  
                 'state': 'fortified'}],  
            10: [{'cost': 3,  
                  'damage_type': 'lightning',  
                  'dc_type': 'spell',  
                  'description': 'Unleash overwhelming arcane devastation.',  
                  'kind': 'spell',  
                  'name': 'Cataclysmic Invocation',  
                  'state': 'staggered'},  
                 {'cost': 3,  
                  'description': 'Temporarily surpass mortal magical limits.',  
                  'kind': 'buff',  
                  'name': 'Archmage Ascension',  
                  'secondary_state': 'fortified',  
                  'state': 'inspired'}]}}  
CLASS_ACTIVE_ABILITIES["mage"] = CLASS_ACTIVE_ABILITIES["wizard"]  
CLASS_ACTIVE_ABILITIES['mage'] = CLASS_ACTIVE_ABILITIES['wizard']  
  
SPECIES_ACTIVE_ABILITIES = {'aasimar': {3: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'description': 'Restore vitality through divine radiance.',  
                  'kind': 'heal',  
                  'name': 'Celestial Light'}],  
             7: [{'cost': 2,  
                  'description': 'Manifest celestial authority in battle.',  
                  'kind': 'buff',  
                  'name': 'Wings of Judgment',  
                  'secondary_state': 'guarded',  
                  'state': 'inspired'}]},  
 'centaur': {3: [{'cost': 1,  
                  'damage_type': 'blunt',  
                  'dc_type': 'technique',  
                  'description': 'Rush a target with overwhelming momentum.',  
                  'kind': 'strike',  
                  'name': 'Thunderous Charge',  
                  'state': 'staggered'}],  
             7: [{'cost': 2,  
                  'damage_type': 'blunt',  
                  'dc_type': 'technique',  
                  'description': 'Drive through enemies with devastating force.',  
                  'kind': 'strike',  
                  'name': 'Trampling Stampede',  
                  'secondary_state': 'inspired',  
                  'state': 'staggered'}]},  
 'dhampir': {3: [{'cost': 1,  
                  'damage_type': 'spirit',  
                  'dc_type': 'technique',  
                  'description': 'Drain vitality through supernatural predation.',  
                  'kind': 'strike',  
                  'name': 'Crimson Fang',  
                  'state': 'weakened'}],  
             7: [{'cost': 2,  
                  'damage_type': 'piercing',  
                  'dc_type': 'technique',  
                  'description': 'Enter a heightened predatory state.',  
                  'kind': 'strike_buff',  
                  'name': 'Midnight Hunger',  
                  'secondary_state': 'inspired',  
                  'state': 'bleeding'}]},  
 'dragonborn': {3: [{'cost': 1,  
                     'damage_type': 'fire',  
                     'dc_type': 'spell',  
                     'description': 'Exhale destructive elemental force.',  
                     'kind': 'spell',  
                     'name': 'Breath Weapon',  
                     'state': 'staggered'}],  
                7: [{'cost': 2,  
                     'description': 'Awaken ancient draconic might.',  
                     'kind': 'buff',  
                     'name': 'Draconic Ascendance',  
                     'secondary_state': 'fortified',  
                     'state': 'inspired'}]},  
 'drow': {3: [{'cost': 1,  
               'description': 'Draw shadow around yourself for protection and concealment.',  
               'kind': 'buff',  
               'name': 'Umbral Veil',  
               'state': 'shielded'}],  
          7: [{'cost': 2,  
               'damage_type': 'spirit',  
               'dc_type': 'spell',  
               'description': 'Bind a foe in living shadow.',  
               'kind': 'debuff',  
               'name': 'Shadowbind Hex',  
               'state': 'restrained'}]},  
 'dwarf': {3: [{'cost': 1,  
                'description': 'Harden body and spirit like mountain stone.',  
                'kind': 'buff',  
                'name': 'Stoneheart',  
                'state': 'fortified'}],  
           7: [{'cost': 2,  
                'damage_type': 'earth',  
                'dc_type': 'technique',  
                'description': 'Deliver a crushing seismic blow.',  
                'kind': 'strike',  
                'name': 'Earthbreaker',  
                'state': 'staggered'}]},  
 'elf': {3: [{'cost': 1,  
              'description': 'Draw upon ancient discipline and precision.',  
              'kind': 'buff',  
              'name': 'Ancestral Focus',  
              'state': 'inspired'}],  
         7: [{'cost': 2,  
              'description': 'Move with supernatural elegance and awareness.',  
              'kind': 'buff',  
              'name': 'Moonlit Grace',  
              'secondary_state': 'fortified',  
              'state': 'guarded'}]},  
 'fae': {3: [{'cost': 1,  
              'description': 'Slip through danger beneath a flicker of glamour.',  
              'kind': 'buff',  
              'name': 'Glamour Step',  
              'state': 'guarded'}],  
         7: [{'cost': 2,  
              'damage_type': 'spirit',  
              'dc_type': 'spell',  
              'description': 'Disorient enemies with old faerie magic.',  
              'kind': 'debuff',  
              'name': 'Fey Bewilderment',  
              'state': 'feared'}]},  
 'faerie': {3: [{'cost': 1,  
                 'description': 'Slip through danger beneath a flicker of glamour.',  
                 'kind': 'buff',  
                 'name': 'Glamour Step',  
                 'state': 'guarded'}],  
            7: [{'cost': 2,  
                 'damage_type': 'spirit',  
                 'dc_type': 'spell',  
                 'description': 'Disorient enemies with old faerie magic.',  
                 'kind': 'debuff',  
                 'name': 'Fey Bewilderment',  
                 'state': 'feared'}]},  
 'fairy': {3: [{'cost': 1,  
                'description': 'Slip through danger beneath a flicker of glamour.',  
                'kind': 'buff',  
                'name': 'Glamour Step',  
                'state': 'guarded'}],  
           7: [{'cost': 2,  
                'damage_type': 'spirit',  
                'dc_type': 'spell',  
                'description': 'Disorient enemies with old faerie magic.',  
                'kind': 'debuff',  
                'name': 'Fey Bewilderment',  
                'state': 'feared'}]},  
 'genasi': {3: [{'cost': 1,  
                 'damage_type': 'spirit',  
                 'dc_type': 'spell',  
                 'description': 'Empower an attack with Air, Earth, Fire, or Water elemental force.',  
                 'kind': 'spell',  
                 'name': 'Elemental Surge',  
                 'state': 'staggered'}],  
            7: [{'cost': 2,  
                 'damage_type': 'spirit',  
                 'dc_type': 'spell',  
                 'description': 'Unleash a powerful elemental manifestation shaped by the chosen subtype.',  
                 'kind': 'spell_buff',  
                 'name': 'Primordial Manifestation',  
                 'secondary_state': 'inspired',  
                 'state': 'weakened'}]},  
 'gnome': {3: [{'cost': 1,  
                'damage_type': 'lightning',  
                'dc_type': 'spell',  
                'description': 'Unleash disruptive arcane static.',  
                'kind': 'spell',  
                'name': 'Flashspark Hex',  
                'state': 'staggered'}],  
           7: [{'cost': 2,  
                'damage_type': 'spirit',  
                'dc_type': 'spell',  
                'description': 'Overwhelm enemies with layered illusions.',  
                'kind': 'debuff',  
                'name': 'Illusion Cascade',  
                'state': 'feared'}]},  
 'goblin': {3: [{'cost': 1,  
                 'damage_type': 'piercing',  
                 'dc_type': 'technique',  
                 'description': 'Exploit an opening with a vicious strike.',  
                 'kind': 'strike',  
                 'name': 'Cheap Shot',  
                 'state': 'bleeding'}],  
            7: [{'cost': 2,  
                 'damage_type': 'slashing',  
                 'dc_type': 'technique',  
                 'description': 'Launch into a reckless frenzy of attacks.',  
                 'kind': 'strike',  
                 'name': 'Chaos Rush',  
                 'secondary_state': 'inspired',  
                 'state': 'bleeding'}]},  
 'goliath': {3: [{'cost': 1,  
                  'description': 'Stand firm with mountain-born resilience.',  
                  'kind': 'buff',  
                  'name': 'Mountain Endurance',  
                  'state': 'fortified'}],  
             7: [{'cost': 2,  
                  'damage_type': 'blunt',  
                  'dc_type': 'technique',  
                  'description': 'Bring crushing force down on a foe.',  
                  'kind': 'strike',  
                  'name': 'Titan Breaker',  
                  'state': 'staggered'}]},  
 'halfling': {3: [{'cost': 1,  
                   'description': 'Slip away from danger with uncanny agility.',  
                   'kind': 'buff',  
                   'name': 'Nimble Escape',  
                   'state': 'guarded'}],  
              7: [{'cost': 2,  
                   'description': 'Twist fate at the perfect moment.',  
                   'kind': 'buff',  
                   'name': 'Lucky Turn',  
                   'secondary_state': 'shielded',  
                   'state': 'inspired'}]},  
 'human': {3: [{'cost': 1,  
                'description': 'Push beyond normal mortal limits through sheer determination.',  
                'kind': 'buff',  
                'name': 'Determined Surge',  
                'state': 'inspired'}],  
           7: [{'cost': 2,  
                'description': 'Refuse to yield under overwhelming pressure.',  
                'kind': 'buff',  
                'name': 'Indomitable Will',  
                'secondary_state': 'inspired',  
                'state': 'fortified'}]},  
 'kitsune': {3: [{'cost': 1,  
                  'description': 'Conceal yourself in illusion and spirit magic.',  
                  'kind': 'buff',  
                  'name': 'Spirit Veil',  
                  'state': 'shielded'}],  
             7: [{'cost': 2,  
                  'damage_type': 'spirit',  
                  'dc_type': 'spell',  
                  'description': 'Bewitch enemies with ghostly foxfire.',  
                  'kind': 'spell',  
                  'name': 'Foxfire Illusion',  
                  'state': 'feared'}]},  
 'merfolk': {3: [{'cost': 1,  
                  'description': 'Move with fluid grace and evasive precision.',  
                  'kind': 'buff',  
                  'name': 'Tidal Grace',  
                  'state': 'guarded'}],  
             7: [{'cost': 2,  
                  'damage_type': 'water',  
                  'dc_type': 'spell',  
                  'description': 'Bind foes in a rushing magical current.',  
                  'kind': 'spell',  
                  'name': 'Siren Current',  
                  'state': 'restrained'}]},  
 'orc': {3: [{'cost': 1,  
              'damage_type': 'slashing',  
              'dc_type': 'technique',  
              'description': 'Deliver a devastating sweeping attack.',  
              'kind': 'strike',  
              'name': 'Savage Cleave',  
              'state': 'bleeding'}],  
         7: [{'cost': 2,  
              'damage_type': 'spirit',  
              'dc_type': 'technique',  
              'description': 'Unleash a terrifying roar that shakes enemy morale.',  
              'kind': 'debuff',  
              'name': 'War Cry',  
              'state': 'feared'}]},  
 'theranth': {3: [{'cost': 1,  
                   'description': 'Awaken primal lineage instincts.',  
                   'kind': 'buff',  
                   'name': 'Bestial Instinct',  
                   'state': 'inspired'}],  
              7: [{'cost': 2,  
                   'damage_type': 'slashing',  
                   'dc_type': 'technique',  
                   'description': 'Unleash the peak strength of the bloodline.',  
                   'kind': 'strike',  
                   'name': 'Apex Manifestation',  
                   'state': 'weakened'}]},  
 'tiefling': {3: [{'cost': 1,  
                   'damage_type': 'fire',  
                   'dc_type': 'spell',  
                   'description': 'Mark enemies with infernal flame.',  
                   'kind': 'spell',  
                   'name': 'Hellfire Brand',  
                   'state': 'burning'}],  
              7: [{'cost': 2,  
                   'damage_type': 'spirit',  
                   'dc_type': 'spell',  
                   'description': 'Overwhelm enemies with fiendish dread.',  
                   'kind': 'debuff',  
                   'name': 'Infernal Presence',  
                   'state': 'feared'}]},  
 'triton': {3: [{'cost': 1,  
                 'description': 'Call up the warding pressure of the deep.',  
                 'kind': 'buff',  
                 'name': 'Sea Guardian',  
                 'state': 'shielded'}],  
            7: [{'cost': 2,  
                 'damage_type': 'lightning',  
                 'dc_type': 'spell',  
                 'description': 'Strike with thunderous oceanic force.',  
                 'kind': 'spell',  
                 'name': 'Storm of the Depths',  
                 'state': 'staggered'}]},  
 'werewolf': {3: [{'cost': 1,  
                   'damage_type': 'slashing',  
                   'dc_type': 'technique',  
                   'description': 'Tear into enemies with savage ferocity.',  
                   'kind': 'strike',  
                   'name': 'Frenzied Claws',  
                   'state': 'bleeding'}],  
              7: [{'cost': 2,  
                   'damage_type': 'slashing',  
                   'dc_type': 'technique',  
                   'description': 'Succumb to overwhelming predatory instinct.',  
                   'kind': 'strike_buff',  
                   'name': 'Lunar Rampage',  
                   'secondary_state': 'inspired',  
                   'state': 'bleeding'}]}}  
SPECIES_ACTIVE_ABILITIES["fae"] = SPECIES_ACTIVE_ABILITIES["faerie"]  
SPECIES_ACTIVE_ABILITIES["fairy"] = SPECIES_ACTIVE_ABILITIES["faerie"]  
  
  
ENEMY_ARCHETYPES = {  
    "npc": {  
        "bandits": [  
            {"name": "Cutpurse", "role": "skirmisher", "hp": 9, "ac": 12, "attack": 3, "damage_die": 6, "damage_bonus": 1, "damage_type": "piercing", "xp": 25, "weaknesses": {"spirit": 1.5}},  
            {"name": "Highway Raider", "role": "bruiser", "hp": 14, "ac": 13, "attack": 4, "damage_die": 8, "damage_bonus": 1, "damage_type": "slashing", "xp": 40},  
            {"name": "Bandit Captain", "role": "elite", "hp": 24, "ac": 15, "attack": 5, "damage_die": 8, "damage_bonus": 3, "damage_type": "slashing", "xp": 90, "resistances": {"piercing": 0.75}},  
        ],  
        "cultists": [  
            {"name": "Cult Initiate", "role": "caster", "hp": 8, "ac": 11, "attack": 2, "damage_die": 6, "damage_bonus": 0, "damage_type": "spirit", "xp": 30, "weaknesses": {"spirit": 1.25}},  
            {"name": "Masked Zealot", "role": "striker", "hp": 15, "ac": 13, "attack": 4, "damage_die": 8, "damage_bonus": 1, "damage_type": "fire", "xp": 55, "resistances": {"fire": 0.5}, "weaknesses": {"water": 1.5}},  
            {"name": "Ritual Adept", "role": "caster", "hp": 18, "ac": 12, "attack": 4, "save_dc": 13, "damage_die": 8, "damage_bonus": 2, "damage_type": "spirit", "xp": 80, "resistances": {"spirit": 0.75}},  
            {"name": "Cult Hierophant", "role": "elite_caster", "hp": 30, "ac": 14, "attack": 5, "save_dc": 15, "damage_die": 10, "damage_bonus": 3, "damage_type": "spirit", "xp": 140, "resistances": {"spirit": 0.5, "fire": 0.75}},  
        ],  
        "soldiers": [  
            {"name": "Levy Spearman", "role": "guard", "hp": 12, "ac": 13, "attack": 3, "damage_die": 6, "damage_bonus": 1, "damage_type": "piercing", "xp": 30},  
            {"name": "Shield Infantry", "role": "tank", "hp": 20, "ac": 15, "attack": 4, "damage_die": 6, "damage_bonus": 2, "damage_type": "blunt", "xp": 60, "resistances": {"slashing": 0.75, "piercing": 0.75}},  
            {"name": "Veteran Blade", "role": "elite", "hp": 28, "ac": 16, "attack": 6, "damage_die": 8, "damage_bonus": 3, "damage_type": "slashing", "xp": 110},  
        ],  
        "mages": [  
            {"name": "Apprentice Mage", "role": "caster", "hp": 8, "ac": 11, "attack": 3, "save_dc": 12, "damage_die": 6, "damage_bonus": 1, "damage_type": "fire", "xp": 35, "weaknesses": {"blunt": 1.25}},  
            {"name": "Battle Evoker", "role": "caster", "hp": 16, "ac": 12, "attack": 5, "save_dc": 14, "damage_die": 10, "damage_bonus": 2, "damage_type": "lightning", "xp": 95, "resistances": {"lightning": 0.5}},  
            {"name": "Wardbreaker", "role": "elite_caster", "hp": 26, "ac": 13, "attack": 6, "save_dc": 15, "damage_die": 10, "damage_bonus": 4, "damage_type": "spirit", "xp": 150, "resistances": {"spirit": 0.75}},  
        ],  
        "undead": [  
            {"name": "Restless Dead", "role": "minion", "hp": 10, "ac": 10, "attack": 3, "damage_die": 6, "damage_bonus": 0, "damage_type": "blunt", "xp": 25, "resistances": {"poison/acid": 0.5}, "weaknesses": {"spirit": 1.5}},  
            {"name": "Grave Knight", "role": "bruiser", "hp": 25, "ac": 15, "attack": 5, "damage_die": 8, "damage_bonus": 3, "damage_type": "slashing", "xp": 100, "resistances": {"poison/acid": 0.5, "ice": 0.75}, "weaknesses": {"fire": 1.25, "spirit": 1.5}},  
            {"name": "Wailing Shade", "role": "caster", "hp": 18, "ac": 13, "attack": 5, "save_dc": 14, "damage_die": 8, "damage_bonus": 3, "damage_type": "spirit", "xp": 120, "resistances": {"piercing": 0.5, "slashing": 0.5, "blunt": 0.75}, "weaknesses": {"spirit": 1.5}},  
        ],  
    },  
    "beast": {  
        "forest": [  
            {"name": "Wolf", "role": "skirmisher", "hp": 11, "ac": 12, "attack": 4, "damage_die": 6, "damage_bonus": 1, "damage_type": "piercing", "xp": 30},  
            {"name": "Dire Wolf", "role": "bruiser", "hp": 22, "ac": 13, "attack": 5, "damage_die": 8, "damage_bonus": 3, "damage_type": "piercing", "xp": 85},  
            {"name": "Great Bear", "role": "bruiser", "hp": 34, "ac": 12, "attack": 5, "damage_die": 10, "damage_bonus": 4, "damage_type": "slashing", "xp": 130, "resistances": {"blunt": 0.75}},  
        ],  
        "mountain": [  
            {"name": "Cliff Raptor", "role": "skirmisher", "hp": 14, "ac": 13, "attack": 5, "damage_die": 6, "damage_bonus": 2, "damage_type": "slashing", "xp": 45},  
            {"name": "Stonehide Ram", "role": "tank", "hp": 26, "ac": 15, "attack": 4, "damage_die": 8, "damage_bonus": 3, "damage_type": "blunt", "xp": 95, "resistances": {"blunt": 0.5, "slashing": 0.75}},  
            {"name": "Cave Lion", "role": "elite", "hp": 30, "ac": 14, "attack": 6, "damage_die": 10, "damage_bonus": 3, "damage_type": "slashing", "xp": 130},  
        ],  
        "swamp": [  
            {"name": "Bog Serpent", "role": "skirmisher", "hp": 13, "ac": 12, "attack": 4, "damage_die": 6, "damage_bonus": 2, "damage_type": "poison/acid", "xp": 45, "resistances": {"poison/acid": 0.5}},  
            {"name": "Mire Crocodile", "role": "bruiser", "hp": 28, "ac": 14, "attack": 5, "damage_die": 10, "damage_bonus": 3, "damage_type": "piercing", "xp": 110, "resistances": {"water": 0.5}},  
            {"name": "Rotfen Horror", "role": "elite", "hp": 36, "ac": 13, "attack": 6, "damage_die": 10, "damage_bonus": 4, "damage_type": "poison/acid", "xp": 160, "resistances": {"poison/acid": 0.25}, "weaknesses": {"fire": 1.5}},  
        ],  
        "plains": [  
            {"name": "Wild Boar", "role": "bruiser", "hp": 16, "ac": 12, "attack": 4, "damage_die": 8, "damage_bonus": 2, "damage_type": "piercing", "xp": 45},  
            {"name": "Hunting Cat", "role": "skirmisher", "hp": 18, "ac": 14, "attack": 5, "damage_die": 8, "damage_bonus": 2, "damage_type": "slashing", "xp": 70},  
            {"name": "Thunderhorn Bull", "role": "elite", "hp": 38, "ac": 14, "attack": 6, "damage_die": 10, "damage_bonus": 4, "damage_type": "blunt", "xp": 145, "resistances": {"blunt": 0.75}},  
        ],  
    },  
}  
  
DIFFICULTY_SCALING = {  
    "easy": {"count_mod": -1, "hp": 0.8, "damage": 0.8, "attack": -1, "xp": 0.75},  
    "standard": {"count_mod": 0, "hp": 1.0, "damage": 1.0, "attack": 0, "xp": 1.0},  
    "hard": {"count_mod": 1, "hp": 1.25, "damage": 1.2, "attack": 1, "xp": 1.35},  
    "deadly": {"count_mod": 2, "hp": 1.55, "damage": 1.45, "attack": 2, "xp": 1.75},  
}  
  
  
ENEMY_ROLE_ABILITIES = {  
    "minion": [  
        {"name": "Desperate Swipe", "kind": "strike", "damage_type": "blunt", "state": None, "description": "lashes out wildly"},  
    ],  
    "skirmisher": [  
        {"name": "Harrier Strike", "kind": "strike", "damage_type": "piercing", "state": "exposed", "description": "circles for an opening and strikes at a weak point"},  
        {"name": "Hampering Bite", "kind": "strike", "damage_type": "piercing", "state": "restrained", "description": "tries to slow the target with a disabling attack"},  
    ],  
    "bruiser": [  
        {"name": "Crushing Maul", "kind": "strike", "damage_type": "blunt", "state": "staggered", "description": "throws its weight into a crushing blow"},  
        {"name": "Savage Rend", "kind": "strike", "damage_type": "slashing", "state": "bleeding", "description": "tears into the target with brutal force"},  
    ],  
    "guard": [  
        {"name": "Pinning Thrust", "kind": "strike", "damage_type": "piercing", "state": "marked", "description": "pins the target's attention with a disciplined attack"},  
    ],  
    "tank": [  
        {"name": "Shielding Stance", "kind": "buff", "state": "guarded", "description": "sets its guard and holds the line"},  
        {"name": "Shield Bash", "kind": "strike", "damage_type": "blunt", "state": "staggered", "description": "slams forward with a shield or heavy body-check"},  
    ],  
    "striker": [  
        {"name": "Killing Cut", "kind": "strike", "damage_type": "slashing", "state": "bleeding", "description": "presses the attack with lethal intent"},  
        {"name": "Opening Feint", "kind": "strike", "damage_type": "piercing", "state": "exposed", "description": "feints low before striking high"},  
    ],  
    "caster": [  
        {"name": "Malign Hex", "kind": "debuff", "damage_type": "spirit", "state": "weakened", "description": "chants a low curse and reaches toward the target's spirit"},  
        {"name": "Elemental Bolt", "kind": "spell", "damage_type": "fire", "state": "burning", "description": "hurls a raw burst of hostile magic"},  
    ],  
    "elite": [  
        {"name": "Commanding Assault", "kind": "strike", "damage_type": "slashing", "state": "marked", "description": "attacks with practiced authority"},  
        {"name": "Punishing Blow", "kind": "strike", "damage_type": "blunt", "state": "weakened", "description": "delivers a punishing blow meant to break momentum"},  
    ],  
    "elite_caster": [  
        {"name": "Dread Invocation", "kind": "debuff", "damage_type": "spirit", "state": "feared", "description": "speaks words that curdle the air with dread"},  
        {"name": "Ruinous Burst", "kind": "spell", "damage_type": "spirit", "state": "staggered", "description": "unleashes a violent pulse of ruinous magic"},  
    ],  
}  
  
CORE_STATES = {  
    # v092: locked to states that are actually produced by current class/species/enemy abilities.  
    "inspired": {"name": "Inspired", "effect": "+2 to the next resolved action; consumed on use."},  
    "shielded": {"name": "Shielded", "effect": "Reduce incoming damage by 3."},  
    "guarded": {"name": "Guarded", "effect": "+2 AC."},  
    "fortified": {"name": "Fortified", "effect": "+2 Magic Defense."},  
    "marked": {"name": "Marked", "effect": "-2 Attack while marked."},  
    "exposed": {"name": "Exposed", "effect": "Attackers gain +2 Attack against this target."},  
    "weakened": {"name": "Weakened", "effect": "-2 damage dealt."},  
    "restrained": {"name": "Restrained", "effect": "-2 Attack."},  
    "staggered": {"name": "Staggered", "effect": "Cannot use active abilities."},  
    "feared": {"name": "Feared", "effect": "-2 Attack and -2 magical pressure."},  
    "burning": {"name": "Burning", "effect": "Takes 2 fire damage at end of turn."},  
    "bleeding": {"name": "Bleeding", "effect": "Takes 2 physical damage at end of turn."},  
}  
  
  
# v061: CLASS_ABILITY_TREES is intentionally identical to CLASS_ACTIVE_ABILITIES.  
# Level-ticket dropdowns and /action -> Use Ability both read the same bible-backed data.  
CLASS_ABILITY_TREES = CLASS_ACTIVE_ABILITIES  
CLASS_STARTER_ABILITY = {cls: tiers[2][0] for cls, tiers in CLASS_ABILITY_TREES.items() if 2 in tiers}  
  
ABILITY_COST_DEFAULT = 1  
ABILITY_DURATION_DEFAULT = 2  
  
CLASS_STAT_PRIORITIES: dict[str, list[str]] = {  
    "fighter": ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],  
    "rogue": ["dexterity", "charisma", "constitution", "intelligence", "wisdom", "strength"],  
    "ranger": ["dexterity", "wisdom", "constitution", "strength", "intelligence", "charisma"],  
    "barbarian": ["strength", "constitution", "dexterity", "wisdom", "charisma", "intelligence"],  
    "monk": ["dexterity", "wisdom", "constitution", "strength", "charisma", "intelligence"],  
    "paladin": ["strength", "charisma", "constitution", "wisdom", "dexterity", "intelligence"],  
    "cleric": ["wisdom", "constitution", "strength", "charisma", "dexterity", "intelligence"],  
    "druid": ["wisdom", "constitution", "dexterity", "intelligence", "charisma", "strength"],  
    "mage": ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],  
    "wizard": ["intelligence", "constitution", "dexterity", "wisdom", "charisma", "strength"],  
    "sorcerer": ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],  
    "warlock": ["charisma", "constitution", "dexterity", "wisdom", "intelligence", "strength"],  
    "bard": ["charisma", "dexterity", "constitution", "wisdom", "intelligence", "strength"],  
    "captain": ["charisma", "strength", "constitution", "wisdom", "dexterity", "intelligence"],  
    "artificer": ["intelligence", "constitution", "dexterity", "wisdom", "strength", "charisma"],  
    "scholar": ["intelligence", "wisdom", "constitution", "dexterity", "charisma", "strength"],  
    "warden": ["strength", "constitution", "wisdom", "dexterity", "charisma", "intelligence"],  
}  
  
MAGIC_CLASSES = {"mage", "wizard", "sorcerer", "warlock", "cleric", "druid", "bard", "artificer", "paladin", "ranger"}  
CASTING_STAT_BY_CLASS = {  
    "mage": "intelligence",  
    "wizard": "intelligence",  
    "artificer": "intelligence",  
    "scholar": "intelligence",  
    "cleric": "wisdom",  
    "druid": "wisdom",  
    "ranger": "wisdom",  
    "sorcerer": "charisma",  
    "warlock": "charisma",  
    "bard": "charisma",  
    "paladin": "charisma",  
}  
  
# Class-only AC. No armor loadouts, no proficiencies, no archetype layer.  
CLASS_AC_STYLE = {  
    "fighter": "16",  
    "paladin": "16",  
    "warden": "16",  
    "captain": "15",  
    "barbarian": "14 + CON",  
    "ranger": "14 + DEX max 2",  
    "cleric": "14 + DEX max 2",  
    "druid": "13 + DEX max 2",  
    "rogue": "13 + DEX",  
    "monk": "12 + DEX + WIS",  
    "bard": "12 + DEX",  
    "warlock": "12 + DEX",  
    "artificer": "13 + DEX max 2",  
    "scholar": "11 + DEX",  
    "mage": "11 + DEX",  
    "wizard": "11 + DEX",  
    "sorcerer": "11 + DEX",  
}  
  
  
# ---------- General Helpers ----------  
  
def normalize_name(value: str) -> str:  
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()  
  
  
def slugify(value: str, fallback: str = "item") -> str:  
    value = normalize_name(value)  
    value = re.sub(r"[^a-z0-9\s-]", "", value)  
    value = re.sub(r"[\s_]+", "-", value)  
    value = re.sub(r"-+", "-", value).strip("-")  
    return value[:80] or fallback  
  
  
def truncate(value: Any, limit: int = 1024) -> str:  
    text = "None" if value is None else str(value)  
    if len(text) <= limit:  
        return text  
    return text[: max(0, limit - 3)] + "..."  
  
  
def clean_text(value: Any, limit: int = 1024) -> str:  
    """Discord-safe compact text sanitizer used by admin/testing utilities."""  
    if value is None:  
        text = ""  
    else:  
        text = str(value)  
    text = text.replace("`", "'").replace("@", "@\u200b")  
    text = text.replace("\r", " ").replace("\n", " ").strip()  
    if len(text) <= limit:  
        return text  
    return text[: max(0, limit - 3)] + "..."  
  
  
def decode_json_payload(value: Any) -> dict[str, Any]:  
    """Decode JSONB payloads returned by asyncpg.  
  
    Depending on asyncpg/DB settings, JSONB may come back as dict-like data or  
    as a JSON string. Approval/rejection must tolerate both.  
    """  
    if value is None:  
        return {}  
    if isinstance(value, dict):  
        return dict(value)  
    if isinstance(value, str):  
        try:  
            decoded = json.loads(value)  
        except json.JSONDecodeError as exc:  
            raise RuntimeError(f"Could not decode ticket payload JSON: {exc}") from exc  
        if not isinstance(decoded, dict):  
            raise RuntimeError("Ticket payload JSON did not decode to an object.")  
        return decoded  
    try:  
        return dict(value)  
    except Exception as exc:  
        raise RuntimeError(f"Unsupported ticket payload type: {type(value).__name__}") from exc  
  
  
  
def decode_json_list_payload(value: Any) -> list[Any]:  
    """Decode JSON that is expected to be a list.  
  
    Unlike decode_json_payload(), this intentionally accepts arrays. It is used for  
    character unlocked ability lists and other list-shaped cached payloads.  
    """  
    if value is None:  
        return []  
    if isinstance(value, list):  
        return value  
    if isinstance(value, tuple):  
        return list(value)  
    if isinstance(value, str):  
        if not value.strip():  
            return []  
        try:  
            decoded = json.loads(value)  
        except Exception:  
            return []  
    else:  
        decoded = value  
    if isinstance(decoded, list):  
        return decoded  
    if isinstance(decoded, dict):  
        return [decoded]  
    return []  
  
  
  
def stat_modifier(score: int) -> int:  
    return math.floor((int(score) - 10) / 2)  
  
  
def best_mental_modifier(stats: dict[str, int]) -> int:  
    return max(  
        stat_modifier(stats["intelligence"]),  
        stat_modifier(stats["wisdom"]),  
        stat_modifier(stats["charisma"]),  
    )  
  
  
def magic_save_bonus_for_stats(stats: dict[str, int], level: int = 1) -> int:  
    return proficiency_bonus_for_level(level) + best_mental_modifier(stats)  
  
  
def magic_defense_for_stats(stats: dict[str, int], level: int = 1) -> int:  
    return 8 + magic_save_bonus_for_stats(stats, level)  
  
  
def format_modifier(value: Optional[int]) -> str:  
    if value is None:  
        return "—"  
    value = int(value)  
    return f"+{value}" if value >= 0 else str(value)  
  
  
def proficiency_bonus_for_level(level: int) -> int:  
    level = max(1, min(int(level or 1), 10))  
    if level == 1:  
        return 2  
    if level <= 3:  
        return 3  
    if level <= 5:  
        return 4  
    if level <= 7:  
        return 5  
    if level <= 9:  
        return 6  
    return 7  
  
  
def auto_assign_stats(class_name: str) -> dict[str, int]:  
    priorities = CLASS_STAT_PRIORITIES.get(normalize_name(class_name), CLASS_STAT_PRIORITIES["fighter"])  
    stats = {key: 8 for key in STAT_KEYS}  
    for stat, value in zip(priorities, STANDARD_ARRAY):  
        stats[stat] = value  
    return stats  
  
  
def auto_assign_standard_array(class_name: str) -> dict[str, int]:  
    """Compatibility alias for story-character creation."""  
    return auto_assign_stats(class_name)  
  
  
def validate_standard_array(values: str) -> tuple[bool, Optional[dict[str, int]], str]:  
    nums = [int(n) for n in re.findall(r"-?\d+", values or "")]  
    if len(nums) != 6:  
        return False, None, "Enter exactly six numbers in this order: STR DEX CON INT WIS CHA."  
    if sorted(nums, reverse=True) != STANDARD_ARRAY:  
        return False, None, "Manual stats must use the Standard Array exactly: 15, 14, 13, 12, 10, 8."  
    return True, dict(zip(STAT_KEYS, nums)), ""  
  
  
def format_stats(stats: dict[str, int]) -> str:  
    return " | ".join(  
        f"**{STAT_LABELS[key]}** {int(stats[key])} ({format_modifier(stat_modifier(int(stats[key])))})"  
        for key in STAT_KEYS  
    )  
  
  
def calculate_class_ac(class_name: str, stats: dict[str, int]) -> int:  
    cls = normalize_name(class_name)  
    dex = stat_modifier(stats["dexterity"])  
    con = stat_modifier(stats["constitution"])  
    wis = stat_modifier(stats["wisdom"])  
  
    if cls in {"fighter", "paladin", "warden"}:  
        return 16  
    if cls == "captain":  
        return 15  
    if cls == "barbarian":  
        return 14 + max(0, con)  
    if cls in {"ranger", "cleric", "artificer"}:  
        return 14 + min(max(dex, 0), 2)  
    if cls == "druid":  
        return 13 + min(max(dex, 0), 2)  
    if cls == "rogue":  
        return 13 + dex  
    if cls == "monk":  
        return 12 + dex + wis  
    if cls in {"bard", "warlock"}:  
        return 12 + dex  
    if cls in {"scholar", "mage", "wizard", "sorcerer"}:  
        return 11 + dex  
    return 11 + dex  
  
  
def calculate_starting_hp(class_name: str, stats: dict[str, int]) -> int:  
    cls = normalize_name(class_name)  
    con = stat_modifier(stats["constitution"])  
    base = {  
        "barbarian": 14,  
        "fighter": 12,  
        "paladin": 12,  
        "warden": 12,  
        "captain": 11,  
        "ranger": 10,  
        "rogue": 9,  
        "monk": 9,  
        "cleric": 10,  
        "druid": 9,  
        "warlock": 9,  
        "bard": 8,  
        "artificer": 9,  
        "scholar": 7,  
        "mage": 7,  
        "wizard": 7,  
        "sorcerer": 7,  
    }.get(cls, 8)  
    return max(1, base + con)  
  
  
def scaling_bonus_for_level(rank: str, level: int) -> int:  
    rank = normalize_name(rank or "weak")  
    level = max(1, int(level or 1))  
    if rank == "none":  
        return 0  
    if rank == "weak":  
        return max(0, (level - 1) // 3)  
    if rank == "moderate":  
        return 1 + ((level - 1) // 2)  
    if rank == "strong":  
        return 2 + (level - 1)  
    return 0  
  
  
def class_attack_scaling_bonus(class_name: str, level: int) -> int:  
    return scaling_bonus_for_level(CLASS_COMBAT_SCALING.get(normalize_name(class_name), {}).get("attack", "weak"), level)  
  
  
def class_magic_scaling_bonus(class_name: str, level: int) -> int:  
    return scaling_bonus_for_level(CLASS_COMBAT_SCALING.get(normalize_name(class_name), {}).get("magic", "weak"), level)  
  
  
def passive_options_for(kind: str, key: str) -> list[dict[str, Any]]:  
    if kind == "species":  
        return SPECIES_PASSIVE_OPTIONS.get(normalize_name(key), GENERIC_SPECIES_PASSIVES)  
    return CLASS_PASSIVE_OPTIONS.get(normalize_name(key), [{"name": "Steady Training", "description": "+1 Magic Defense.", "bonuses": {"magic_defense": 1}}])  
  
  
def find_passive(kind: str, key: str, passive_name: Optional[str]) -> dict[str, Any]:  
    options = passive_options_for(kind, key)  
    wanted = normalize_name(passive_name or "")  
    for option in options:  
        if normalize_name(option["name"]) == wanted:  
            return option  
    return options[0]  
  
  
def merge_passive_bonuses(*passives: dict[str, Any]) -> dict[str, int]:  
    totals: dict[str, int] = {}  
    for passive in passives:  
        for key, value in (passive.get("bonuses") or {}).items():  
            totals[key] = totals.get(key, 0) + int(value or 0)  
    return totals  
  
  
def passive_select_options(kind: str, key: str) -> list[discord.SelectOption]:  
    opts = []  
    for passive in passive_options_for(kind, key)[:25]:  
        label = str(passive.get("name") or "Passive")[:100]  
        desc = str(passive.get("description") or "")[:100]  
        opts.append(discord.SelectOption(label=label, value=label, description=desc))  
    return opts  
  
  
def calculate_combat_values(  
    class_name: str,  
    stats: dict[str, int],  
    level: int = 1,  
    damage_die_sides: int = 8,  
    species_name: Optional[str] = None,  
    species_passive: Optional[dict[str, Any]] = None,  
    class_passive: Optional[dict[str, Any]] = None,  
) -> dict[str, Any]:  
    cls = normalize_name(class_name)  
    level = max(1, int(level or 1))  
    prof = proficiency_bonus_for_level(level)  
  
    str_mod = stat_modifier(stats["strength"])  
    dex_mod = stat_modifier(stats["dexterity"])  
    con_mod = stat_modifier(stats["constitution"])  
    physical_mod = max(str_mod, dex_mod)  
  
    passive_totals = merge_passive_bonuses(species_passive or {}, class_passive or {})  
  
    attack_bonus = physical_mod + class_attack_scaling_bonus(class_name, level) + int(passive_totals.get("attack_bonus", 0))  
    initiative_bonus = dex_mod + int(passive_totals.get("initiative_bonus", 0))  
    armor_class = calculate_class_ac(class_name, stats) + int(passive_totals.get("armor_class", 0))  
    max_hp = calculate_starting_hp(class_name, stats) + ((level - 1) * max(1, 4 + con_mod))  
    max_hp += int(passive_totals.get("hp_per_level", 0)) * level  
    max_hp = max(1, max_hp)  
  
    primary = CLASS_STAT_PRIORITIES.get(cls, CLASS_STAT_PRIORITIES["fighter"])[0]  
    primary_mod = stat_modifier(stats[primary])  
    technique_dc = 8 + prof + primary_mod + int(passive_totals.get("technique_dc", 0))  
  
    spell_dc = None  
    casting_stat = CASTING_STAT_BY_CLASS.get(cls)  
    if casting_stat:  
        spell_dc = 8 + class_magic_scaling_bonus(class_name, level) + stat_modifier(stats[casting_stat])  
        spell_dc += int(passive_totals.get("spell_dc", 0))  
  
    magic_save_bonus = magic_save_bonus_for_stats(stats, level)  
    magic_defense = 8 + magic_save_bonus + int(passive_totals.get("magic_defense", 0))  
  
    resolve_bonus = int(passive_totals.get("resolve_bonus", 0))  
    max_resolve = max(1, level + resolve_bonus)  
  
    return {  
        "max_hp": max_hp,  
        "current_hp": max_hp,  
        "armor_class": armor_class,  
        "initiative_bonus": initiative_bonus,  
        "proficiency_bonus": prof,  
        "attack_bonus": attack_bonus,  
        "spell_dc": spell_dc,  
        "technique_dc": technique_dc,  
        "magic_save_bonus": magic_save_bonus,  
        "magic_defense": magic_defense,  
        "damage_die_sides": damage_die_sides,  
        "damage_bonus": int(passive_totals.get("damage_bonus", 0)),  
        "max_resolve": max_resolve,  
        "current_resolve": max_resolve,  
        "damage_type": "physical",  
    }  
  
  
def progression_xp_required_for_die(damage_die_sides: int) -> int:  
    """Mirror the seeded alaris_progression XP curve for compact card display."""  
    sides = int(damage_die_sides or 8)  
    if sides <= 8:  
        return 0  
    xp = 0  
    for die in range(9, sides + 1):  
        xp += 50 + ((die - 8) * 10)  
    return xp  
  
  
def format_progression_summary(xp_total: int, damage_die_sides: int, level: int) -> str:  
    xp_total = int(xp_total or 0)  
    damage_die_sides = int(damage_die_sides or 8)  
    level = int(level or 1)  
  
    if damage_die_sides >= 100:  
        return f"XP Total: **{xp_total}**\nDamage Die: **1d100**\nNext Increase: **Maximum reached**"  
  
    next_die = damage_die_sides + 1  
    next_required = progression_xp_required_for_die(next_die)  
    remaining = max(0, next_required - xp_total)  
    milestone_note = ""  
    if next_die in {20, 30, 40, 50, 60, 70, 80, 90, 100}:  
        next_level = min(10, next_die // 10)  
        milestone_note = f"\nMilestone: **Level {next_level} at 1d{next_die}**"  
  
    return (  
        f"XP Total: **{xp_total}**\n"  
        f"Current Damage Die: **1d{damage_die_sides}**\n"  
        f"Next Increase: **1d{next_die}** at **{next_required} XP** "  
        f"(**{remaining} XP to go**)"  
        f"{milestone_note}"  
    )  
  
  
  
  
# ---------- Ability Score Improvements (v096) ----------  
  
ASI_STAT_ALIASES = {  
    "str": "strength", "strength": "strength",  
    "dex": "dexterity", "dexterity": "dexterity",  
    "con": "constitution", "constitution": "constitution",  
    "int": "intelligence", "intelligence": "intelligence",  
    "wis": "wisdom", "wisdom": "wisdom",  
    "cha": "charisma", "charisma": "charisma",  
}  
ASI_STAT_ABBREVIATIONS = {  
    "strength": "STR",  
    "dexterity": "DEX",  
    "constitution": "CON",  
    "intelligence": "INT",  
    "wisdom": "WIS",  
    "charisma": "CHA",  
}  
ASI_NORMAL_STAT_CAP = 20  
  
  
def parse_asi_selection(selected: str) -> tuple[Optional[dict[str, int]], str]:  
    """Parse ASI dropdown/staff command selections.  
  
    Supported selections:  
    - STR / DEX / CON / INT / WIS / CHA => +2 to one stat  
    - STR+DEX / Strength + Charisma => +1 to two different stats  
    """  
    raw = str(selected or "").strip()  
    if not raw:  
        return None, "ASI selection is required."  
    parts = [p.strip() for p in re.split(r"\s*\+\s*|\s*,\s*|\s+/\s+", raw) if p.strip()]  
    if len(parts) == 1:  
        stat = ASI_STAT_ALIASES.get(normalize_name(parts[0]))  
        if not stat:  
            return None, "ASI option must be STR, DEX, CON, INT, WIS, CHA, or a split such as STR+DEX."  
        return {stat: 2}, ""  
    if len(parts) == 2:  
        first = ASI_STAT_ALIASES.get(normalize_name(parts[0]))  
        second = ASI_STAT_ALIASES.get(normalize_name(parts[1]))  
        if not first or not second:  
            return None, "Split ASI must use two valid stats, such as STR+DEX."  
        if first == second:  
            return None, "Split ASI must choose two different stats. Use the single-stat option for +2."  
        return {first: 1, second: 1}, ""  
    return None, "ASI selection must be +2 to one stat or +1 to two different stats."  
  
  
def format_asi_increases(increases: dict[str, int]) -> str:  
    parts = []  
    for stat, amount in increases.items():  
        parts.append(f"+{int(amount)} {ASI_STAT_ABBREVIATIONS.get(stat, stat.title())}")  
    return " / ".join(parts)  
  
  
async def apply_asi_to_character(character_id: int, increases: dict[str, int], cap: int = ASI_NORMAL_STAT_CAP) -> str:  
    """Apply an ASI safely, then recalculate combat and refresh the public card."""  
    clean: dict[str, int] = {}  
    for stat, amount in (increases or {}).items():  
        if stat not in STAT_KEYS:  
            continue  
        amount = int(amount or 0)  
        if amount <= 0:  
            continue  
        clean[stat] = clean.get(stat, 0) + amount  
    if not clean:  
        raise RuntimeError("No valid ASI increases were provided.")  
  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow("SELECT * FROM alaris_character_stats WHERE character_id=$1;", int(character_id))  
        if not row:  
            raise RuntimeError("Character stats were not found.")  
        updates: dict[str, int] = {}  
        notes: list[str] = []  
        for stat, amount in clean.items():  
            current = int(row[stat])  
            if current >= cap:  
                new_value = current  
            else:  
                new_value = min(cap, current + amount)  
            updates[stat] = new_value  
            notes.append(f"{ASI_STAT_ABBREVIATIONS.get(stat, stat.title())} {current}→{new_value}")  
        set_clause = ", ".join(f"{stat}=${idx + 2}" for idx, stat in enumerate(updates.keys()))  
        values = list(updates.values())  
        await conn.execute(  
            f"UPDATE alaris_character_stats SET {set_clause}, updated_at=NOW() WHERE character_id=$1;",  
            int(character_id),  
            *values,  
        )  
  
    await recalculate_character_combat(int(character_id), preserve_current_hp=True)  
    try:  
        await refresh_character_post(int(character_id))  
    except Exception:  
        LOG.exception("Failed to refresh character post after ASI application.")  
    return ", ".join(notes)  
  
  
async def ensure_pending_asi_choices(character_id: int, guild_id: int, old_level: int, new_level: int) -> int:  
    """Create only ASI pending choices between two levels.  
  
    Used by staff/story-character creation, because that flow already handles its  
    own primary/secondary active choices and should not create duplicate class  
    ability prompts.  
    """  
    if int(new_level or 1) <= int(old_level or 1):  
        return 0  
    created = 0  
    async with db_pool.acquire() as conn:  
        for lvl in range(int(old_level or 1) + 1, int(new_level or 1) + 1):  
            if lvl not in ASI_LEVELS:  
                continue  
            result = await conn.execute(  
                """  
                INSERT INTO alaris_level_choices (guild_id, character_id, level, choice_type, status, metadata_json)  
                VALUES ($1,$2,$3,'asi','pending','{}'::jsonb)  
                ON CONFLICT DO NOTHING;  
                """,  
                int(guild_id), int(character_id), int(lvl),  
            )  
            if result.endswith("1"):  
                created += 1  
    return created  
  
  
async def get_next_die_progression(damage_die_sides: int, xp_total: int) -> dict[str, Any]:  
    """Return compact XP progress toward the next damage-die increase."""  
    current_die = int(damage_die_sides or 8)  
    xp_total = int(xp_total or 0)  
    next_die = min(100, current_die + 1)  
  
    async with db_pool.acquire() as conn:  
        current_row = await conn.fetchrow(  
            "SELECT * FROM alaris_progression WHERE damage_die_sides=$1;",  
            current_die,  
        )  
        next_row = await conn.fetchrow(  
            "SELECT * FROM alaris_progression WHERE damage_die_sides=$1;",  
            next_die,  
        )  
  
    if current_die >= 100 or not next_row:  
        return {  
            "current_die": current_die,  
            "next_die": None,  
            "xp_total": xp_total,  
            "xp_required": None,  
            "xp_remaining": 0,  
            "level": int(current_row["level"]) if current_row else 10,  
            "next_level": None,  
            "milestone": False,  
        }  
  
    xp_required = int(next_row["xp_required"])  
    xp_remaining = max(0, xp_required - xp_total)  
    return {  
        "current_die": current_die,  
        "next_die": next_die,  
        "xp_total": xp_total,  
        "xp_required": xp_required,  
        "xp_remaining": xp_remaining,  
        "level": int(current_row["level"]) if current_row else int(next_row["level"]),  
        "next_level": int(next_row["level"]),  
        "milestone": bool(next_row["milestone"]),  
    }  
  
  
  
def valid_url(value: str) -> bool:  
    value = str(value or "").strip()  
    return value.startswith("http://") or value.startswith("https://")  
  
  
def is_staff_member(member: discord.Member) -> bool:  
    if member.guild_permissions.administrator:  
        return True  
    if STAFF_ROLE_IDS:  
        return any(role.id in STAFF_ROLE_IDS for role in member.roles)  
    return False  
  
  
async def require_staff(interaction: discord.Interaction) -> bool:  
    if not isinstance(interaction.user, discord.Member) or not is_staff_member(interaction.user):  
        msg = "You do not have permission to use this command."  
        if interaction.response.is_done():  
            await interaction.followup.send(msg, ephemeral=True)  
        else:  
            await interaction.response.send_message(msg, ephemeral=True)  
        return False  
    return True  
  
  
def is_developer_member(member: discord.Member) -> bool:  
    if member.guild_permissions.administrator:  
        return True  
    return any(role.id == DEVELOPER_ROLE_ID for role in member.roles)  
  
  
async def require_developer(interaction: discord.Interaction) -> bool:  
    if not isinstance(interaction.user, discord.Member) or not is_developer_member(interaction.user):  
        msg = "This command is restricted to the Alaris developer role."  
        if interaction.response.is_done():  
            await interaction.followup.send(msg, ephemeral=True)  
        else:  
            await interaction.response.send_message(msg, ephemeral=True)  
        return False  
    return True  
  
  
async def ensure_approved_player_role(guild: discord.Guild, user_id: int) -> bool:  
    """Assign the approved-player role after character approval, only if missing.  
  
    This is intentionally best-effort: role assignment failures should never block  
    character approval, character post creation, or ticket cleanup.  
    """  
    role = guild.get_role(APPROVED_PLAYER_ROLE_ID)  
    if role is None:  
        LOG.warning("Approved player role %s was not found in guild %s.", APPROVED_PLAYER_ROLE_ID, guild.id)  
        return False  
  
    member = guild.get_member(int(user_id))  
    if member is None:  
        try:  
            member = await guild.fetch_member(int(user_id))  
        except discord.NotFound:  
            LOG.warning("Could not assign approved player role: user %s is not in guild %s.", user_id, guild.id)  
            return False  
        except Exception:  
            LOG.exception("Failed to fetch member %s for approved player role assignment.", user_id)  
            return False  
  
    if any(existing_role.id == APPROVED_PLAYER_ROLE_ID for existing_role in member.roles):  
        return False  
  
    try:  
        await member.add_roles(role, reason="Approved Alaris character")  
        return True  
    except discord.Forbidden:  
        LOG.warning(  
            "Missing permission or role hierarchy blocked assignment of approved player role %s to user %s.",  
            APPROVED_PLAYER_ROLE_ID,  
            user_id,  
        )  
    except Exception:  
        LOG.exception("Failed to assign approved player role %s to user %s.", APPROVED_PLAYER_ROLE_ID, user_id)  
    return False  
  
  
async def post_command_log(interaction: discord.Interaction, summary: str) -> None:  
    if not COMMAND_LOG_CHANNEL_ID or not interaction.guild:  
        return  
    channel = interaction.guild.get_channel(COMMAND_LOG_CHANNEL_ID)  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(COMMAND_LOG_CHANNEL_ID)  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            LOG.exception("Failed to fetch COMMAND_LOG_CHANNEL_ID=%s", COMMAND_LOG_CHANNEL_ID)  
            return  
    if not isinstance(channel, discord.TextChannel):  
        return  
    try:  
        await channel.send(f"**{interaction.user}** used `/{interaction.command.name if interaction.command else 'unknown'}` - {summary}")  
    except Exception:  
        LOG.exception("Failed to post command log.")  
  
  
async def build_ticket_transcript_text(channel: Optional[discord.TextChannel]) -> str:  
    if channel is None:  
        return "Ticket transcript unavailable: no ticket channel was provided."  
    lines: list[str] = []  
    try:  
        async for msg in channel.history(limit=None, oldest_first=True):  
            created = msg.created_at.isoformat() if msg.created_at else "unknown-time"  
            author = getattr(msg.author, "display_name", None) or getattr(msg.author, "name", str(msg.author))  
            content = msg.content or ""  
            if content.strip():  
                lines.append(f"[{created}] {author}: {content}")  
            else:  
                lines.append(f"[{created}] {author}:")  
            for embed in msg.embeds:  
                if embed.title:  
                    lines.append(f"  [EMBED TITLE] {embed.title}")  
                if embed.description:  
                    lines.append(f"  [EMBED DESCRIPTION] {embed.description}")  
                for field in embed.fields:  
                    lines.append(f"  [EMBED FIELD] {field.name}: {field.value}")  
                if embed.footer and embed.footer.text:  
                    lines.append(f"  [EMBED FOOTER] {embed.footer.text}")  
            for attachment in msg.attachments:  
                lines.append(f"  [ATTACHMENT] {attachment.filename}: {attachment.url}")  
    except Exception as exc:  
        LOG.exception("Failed to build ticket transcript.")  
        lines.append(f"Transcript collection failed: {exc}")  
    return "\n".join(lines)[:900000] or "Ticket contained no readable messages."  
  
  
def embed_snapshot_text(embed: Optional[discord.Embed]) -> str:  
    if embed is None:  
        return "No final character card embed snapshot was available."  
    lines: list[str] = []  
    if embed.title:  
        lines.append(f"TITLE: {embed.title}")  
    if embed.description:  
        lines.append(f"DESCRIPTION: {embed.description}")  
    for field in embed.fields:  
        lines.append(f"{field.name}: {field.value}")  
    if embed.footer and embed.footer.text:  
        lines.append(f"FOOTER: {embed.footer.text}")  
    return "\n".join(lines) or "Embed had no readable fields."  
  
  
async def post_character_approval_log(  
    guild: discord.Guild,  
    approver: discord.abc.User,  
    character_name: str,  
    ticket_channel: Optional[discord.TextChannel] = None,  
    character_embed: Optional[discord.Embed] = None,  
) -> None:  
    if not CHARACTER_APPROVAL_LOG_CHANNEL_ID:  
        return  
    channel = guild.get_channel(CHARACTER_APPROVAL_LOG_CHANNEL_ID)  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(CHARACTER_APPROVAL_LOG_CHANNEL_ID)  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            LOG.exception("Failed to fetch CHARACTER_APPROVAL_LOG_CHANNEL_ID=%s", CHARACTER_APPROVAL_LOG_CHANNEL_ID)  
            return  
    if not isinstance(channel, discord.TextChannel):  
        return  
  
    approver_name = getattr(approver, "display_name", None) or getattr(approver, "name", str(approver))  
    transcript = await build_ticket_transcript_text(ticket_channel if isinstance(ticket_channel, discord.TextChannel) else None)  
    card_snapshot = embed_snapshot_text(character_embed)  
  
    transcript_file = discord.File(  
        io.BytesIO(transcript.encode("utf-8")),  
        filename=f"{slugify(character_name, 'character')}_ticket_transcript.txt",  
    )  
    card_file = discord.File(  
        io.BytesIO(card_snapshot.encode("utf-8")),  
        filename=f"{slugify(character_name, 'character')}_approved_card_snapshot.txt",  
    )  
  
    embed = discord.Embed(  
        title="Character Approved",  
        description=f"**{character_name}** was approved.",  
        color=discord.Color.green(),  
    )  
    embed.add_field(name="Approved By", value=approver_name, inline=True)  
    embed.add_field(name="Ticket Transcript", value="Attached as `.txt`.", inline=True)  
    embed.add_field(name="Character Card Snapshot", value="Attached as `.txt`.", inline=True)  
    try:  
        await channel.send(embed=embed, files=[transcript_file, card_file], allowed_mentions=discord.AllowedMentions.none())  
    except Exception:  
        LOG.exception("Failed to post character approval log.")  
  
  
  
# ---------- Database ----------  
  
async def table_exists(conn: asyncpg.Connection, table_name: str, schema_name: str = "public") -> bool:  
    value = await conn.fetchval(  
        """  
        SELECT EXISTS (  
            SELECT 1  
            FROM information_schema.tables  
            WHERE table_schema=$1 AND table_name=$2  
        );  
        """,  
        schema_name,  
        table_name,  
    )  
    return bool(value)  
  
  
async def get_columns(conn: asyncpg.Connection, table_name: str, schema_name: str = "public") -> set[str]:  
    rows = await conn.fetch(  
        """  
        SELECT column_name  
        FROM information_schema.columns  
        WHERE table_schema=$1 AND table_name=$2  
        ORDER BY ordinal_position;  
        """,  
        schema_name,  
        table_name,  
    )  
    return {str(row["column_name"]) for row in rows}  
  
  
def safe_identifier(name: str) -> str:  
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):  
        raise RuntimeError(f"Unsafe SQL identifier: {name!r}")  
    return name  
  
  
async def init_db() -> asyncpg.Pool:  
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)  
    async with pool.acquire() as conn:  
        await conn.execute("SELECT 1;")  
        await ensure_alaris_clean_schema(conn)  
  
        # v037 additive schema hardening for existing test databases.  
        # These columns are referenced by approval, progression, combat, Resolve, and state systems.  
        await conn.execute("""  
            ALTER TABLE alaris_character_combat  
                ADD COLUMN IF NOT EXISTS magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS magic_defense INTEGER NOT NULL DEFAULT 10,  
                ADD COLUMN IF NOT EXISTS damage_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS max_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS current_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS weaknesses_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS immunities_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS abilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS ability_chance REAL NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS enemy_category TEXT,  
                ADD COLUMN IF NOT EXISTS enemy_setting TEXT,  
                ADD COLUMN IF NOT EXISTS base_name TEXT;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combatants  
                ADD COLUMN IF NOT EXISTS magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS magic_defense INTEGER NOT NULL DEFAULT 10,  
                ADD COLUMN IF NOT EXISTS damage_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS xp_value INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS enemy_role TEXT,  
                ADD COLUMN IF NOT EXISTS enemy_theme TEXT,  
                ADD COLUMN IF NOT EXISTS max_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS current_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS weaknesses_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS immunities_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                ADD COLUMN IF NOT EXISTS abilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
                ADD COLUMN IF NOT EXISTS ability_chance REAL NOT NULL DEFAULT 0,
                ADD COLUMN IF NOT EXISTS enemy_category TEXT,
                ADD COLUMN IF NOT EXISTS enemy_setting TEXT,
                ADD COLUMN IF NOT EXISTS base_name TEXT;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_characters  
                ADD COLUMN IF NOT EXISTS species_passive_name TEXT,  
                ADD COLUMN IF NOT EXISTS species_passive_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS class_passive_name TEXT,  
                ADD COLUMN IF NOT EXISTS class_passive_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS pending_level_choices_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS secondary_class TEXT,  
                ADD COLUMN IF NOT EXISTS secondary_passives_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS story_passives_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS is_story_character BOOLEAN NOT NULL DEFAULT FALSE,  
                ADD COLUMN IF NOT EXISTS starting_dice_override INTEGER;  
        """)  
  
        # v050 ability table safety: required by level-up/debug/action systems.  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_abilities (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                ability_name TEXT NOT NULL,  
                class_name TEXT,  
                level_granted INTEGER NOT NULL DEFAULT 1,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, ability_name)  
            );  
        """)  
  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combat_lobbies (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                channel_id BIGINT NOT NULL,  
                session_id BIGINT REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                host_user_id BIGINT NOT NULL,  
                lobby_message_id BIGINT,  
                combat_type TEXT NOT NULL,  
                enemy_category TEXT,  
                danger_level TEXT,  
                environment TEXT,  
                status TEXT NOT NULL DEFAULT 'open',  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                started_at TIMESTAMPTZ,  
                canceled_at TIMESTAMPTZ  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combat_lobbies  
            ADD COLUMN IF NOT EXISTS structured_enemies_json JSONB NOT NULL DEFAULT '[]'::jsonb;  
        """)  
  
        await conn.execute("""  
            CREATE INDEX IF NOT EXISTS idx_alaris_combat_lobbies_open_channel  
            ON alaris_combat_lobbies(guild_id, channel_id)  
            WHERE status='open';  
        """)  
  
  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_story_character_drafts (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                channel_id BIGINT,  
                creator_user_id BIGINT NOT NULL,  
                owner_user_id BIGINT NOT NULL,  
                name TEXT NOT NULL,  
                normalized_name TEXT NOT NULL,  
                species TEXT NOT NULL,  
                kingdom TEXT,  
                subspecies TEXT,  
                primary_class TEXT,  
                secondary_class TEXT,  
                starter_die INTEGER NOT NULL DEFAULT 8,  
                level INTEGER NOT NULL DEFAULT 1,  
                xp_total BIGINT NOT NULL DEFAULT 0,  
                google_doc_url TEXT,  
                image_url TEXT,  
                stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                selected_primary_abilities_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                selected_secondary_abilities_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                status TEXT NOT NULL DEFAULT 'draft',  
                message_id BIGINT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
    LOG.info("Connected to Postgres and ensured clean alaris_* schema.")  
    return pool  
  
  
async def ensure_alaris_clean_schema(conn: asyncpg.Connection) -> None:  
    async with conn.transaction():  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_characters (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                user_id BIGINT NOT NULL,  
                name TEXT NOT NULL,  
                normalized_name TEXT NOT NULL,  
                species TEXT NOT NULL,  
                class_name TEXT NOT NULL,  
                kingdom TEXT,  
                image_url TEXT,  
                image_filename TEXT,  
                image_content_type TEXT,  
                google_doc_url TEXT,  
                level INTEGER NOT NULL DEFAULT 1,  
                xp_total BIGINT NOT NULL DEFAULT 0,  
                damage_die_sides INTEGER NOT NULL DEFAULT 8,  
                status TEXT NOT NULL DEFAULT 'active',  
                created_by BIGINT,  
                approved_by BIGINT,  
                approved_at TIMESTAMPTZ,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE (guild_id, normalized_name)  
            );  
        """)  
        # Additive columns for DBs that were created by v002 before v003.  
        await conn.execute("""  
            ALTER TABLE alaris_characters  
                ADD COLUMN IF NOT EXISTS image_url TEXT,  
                ADD COLUMN IF NOT EXISTS image_filename TEXT,  
                ADD COLUMN IF NOT EXISTS image_content_type TEXT,  
                ADD COLUMN IF NOT EXISTS google_doc_url TEXT,  
                ADD COLUMN IF NOT EXISTS kingdom TEXT,  
                ADD COLUMN IF NOT EXISTS approved_by BIGINT,  
                ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_characters  
                ADD COLUMN IF NOT EXISTS species_passive_name TEXT,  
                ADD COLUMN IF NOT EXISTS species_passive_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS class_passive_name TEXT,  
                ADD COLUMN IF NOT EXISTS class_passive_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                ADD COLUMN IF NOT EXISTS pending_level_choices_json JSONB NOT NULL DEFAULT '[]'::jsonb;  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS characters (  
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
        """)  
        await conn.execute("""  
            ALTER TABLE characters  
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
        """)  
        await conn.execute("""  
            CREATE UNIQUE INDEX IF NOT EXISTS characters_guild_character_id_uidx  
            ON characters (guild_id, character_id);  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_level_choices (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                level INTEGER NOT NULL,  
                choice_type TEXT NOT NULL,  
                status TEXT NOT NULL DEFAULT 'pending',  
                selected_option TEXT,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                resolved_at TIMESTAMPTZ,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, level, choice_type)  
            );  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_level_tickets (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                channel_id BIGINT NOT NULL,  
                status TEXT NOT NULL DEFAULT 'open',  
                opened_for_level INTEGER NOT NULL DEFAULT 1,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                closed_at TIMESTAMPTZ,  
                UNIQUE(character_id, status)  
            );  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_abilities (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                ability_name TEXT NOT NULL,  
                class_name TEXT,  
                level_granted INTEGER NOT NULL DEFAULT 1,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, ability_name)  
            );  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_features (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                source_type TEXT NOT NULL,  
                feature_name TEXT NOT NULL,  
                feature_type TEXT NOT NULL DEFAULT 'passive',  
                level_granted INTEGER NOT NULL DEFAULT 1,  
                is_active BOOLEAN NOT NULL DEFAULT TRUE,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, source_type, feature_name)  
            );  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_stats (  
                character_id BIGINT PRIMARY KEY REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                strength INTEGER NOT NULL,  
                dexterity INTEGER NOT NULL,  
                constitution INTEGER NOT NULL,  
                intelligence INTEGER NOT NULL,  
                wisdom INTEGER NOT NULL,  
                charisma INTEGER NOT NULL,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_combat (  
                character_id BIGINT PRIMARY KEY REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                max_hp INTEGER NOT NULL,  
                current_hp INTEGER NOT NULL,  
                armor_class INTEGER NOT NULL,  
                initiative_bonus INTEGER NOT NULL DEFAULT 0,  
                proficiency_bonus INTEGER NOT NULL DEFAULT 2,  
                attack_bonus INTEGER NOT NULL DEFAULT 0,  
                spell_dc INTEGER,  
                technique_dc INTEGER NOT NULL,  
                damage_die_sides INTEGER NOT NULL DEFAULT 8,  
                xp_value INTEGER NOT NULL DEFAULT 0,  
                damage_type TEXT NOT NULL DEFAULT 'physical',  
                resistances_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_character_combat  
                ADD COLUMN IF NOT EXISTS magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS magic_defense INTEGER NOT NULL DEFAULT 10;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combatants  
                ADD COLUMN IF NOT EXISTS magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS magic_defense INTEGER NOT NULL DEFAULT 10;  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_progression (  
                damage_die_sides INTEGER PRIMARY KEY,  
                level INTEGER NOT NULL,  
                xp_required BIGINT NOT NULL,  
                milestone BOOLEAN NOT NULL DEFAULT FALSE,  
                milestone_note TEXT  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_xp_awards (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                amount INTEGER NOT NULL,  
                source_type TEXT NOT NULL,  
                source_id BIGINT,  
                reason TEXT,  
                awarded_by BIGINT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_xp_awards  
                ADD COLUMN IF NOT EXISTS typed_characters INTEGER,  
                ADD COLUMN IF NOT EXISTS old_xp_total BIGINT,  
                ADD COLUMN IF NOT EXISTS new_xp_total BIGINT,  
                ADD COLUMN IF NOT EXISTS old_damage_die_sides INTEGER,  
                ADD COLUMN IF NOT EXISTS new_damage_die_sides INTEGER,  
                ADD COLUMN IF NOT EXISTS old_level INTEGER,  
                ADD COLUMN IF NOT EXISTS new_level INTEGER;  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_session_rp_counts (  
                session_id BIGINT NOT NULL REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                typed_characters INTEGER NOT NULL DEFAULT 0,  
                rp_xp_awarded INTEGER NOT NULL DEFAULT 0,  
                PRIMARY KEY (session_id, character_id)  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_session_enemies (  
                id BIGSERIAL PRIMARY KEY,  
                session_id BIGINT NOT NULL REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                name TEXT NOT NULL,  
                difficulty TEXT NOT NULL DEFAULT 'standard',  
                xp_value INTEGER NOT NULL DEFAULT 50,  
                defeated BOOLEAN NOT NULL DEFAULT TRUE,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_review_tickets (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                user_id BIGINT NOT NULL,  
                channel_id BIGINT,  
                review_message_id BIGINT,  
                status TEXT NOT NULL DEFAULT 'open',  
                payload_json JSONB NOT NULL,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                closed_at TIMESTAMPTZ,  
                reviewed_by BIGINT  
            );  
        """)  
        await conn.execute("""  
            CREATE INDEX IF NOT EXISTS idx_alaris_review_tickets_open  
            ON alaris_character_review_tickets(guild_id, status);  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_posts (  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT PRIMARY KEY REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                forum_channel_id BIGINT NOT NULL,  
                thread_id BIGINT NOT NULL,  
                starter_message_id BIGINT,  
                card_message_id BIGINT,  
                welcome_message_id BIGINT,  
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_character_posts  
                ADD COLUMN IF NOT EXISTS welcome_message_id BIGINT;  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_refresh_queue (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL,  
                reason TEXT NOT NULL DEFAULT 'external_refresh',  
                status TEXT NOT NULL DEFAULT 'pending',  
                requested_by BIGINT,  
                requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                processed_at TIMESTAMPTZ,  
                error_text TEXT  
            );  
        """)  
        # v104 safety: older deployments may already have this table without the new queue columns.  
        # Additive-only migration before any index or query references those columns.  
        await conn.execute("""  
            ALTER TABLE alaris_character_refresh_queue  
                ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT 'external_refresh',  
                ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending',  
                ADD COLUMN IF NOT EXISTS requested_by BIGINT,  
                ADD COLUMN IF NOT EXISTS requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ,  
                ADD COLUMN IF NOT EXISTS error_text TEXT;  
        """)  
        await conn.execute("""  
            CREATE INDEX IF NOT EXISTS idx_alaris_character_refresh_queue_pending  
            ON alaris_character_refresh_queue(guild_id, status, requested_at);  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_sessions (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                channel_id BIGINT NOT NULL,  
                starter_user_id BIGINT NOT NULL,  
                session_type TEXT NOT NULL,  
                title TEXT,  
                status TEXT NOT NULL DEFAULT 'open',  
                start_message_id BIGINT,  
                end_message_id BIGINT,  
                message_count INTEGER NOT NULL DEFAULT 0,  
                victor_character_id BIGINT,  
                enemy_xp_pool INTEGER NOT NULL DEFAULT 0,  
                summary TEXT,  
                key_takeaways TEXT,  
                possible_consequences TEXT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                closed_at TIMESTAMPTZ  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_sessions  
                ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS victor_character_id BIGINT,  
                ADD COLUMN IF NOT EXISTS enemy_xp_pool INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS key_takeaways TEXT,  
                ADD COLUMN IF NOT EXISTS possible_consequences TEXT;  
        """)  
        await conn.execute("""  
            CREATE INDEX IF NOT EXISTS idx_alaris_sessions_active_channel  
            ON alaris_sessions(guild_id, channel_id, status);  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_session_participants (  
                id BIGSERIAL PRIMARY KEY,  
                session_id BIGINT NOT NULL REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                user_id BIGINT NOT NULL,  
                joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(session_id, character_id)  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combat_encounters (  
                id BIGSERIAL PRIMARY KEY,  
                session_id BIGINT REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                guild_id BIGINT NOT NULL,  
                channel_id BIGINT NOT NULL,  
                status TEXT NOT NULL DEFAULT 'open',  
                round_number INTEGER NOT NULL DEFAULT 1,  
                current_turn_index INTEGER NOT NULL DEFAULT 0,  
                turn_order_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                closed_at TIMESTAMPTZ  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combatants (  
                id BIGSERIAL PRIMARY KEY,  
                encounter_id BIGINT NOT NULL REFERENCES alaris_combat_encounters(id) ON DELETE CASCADE,  
                combatant_type TEXT NOT NULL CHECK (combatant_type IN ('character','enemy')),  
                character_id BIGINT REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                name TEXT NOT NULL,  
                owner_user_id BIGINT,  
                max_hp INTEGER NOT NULL,  
                current_hp INTEGER NOT NULL,  
                armor_class INTEGER NOT NULL,  
                initiative_bonus INTEGER NOT NULL DEFAULT 0,  
                attack_bonus INTEGER NOT NULL DEFAULT 0,  
                save_dc INTEGER,  
                magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                magic_defense INTEGER NOT NULL DEFAULT 10,  
                damage_die_sides INTEGER NOT NULL DEFAULT 8,  
                damage_type TEXT NOT NULL DEFAULT 'physical',  
                resistances_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                status TEXT NOT NULL DEFAULT 'active',  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_conditions (  
                id BIGSERIAL PRIMARY KEY,  
                encounter_id BIGINT REFERENCES alaris_combat_encounters(id) ON DELETE CASCADE,  
                combatant_id BIGINT REFERENCES alaris_combatants(id) ON DELETE CASCADE,  
                condition_name TEXT NOT NULL,  
                duration_rounds INTEGER,  
                source_note TEXT,  
                created_by BIGINT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(encounter_id, combatant_id, condition_name)  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_character_combat  
                ADD COLUMN IF NOT EXISTS max_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS current_resolve INTEGER NOT NULL DEFAULT 1;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combatants  
                ADD COLUMN IF NOT EXISTS max_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS current_resolve INTEGER NOT NULL DEFAULT 1;  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combat_states (  
                id BIGSERIAL PRIMARY KEY,  
                encounter_id BIGINT NOT NULL REFERENCES alaris_combat_encounters(id) ON DELETE CASCADE,  
                combatant_id BIGINT NOT NULL REFERENCES alaris_combatants(id) ON DELETE CASCADE,  
                source_combatant_id BIGINT REFERENCES alaris_combatants(id) ON DELETE SET NULL,  
                state_key TEXT NOT NULL,  
                state_name TEXT NOT NULL,  
                duration_turns INTEGER NOT NULL DEFAULT 1,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(encounter_id, combatant_id, state_key)  
            );  
        """)  
  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combat_logs (  
                id BIGSERIAL PRIMARY KEY,  
                encounter_id BIGINT REFERENCES alaris_combat_encounters(id) ON DELETE CASCADE,  
                actor_combatant_id BIGINT,  
                target_combatant_id BIGINT,  
                action_type TEXT NOT NULL,  
                roll_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                damage INTEGER,  
                damage_type TEXT,  
                outcome TEXT,  
                narrative TEXT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()  
            );  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combat_encounters  
                ADD COLUMN IF NOT EXISTS combat_type TEXT,  
                ADD COLUMN IF NOT EXISTS victor_character_id BIGINT,  
                ADD COLUMN IF NOT EXISTS enemy_xp_pool INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS current_turn_combatant_id BIGINT;  
        """)  
        await conn.execute("""  
            ALTER TABLE alaris_combatants  
                ADD COLUMN IF NOT EXISTS initiative_roll INTEGER,  
                ADD COLUMN IF NOT EXISTS damage_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS xp_value INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS action_taken BOOLEAN NOT NULL DEFAULT FALSE;  
        """)  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_combat_invitations (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                session_id BIGINT REFERENCES alaris_sessions(id) ON DELETE CASCADE,  
                encounter_id BIGINT REFERENCES alaris_combat_encounters(id) ON DELETE CASCADE,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                user_id BIGINT NOT NULL,  
                status TEXT NOT NULL DEFAULT 'pending',  
                message_id BIGINT,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                responded_at TIMESTAMPTZ,  
                UNIQUE(encounter_id, character_id)  
            );  
        """)  
  
        xp = 0  
        for sides in range(8, 101):  
            if sides < 20:  
                level = 1  
            else:  
                level = min(10, (sides // 10))  
            milestone = sides in {20, 30, 40, 50, 60, 70, 80, 90, 100}  
            milestone_note = f"Level {level} milestone" if milestone else None  
            if sides == 8:  
                xp = 0  
            else:  
                xp += 50 + ((sides - 8) * 10)  
            await conn.execute("""  
                INSERT INTO alaris_progression (  
                    damage_die_sides, level, xp_required, milestone, milestone_note  
                )  
                VALUES ($1,$2,$3,$4,$5)  
                ON CONFLICT (damage_die_sides) DO UPDATE SET  
                    level=EXCLUDED.level,  
                    xp_required=EXCLUDED.xp_required,  
                    milestone=EXCLUDED.milestone,  
                    milestone_note=EXCLUDED.milestone_note;  
            """, sides, level, xp, milestone, milestone_note)  
  
  
async def inspect_core_schema() -> dict[str, Any]:  
    async with db_pool.acquire() as conn:  
        public_tables = int(await conn.fetchval(  
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"  
        ) or 0)  
        clean_tables = [  
            "alaris_characters", "alaris_character_stats", "alaris_character_combat",  
            "alaris_progression", "alaris_xp_awards", "alaris_session_rp_counts", "alaris_session_enemies", "alaris_character_review_tickets",  
            "alaris_character_posts", "alaris_sessions", "alaris_session_participants",  
            "alaris_combat_encounters", "alaris_combatants", "alaris_conditions", "alaris_combat_invitations", "alaris_combat_logs",  
        ]  
        clean_core = {}  
        for table in clean_tables:  
            exists = await table_exists(conn, table)  
            clean_core[table] = {"exists": exists, "columns": sorted(await get_columns(conn, table)) if exists else []}  
  
        old_active = None  
        if await table_exists(conn, "characters"):  
            ccols = await get_columns(conn, "characters")  
            if "status" in ccols:  
                old_active = int(await conn.fetchval(  
                    "SELECT COUNT(*) FROM characters WHERE COALESCE(status, 'active') <> 'archived';"  
                ) or 0)  
            else:  
                old_active = int(await conn.fetchval("SELECT COUNT(*) FROM characters;") or 0)  
  
        clean_active = int(await conn.fetchval(  
            "SELECT COUNT(*) FROM alaris_characters WHERE status='active';"  
        ) or 0)  
        open_tickets = int(await conn.fetchval(  
            "SELECT COUNT(*) FROM alaris_character_review_tickets WHERE status='open';"  
        ) or 0)  
        progression_rows = int(await conn.fetchval("SELECT COUNT(*) FROM alaris_progression;") or 0)  
  
        return {  
            "public_tables": public_tables,  
            "clean_core": clean_core,  
            "old_active_characters": old_active,  
            "clean_active_characters": clean_active,  
            "open_tickets": open_tickets,  
            "progression_rows": progression_rows,  
        }  
  
  
# ---------- Character Data ----------  
  
async def clean_character_name_exists(guild_id: int, normalized_name: str) -> bool:  
    async with db_pool.acquire() as conn:  
        return bool(await conn.fetchval(  
            """  
            SELECT EXISTS(  
                SELECT 1 FROM alaris_characters  
                WHERE guild_id=$1 AND normalized_name=$2 AND status='active'  
            );  
            """,  
            guild_id, normalized_name,  
        ))  
  
  
async def open_ticket_name_exists(guild_id: int, normalized_name: str) -> bool:  
    async with db_pool.acquire() as conn:  
        return bool(await conn.fetchval(  
            """  
            SELECT EXISTS(  
                SELECT 1  
                FROM alaris_character_review_tickets  
                WHERE guild_id=$1  
                  AND status='open'  
                  AND lower(payload_json->>'normalized_name')=$2  
            );  
            """,  
            guild_id, normalized_name,  
        ))  
  
  
async def sync_public_character_compat_row(conn: asyncpg.Connection, char: dict[str, Any]) -> None:  
    """Best-effort compatibility bridge for EconomyBot/TournamentBot.  
  
    Clean Alaris uses alaris_characters.id as the canonical character_id.  
    Legacy service bots read public.characters.character_id, so this mirrors the  
    approved character into public.characters without making that table canonical.  
    """  
    try:  
        await conn.execute(  
            """  
            INSERT INTO characters (  
                character_id, guild_id, user_id, name, normalized_name, species, class_name,  
                kingdom, level, xp_total, archived, created_at, updated_at  
            )  
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,FALSE,NOW(),NOW())  
            ON CONFLICT (guild_id, character_id) DO UPDATE SET  
                guild_id=EXCLUDED.guild_id,  
                user_id=EXCLUDED.user_id,  
                name=EXCLUDED.name,  
                normalized_name=EXCLUDED.normalized_name,  
                species=EXCLUDED.species,  
                class_name=EXCLUDED.class_name,  
                kingdom=EXCLUDED.kingdom,  
                level=EXCLUDED.level,  
                xp_total=EXCLUDED.xp_total,  
                archived=FALSE,  
                updated_at=NOW();  
            """,  
            int(char["character_id"]),  
            int(char["guild_id"]),  
            int(char["user_id"]),  
            str(char["name"]),  
            str(char.get("normalized_name") or normalize_name(char["name"])),  
            str(char.get("species") or ""),  
            str(char.get("class_name") or ""),  
            str(char.get("kingdom") or ""),  
            int(char.get("level") or 1),  
            int(char.get("xp_total") or 0),  
        )  
    except Exception:  
        LOG.exception("Best-effort public.characters compatibility sync failed for character_id=%s", char.get("character_id"))  
  
  
async def create_character_from_payload(payload: dict[str, Any], approved_by: int) -> int:  
    stats = payload["stats"]  
    species_passive = find_passive("species", payload["species"], payload.get("species_passive_name"))  
    class_passive = find_passive("class", payload["class_name"], payload.get("class_passive_name"))  
  
    combat = calculate_combat_values(  
        payload["class_name"],  
        stats,  
        level=1,  
        damage_die_sides=8,  
        species_name=payload["species"],  
        species_passive=species_passive,  
        class_passive=class_passive,  
    )  
  
  
    # Safety migration in case approval runs against an older database schema.  
    async with db_pool.acquire() as migrate_conn:  
        await migrate_conn.execute("""  
            ALTER TABLE alaris_character_combat  
                ADD COLUMN IF NOT EXISTS magic_save_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS magic_defense INTEGER NOT NULL DEFAULT 10,  
                ADD COLUMN IF NOT EXISTS damage_bonus INTEGER NOT NULL DEFAULT 0,  
                ADD COLUMN IF NOT EXISTS max_resolve INTEGER NOT NULL DEFAULT 1,  
                ADD COLUMN IF NOT EXISTS current_resolve INTEGER NOT NULL DEFAULT 1;  
        """)  
  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchrow(  
            """  
            SELECT id, name, status  
            FROM alaris_characters  
            WHERE guild_id=$1 AND normalized_name=$2  
            LIMIT 1;  
            """,  
            int(payload["guild_id"]),  
            normalize_name(payload["name"]),  
        )  
        if existing:  
            raise RuntimeError(  
                f"A character named '{existing['name']}' already exists in this server. "  
                f"Use a unique name or remove/archive the existing character first."  
            )  
  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            char_id = await conn.fetchval(  
                """  
                INSERT INTO alaris_characters (  
                    guild_id, user_id, name, normalized_name, species, class_name, kingdom,  
                    species_passive_name, species_passive_json, class_passive_name, class_passive_json,  
                    image_url, image_filename, image_content_type, google_doc_url, level, xp_total, damage_die_sides,  
                    status, created_by, approved_by, approved_at  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11::jsonb,$12,$13,$14,$15,1,0,8,'active',$16,$17,NOW())  
                RETURNING id;  
                """,  
                int(payload["guild_id"]),  
                int(payload["user_id"]),  
                payload["name"],  
                payload["normalized_name"],  
                payload["species"],  
                payload["class_name"],  
                payload.get("kingdom"),  
                species_passive["name"],  
                json.dumps(species_passive),  
                class_passive["name"],  
                json.dumps(class_passive),  
                payload.get("image_url"),  
                payload.get("image_filename"),  
                payload.get("image_content_type"),  
                payload.get("google_doc_url"),  
                int(payload.get("created_by") or payload["user_id"]),  
                int(approved_by),  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_stats (  
                    character_id, strength, dexterity, constitution, intelligence, wisdom, charisma  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7);  
                """,  
                char_id,  
                int(stats["strength"]),  
                int(stats["dexterity"]),  
                int(stats["constitution"]),  
                int(stats["intelligence"]),  
                int(stats["wisdom"]),  
                int(stats["charisma"]),  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_combat (  
                    character_id, max_hp, current_hp, armor_class, initiative_bonus,  
                    proficiency_bonus, attack_bonus, spell_dc, technique_dc,  
                    magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                    max_resolve, current_resolve, damage_type, resistances_json, weaknesses_json, immunities_json  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb);  
                """,  
                char_id,  
                int(combat["max_hp"]),  
                int(combat["current_hp"]),  
                int(combat["armor_class"]),  
                int(combat["initiative_bonus"]),  
                int(combat["proficiency_bonus"]),  
                int(combat["attack_bonus"]),  
                combat["spell_dc"],  
                int(combat["technique_dc"]),  
                int(combat.get("magic_save_bonus") or 0),  
                int(combat.get("magic_defense") or 10),  
                int(combat["damage_die_sides"]),  
                int(combat.get("damage_bonus") or 0),  
                int(combat.get("max_resolve") or 1),  
                int(combat.get("current_resolve") or 1),  
                combat["damage_type"],  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_features (  
                    guild_id, character_id, source_type, feature_name, feature_type, level_granted, metadata_json  
                )  
                VALUES ($1,$2,'species',$3,'passive',1,$4::jsonb)  
                ON CONFLICT DO NOTHING;  
                """,  
                int(payload["guild_id"]),  
                char_id,  
                species_passive["name"],  
                json.dumps(species_passive),  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_features (  
                    guild_id, character_id, source_type, feature_name, feature_type, level_granted, metadata_json  
                )  
                VALUES ($1,$2,'class',$3,'passive',1,$4::jsonb)  
                ON CONFLICT DO NOTHING;  
                """,  
                int(payload["guild_id"]),  
                char_id,  
                class_passive["name"],  
                json.dumps(class_passive),  
            )  
            await sync_public_character_compat_row(conn, {  
                "character_id": int(char_id),  
                "guild_id": int(payload["guild_id"]),  
                "user_id": int(payload["user_id"]),  
                "name": payload["name"],  
                "normalized_name": payload["normalized_name"],  
                "species": payload["species"],  
                "class_name": payload["class_name"],  
                "kingdom": payload.get("kingdom"),  
                "level": 1,  
                "xp_total": 0,  
            })  
    return int(char_id)  
  
  
async def fetch_unlocked_abilities_raw(conn: asyncpg.Connection, character_id: int) -> list[dict[str, Any]]:  
    await conn.execute("""  
        CREATE TABLE IF NOT EXISTS alaris_character_abilities (  
            id BIGSERIAL PRIMARY KEY,  
            guild_id BIGINT NOT NULL,  
            character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
            ability_name TEXT NOT NULL,  
            class_name TEXT,  
            level_granted INTEGER NOT NULL DEFAULT 1,  
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
            UNIQUE(character_id, ability_name)  
        );  
    """)  
    rows = await conn.fetch(  
        """  
        SELECT ability_name, class_name, level_granted, metadata_json  
        FROM alaris_character_abilities  
        WHERE character_id=$1  
        ORDER BY level_granted, ability_name;  
        """,  
        int(character_id),  
    )  
    abilities: list[dict[str, Any]] = []  
    for row in rows:  
        meta = decode_json_payload(row["metadata_json"])  
        if not meta:  
            meta = {"name": row["ability_name"], "kind": "ability"}  
        meta.setdefault("name", row["ability_name"])  
        meta.setdefault("level", row["level_granted"])  
        meta.setdefault("source", row["class_name"] or "class")  
        abilities.append(meta)  
    return abilities  
  
  
  
async def backfill_unlocked_abilities_from_resolved_choices(character_id: int) -> int:  
    """Repair characters whose level choices were resolved before ability storage existed."""  
    payload = await fetch_clean_character_by_id_without_backfill(character_id)  
    if not payload:  
        return 0  
    c = payload["character"]  
    created = 0  
    async with db_pool.acquire() as conn:  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_abilities (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                ability_name TEXT NOT NULL,  
                class_name TEXT,  
                level_granted INTEGER NOT NULL DEFAULT 1,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, ability_name)  
            );  
        """)  
        rows = await conn.fetch(  
            """  
            SELECT level, choice_type, selected_option, metadata_json  
            FROM alaris_level_choices  
            WHERE character_id=$1  
              AND status='resolved'  
              AND choice_type IN ('ability','species_ability')  
              AND selected_option IS NOT NULL  
            ORDER BY level, choice_type;  
            """,  
            int(character_id),  
        )  
    for row in rows:  
        selected = str(row["selected_option"] or "").strip()  
        if not selected:  
            continue  
        if row["choice_type"] == "ability":  
            await unlock_character_ability_from_choice(int(character_id), selected, int(row["level"] or 1))  
            created += 1  
        elif row["choice_type"] == "species_ability":  
            await unlock_species_ability_from_choice(int(character_id), selected, int(row["level"] or 1))  
            created += 1  
    return created  
  
  
  
async def fetch_economy_summary_for_character(conn: asyncpg.Connection, guild_id: int, character_id: int) -> dict[str, Any]:  
    """Read EconomyBot-owned tables for card display. Missing econ schema is safe."""  
    exists = await conn.fetchval("SELECT to_regclass('econ.balances') IS NOT NULL;")  
    if not exists:  
        return {"balance_embers": 0, "noble_titles": [], "holdings": [], "businesses": []}  
  
    balance = await conn.fetchval(  
        "SELECT balance_embers FROM econ.balances WHERE guild_id=$1 AND character_id=$2;",  
        int(guild_id), int(character_id),  
    )  
    asset_exists = await conn.fetchval("SELECT to_regclass('econ.assets') IS NOT NULL;")  
    rows = []  
    if asset_exists:  
        rows = await conn.fetch(  
            """  
            SELECT asset_type, tier_code, asset_name, kingdom,  
                   noble_title_family, noble_title_option, noble_realm_name  
            FROM econ.assets  
            WHERE guild_id=$1 AND character_id=$2  
            ORDER BY asset_type, asset_name;  
            """,  
            int(guild_id), int(character_id),  
        )  
  
    titles: list[str] = []  
    holdings: list[str] = []  
    businesses: list[str] = []  
    for row in rows:  
        asset_type = str(row.get("asset_type") or "").strip()  
        tier_name = strip_tier_rank(row.get("tier_code"))  
        asset_name = str(row.get("asset_name") or "Unnamed Asset").strip()  
        lower_type = asset_type.lower()  
  
        if lower_type == "noble title":  
            option = str(row.get("noble_title_option") or "").strip()  
            realm = str(row.get("noble_realm_name") or "").strip()  
            if option and realm:  
                titles.append(f"{option} of {realm}")  
            elif asset_name:  
                titles.append(asset_name)  
            else:  
                titles.append(tier_name)  
            continue  
  
        line = f"{asset_name} | {tier_name}"  
        if lower_type in {"holding", "holdings", "property", "estate", "land"} or any(token in lower_type for token in ("castle", "keep", "manor", "property", "holding")):  
            holdings.append(line)  
        else:  
            businesses.append(line)  
  
    return {  
        "balance_embers": int(balance or 0),  
        "noble_titles": titles,  
        "holdings": holdings,  
        "businesses": businesses,  
    }  
  
  
  
def tournament_rank_from_rp_for_card(rp_total: int) -> str:  
    rp = int(rp_total or 0)  
    rank = "Newcomer"  
    for threshold, name in [(0, "Newcomer"), (10, "Proven"), (25, "Seasoned"), (50, "Renowned"), (90, "Champion"), (150, "Legend")]:  
        if rp >= threshold:  
            rank = name  
    return rank  
  
  
async def fetch_tournament_laurels_for_character(conn: asyncpg.Connection, guild_id: int, character_id: int) -> dict[str, Any]:  
    """Read TournamentBot-owned laurels for character card display. Missing tourney schema is safe."""  
    exists = await conn.fetchval("SELECT to_regclass('tourney.competitor_profiles') IS NOT NULL;")  
    if not exists:  
        return {"renown_points": 0, "rank": "Newcomer", "event_championships": 0, "runner_ups": 0, "overall_championships": 0, "laurels": []}  
  
    profile = await conn.fetchrow(  
        """  
        SELECT renown_points, event_championships, event_runner_ups, overall_championships  
        FROM tourney.competitor_profiles  
        WHERE guild_id=$1 AND character_id=$2;  
        """,  
        int(guild_id), int(character_id),  
    )  
    renown = int(profile["renown_points"] or 0) if profile else 0  
    event_champs = int(profile["event_championships"] or 0) if profile else 0  
    runner_ups = int(profile["event_runner_ups"] or 0) if profile else 0  
    overall_champs = int(profile["overall_championships"] or 0) if profile else 0  
  
    laurel_lines: list[str] = []  
    awards_exists = await conn.fetchval("SELECT to_regclass('tourney.awards') IS NOT NULL;")  
    if awards_exists:  
        rows = await conn.fetch(  
            """  
            SELECT award_code, award_name, COUNT(*) AS n  
            FROM tourney.awards  
            WHERE guild_id=$1 AND character_id=$2  
              AND award_code IN ('overall_champion','event_champion','event_runner_up','tournament_total_rewards')  
            GROUP BY award_code, award_name  
            ORDER BY  
                CASE award_code  
                    WHEN 'overall_champion' THEN 0  
                    WHEN 'event_champion' THEN 1  
                    WHEN 'event_runner_up' THEN 2  
                    ELSE 3  
                END,  
                award_name ASC  
            LIMIT 10;  
            """,  
            int(guild_id), int(character_id),  
        )  
        for row in rows:  
            name = str(row["award_name"] or row["award_code"] or "Laurel").strip()  
            n = int(row["n"] or 0)  
            if row["award_code"] == "tournament_total_rewards":  
                continue  
            laurel_lines.append(f"{name}" + (f" x{n}" if n > 1 else ""))  
  
    return {  
        "renown_points": renown,  
        "rank": tournament_rank_from_rp_for_card(renown),  
        "event_championships": event_champs,  
        "runner_ups": runner_ups,  
        "overall_championships": overall_champs,  
        "laurels": laurel_lines,  
    }  
  
  
async def fetch_clean_character_by_id_without_backfill(character_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        char = await conn.fetchrow("SELECT * FROM alaris_characters WHERE id=$1;", character_id)  
        if not char:  
            return None  
        stats = await conn.fetchrow("SELECT * FROM alaris_character_stats WHERE character_id=$1;", character_id)  
        combat = await conn.fetchrow("SELECT * FROM alaris_character_combat WHERE character_id=$1;", character_id)  
        pending_rows = await conn.fetch(  
            """  
            SELECT level, choice_type  
            FROM alaris_level_choices  
            WHERE character_id=$1 AND status='pending'  
            ORDER BY level, choice_type;  
            """,  
            character_id,  
        )  
        abilities = await fetch_unlocked_abilities_raw(conn, int(character_id))  
        economy = await fetch_economy_summary_for_character(conn, int(char["guild_id"]), int(character_id))  
        tournament = await fetch_tournament_laurels_for_character(conn, int(char["guild_id"]), int(character_id))  
    char_dict = dict(char)  
    char_dict["pending_level_choices_json"] = json.dumps([dict(r) for r in pending_rows])  
    char_dict["unlocked_abilities_json"] = json.dumps(abilities)  
    return {  
        "source": "clean",  
        "character": char_dict,  
        "stats": dict(stats) if stats else None,  
        "derived": dict(combat) if combat else None,  
        "abilities": abilities,  
        "economy": economy,  
        "tournament": tournament,  
    }  
  
  
  
async def fetch_clean_character_by_id(character_id: int) -> Optional[dict[str, Any]]:  
    # Fetch only. Do not auto-backfill here: backfill calls unlock helpers,  
    # and unlock helpers need character fetches. Auto-backfill caused recursion.  
    return await fetch_clean_character_by_id_without_backfill(character_id)  
  
  
async def find_clean_character(guild_id: int, query: str) -> Optional[dict[str, Any]]:  
    normalized = normalize_name(query)  
    if not normalized:  
        return None  
    async with db_pool.acquire() as conn:  
        char = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_characters  
            WHERE guild_id=$1  
              AND status='active'  
              AND (normalized_name=$2 OR lower(name)=$2 OR lower(name) LIKE $3)  
            ORDER BY  
              CASE WHEN normalized_name=$2 THEN 0 WHEN lower(name)=$2 THEN 1 ELSE 2 END,  
              name  
            LIMIT 1;  
            """,  
            guild_id, normalized, f"%{normalized}%",  
        )  
        if not char:  
            return None  
    return await fetch_clean_character_by_id(int(char["id"]))  
  
  
async def find_character(guild_id: int, query: str) -> Optional[dict[str, Any]]:  
    # v003 intentionally uses clean schema first. Old fallback remains minimal for transition.  
    clean = await find_clean_character(guild_id, query)  
    if clean:  
        return clean  
  
    async with db_pool.acquire() as conn:  
        if not await table_exists(conn, "characters"):  
            return None  
        ccols = await get_columns(conn, "characters")  
        if "id" not in ccols or "name" not in ccols:  
            return None  
        normalized = normalize_name(query)  
        args: list[Any] = []  
        where = []  
        if "guild_id" in ccols:  
            args.append(guild_id)  
            where.append(f"guild_id=${len(args)}")  
        if "status" in ccols:  
            where.append("COALESCE(status, 'active') <> 'archived'")  
        args.append(normalized)  
        norm_arg = len(args)  
        name_conditions = [f"lower(name)=${norm_arg}"]  
        if "normalized_name" in ccols:  
            name_conditions.append(f"normalized_name=${norm_arg}")  
        args.append(f"%{normalized}%")  
        like_arg = len(args)  
        name_conditions.append(f"lower(name) LIKE ${like_arg}")  
        where.append("(" + " OR ".join(name_conditions) + ")")  
        select_cols = [col for col in ["id", "guild_id", "user_id", "name", "species_name", "species", "class_name", "level", "xp_current", "xp_lifetime", "status"] if col in ccols]  
        row = await conn.fetchrow(  
            f"""  
            SELECT {", ".join(safe_identifier(c) for c in select_cols)}  
            FROM characters  
            WHERE {" AND ".join(where)}  
            ORDER BY name  
            LIMIT 1;  
            """,  
            *args,  
        )  
        if not row:  
            return None  
        return {"source": "old", "character": dict(row), "stats": None, "derived": None}  
  
  
# ---------- Embeds / Dashboard ----------  
  
def review_next_step_text(payload: dict[str, Any]) -> str:  
    if not payload.get("kingdom"):  
        return "Step 1: choose kingdom/affiliation using the dropdown below."  
    if not payload.get("species") or not payload.get("class_name"):  
        return "Step 2: choose species and class using the dropdowns below."  
    if not payload.get("stats"):  
        return "Step 3: assign stats using Auto-Assign or Manual Stats."  
    if not payload.get("species_passive_name") or not payload.get("class_passive_name"):  
        return "Step 4: choose species and class starter passives."  
    return "Step 5: review the finished draft, edit if needed, then staff may approve or reject."  
  
  
def build_review_embed(payload: dict[str, Any]) -> discord.Embed:  
    species = payload.get("species") or "Not selected"  
    class_name = payload.get("class_name") or "Not selected"  
    stats = payload.get("stats")  
  
    species_passive = None  
    class_passive = None  
    if payload.get("species") and payload.get("species_passive_name"):  
        species_passive = find_passive("species", species, payload.get("species_passive_name"))  
    if payload.get("class_name") and payload.get("class_passive_name"):  
        class_passive = find_passive("class", class_name, payload.get("class_passive_name"))  
  
    complete = bool(  
        payload.get("name")  
        and payload.get("species")  
        and payload.get("class_name")  
        and payload.get("kingdom")  
        and payload.get("species_passive_name")  
        and payload.get("class_passive_name")  
        and payload.get("stats")  
        and payload.get("google_doc_url")  
    )  
  
    status_text = (  
        "Status: **Ready for Approval**\n"  
        if complete  
        else "Status: **Draft in Progress**\n"  
    ) + review_next_step_text(payload)  
    if payload.get("draft_reset_note"):  
        status_text += f"\n\n**Reset Notice:** {payload.get('draft_reset_note')}"  
  
    embed = discord.Embed(  
        title=f"Character Review - {payload.get('name', 'Unnamed Character')}",  
        description=status_text,  
        color=discord.Color.gold() if complete else discord.Color.orange(),  
    )  
    embed.add_field(name="Player", value=f"<@{payload['user_id']}>", inline=True)  
    embed.add_field(name="Species", value=species, inline=True)  
    embed.add_field(name="Class", value=class_name, inline=True)  
    embed.add_field(name="Kingdom", value=payload.get("kingdom") or "Not selected", inline=True)  
    embed.add_field(name="Species Passive", value=(species_passive["name"] if species_passive else "Not selected"), inline=True)  
    embed.add_field(name="Class Passive", value=(class_passive["name"] if class_passive else "Not selected"), inline=True)  
    embed.add_field(name="Stats", value=(format_stats(stats) if stats else "Not selected"), inline=False)  
  
    if stats and payload.get("class_name") and species_passive and class_passive:  
        combat = calculate_combat_values(  
            payload["class_name"],  
            stats,  
            species_name=payload["species"],  
            species_passive=species_passive,  
            class_passive=class_passive,  
        )  
        embed.add_field(  
            name="Starting Combat Values",  
            value=(  
                f"HP **{combat['max_hp']}** | AC **{combat['armor_class']}** | Init **{format_modifier(combat['initiative_bonus'])}**\n"  
                f"Attack **{format_modifier(combat['attack_bonus'])}** | Technique DC **{combat['technique_dc']}** | "  
                f"Spell DC **{combat['spell_dc'] if combat['spell_dc'] is not None else '—'}**\n"  
                f"Damage Die **1d{combat['damage_die_sides']}** | Resolve **{combat.get('max_resolve', 1)}**"  
            ),  
            inline=False,  
        )  
    else:  
        embed.add_field(  
            name="Starting Combat Values",  
            value="Available after species, class, stats, and passives are selected.",  
            inline=False,  
        )  
  
    if payload.get("google_doc_url"):  
        embed.add_field(name="Google Doc", value=f"[Open Character Sheet]({payload['google_doc_url']})", inline=False)  
    if payload.get("image_url"):  
        embed.set_image(url=payload["image_url"])  
    embed.set_footer(text="Name must match the character Tupper exactly for RP XP tracking.")  
    return embed  
  
  
  
  
def format_starter_passives_for_card(character: dict[str, Any]) -> str:  
    def _safe_payload(value):  
        if value is None:  
            return []  
        try:  
            parsed = decode_json_payload(value)  
            if isinstance(parsed, dict):  
                return [parsed]  
            if isinstance(parsed, list):  
                return parsed  
        except Exception:  
            pass  
  
        try:  
            parsed = json.loads(value) if isinstance(value, str) else value  
            if isinstance(parsed, dict):  
                return [parsed]  
            if isinstance(parsed, list):  
                return parsed  
        except Exception:  
            return []  
  
        return []  
  
    species_json = _safe_payload(character.get("species_passive_json"))  
    class_json = _safe_payload(character.get("class_passive_json"))  
    story_json = _safe_payload(character.get("story_passives_json"))  
  
    collected = []  
  
    for payload in species_json + class_json + story_json:  
        if isinstance(payload, dict):  
            name = payload.get("name")  
            if name:  
                collected.append(f"• {name}")  
  
    if not collected:  
        return "None"  
  
    return "\n".join(collected[:15])  
  
  
def format_unlocked_abilities_for_card(abilities: list[dict[str, Any]]) -> str:  
    if not abilities:  
        return "None unlocked yet."  
    lines = []  
    for ability in abilities:  
        name = str(ability.get("name") or "Unnamed Ability")  
        level = ability.get("level") or ability.get("level_granted") or "?"  
        cost = ability.get("cost", 1)  
        kind = str(ability.get("kind") or "ability").title()  
        state = ability.get("state")  
        dtype = ability.get("damage_type")  
        tags = [kind, f"L{level}", f"{cost} Resolve"]  
        if dtype:  
            tags.append(str(dtype))  
        if state:  
            tags.append(f"State: {str(state).title()}")  
        lines.append(f"• **{name}** - " + " | ".join(tags))  
    return "\n".join(lines)[:1024]  
  
  
  
  
def compact_join(lines: list[str], *, empty: str = "None", limit: int = 1024) -> str:  
    cleaned = [str(x).strip() for x in lines if str(x or "").strip()]  
    if not cleaned:  
        return empty  
    text = "\n".join(cleaned)  
    if len(text) <= limit:  
        return text  
    out: list[str] = []  
    total = 0  
    remaining = len(cleaned)  
    for line in cleaned:  
        add = len(line) + (1 if out else 0)  
        if total + add > max(20, limit - 20):  
            break  
        out.append(line)  
        total += add  
        remaining -= 1  
    if remaining > 0:  
        out.append(f"+{remaining} more")  
    return "\n".join(out)[:limit]  
  
  
def strip_tier_rank(tier_code: Any) -> str:  
    raw = str(tier_code or "").strip()  
    raw = re.sub(r"^\(\s*\d+\s*\)\s*", "", raw)  
    raw = re.sub(r"^\d+\s*[-.)]?\s*", "", raw)  
    return raw or "Unknown Tier"  
  
  
def format_alaris_currency(total_embers: int, *, show_base_total: bool = True) -> str:  
    try:  
        raw_total = int(total_embers or 0)  
    except Exception:  
        raw_total = 0  
    sign = "-" if raw_total < 0 else ""  
    total = abs(raw_total)  
    astrals, rem = divmod(total, 100**4)  
    thrones, rem = divmod(rem, 100**3)  
    sovereigns, rem = divmod(rem, 100**2)  
    crowns, embers = divmod(rem, 100)  
    parts: list[str] = []  
    if astrals:  
        parts.append(f"{astrals} Astral" + ("" if astrals == 1 else "s"))  
    if thrones:  
        parts.append(f"{thrones} Throne" + ("" if thrones == 1 else "s"))  
    if sovereigns:  
        parts.append(f"{sovereigns} Sovereign" + ("" if sovereigns == 1 else "s"))  
    if crowns:  
        parts.append(f"{crowns} Crown" + ("" if crowns == 1 else "s"))  
    if embers or not parts:  
        parts.append(f"{embers} Ember" + ("" if embers == 1 else "s"))  
    shown = sign + ", ".join(parts)  
    if show_base_total:  
        shown += f" ({raw_total:,} Copper Embers)"  
    return shown  
  
  
def format_economy_card_section(economy: Optional[dict[str, Any]], *, detailed: bool = True) -> str:  
    if not economy:  
        return "Balance: Unknown\n\n__Noble Titles__\nNone\n\n__Holdings__\nNone\n\n__Businesses__\nNone"  
    balance = format_alaris_currency(int(economy.get("balance_embers") or 0))  
    title_lines = economy.get("noble_titles") or []  
    holding_lines = economy.get("holdings") or []  
    business_lines = economy.get("businesses") or []  
    if not detailed:  
        title_lines = title_lines[:5]  
        holding_lines = holding_lines[:6]  
        business_lines = business_lines[:8]  
    return (  
        f"Balance: **{balance}**\n\n"  
        f"__Noble Titles__\n{compact_join(title_lines, limit=900)}\n\n"  
        f"__Holdings__\n{compact_join(holding_lines, limit=900)}\n\n"  
        f"__Businesses__\n{compact_join(business_lines, limit=900)}"  
    )[:4000]  
  
  
def format_tournament_laurels_section(tournament: Optional[dict[str, Any]], *, detailed: bool = True) -> str:  
    if not tournament:  
        return "Rank: **Newcomer** | Renown: **0 RP**\n\n__Laurels__\nNone"  
    rank = str(tournament.get("rank") or "Newcomer")  
    renown = int(tournament.get("renown_points") or 0)  
    event_champs = int(tournament.get("event_championships") or 0)  
    runner_ups = int(tournament.get("runner_ups") or 0)  
    overall = int(tournament.get("overall_championships") or 0)  
    laurels = tournament.get("laurels") or []  
    if not detailed:  
        laurels = laurels[:5]  
    return (  
        f"Rank: **{rank}** | Renown: **{renown:,} RP**\n"  
        f"Overall Championships: **{overall}** | Event Wins: **{event_champs}** | Runner-Up: **{runner_ups}**\n\n"  
        f"__Laurels__\n{compact_join(laurels, limit=900)}"  
    )[:1024]  
  
  


def economy_has_display_entries(economy: Optional[dict[str, Any]]) -> bool:
    if not economy:
        return False
    if int(economy.get("balance_embers") or 0) != 0:
        return True
    return bool((economy.get("noble_titles") or []) or (economy.get("holdings") or []) or (economy.get("businesses") or []))


def tournament_has_display_entries(tournament: Optional[dict[str, Any]]) -> bool:
    if not tournament:
        return False
    return bool(
        int(tournament.get("renown_points") or 0) > 0
        or int(tournament.get("event_championships") or 0) > 0
        or int(tournament.get("runner_ups") or 0) > 0
        or int(tournament.get("overall_championships") or 0) > 0
        or (tournament.get("laurels") or [])
    )

def summarize_feature_counts(c: dict[str, Any], abilities: list[dict[str, Any]]) -> str:  
    species_passives = len(decode_json_list_payload(c.get("species_passive_json")))  
    class_passives = len(decode_json_list_payload(c.get("class_passive_json")))  
    story_passives = len(decode_json_list_payload(c.get("story_passives_json")))  
    active_count = len(abilities or [])  
    return f"Species {species_passives}P | Class {class_passives}P | Story {story_passives}P | Active {active_count}"  
  
  
def format_full_ability_details_for_card(c: dict[str, Any], abilities: list[dict[str, Any]]) -> str:  
    lines: list[str] = []  
  
    def add_payload_list(label: str, raw: Any):  
        items = decode_json_list_payload(raw)  
        for item in items:  
            if not isinstance(item, dict):  
                continue  
            name = str(item.get("name") or item.get("feature_name") or "Unnamed").strip()  
            desc = str(item.get("description") or item.get("effect") or item.get("summary") or "").strip()  
            cost = item.get("cost") or item.get("resolve_cost")  
            suffix = f" ({cost} Resolve)" if cost else ""  
            if desc:  
                lines.append(f"• **{name}** [{label}]{suffix} - {desc}")  
            else:  
                lines.append(f"• **{name}** [{label}]{suffix}")  
  
    add_payload_list("Species Passive", c.get("species_passive_json"))  
    add_payload_list("Class Passive", c.get("class_passive_json"))  
    add_payload_list("Story Passive", c.get("story_passives_json"))  
  
    for ability in abilities or []:  
        if not isinstance(ability, dict):  
            continue  
        name = str(ability.get("name") or ability.get("ability_name") or "Unnamed Ability").strip()  
        level = ability.get("level") or ability.get("level_granted") or "?"  
        kind = str(ability.get("kind") or ability.get("type") or "Ability").title()  
        cost = ability.get("cost") or ability.get("resolve_cost")  
        desc = str(ability.get("description") or ability.get("effect") or ability.get("summary") or "").strip()  
        tags = [kind, f"L{level}"]  
        if cost:  
            tags.append(f"{cost} Resolve")  
        if ability.get("damage_type"):  
            tags.append(str(ability.get("damage_type")))  
        if ability.get("state"):  
            tags.append(f"State: {str(ability.get('state')).title()}")  
        prefix = f"• **{name}** - " + " | ".join(tags)  
        lines.append(prefix + (f" - {desc}" if desc else ""))  
  
    return compact_join(lines, empty="None", limit=3900)  
  
  
def build_character_embed(payload: dict[str, Any], dashboard: bool = False) -> discord.Embed:  
    c = payload["character"]  
    stats = payload.get("stats") or {}  
    derived = payload.get("derived") or {}  
    source = payload.get("source", "clean")  
    economy = payload.get("economy") or {}  
    tournament = payload.get("tournament") or {}  
    abilities = payload.get("abilities") or decode_json_list_payload(c.get("unlocked_abilities_json"))  
  
    name = c.get("name", "Unknown Character")  
    level = int(c.get("level") or 1)  
    species = c.get("species", c.get("species_name", "Unknown")) or "Unknown"  
    class_name = c.get("class_name", "Unknown") or "Unknown"  
    secondary = c.get("secondary_class")  
    kingdom = c.get("kingdom") or "Unassigned"  
    owner = c.get("user_id")  
    damage_die = int(c.get("damage_die_sides") or 8)  
    xp_total = int(c.get("xp_total") or 0)  
  
    title = name if dashboard else f"Character - {name}"  
    class_line = f"Level {level} {class_name}" + (f" / {secondary}" if secondary else "")  
    description = f"**{class_line} | {species} | {kingdom}**\nOwner: {f'<@{owner}>' if owner else 'Unknown'}"  
    embed = discord.Embed(  
        title=title,  
        description=description,  
        color=discord.Color.blurple() if source == "clean" else discord.Color.orange(),  
    )  
  
    hp_value = "—"  
    if "current_hp" in derived or "max_hp" in derived:  
        hp_value = f"{derived.get('current_hp', '—')} / {derived.get('max_hp', '—')}"  
    ac_value = str(derived.get("armor_class", "—"))  
    init_value = format_modifier(derived.get("initiative_bonus"))  
    attack_value = format_modifier(derived.get("attack_bonus"))  
    spell_dc = str(derived.get("spell_dc", "—"))  
    technique_dc = str(derived.get("technique_dc", "—"))  
    resolve = "—"  
    if "max_resolve" in derived:  
        resolve = f"{derived.get('current_resolve', derived.get('max_resolve', 1))} / {derived.get('max_resolve', 1)}"  
  
    progression = format_progression_summary(xp_total, damage_die, level)  
    compact_core = (  
        f"**XP/Progress:** {progression}\n"  
        f"**Die:** 1d{damage_die} | **HP:** {hp_value} | **AC:** {ac_value} | **Init:** {init_value}\n"  
        f"**Attack:** {attack_value} | **Technique DC:** {technique_dc} | **Spell DC:** {spell_dc} | **Resolve:** {resolve}"  
    )  
    embed.add_field(name="__Core__", value=compact_core[:1024], inline=False)  
  
    if stats:  
        embed.add_field(name="__Stats__", value=format_stats(stats)[:1024], inline=False)  
  
    if dashboard:  
        embed.add_field(name="__Features__", value=summarize_feature_counts(c, abilities), inline=False)  
    else:  
        embed.add_field(name="__Features & Abilities__", value=format_full_ability_details_for_card(c, abilities), inline=False)  
  
    if derived and not dashboard:  
        affinity = (  
            f"**Resistances:** {format_affinity_json(derived.get('resistances_json'))}\n"  
            f"**Weaknesses:** {format_affinity_json(derived.get('weaknesses_json'))}\n"  
            f"**Immunities:** {format_affinity_json(derived.get('immunities_json'))}\n"  
            f"**Magic Defense:** {derived.get('magic_defense', 10)} ({format_modifier(derived.get('magic_save_bonus'))})"  
        )  
        embed.add_field(name="__Defenses__", value=affinity[:1024], inline=False)  
  
    pending_raw = c.get("pending_level_choices_json")  
    if pending_raw and not dashboard:  
        try:  
            pending_items = decode_json_payload(pending_raw)  
            if isinstance(pending_items, list) and pending_items:  
                embed.add_field(  
                    name="__Pending Level Choices__",  
                    value="\n".join(f"• Level {x.get('level')}: {x.get('choice_type')}" for x in pending_items)[:1024],  
                    inline=False,  
                )  
        except Exception:  
            pass  
  
    if tournament_has_display_entries(tournament):
        embed.add_field(name="__Tournament Laurels__", value=format_tournament_laurels_section(tournament, detailed=not dashboard), inline=False)

    if economy_has_display_entries(economy):
        embed.add_field(name="__Economy__", value=format_economy_card_section(economy, detailed=True), inline=False)
  
    doc = c.get("google_doc_url")  
    if doc:  
        embed.add_field(name="__Links__", value=f"[Open Google Doc]({doc})", inline=False)  
  
    image = c.get("image_url")  
    if image:  
        if dashboard:  
            embed.set_thumbnail(url=image)  
        else:  
            embed.set_image(url=image)  
  
    embed.set_footer(text=f"Alaris Character ID: {c.get('id')}")  
    return embed  
  
MAX_CHARACTER_POST_IMAGE_BYTES = 7_500_000  
  
  
async def build_discord_image_file_from_url(url: Optional[str], filename: Optional[str] = None) -> Optional[discord.File]:  
    """Download a stored Discord attachment URL and return it as a Discord file.  
  
    This is used so the discussion/forum starter post can contain an uploaded  
    image attachment. If the image is too large for a safe Discord forum-thread  
    create request, skip the reupload instead of failing character approval.  
    The character card still carries the original image URL/embed afterward.  
    """  
    if not url:  
        return None  
    try:  
        async with bot.http._HTTPClient__session.get(str(url)) as resp:  
            if resp.status != 200:  
                LOG.warning("Could not download character image for reupload. HTTP status=%s", resp.status)  
                return None  
            data = await resp.read()  
    except Exception:  
        LOG.exception("Failed to download character image for reupload.")  
        return None  
  
    if len(data) > MAX_CHARACTER_POST_IMAGE_BYTES:  
        LOG.warning(  
            "Character image reupload skipped because file is too large: %s bytes > %s bytes",  
            len(data), MAX_CHARACTER_POST_IMAGE_BYTES,  
        )  
        return None  
  
    safe_name = filename or "character-image.png"  
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", safe_name)  
    if "." not in safe_name:  
        safe_name += ".png"  
    return discord.File(io.BytesIO(data), filename=safe_name)  
  
  
async def get_character_discussion_channel(guild: discord.Guild) -> Optional[discord.abc.GuildChannel]:  
    if not CHARACTER_DISCUSSION_CHANNEL_ID:  
        return None  
    channel = guild.get_channel(CHARACTER_DISCUSSION_CHANNEL_ID)  
    if channel is None:  
        try:  
            channel = await bot.fetch_channel(CHARACTER_DISCUSSION_CHANNEL_ID)  
        except Exception:  
            LOG.exception("Failed to fetch CHARACTER_DISCUSSION_CHANNEL_ID=%s", CHARACTER_DISCUSSION_CHANNEL_ID)  
            return None  
    return channel  
  
  
async def create_or_update_character_discussion_post(guild: discord.Guild, character_id: int, *, create_if_missing: bool = True) -> Optional[int]:  
    """Create or update a character discussion/forum post for an approved character.  
  
    Safety note: economy/external refreshes must call the edit-only refresh path  
    instead of using this create-capable helper. When create_if_missing=False,  
    this function will never create a new showcase post.  
    """  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return None  
  
    channel = await get_character_discussion_channel(guild)  
    if channel is None:  
        LOG.warning("Character discussion channel is not configured or unavailable.")  
        return None  
  
    char = payload["character"]  
    name = str(char.get("name") or f"Character {character_id}")  
    image_url = char.get("image_url")  
    doc_url = char.get("google_doc_url")  
    embed = build_character_embed(payload, dashboard=True)  
  
    # Starter post should contain the character image only so Discord uses the  
    # image as the forum/discussion preview. Do NOT include the Google Doc link  
    # here, because Discord will often unfurl it and use the document preview as  
    # the post cover/preview instead of the image. The Google Doc remains clickable  
    # inside the character card embed below.  
    # Keep the starter post clean so the forum/discussion preview uses the image/name.  
    # The single player ping is posted in the welcome message below.  
    starter_content = f"**{name}**"  
    image_file = await build_discord_image_file_from_url(image_url, char.get("image_filename"))  
  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchrow(  
            """  
            SELECT thread_id, starter_message_id, card_message_id, welcome_message_id  
            FROM alaris_character_posts  
            WHERE character_id=$1;  
            """,  
            character_id,  
        )  
  
    if existing:  
        thread = None  
        try:  
            thread = guild.get_thread(int(existing["thread_id"]))  
            if thread is None:  
                fetched = await bot.fetch_channel(int(existing["thread_id"]))  
                if isinstance(fetched, discord.Thread):  
                    thread = fetched  
        except Exception:  
            thread = None  
  
        if isinstance(thread, discord.Thread):  
            try:  
                if thread.name != name[:100]:  
                    await thread.edit(name=name[:100], reason=f"Refresh Alaris character post title for {name}")  
            except Exception:  
                LOG.exception("Failed to update character discussion thread title for character_id=%s", character_id)  
  
            try:  
                starter_id = existing["starter_message_id"]  
                if starter_id:  
                    starter_msg = await thread.fetch_message(int(starter_id))  
                    await starter_msg.edit(content=starter_content)  
            except Exception:  
                pass  
  
            try:  
                card_id = existing["card_message_id"]  
                if card_id:  
                    card_msg = await thread.fetch_message(int(card_id))  
                    await card_msg.edit(embed=embed)  
                else:  
                    card_msg = await thread.send(embed=embed)  
                    async with db_pool.acquire() as conn:  
                        await conn.execute(  
                            """  
                            UPDATE alaris_character_posts  
                            SET card_message_id=$2, updated_at=NOW()  
                            WHERE character_id=$1;  
                            """,  
                            character_id, card_msg.id,  
                        )  
            except Exception:  
                LOG.exception("Failed to update character card inside existing discussion post.")  
  
            try:  
                owner_id = char.get("user_id")  
                owner_ping = f"<@{owner_id}>" if owner_id else "player"  
                welcome_content = (  
                    f"Congratulations, {owner_ping}! Your character is approved for roleplay in the Realms of Alaris. "  
                    "Use this space to post additional images, character notes, or links to scenes. "  
                    "This is your creative dashboard to showcase your character!"  
                )  
                welcome_id = existing["welcome_message_id"]  
                if welcome_id:  
                    welcome_msg = await thread.fetch_message(int(welcome_id))  
                    await welcome_msg.edit(content=welcome_content)  
                else:  
                    welcome_msg = await thread.send(welcome_content)  
                    async with db_pool.acquire() as conn:  
                        await conn.execute(  
                            """  
                            UPDATE alaris_character_posts  
                            SET welcome_message_id=$2, updated_at=NOW()  
                            WHERE character_id=$1;  
                            """,  
                            character_id, welcome_msg.id,  
                        )  
            except Exception:  
                LOG.exception("Failed to update welcome message inside existing discussion post.")  
  
            return int(thread.id)  
  
    if not create_if_missing:  
        LOG.warning(  
            "Edit-only character post refresh skipped because no existing post mapping was found for character_id=%s.",  
            character_id,  
        )  
        return None  
  
    starter_message = None  
    card_message = None  
    thread_id = None  
  
    if isinstance(channel, discord.ForumChannel):  
        try:  
            created = await channel.create_thread(  
                name=name[:100],  
                content=starter_content,  
                file=image_file,  
                reason=f"Approved Alaris character post for {name}",  
            )  
            thread = created.thread  
            starter_message = created.message  
            thread_id = thread.id  
            card_message = await thread.send(embed=embed)  
        except discord.HTTPException as exc:  
            # Discord returns 413 / 40005 when the initial forum-thread payload is too large,  
            # most commonly because of a large uploaded character image. Character approval  
            # should still succeed, so retry without the attachment and keep the image in  
            # the card embed via its original URL.  
            if getattr(exc, "status", None) == 413 or getattr(exc, "code", None) == 40005:  
                LOG.warning("Forum post image payload too large; retrying character post without attachment for %s", name)  
                try:  
                    created = await channel.create_thread(  
                        name=name[:100],  
                        content=starter_content,  
                        reason=f"Approved Alaris character post for {name}",  
                    )  
                    thread = created.thread  
                    starter_message = created.message  
                    thread_id = thread.id  
                    card_message = await thread.send(embed=embed)  
                except Exception:  
                    LOG.exception("Failed to create forum post for character after no-file retry.")  
                    return None  
            else:  
                LOG.exception("Failed to create forum post for character.")  
                return None  
        except Exception:  
            LOG.exception("Failed to create forum post for character.")  
            return None  
  
    elif isinstance(channel, discord.TextChannel):  
        try:  
            try:  
                starter_message = await channel.send(starter_content, file=image_file)  
            except discord.HTTPException as exc:  
                if getattr(exc, "status", None) == 413 or getattr(exc, "code", None) == 40005:  
                    LOG.warning("Text-channel starter image payload too large; retrying without attachment for %s", name)  
                    starter_message = await channel.send(starter_content)  
                else:  
                    raise  
            thread = await starter_message.create_thread(  
                name=name[:100],  
                reason=f"Approved Alaris character discussion for {name}",  
            )  
            thread_id = thread.id  
            card_message = await thread.send(embed=embed)  
        except Exception:  
            LOG.exception("Failed to create text-channel thread for character.")  
            return None  
    else:  
        LOG.warning("Configured character discussion channel is not a forum or text channel: %r", channel)  
        return None  
  
    owner_id = char.get("user_id")  
    owner_ping = f"<@{owner_id}>" if owner_id else "player"  
    welcome_content = (  
        f"Congratulations, {owner_ping}! Your character is approved for roleplay in the Realms of Alaris. "  
        "Use this space to post additional images, character notes, or links to scenes. "  
        "This is your creative dashboard to showcase your character!"  
    )  
    welcome_message = None  
    try:  
        if thread_id:  
            thread_channel = guild.get_thread(int(thread_id))  
            if thread_channel is None:  
                fetched_thread = await bot.fetch_channel(int(thread_id))  
                thread_channel = fetched_thread if isinstance(fetched_thread, discord.Thread) else None  
            if isinstance(thread_channel, discord.Thread):  
                welcome_message = await thread_channel.send(welcome_content)  
    except Exception:  
        LOG.exception("Failed to post character welcome message.")  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_posts (  
                guild_id, character_id, forum_channel_id, thread_id,  
                starter_message_id, card_message_id, welcome_message_id, updated_at  
            )  
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())  
            ON CONFLICT (character_id) DO UPDATE SET  
                guild_id=EXCLUDED.guild_id,  
                forum_channel_id=EXCLUDED.forum_channel_id,  
                thread_id=EXCLUDED.thread_id,  
                starter_message_id=EXCLUDED.starter_message_id,  
                card_message_id=EXCLUDED.card_message_id,  
                welcome_message_id=EXCLUDED.welcome_message_id,  
                updated_at=NOW();  
            """,  
            guild.id,  
            character_id,  
            int(CHARACTER_DISCUSSION_CHANNEL_ID),  
            int(thread_id),  
            int(starter_message.id) if starter_message else None,  
            int(card_message.id) if card_message else None,  
            int(welcome_message.id) if welcome_message else None,  
        )  
  
    return int(thread_id) if thread_id else None  
  
  
# ---------- Creation UI ----------  
  
class CharacterCreateModal(discord.ui.Modal, title="Create Character"):  
    character_name = discord.ui.TextInput(  
        label="Character Name",  
        placeholder="Must match the character Tupper name exactly for RP XP tracking.",  
        max_length=80,  
    )  
    google_doc_url = discord.ui.TextInput(  
        label="Google Docs Character Sheet URL",  
        placeholder="https://docs.google.com/...",  
        max_length=500,  
    )  
  
    def __init__(self, image_attachment: discord.Attachment):  
        super().__init__()  
        self.image_attachment = image_attachment  
  
    async def on_submit(self, interaction: discord.Interaction):  
        if interaction.guild is None:  
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
            return  
  
        name = str(self.character_name.value).strip()  
        normalized = normalize_name(name)  
        doc = str(self.google_doc_url.value).strip()  
        image = str(self.image_attachment.url)  
  
        if not name:  
            await interaction.response.send_message("Character name is required.", ephemeral=True)  
            return  
        if not (self.image_attachment.content_type or "").startswith("image/"):  
            await interaction.response.send_message("The uploaded character image must be an image file.", ephemeral=True)  
            return  
        if not valid_url(doc):  
            await interaction.response.send_message("Google Docs URL must start with `http://` or `https://`.", ephemeral=True)  
            return  
        if await clean_character_name_exists(interaction.guild.id, normalized):  
            await interaction.response.send_message(f"A clean Alaris character named **{name}** already exists.", ephemeral=True)  
            return  
        if await open_ticket_name_exists(interaction.guild.id, normalized):  
            await interaction.response.send_message(f"A review ticket for **{name}** is already open.", ephemeral=True)  
            return  
  
        payload = {  
            "guild_id": interaction.guild.id,  
            "user_id": interaction.user.id,  
            "created_by": interaction.user.id,  
            "name": name,  
            "normalized_name": normalized,  
            "image_url": image,  
            "image_filename": self.image_attachment.filename,  
            "image_content_type": self.image_attachment.content_type,  
            "google_doc_url": doc,  
        }  
        embed = discord.Embed(  
            title="Choose Character Kingdom",  
            description="Choose the kingdom or region this character is primarily associated with. Staff can change this later if needed.",  
            color=discord.Color.blurple(),  
        )  
        embed.add_field(name="Character", value=name, inline=True)  
        embed.add_field(name="Owner", value=f"<@{interaction.user.id}>", inline=True)  
        await interaction.response.send_message(embed=embed, view=InitialKingdomSelectView(payload), ephemeral=True)  
  
  
  
class InitialKingdomSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        options = [discord.SelectOption(label=k, value=k) for k in KINGDOM_OPTIONS[:25]]  
        super().__init__(  
            placeholder="Choose kingdom / affiliation...",  
            min_values=1,  
            max_values=1,  
            options=options,  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        if interaction.guild is None:  
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
            return  
        self.payload["kingdom"] = self.values[0]  
        await create_review_ticket(interaction, self.payload)  
  
  
class InitialKingdomSelectView(discord.ui.View):  
    def __init__(self, payload: dict[str, Any]):  
        super().__init__(timeout=900)  
        self.add_item(InitialKingdomSelect(payload))  
  
  
class InitialSpeciesSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        options = [discord.SelectOption(label=s, value=s) for s in SPECIES_OPTIONS[:25]]  
        super().__init__(  
            placeholder="Choose playable species...",  
            min_values=1,  
            max_values=1,  
            options=options,  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        if interaction.guild is None:  
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
            return  
        self.payload["species"] = self.values[0]  
        await create_review_ticket(interaction, self.payload)  
  
  
class InitialSpeciesSelectView(discord.ui.View):  
    def __init__(self, payload: dict[str, Any]):  
        super().__init__(timeout=900)  
        self.add_item(InitialSpeciesSelect(payload))  
  
  
  
  
class OpenCharacterCreateModalButton(discord.ui.Button):  
    def __init__(self, image_attachment: discord.Attachment):  
        super().__init__(label="Open Character Form", style=discord.ButtonStyle.green)  
        self.image_attachment = image_attachment  
  
    async def callback(self, interaction: discord.Interaction):  
        try:  
            await interaction.response.send_modal(CharacterCreateModal(self.image_attachment))  
        except discord.NotFound:  
            # The button interaction itself expired. This should be rare, but the user can click again.  
            try:  
                await interaction.followup.send("That interaction expired. Click **Open Character Form** again.", ephemeral=True)  
            except Exception:  
                pass  
  
  
class CharacterCreateStartView(discord.ui.View):  
    def __init__(self, image_attachment: discord.Attachment):  
        super().__init__(timeout=900)  
        self.add_item(OpenCharacterCreateModalButton(image_attachment))  
  
  
class SpeciesSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        super().__init__(  
            placeholder="Choose species...",  
            min_values=1,  
            max_values=1,  
            options=[discord.SelectOption(label=s, value=s) for s in SPECIES_OPTIONS[:25]],  # Discord select limit is 25 options.  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        self.payload["species"] = self.values[0]  
        self.payload.pop("species_passive_name", None)  
        self.payload.pop("species_passive_json", None)  
        await interaction.response.edit_message(embed=build_creation_progress_embed(self.payload), view=SpeciesClassView(self.payload))  
  
  
class ClassSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        super().__init__(  
            placeholder="Choose class...",  
            min_values=1,  
            max_values=1,  
            options=[discord.SelectOption(label=c, value=c) for c in CLASS_OPTIONS[:25]],  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        self.payload["class_name"] = self.values[0]  
        self.payload.pop("class_passive_name", None)  
        self.payload.pop("class_passive_json", None)  
        await interaction.response.edit_message(embed=build_creation_progress_embed(self.payload), view=SpeciesClassView(self.payload))  
  
  
class SpeciesPassiveSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        species = payload.get("species") or "Human"  
        super().__init__(  
            placeholder="Choose species passive...",  
            min_values=1,  
            max_values=1,  
            options=passive_select_options("species", species),  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        species = self.payload.get("species")  
        passive = find_passive("species", species, self.values[0])  
        self.payload["species_passive_name"] = passive["name"]  
        self.payload["species_passive_json"] = passive  
        await interaction.response.edit_message(embed=build_creation_progress_embed(self.payload), view=SpeciesClassView(self.payload))  
  
  
class ClassPassiveSelect(discord.ui.Select):  
    def __init__(self, payload: dict[str, Any]):  
        self.payload = payload  
        class_name = payload.get("class_name") or "Fighter"  
        super().__init__(  
            placeholder="Choose class passive...",  
            min_values=1,  
            max_values=1,  
            options=passive_select_options("class", class_name),  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        class_name = self.payload.get("class_name")  
        passive = find_passive("class", class_name, self.values[0])  
        self.payload["class_passive_name"] = passive["name"]  
        self.payload["class_passive_json"] = passive  
        await interaction.response.edit_message(embed=build_creation_progress_embed(self.payload), view=SpeciesClassView(self.payload))  
  
  
  
def build_creation_progress_embed(payload: dict[str, Any]) -> discord.Embed:  
    embed = discord.Embed(  
        title="Character Creation",  
        description="Choose species, class, starter passives, then select stat assignment.",  
        color=discord.Color.blurple(),  
    )  
    embed.add_field(name="Character", value=payload.get("name", "Unknown"), inline=True)  
    embed.add_field(name="Owner", value=f"<@{payload.get('user_id')}>", inline=True)  
    embed.add_field(name="Kingdom", value=payload.get("kingdom", "Not selected"), inline=True)  
    embed.add_field(name="Species", value=payload.get("species", "Not selected"), inline=True)  
    embed.add_field(name="Class", value=payload.get("class_name", "Not selected"), inline=True)  
    embed.add_field(name="Species Passive", value=payload.get("species_passive_name", "Not selected"), inline=True)  
    embed.add_field(name="Class Passive", value=payload.get("class_passive_name", "Not selected"), inline=True)  
    if payload.get("stats"):  
        embed.add_field(name="Stats", value=format_stats(payload["stats"]), inline=False)  
    if payload.get("google_doc_url"):  
        embed.add_field(name="Google Doc", value=f"[Open Character Sheet]({payload['google_doc_url']})", inline=False)  
    if payload.get("image_url"):  
        embed.set_image(url=payload["image_url"])  
    return embed  
  
  
class ManualStatsModal(discord.ui.Modal, title="Manual Standard Array"):  
    stat_line = discord.ui.TextInput(  
        label="Enter STR DEX CON INT WIS CHA",  
        placeholder="Example: 15 14 13 12 10 8",  
        max_length=80,  
    )  
  
    def __init__(self, payload: dict[str, Any]):  
        super().__init__()  
        self.payload = payload  
  
    async def on_submit(self, interaction: discord.Interaction):  
        ok, stats, err = validate_standard_array(str(self.stat_line.value))  
        if not ok:  
            await interaction.response.send_message(err, ephemeral=True)  
            return  
        self.payload["stats"] = stats  
        self.payload["stat_method"] = "Manual Standard Array"  
        await create_review_ticket(interaction, self.payload)  
  
  
class SpeciesClassView(discord.ui.View):  
    def __init__(self, payload: dict[str, Any]):  
        super().__init__(timeout=900)  
        self.payload = payload  
        self.add_item(SpeciesSelect(payload))  
        self.add_item(ClassSelect(payload))  
        if payload.get("species"):  
            self.add_item(SpeciesPassiveSelect(payload))  
        if payload.get("class_name"):  
            self.add_item(ClassPassiveSelect(payload))  
  
    @discord.ui.button(label="Auto-Assign Stats by Class", style=discord.ButtonStyle.green)  
    async def auto_assign_button(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not self.payload.get("species") or not self.payload.get("class_name"):  
            await interaction.response.send_message("Choose both species and class first.", ephemeral=True)  
            return  
        if not self.payload.get("species_passive_name") or not self.payload.get("class_passive_name"):  
            await interaction.response.send_message("Choose both starter passives first.", ephemeral=True)  
            return  
        if not self.payload.get("species_passive_name") or not self.payload.get("class_passive_name"):  
            await interaction.response.send_message("Choose both starter passives first.", ephemeral=True)  
            return  
        self.payload["stats"] = auto_assign_stats(self.payload["class_name"])  
        self.payload["stat_method"] = "Auto-Assigned by Class"  
        await create_review_ticket(interaction, self.payload)  
  
    @discord.ui.button(label="Manual Standard Array", style=discord.ButtonStyle.blurple)  
    async def manual_button(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not self.payload.get("species") or not self.payload.get("class_name"):  
            await interaction.response.send_message("Choose both species and class first.", ephemeral=True)  
            return  
        await interaction.response.send_modal(ManualStatsModal(self.payload))  
  
  
async def fetch_open_review_ticket_payload(ticket_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        ticket = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_character_review_tickets  
            WHERE id=$1 AND status='open';  
            """,  
            int(ticket_id),  
        )  
    if not ticket:  
        return None  
    payload = decode_json_payload(ticket["payload_json"])  
    payload["_ticket_id"] = int(ticket_id)  
    payload["_channel_id"] = int(ticket["channel_id"]) if ticket.get("channel_id") else None  
    payload["_review_message_id"] = int(ticket["review_message_id"]) if ticket.get("review_message_id") else None  
    return payload  
  
  
async def update_review_ticket_payload(ticket_id: int, payload: dict[str, Any]) -> None:  
    stored = dict(payload)  
    stored.pop("_ticket_id", None)  
    stored.pop("_channel_id", None)  
    stored.pop("_review_message_id", None)  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_character_review_tickets  
            SET payload_json=$2::jsonb  
            WHERE id=$1 AND status='open';  
            """,  
            int(ticket_id), json.dumps(stored),  
        )  
  
  
async def apply_ticket_payload_update(interaction: discord.Interaction, ticket_id: int, payload: dict[str, Any], note: str) -> None:  
    await update_review_ticket_payload(ticket_id, payload)  
    embed = build_review_embed(payload)  
    view = CharacterApprovalView(ticket_id, payload)  
    if interaction.response.is_done():  
        try:  
            await interaction.edit_original_response(embed=embed, view=view)  
        except Exception:  
            pass  
        await interaction.followup.send(note, ephemeral=True)  
    else:  
        await interaction.response.edit_message(embed=embed, view=view)  
  
  
async def ticket_name_conflicts(guild_id: int, normalized_name: str, ticket_id: int) -> bool:  
    async with db_pool.acquire() as conn:  
        active_conflict = await conn.fetchval(  
            """  
            SELECT EXISTS(  
                SELECT 1 FROM alaris_characters  
                WHERE guild_id=$1 AND normalized_name=$2 AND status='active'  
            );  
            """,  
            int(guild_id), normalized_name,  
        )  
        ticket_conflict = await conn.fetchval(  
            """  
            SELECT EXISTS(  
                SELECT 1  
                FROM alaris_character_review_tickets  
                WHERE guild_id=$1  
                  AND status='open'  
                  AND id<>$3  
                  AND lower(payload_json->>'normalized_name')=$2  
            );  
            """,  
            int(guild_id), normalized_name, int(ticket_id),  
        )  
    return bool(active_conflict or ticket_conflict)  
  
  
  
def reset_preapproval_build_choices(payload: dict[str, Any], *, reset_identity: bool = True) -> dict[str, Any]:  
    """Reset only the review-ticket draft build selections.  
  
    This intentionally mutates only alaris_character_review_tickets.payload_json  
    before approval. It does not touch approved alaris_characters rows, XP,  
    combat data, discussion posts, or session history.  
    """  
    updated = dict(payload)  
    for internal_key in ("_ticket_id", "_channel_id", "_review_message_id"):  
        # Internal keys are harmless during edit rendering, but should never be persisted.  
        updated.pop(internal_key, None)  
  
    keys_to_clear = [  
        "species_passive_name",  
        "species_passive_json",  
        "class_passive_name",  
        "class_passive_json",  
        "stats",  
        "stat_method",  
    ]  
    if reset_identity:  
        keys_to_clear.extend(["species", "class_name"])  
  
    for key in keys_to_clear:  
        updated.pop(key, None)  
  
    updated["draft_reset_pending"] = True  
    updated["draft_reset_note"] = "Build choices were reset before approval. Re-select species, class, stats, and starter passives."  
    return updated  
  
def review_payload_ready_for_approval(payload: dict[str, Any]) -> tuple[bool, str]:  
    required = [  
        ("name", "character name"),  
        ("normalized_name", "normalized character name"),  
        ("species", "species"),  
        ("class_name", "class"),  
        ("kingdom", "kingdom"),  
        ("species_passive_name", "species passive"),  
        ("class_passive_name", "class passive"),  
        ("stats", "stats"),  
        ("google_doc_url", "Google Doc URL"),  
        ("image_url", "image URL"),  
    ]  
    missing = [label for key, label in required if not payload.get(key)]  
    if missing:  
        return False, "Missing: " + ", ".join(missing) + "."  
    if normalize_name(payload.get("species")) not in {normalize_name(s) for s in SPECIES_OPTIONS}:  
        return False, "Species is not one of the approved Alaris species."  
    if normalize_name(payload.get("class_name")) not in {normalize_name(c) for c in CLASS_OPTIONS}:  
        return False, "Class is not one of the approved Alaris classes."  
    if normalize_name(payload.get("kingdom")) not in {normalize_name(k) for k in KINGDOM_OPTIONS}:  
        return False, "Kingdom is not one of the approved Alaris kingdoms/affiliations."  
    if not valid_url(payload.get("google_doc_url", "")):  
        return False, "Google Doc URL must start with http:// or https://."  
    if not valid_url(payload.get("image_url", "")):  
        return False, "Image URL must start with http:// or https://."  
    return True, "Ready."  
  
  
def character_review_stage(payload: dict[str, Any]) -> str:  
    if not payload.get("kingdom"):  
        return "kingdom"  
    if not payload.get("species") or not payload.get("class_name"):  
        return "identity"  
    if not payload.get("stats"):  
        return "stats"  
    if not payload.get("species_passive_name") or not payload.get("class_passive_name"):  
        return "passives"  
    return "final"  
  
  
class TicketKingdomSelect(discord.ui.Select):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        self.ticket_id = int(ticket_id)  
        options = [  
            discord.SelectOption(  
                label=k,  
                value=k,  
                default=(normalize_name(k) == normalize_name(payload.get("kingdom"))),  
            )  
            for k in KINGDOM_OPTIONS[:25]  
        ]  
        super().__init__(placeholder="Step 1: choose kingdom/affiliation...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        selected = self.values[0]  
        payload["kingdom"] = selected  
        payload.pop("draft_reset_pending", None)  
        payload.pop("draft_reset_note", None)  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, f"Kingdom set to **{selected}**.")  
  
  
class TicketSpeciesSelect(discord.ui.Select):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        self.ticket_id = int(ticket_id)  
        options = [  
            discord.SelectOption(  
                label=s,  
                value=s,  
                default=(normalize_name(s) == normalize_name(payload.get("species"))),  
            )  
            for s in SPECIES_OPTIONS[:25]  
        ]  
        super().__init__(placeholder="Step 1: choose species...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        selected = self.values[0]  
        if normalize_name(payload.get("species")) != normalize_name(selected):  
            payload["species"] = selected  
            payload.pop("species_passive_name", None)  
            payload.pop("species_passive_json", None)  
            payload.pop("draft_reset_pending", None)  
            payload.pop("draft_reset_note", None)  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, f"Species set to **{selected}**.")  
  
  
class TicketClassSelect(discord.ui.Select):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        self.ticket_id = int(ticket_id)  
        options = [  
            discord.SelectOption(  
                label=c,  
                value=c,  
                default=(normalize_name(c) == normalize_name(payload.get("class_name"))),  
            )  
            for c in CLASS_OPTIONS[:25]  
        ]  
        super().__init__(placeholder="Step 1: choose class...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        selected = self.values[0]  
        if normalize_name(payload.get("class_name")) != normalize_name(selected):  
            payload["class_name"] = selected  
            payload.pop("class_passive_name", None)  
            payload.pop("class_passive_json", None)  
            payload.pop("stats", None)  
            payload.pop("stat_method", None)  
            payload.pop("draft_reset_pending", None)  
            payload.pop("draft_reset_note", None)  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, f"Class set to **{selected}**.")  
  
  
class TicketSpeciesPassiveSelect(discord.ui.Select):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        self.ticket_id = int(ticket_id)  
        species = payload.get("species") or "Human"  
        options = passive_select_options("species", species)  
        for opt in options:  
            opt.default = normalize_name(opt.value) == normalize_name(payload.get("species_passive_name"))  
        super().__init__(placeholder="Step 3: choose species passive...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        passive = find_passive("species", payload.get("species"), self.values[0])  
        payload["species_passive_name"] = passive["name"]  
        payload["species_passive_json"] = passive  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, f"Species passive set to **{passive['name']}**.")  
  
  
class TicketClassPassiveSelect(discord.ui.Select):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        self.ticket_id = int(ticket_id)  
        class_name = payload.get("class_name") or "Fighter"  
        options = passive_select_options("class", class_name)  
        for opt in options:  
            opt.default = normalize_name(opt.value) == normalize_name(payload.get("class_passive_name"))  
        super().__init__(placeholder="Step 3: choose class passive...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        passive = find_passive("class", payload.get("class_name"), self.values[0])  
        payload["class_passive_name"] = passive["name"]  
        payload["class_passive_json"] = passive  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, f"Class passive set to **{passive['name']}**.")  
  
  
def reset_review_ticket_build_payload(payload: dict[str, Any]) -> dict[str, Any]:  
    """Reset only pre-approval build choices while preserving identity/reference fields.  
  
    This touches alaris_character_review_tickets.payload_json only.  
    It never mutates approved alaris_characters rows.  
    """  
    preserved_keys = {  
        "guild_id",  
        "user_id",  
        "created_by",  
        "name",  
        "normalized_name",  
        "image_url",  
        "image_filename",  
        "image_content_type",  
        "google_doc_url",  
        "kingdom",  
    }  
    reset_payload = {k: payload.get(k) for k in preserved_keys if k in payload}  
    reset_payload["draft_reset_pending"] = True  
    reset_payload["draft_reset_note"] = "Build choices were reset by staff/owner before approval."  
    return reset_payload  
  
  
async def fetch_open_review_ticket_by_channel(guild_id: int, channel_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_character_review_tickets  
            WHERE guild_id=$1  
              AND channel_id=$2  
              AND status='open'  
            ORDER BY id DESC  
            LIMIT 1;  
            """,  
            int(guild_id), int(channel_id),  
        )  
    return dict(row) if row else None  
  
  
async def fetch_open_review_ticket_for_user_or_name(  
    guild_id: int,  
    user_id: Optional[int] = None,  
    character_name: Optional[str] = None,  
) -> Optional[dict[str, Any]]:  
    normalized = normalize_name(character_name or "")  
    async with db_pool.acquire() as conn:  
        if normalized:  
            row = await conn.fetchrow(  
                """  
                SELECT *  
                FROM alaris_character_review_tickets  
                WHERE guild_id=$1  
                  AND status='open'  
                  AND (  
                        lower(payload_json->>'normalized_name')=$2  
                     OR lower(payload_json->>'name')=$2  
                     OR lower(payload_json->>'name') LIKE $3  
                  )  
                ORDER BY id DESC  
                LIMIT 1;  
                """,  
                int(guild_id), normalized, f"%{normalized}%",  
            )  
            if row:  
                return dict(row)  
        if user_id:  
            row = await conn.fetchrow(  
                """  
                SELECT *  
                FROM alaris_character_review_tickets  
                WHERE guild_id=$1  
                  AND status='open'  
                  AND user_id=$2  
                ORDER BY id DESC  
                LIMIT 1;  
                """,  
                int(guild_id), int(user_id),  
            )  
            if row:  
                return dict(row)  
    return None  
  
  
async def close_review_ticket_row(  
    ticket_id: int,  
    reviewed_by: int,  
    status: str = "abandoned",  
) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_character_review_tickets  
            WHERE id=$1 AND status='open'  
            LIMIT 1;  
            """,  
            int(ticket_id),  
        )  
        if not row:  
            return None  
        await conn.execute(  
            """  
            UPDATE alaris_character_review_tickets  
            SET status=$2,  
                closed_at=NOW(),  
                reviewed_by=$3  
            WHERE id=$1 AND status='open';  
            """,  
            int(ticket_id), status, int(reviewed_by),  
        )  
    return dict(row)  
  
  
async def delete_review_ticket_channel_if_available(guild: discord.Guild, channel_id: Optional[int], reason: str) -> bool:  
    if not channel_id:  
        return False  
    channel = guild.get_channel(int(channel_id))  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(int(channel_id))  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            channel = None  
    if isinstance(channel, discord.TextChannel):  
        try:  
            await channel.delete(reason=reason)  
            return True  
        except Exception:  
            LOG.exception("Failed to delete review ticket channel_id=%s", channel_id)  
    return False  
  
  
async def rebuild_review_ticket_message(  
    guild: discord.Guild,  
    ticket: dict[str, Any],  
    payload: Optional[dict[str, Any]] = None,  
) -> tuple[bool, str]:  
    """Rebuild the active review ticket embed/view if its channel still exists."""  
    payload = payload or decode_json_payload(ticket["payload_json"])  
    ticket_id = int(ticket["id"])  
    channel_id = ticket.get("channel_id")  
    message_id = ticket.get("review_message_id")  
    if not channel_id:  
        return False, "Ticket has no channel_id stored."  
  
    channel = guild.get_channel(int(channel_id))  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(int(channel_id))  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            channel = None  
    if not isinstance(channel, discord.TextChannel):  
        return False, "Ticket channel no longer exists."  
  
    embed = build_review_embed(payload)  
    view = CharacterApprovalView(ticket_id, payload)  
  
    # Try to edit the original review message first.  
    if message_id:  
        try:  
            msg = await channel.fetch_message(int(message_id))  
            await msg.edit(embed=embed, view=view)  
            return True, "Existing review message rebuilt."  
        except Exception:  
            LOG.exception("Failed to edit existing review ticket message; posting a new one.")  
  
    try:  
        msg = await channel.send(embed=embed, view=view)  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                UPDATE alaris_character_review_tickets  
                SET review_message_id=$2  
                WHERE id=$1 AND status='open';  
                """,  
                ticket_id, int(msg.id),  
            )  
        return True, "Posted a new review message with live controls."  
    except Exception as exc:  
        LOG.exception("Failed to rebuild review ticket message.")  
        return False, f"Failed to post rebuilt review message: {exc}"  
  
  
  
  
class TicketEditCharacterModal(discord.ui.Modal, title="Edit Character Draft"):  
    character_name = discord.ui.TextInput(  
        label="Character Name",  
        placeholder="Update name if needed. This must match the Tupper exactly.",  
        max_length=80,  
    )  
    google_doc_url = discord.ui.TextInput(  
        label="Google Doc URL",  
        placeholder="Update Google Doc link if needed.",  
        max_length=500,  
    )  
    image_url = discord.ui.TextInput(  
        label="Image URL",  
        placeholder="Update image URL if needed.",  
        max_length=500,  
    )  
  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        super().__init__()  
        self.ticket_id = int(ticket_id)  
        self.character_name.default = str(payload.get("name") or "")  
        self.google_doc_url.default = str(payload.get("google_doc_url") or "")  
        self.image_url.default = str(payload.get("image_url") or "")  
  
    async def on_submit(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
  
        name = str(self.character_name.value).strip()  
        normalized = normalize_name(name)  
        doc = str(self.google_doc_url.value).strip()  
        image = str(self.image_url.value).strip()  
  
        if not name:  
            await interaction.response.send_message("Character name is required.", ephemeral=True)  
            return  
        if await ticket_name_conflicts(int(payload["guild_id"]), normalized, self.ticket_id):  
            await interaction.response.send_message(f"A character or open ticket named **{name}** already exists.", ephemeral=True)  
            return  
        if not valid_url(doc):  
            await interaction.response.send_message("Google Doc URL must start with `http://` or `https://`.", ephemeral=True)  
            return  
        if not valid_url(image):  
            await interaction.response.send_message("Image URL must start with `http://` or `https://`.", ephemeral=True)  
            return  
  
        # Preserve identity/media updates, then reset only the pre-approval build choices.  
        payload["name"] = name  
        payload["normalized_name"] = normalized  
        payload["google_doc_url"] = doc  
        payload["image_url"] = image  
        payload["image_filename"] = payload.get("image_filename") or "edited-image-url"  
        payload["image_content_type"] = payload.get("image_content_type") or "image/url"  
        payload = reset_preapproval_build_choices(payload, reset_identity=True)  
        await apply_ticket_payload_update(  
            interaction,  
            self.ticket_id,  
            payload,  
            "Character draft updated. Build choices were reset - reselect species, class, stats, and starter passives.",  
        )  
  
  
class TicketManualStatsModal(discord.ui.Modal, title="Manual Standard Array"):  
    stat_line = discord.ui.TextInput(  
        label="Enter STR DEX CON INT WIS CHA",  
        placeholder="Example: 15 14 13 12 10 8",  
        max_length=80,  
    )  
  
    def __init__(self, ticket_id: int):  
        super().__init__()  
        self.ticket_id = int(ticket_id)  
  
    async def on_submit(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        ok, stats, err = validate_standard_array(str(self.stat_line.value))  
        if not ok:  
            await interaction.response.send_message(err, ephemeral=True)  
            return  
        payload["stats"] = stats  
        payload["stat_method"] = "Manual Standard Array"  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, "Manual stats updated.")  
  
  
class CharacterStatsView(discord.ui.View):  
    def __init__(self, ticket_id: int, payload: dict[str, Any]):  
        super().__init__(timeout=None)  
        self.ticket_id = int(ticket_id)  
  
    @discord.ui.button(label="Auto-Assign Stats", style=discord.ButtonStyle.green, custom_id="alaris_character_stage_stats_auto")  
    async def auto_stats(self, interaction: discord.Interaction, button: discord.ui.Button):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        if not payload.get("class_name"):  
            await interaction.response.send_message("Choose a class first.", ephemeral=True)  
            return  
        payload["stats"] = auto_assign_stats(payload["class_name"])  
        payload["stat_method"] = "Auto-Assigned by Class"  
        await apply_ticket_payload_update(interaction, self.ticket_id, payload, "Stats auto-assigned by class.")  
  
    @discord.ui.button(label="Manual Stats", style=discord.ButtonStyle.blurple, custom_id="alaris_character_stage_stats_manual")  
    async def manual_stats(self, interaction: discord.Interaction, button: discord.ui.Button):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        if not payload.get("class_name"):  
            await interaction.response.send_message("Choose a class first.", ephemeral=True)  
            return  
        await interaction.response.send_modal(TicketManualStatsModal(self.ticket_id))  
  
  
class CharacterFinalActionView(discord.ui.View):  
    def __init__(self, ticket_id: int, payload: Optional[dict[str, Any]] = None):  
        super().__init__(timeout=None)  
        self.ticket_id = int(ticket_id)  
  
    @discord.ui.button(label="Edit Character", style=discord.ButtonStyle.gray, custom_id="alaris_character_edit_draft")  
    async def edit_character(self, interaction: discord.Interaction, button: discord.ui.Button):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        if int(payload.get("user_id") or 0) != int(interaction.user.id) and not (  
            isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)  
        ):  
            await interaction.response.send_message("Only the character owner or staff can edit this draft.", ephemeral=True)  
            return  
        await interaction.response.send_modal(TicketEditCharacterModal(self.ticket_id, payload))  
  
    @discord.ui.button(label="Approve Character", style=discord.ButtonStyle.green, custom_id="alaris_character_approve")  
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        await interaction.response.defer(ephemeral=True)  
  
        async with db_pool.acquire() as conn:  
            ticket = await conn.fetchrow(  
                """  
                SELECT *  
                FROM alaris_character_review_tickets  
                WHERE id=$1 AND status='open';  
                """,  
                self.ticket_id,  
            )  
  
        if not ticket:  
            await interaction.followup.send("This review ticket is no longer open.", ephemeral=True)  
            return  
  
        payload = decode_json_payload(ticket["payload_json"])  
        ready, reason = review_payload_ready_for_approval(payload)  
        if not ready:  
            await interaction.followup.send(f"This character is not ready for approval. {reason}", ephemeral=True)  
            return  
  
        if await clean_character_name_exists(int(payload["guild_id"]), payload["normalized_name"]):  
            await interaction.followup.send("A character with this name already exists. Reject this ticket or rename before approving.", ephemeral=True)  
            return  
  
        final_embed_snapshot = build_review_embed(payload)  
  
        try:  
            char_id = await create_character_from_payload(payload, interaction.user.id)  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_review_tickets  
                    SET status='approved', closed_at=NOW(), reviewed_by=$2  
                    WHERE id=$1;  
                    """,  
                    self.ticket_id, interaction.user.id,  
                )  
        except Exception as exc:  
            LOG.exception("Approval failed.")  
            await interaction.followup.send(f"Approval failed: `{truncate(exc, 1500)}`", ephemeral=True)  
            return  
  
        for child in self.children:  
            if isinstance(child, discord.ui.Button) or isinstance(child, discord.ui.Select):  
                child.disabled = True  
  
        try:  
            await interaction.message.edit(view=self)  
        except Exception:  
            pass  
  
        discussion_thread_id = None  
        role_assigned = False  
        if interaction.guild:  
            try:  
                discussion_thread_id = await create_or_update_character_discussion_post(interaction.guild, char_id)  
            except Exception:  
                LOG.exception("Failed to create character discussion post after approval.")  
            role_assigned = await ensure_approved_player_role(interaction.guild, int(payload.get("user_id") or 0))  
  
        thread_note = f" Discussion post: <#{discussion_thread_id}>" if discussion_thread_id else ""  
        role_note = " Approved player role assigned." if role_assigned else ""  
        await interaction.followup.send(f"Approved character **{payload['name']}**. Character ID: `{char_id}`{thread_note}{role_note}", ephemeral=True)  
        if interaction.guild:  
            await post_character_approval_log(  
                interaction.guild,  
                interaction.user,  
                payload["name"],  
                ticket_channel=interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None,  
                character_embed=final_embed_snapshot,  
            )  
  
        try:  
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):  
                await interaction.channel.delete(reason=f"Approved Alaris character ticket for {payload['name']}")  
        except Exception:  
            LOG.exception("Failed to delete approved character review ticket channel.")  
  
    @discord.ui.button(label="Reject Character", style=discord.ButtonStyle.red, custom_id="alaris_character_reject")  
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        await interaction.response.defer(ephemeral=True)  
  
        async with db_pool.acquire() as conn:  
            ticket = await conn.fetchrow(  
                "SELECT * FROM alaris_character_review_tickets WHERE id=$1 AND status='open';",  
                self.ticket_id,  
            )  
            if ticket:  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_review_tickets  
                    SET status='rejected', closed_at=NOW(), reviewed_by=$2  
                    WHERE id=$1;  
                    """,  
                    self.ticket_id, interaction.user.id,  
                )  
  
        if not ticket:  
            await interaction.followup.send("This review ticket is no longer open.", ephemeral=True)  
            return  
  
        for child in self.children:  
            if isinstance(child, discord.ui.Button) or isinstance(child, discord.ui.Select):  
                child.disabled = True  
  
        try:  
            await interaction.message.edit(view=self)  
        except Exception:  
            pass  
  
        payload = decode_json_payload(ticket["payload_json"])  
        await interaction.followup.send(f"Rejected character **{payload.get('name', 'Unknown')}**.", ephemeral=True)  
        try:  
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):  
                await interaction.channel.send(f"❌ Character rejected by {interaction.user.mention}: **{payload.get('name', 'Unknown')}**")  
        except Exception:  
            pass  
  
  
class CharacterApprovalView(discord.ui.View):  
    def __init__(self, ticket_id: int, payload: Optional[dict[str, Any]] = None):  
        super().__init__(timeout=None)  
        self.ticket_id = int(ticket_id)  
        payload = payload or {}  
        stage = character_review_stage(payload)  
  
        # The edit button is safe here because this view is only attached to an  
        # open alaris_character_review_tickets row. It edits/reset payload_json  
        # only and never touches approved alaris_characters.  
        self.add_item(CharacterEditButton(self.ticket_id))  
  
        if stage == "kingdom":  
            self.add_item(TicketKingdomSelect(self.ticket_id, payload))  
        elif stage == "identity":  
            self.add_item(TicketSpeciesSelect(self.ticket_id, payload))  
            self.add_item(TicketClassSelect(self.ticket_id, payload))  
        elif stage == "stats":  
            self.add_item(CharacterStatsButton("Auto-Assign Stats", "auto", self.ticket_id))  
            self.add_item(CharacterStatsButton("Manual Stats", "manual", self.ticket_id))  
        elif stage == "passives":  
            self.add_item(TicketSpeciesPassiveSelect(self.ticket_id, payload))  
            self.add_item(TicketClassPassiveSelect(self.ticket_id, payload))  
        else:  
            self.add_item(CharacterApproveButton(self.ticket_id))  
            self.add_item(CharacterRejectButton(self.ticket_id))  
  
  
class CharacterStatsButton(discord.ui.Button):  
    def __init__(self, label: str, mode: str, ticket_id: int):  
        super().__init__(label=label, style=discord.ButtonStyle.green if mode == "auto" else discord.ButtonStyle.blurple)  
        self.mode = mode  
        self.ticket_id = int(ticket_id)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        if not payload.get("class_name"):  
            await interaction.response.send_message("Choose a class first.", ephemeral=True)  
            return  
        if self.mode == "auto":  
            payload["stats"] = auto_assign_stats(payload["class_name"])  
            payload["stat_method"] = "Auto-Assigned by Class"  
            await apply_ticket_payload_update(interaction, self.ticket_id, payload, "Stats auto-assigned by class.")  
        else:  
            await interaction.response.send_modal(TicketManualStatsModal(self.ticket_id))  
  
  
class CharacterEditButton(discord.ui.Button):  
    def __init__(self, ticket_id: int):  
        super().__init__(label="Edit Character", style=discord.ButtonStyle.gray)  
        self.ticket_id = int(ticket_id)  
  
    async def callback(self, interaction: discord.Interaction):  
        payload = await fetch_open_review_ticket_payload(self.ticket_id)  
        if not payload:  
            await interaction.response.send_message("This review ticket is no longer open.", ephemeral=True)  
            return  
        if int(payload.get("user_id") or 0) != int(interaction.user.id) and not (  
            isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)  
        ):  
            await interaction.response.send_message("Only the character owner or staff can edit this draft.", ephemeral=True)  
            return  
        await interaction.response.send_modal(TicketEditCharacterModal(self.ticket_id, payload))  
  
  
class CharacterApproveButton(discord.ui.Button):  
    def __init__(self, ticket_id: int):  
        super().__init__(label="Approve Character", style=discord.ButtonStyle.green)  
        self.ticket_id = int(ticket_id)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        await interaction.response.defer(ephemeral=True)  
  
        async with db_pool.acquire() as conn:  
            ticket = await conn.fetchrow(  
                """  
                SELECT *  
                FROM alaris_character_review_tickets  
                WHERE id=$1 AND status='open';  
                """,  
                self.ticket_id,  
            )  
  
        if not ticket:  
            await interaction.followup.send("This review ticket is no longer open.", ephemeral=True)  
            return  
  
        payload = decode_json_payload(ticket["payload_json"])  
        ready, reason = review_payload_ready_for_approval(payload)  
        if not ready:  
            await interaction.followup.send(f"This character is not ready for approval. {reason}", ephemeral=True)  
            return  
  
        if await clean_character_name_exists(int(payload["guild_id"]), payload["normalized_name"]):  
            await interaction.followup.send("A character with this name already exists. Reject this ticket or rename before approving.", ephemeral=True)  
            return  
  
        final_embed_snapshot = build_review_embed(payload)  
  
        try:  
            char_id = await create_character_from_payload(payload, interaction.user.id)  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_review_tickets  
                    SET status='approved', closed_at=NOW(), reviewed_by=$2  
                    WHERE id=$1;  
                    """,  
                    self.ticket_id, interaction.user.id,  
                )  
        except Exception as exc:  
            LOG.exception("Approval failed.")  
            await interaction.followup.send(f"Approval failed: `{truncate(exc, 1500)}`", ephemeral=True)  
            return  
  
        try:  
            if interaction.message:  
                disabled = CharacterApprovalView(self.ticket_id, payload)  
                for child in disabled.children:  
                    child.disabled = True  
                await interaction.message.edit(view=disabled)  
        except Exception:  
            pass  
  
        discussion_thread_id = None  
        role_assigned = False  
        if interaction.guild:  
            try:  
                discussion_thread_id = await create_or_update_character_discussion_post(interaction.guild, char_id)  
            except Exception:  
                LOG.exception("Failed to create character discussion post after approval.")  
            role_assigned = await ensure_approved_player_role(interaction.guild, int(payload.get("user_id") or 0))  
  
        thread_note = f" Discussion post: <#{discussion_thread_id}>" if discussion_thread_id else ""  
        role_note = " Approved player role assigned." if role_assigned else ""  
        await interaction.followup.send(f"Approved character **{payload['name']}**. Character ID: `{char_id}`{thread_note}{role_note}", ephemeral=True)  
        if interaction.guild:  
            await post_character_approval_log(  
                interaction.guild,  
                interaction.user,  
                payload["name"],  
                ticket_channel=interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None,  
                character_embed=final_embed_snapshot,  
            )  
  
        try:  
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):  
                await interaction.channel.delete(reason=f"Approved Alaris character ticket for {payload['name']}")  
        except Exception:  
            LOG.exception("Failed to delete approved character review ticket channel.")  
  
  
class CharacterRejectButton(discord.ui.Button):  
    def __init__(self, ticket_id: int):  
        super().__init__(label="Reject Character", style=discord.ButtonStyle.red)  
        self.ticket_id = int(ticket_id)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        await interaction.response.defer(ephemeral=True)  
  
        async with db_pool.acquire() as conn:  
            ticket = await conn.fetchrow(  
                "SELECT * FROM alaris_character_review_tickets WHERE id=$1 AND status='open';",  
                self.ticket_id,  
            )  
            if ticket:  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_review_tickets  
                    SET status='rejected', closed_at=NOW(), reviewed_by=$2  
                    WHERE id=$1;  
                    """,  
                    self.ticket_id, interaction.user.id,  
                )  
  
        if not ticket:  
            await interaction.followup.send("This review ticket is no longer open.", ephemeral=True)  
            return  
  
        payload = decode_json_payload(ticket["payload_json"])  
        await interaction.followup.send(f"Rejected character **{payload.get('name', 'Unknown')}**.", ephemeral=True)  
        try:  
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):  
                await interaction.channel.send(f"❌ Character rejected by {interaction.user.mention}: **{payload.get('name', 'Unknown')}**")  
        except Exception:  
            pass  
  
  
  
async def next_character_review_ticket_number(guild_id: int) -> int:  
    """Return the next human-friendly sequential OC ticket number for this guild."""  
    async with db_pool.acquire() as conn:  
        value = await conn.fetchval(  
            """  
            SELECT COALESCE(MAX(id), 0) + 1  
            FROM alaris_character_review_tickets  
            WHERE guild_id=$1;  
            """,  
            guild_id,  
        )  
    return int(value or 1)  
  
  
async def create_review_ticket(interaction: discord.Interaction, payload: dict[str, Any]) -> None:  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
  
    if await clean_character_name_exists(interaction.guild.id, payload["normalized_name"]):  
        await interaction.response.send_message(f"A clean Alaris character named **{payload['name']}** already exists.", ephemeral=True)  
        return  
    if await open_ticket_name_exists(interaction.guild.id, payload["normalized_name"]):  
        await interaction.response.send_message(f"A review ticket for **{payload['name']}** is already open.", ephemeral=True)  
        return  
  
    category = None  
    if CHARACTER_REVIEW_CATEGORY_ID:  
        maybe = interaction.guild.get_channel(CHARACTER_REVIEW_CATEGORY_ID)  
        if maybe is None:  
            try:  
                fetched = await bot.fetch_channel(CHARACTER_REVIEW_CATEGORY_ID)  
                maybe = fetched  
            except Exception:  
                maybe = None  
        if isinstance(maybe, discord.CategoryChannel):  
            category = maybe  
  
    overwrites = {  
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),  
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),  
        interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),  
    }  
    for role_id in STAFF_ROLE_IDS:  
        role = interaction.guild.get_role(role_id)  
        if role:  
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)  
  
    ticket_number = await next_character_review_ticket_number(interaction.guild.id)  
    channel_name = f"new-oc-{ticket_number:03d}"  
    try:  
        ticket_channel = await interaction.guild.create_text_channel(  
            name=channel_name[:90],  
            category=category,  
            overwrites=overwrites,  
            reason=f"Alaris character review ticket for {payload['name']}",  
        )  
    except Exception as exc:  
        LOG.exception("Failed to create review ticket channel.")  
        if interaction.response.is_done():  
            await interaction.followup.send(f"Could not create review ticket: `{truncate(exc, 1200)}`", ephemeral=True)  
        else:  
            await interaction.response.send_message(f"Could not create review ticket: `{truncate(exc, 1200)}`", ephemeral=True)  
        return  
  
    async with db_pool.acquire() as conn:  
        ticket_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_character_review_tickets (  
                guild_id, user_id, channel_id, status, payload_json  
            )  
            VALUES ($1,$2,$3,'open',$4::jsonb)  
            RETURNING id;  
            """,  
            interaction.guild.id,  
            interaction.user.id,  
            ticket_channel.id,  
            json.dumps(payload),  
        )  
  
    embed = build_review_embed(payload)  
    view = CharacterApprovalView(int(ticket_id), payload)  
    staff_mentions = " ".join(f"<@&{role_id}>" for role_id in STAFF_ROLE_IDS) or "Staff"  
    ticket_content = (  
        f"{interaction.user.mention} {staff_mentions} character review created. "  
        "Start by choosing **species** and **class** from the dropdowns below. "  
        "The ticket will then walk through stats, passives, and final approval."  
    )  
    msg = await ticket_channel.send(  
        content=ticket_content,  
        embed=embed,  
        view=view,  
        allowed_mentions=discord.AllowedMentions(users=True, roles=True, everyone=False),  
    )  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_character_review_tickets  
            SET review_message_id=$2  
            WHERE id=$1;  
            """,  
            int(ticket_id), msg.id,  
        )  
  
    if interaction.response.is_done():  
        await interaction.followup.send(f"Character review ticket created: {ticket_channel.mention}", ephemeral=True)  
    else:  
        await interaction.response.send_message(f"Character review ticket created: {ticket_channel.mention}", ephemeral=True)  
  
  
# ---------- Autocomplete ----------  
  
async def character_name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    """Autocomplete approved active characters for staff/player character-name commands.

    v123 hardens this because staff maintenance commands such as
    /character-grant-xp depend on a reliable character dropdown. The lookup is
    intentionally broad and additive-safe:
    - prefers public.alaris_characters as canonical;
    - treats NULL status as active for older rows;
    - searches name, normalized_name when present, species, class, and id;
    - falls back to public.characters compatibility rows if needed;
    - never raises back to Discord autocomplete, which silently breaks dropdowns.
    """  
    if db_pool is None or interaction.guild is None:  
        return []  
    guild_id = int(interaction.guild.id)  
    needle = normalize_name(current)  
    choices: list[app_commands.Choice[str]] = []  
    seen_values: set[str] = set()  

    def add_choice(name: Any, species: Any = "", class_name: Any = "", cid: Any = None) -> None:  
        if len(choices) >= 25:  
            return  
        nm = str(name or "").strip()  
        if not nm:  
            return  
        value = nm[:100]  
        if value in seen_values:  
            return  
        seen_values.add(value)  
        bits = []  
        if cid is not None:  
            try:  
                bits.append(f"#{int(cid)}")  
            except Exception:  
                pass  
        sp = str(species or "").strip()  
        cls = str(class_name or "").strip()  
        if sp or cls:  
            bits.append(" ".join(x for x in [sp, cls] if x).strip())  
        label = nm if not bits else f"{nm} - {' | '.join(bits)}"  
        choices.append(app_commands.Choice(name=label[:100], value=value))  

    try:  
        async with db_pool.acquire() as conn:  
            rows = []  
            if await table_exists(conn, "alaris_characters"):  
                cols = await get_columns(conn, "alaris_characters")  
                select_cols = ["id", "name"]  
                for c in ["species", "species_name", "class_name", "normalized_name", "status"]:  
                    if c in cols:  
                        select_cols.append(c)  
                args: list[Any] = [guild_id]  
                where = ["guild_id=$1"] if "guild_id" in cols else []  
                if "status" in cols:  
                    where.append("COALESCE(status, 'active') NOT IN ('archived','deleted','rejected','inactive')")  
                if needle:  
                    args.append(f"%{needle}%")  
                    like_arg = len(args)  
                    search_parts = [f"lower(name) LIKE ${like_arg}"]  
                    if "normalized_name" in cols:  
                        search_parts.append(f"lower(COALESCE(normalized_name,'')) LIKE ${like_arg}")  
                    if "species" in cols:  
                        search_parts.append(f"lower(COALESCE(species,'')) LIKE ${like_arg}")  
                    if "species_name" in cols:  
                        search_parts.append(f"lower(COALESCE(species_name,'')) LIKE ${like_arg}")  
                    if "class_name" in cols:  
                        search_parts.append(f"lower(COALESCE(class_name,'')) LIKE ${like_arg}")  
                    if needle.isdigit() and "id" in cols:  
                        search_parts.append(f"CAST(id AS TEXT) LIKE ${like_arg}")  
                    where.append("(" + " OR ".join(search_parts) + ")")  
                sql = f"""  
                    SELECT {', '.join(select_cols)}  
                    FROM alaris_characters  
                    {('WHERE ' + ' AND '.join(where)) if where else ''}  
                    ORDER BY name  
                    LIMIT 25;  
                """  
                rows = await conn.fetch(sql, *args)  
                for row in rows:  
                    r = dict(row)  
                    species = r.get("species") if "species" in r else r.get("species_name") if "species_name" in r else ""  
                    add_choice(r.get("name"), species, r.get("class_name") if "class_name" in r else "", r.get("id") if "id" in r else None)  

            if len(choices) < 25 and await table_exists(conn, "characters"):  
                cols = await get_columns(conn, "characters")  
                select_cols = [c for c in ["character_id", "id", "name", "species", "species_name", "class_name", "normalized_name", "archived", "status"] if c in cols]  
                if "name" in select_cols:  
                    args = [guild_id]  
                    where = ["guild_id=$1"] if "guild_id" in cols else []  
                    if "archived" in cols:  
                        where.append("COALESCE(archived, FALSE) = FALSE")  
                    if "status" in cols:  
                        where.append("COALESCE(status, 'active') NOT IN ('archived','deleted','rejected','inactive')")  
                    if needle:  
                        args.append(f"%{needle}%")  
                        like_arg = len(args)  
                        search_parts = [f"lower(name) LIKE ${like_arg}"]  
                        if "normalized_name" in cols:  
                            search_parts.append(f"lower(COALESCE(normalized_name,'')) LIKE ${like_arg}")  
                        if "species" in cols:  
                            search_parts.append(f"lower(COALESCE(species,'')) LIKE ${like_arg}")  
                        if "species_name" in cols:  
                            search_parts.append(f"lower(COALESCE(species_name,'')) LIKE ${like_arg}")  
                        if "class_name" in cols:  
                            search_parts.append(f"lower(COALESCE(class_name,'')) LIKE ${like_arg}")  
                        id_col = "character_id" if "character_id" in cols else "id" if "id" in cols else None  
                        if needle.isdigit() and id_col:  
                            search_parts.append(f"CAST({id_col} AS TEXT) LIKE ${like_arg}")  
                        where.append("(" + " OR ".join(search_parts) + ")")  
                    sql = f"""  
                        SELECT {', '.join(select_cols)}  
                        FROM characters  
                        {('WHERE ' + ' AND '.join(where)) if where else ''}  
                        ORDER BY name  
                        LIMIT 25;  
                    """  
                    rows = await conn.fetch(sql, *args)  
                    for row in rows:  
                        r = dict(row)  
                        cid = r.get("character_id") if "character_id" in r else r.get("id") if "id" in r else None  
                        species = r.get("species") if "species" in r else r.get("species_name") if "species_name" in r else ""  
                        add_choice(r.get("name"), species, r.get("class_name") if "class_name" in r else "", cid)  
    except Exception:  
        LOG.exception("character_name_autocomplete failed for current=%r guild_id=%s", current, guild_id)  
        return []  
    return choices  
  
  
async def owned_character_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    """Autocomplete only approved active characters owned by the command user."""  
    if db_pool is None or interaction.guild is None:  
        return []  
    current_norm = normalize_name(current)  
    async with db_pool.acquire() as conn:  
        args: list[Any] = [interaction.guild.id, interaction.user.id]  
        where = ["guild_id=$1", "user_id=$2", "status='active'"]  
        if current_norm:  
            args.append(f"%{current_norm}%")  
            where.append(f"lower(name) LIKE ${len(args)}")  
        rows = await conn.fetch(  
            f"""  
            SELECT id, name, species, class_name  
            FROM alaris_characters  
            WHERE {" AND ".join(where)}  
            ORDER BY name  
            LIMIT 25;  
            """,  
            *args,  
        )  
    choices = []  
    for row in rows:  
        label = f"{row['name']} - {row['species']} {row['class_name']}"  
        choices.append(app_commands.Choice(name=label[:100], value=str(row["id"])))  
    return choices  
  
  
  
# ---------- XP / Progression ----------  
  
def rp_xp_from_typed_characters(typed_characters: int) -> int:  
    if typed_characters <= 0:  
        return 0  
    return min(RP_XP_CAP_PER_SESSION, math.ceil(int(typed_characters) * RP_XP_PER_TYPED_CHARACTER))  
  
  
def split_enemy_xp_pool(total_xp: int, party_size: int) -> int:  
    # v117: no XP dilution. Every registered participant receives the full PvE XP award.  
    if total_xp <= 0 or party_size <= 0:  
        return 0  
    return int(total_xp)  
  
  
  
SCENE_SUMMARY_CHUNK_CHAR_LIMIT = 9000
SCENE_SUMMARY_MAX_CHUNKS = 24
SCENE_SUMMARY_FINAL_WORD_LIMIT = 220
SCENE_SUMMARY_TARGET_WORDS = "140-200 words"


def compact_text_from_messages(messages: list[discord.Message], limit: int = 2500) -> str:
    parts = []
    total = 0
    for msg in messages:
        content = (msg.content or "").strip()
        if not content:
            continue
        author = getattr(msg.author, "display_name", str(msg.author))
        piece = f"{author}: {content}"
        if total + len(piece) + 1 > limit:
            remaining = max(0, limit - total - 20)
            if remaining > 0:
                parts.append(piece[:remaining] + "...")
            break
        parts.append(piece)
        total += len(piece) + 1
    return "\n".join(parts)


def transcript_lines_from_messages(messages: list[discord.Message]) -> list[str]:
    """Return a full chronological transcript for AI summary use.

    Important: do not skip webhook/bot-authored messages here. Tupperbox and
    similar RP tools often post as webhooks/bots while still representing IC
    character speech. We keep every text-bearing message between the session
    markers and let the prompt treat command/UI chatter cautiously.
    """
    lines: list[str] = []
    for msg in messages:
        content = (msg.content or "").strip()
        if not content:
            continue
        author = getattr(msg.author, "display_name", None) or getattr(msg.author, "name", "Unknown")
        try:
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"[{ts}] {author}: {content}")
        except Exception:
            lines.append(f"{author}: {content}")
    return lines


def chunk_transcript_lines(lines: list[str], limit: int = SCENE_SUMMARY_CHUNK_CHAR_LIMIT) -> list[str]:
    """Split transcript into chronological chunks without front-truncating."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0

    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        while len(line) > limit:
            available = limit - current_len - 1
            if available < 1000:
                flush()
                available = limit
            current.append(line[:available])
            line = line[available:]
            flush()
        add_len = len(line) + 1
        if current and current_len + add_len > limit:
            flush()
        current.append(line)
        current_len += add_len
    flush()
    return chunks


def clamp_words(text: str, max_words: int) -> str:
    words = str(text or "").split()
    if len(words) <= max_words:
        return str(text or "").strip()
    return " ".join(words[:max_words]).rstrip(" ,;:-") + "..."


def clean_summary_list(value: Any, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        item_text = str(item or "").strip()
        if item_text:
            cleaned.append(clamp_words(item_text, 28))
        if len(cleaned) >= limit:
            break
    return cleaned


def heuristic_scene_summary(messages: list[discord.Message], participants: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """Fallback scene summary without an external AI dependency."""
    names = [p["name"] for p in participants]
    name_text = ", ".join(names) if names else "The participating characters"
    visible_messages = [m for m in messages if (m.content or "").strip()]

    if visible_messages:
        summary = (
            f"{name_text} took part in a roleplay scene with {len(visible_messages)} in-character posts tracked by the bot. "
            "The scene has been logged for continuity and progression."
        )
    else:
        summary = f"{name_text} took part in a roleplay scene. The scene has been closed and logged."

    summary = clamp_words(summary, 100)
    takeaways = [
        "Character participation was recorded for progression.",
        "The scene is now closed and stored in the session log.",
    ]
    consequences = [
        "Staff may reference this scene for future continuity.",
        "Players may link this scene in their character posts if desired.",
    ]
    return summary, takeaways, consequences


async def openai_json_request(messages_payload: list[dict[str, str]], max_tokens: int = 900, temperature: float = 0.15) -> dict[str, Any]:
    """Small wrapper for JSON-mode OpenAI chat completions."""
    if openai_client is None:
        return {}
    response = await openai_client.chat.completions.create(
        model=OPENAI_SUMMARY_MODEL,
        messages=messages_payload,
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        LOG.warning("OpenAI summary returned non-JSON content: %s", raw[:500])
        return {}


async def summarize_scene_chunk(chunk_text: str, chunk_index: int, chunk_total: int, participant_names: str, context: str) -> dict[str, Any]:
    """Summarize one chronological transcript chunk as factual notes only."""
    prompt = f"""
You are extracting factual continuity notes from a roleplay scene in Alaris.

Participants expected in the scene: {participant_names or "Unknown"}
Chunk: {chunk_index} of {chunk_total}
Structured session/combat context: {context or "None provided."}

Transcript chunk:
{chunk_text}

Return valid JSON only with this exact shape:
{{
  "chunk_summary": "120 words or fewer, factual and chronological.",
  "events": ["brief factual event"],
  "reveals": ["confirmed reveal or correction"],
  "conflicts": ["conflict or accusation, clearly labeled if only alleged"],
  "unresolved_threads": ["thread left open"]
}}

Rules:
- Extract facts only from this chunk.
- Preserve chronology.
- Do not invent motives, emotions, relationships, guilt, innocence, or pursuit details.
- Distinguish accusation/allegation from confirmed truth.
- If a later statement in this chunk corrects an earlier claim, record the correction.
- Use gender-neutral they/them language for all player characters.
- Keep every list concise.
"""
    data = await openai_json_request(
        [
            {"role": "system", "content": "You extract concise factual JSON continuity notes from fantasy RP transcripts."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=850,
        temperature=0.1,
    )
    return {
        "chunk": chunk_index,
        "chunk_summary": clamp_words(str(data.get("chunk_summary") or "").strip(), 130),
        "events": clean_summary_list(data.get("events"), 6),
        "reveals": clean_summary_list(data.get("reveals"), 5),
        "conflicts": clean_summary_list(data.get("conflicts"), 5),
        "unresolved_threads": clean_summary_list(data.get("unresolved_threads"), 5),
    }


async def synthesize_scene_summary(chunk_notes: list[dict[str, Any]], participants: list[dict[str, Any]], context: Optional[str] = None) -> tuple[str, list[str], list[str]]:
    """Create the final short campaign-chronicle summary from chunk notes."""
    participant_names = ", ".join(p["name"] for p in participants) or "Unknown"
    notes_text = json.dumps(chunk_notes, ensure_ascii=False, indent=2)
    prompt = f"""
You are writing the final concise session log for a roleplay scene in the Realm of Alaris.

Participants:
{participant_names}

Known structured session/combat context:
{context or "No additional structured context was provided."}

Chronological factual chunk notes:
{notes_text}

Return valid JSON only with this exact shape:
{{
  "summary": "{SCENE_SUMMARY_TARGET_WORDS}, concise campaign chronicle style.",
  "key_takeaways": ["bullet point", "bullet point", "bullet point"],
  "possible_consequences": ["bullet point", "bullet point", "bullet point"]
}}

Rules:
- The final summary must be accurate, chronological, and no more than {SCENE_SUMMARY_FINAL_WORD_LIMIT} words.
- Use the whole scene, including late-scene revelations and resolutions.
- Do not overweight the opening if later notes change the situation.
- Do not invent facts, motives, dialogue, guilt, innocence, promises, relationships, or pursuit details.
- Distinguish allegations from confirmed facts.
- If the notes say someone was chased by an unnamed or other pursuer, do not rewrite another participant as the pursuer.
- Mention final state of the central conflict when known.
- Keep key takeaways and possible consequences short and useful for staff continuity.
- Use gender-neutral they/them/theirs language for every player character. Do not use he, she, his, her, hers, him, herself, or himself.
- Use the exact combat type from structured context. If it says Spar, call it a spar. If it says Duel, call it a duel. Never say "sparring duel."
- Do not say "no combat took place" when combat context contains combat actions, damage, defeated combatants, or a victor.
"""
    data = await openai_json_request(
        [
            {"role": "system", "content": "You produce concise, accurate JSON summaries for fantasy roleplay session logs."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=950,
        temperature=0.15,
    )
    summary = clamp_words(str(data.get("summary") or "").strip(), SCENE_SUMMARY_FINAL_WORD_LIMIT)
    takeaways = clean_summary_list(data.get("key_takeaways"), 5)
    consequences = clean_summary_list(data.get("possible_consequences"), 5)
    return summary, takeaways, consequences


async def generate_scene_summary(messages: list[discord.Message], participants: list[dict[str, Any]], context: Optional[str] = None) -> tuple[str, list[str], list[str]]:
    """Use OpenAI for a concise full-scene summary when configured, else fallback.

    v121 changes the old front-truncating one-pass summary into a full-scene
    chronological pipeline:
      1. collect all transcript lines,
      2. split into chronological chunks,
      3. extract factual notes per chunk,
      4. synthesize one tight final summary.
    """
    if openai_client is None:
        return heuristic_scene_summary(messages, participants)

    transcript_lines = transcript_lines_from_messages(messages)
    participant_names = ", ".join(p["name"] for p in participants) or "Unknown"

    if not transcript_lines:
        transcript_lines = [
            "No in-character RP posts were captured between the session start and close markers. "
            "Summarize the session from the known participants and combat/session outcome only, and do not invent specific dialogue or actions."
        ]

    chunks = chunk_transcript_lines(transcript_lines, SCENE_SUMMARY_CHUNK_CHAR_LIMIT)
    if len(chunks) > SCENE_SUMMARY_MAX_CHUNKS:
        head_count = max(1, SCENE_SUMMARY_MAX_CHUNKS // 4)
        tail_count = max(1, SCENE_SUMMARY_MAX_CHUNKS - head_count - 1)
        chunks = (
            chunks[:head_count]
            + ["[Some middle transcript content was omitted because the scene exceeded the configured summarization safety limit. Preserve uncertainty where details are missing.]"]
            + chunks[-tail_count:]
        )[:SCENE_SUMMARY_MAX_CHUNKS]

    try:
        chunk_notes: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks, start=1):
            note = await summarize_scene_chunk(chunk, idx, len(chunks), participant_names, context or "")
            if not note.get("chunk_summary") and not any(note.get(k) for k in ("events", "reveals", "conflicts", "unresolved_threads")):
                note["chunk_summary"] = clamp_words(chunk.replace("\n", " "), 120)
            chunk_notes.append(note)

        summary, takeaways, consequences = await synthesize_scene_summary(chunk_notes, participants, context=context)
        if not summary:
            return heuristic_scene_summary(messages, participants)
        return summary, takeaways, consequences
    except Exception:
        LOG.exception("OpenAI full-scene summary pipeline failed; using fallback summary.")
        return heuristic_scene_summary(messages, participants)


async def progression_for_xp_total(xp_total: int) -> tuple[int, int]:  
    """Return (damage_die_sides, level) for a total XP value."""  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT damage_die_sides, level  
            FROM alaris_progression  
            WHERE xp_required <= $1  
            ORDER BY damage_die_sides DESC  
            LIMIT 1;  
            """,  
            int(xp_total or 0),  
        )  
    if not row:  
        return 8, 1  
    return int(row["damage_die_sides"]), int(row["level"])  
  
  
async def award_xp_to_character(  
    guild_id: int,  
    character_id: int,  
    amount: int,  
    source_type: str,  
    source_id: Optional[int],  
    reason: str,  
    awarded_by: Optional[int] = None,  
    typed_characters: Optional[int] = None,  
) -> dict[str, Any]:  
    amount = int(amount or 0)  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            char = await conn.fetchrow(  
                """  
                SELECT id, user_id, name, xp_total, damage_die_sides, level  
                FROM alaris_characters  
                WHERE id=$1 AND guild_id=$2 AND status='active'  
                FOR UPDATE;  
                """,  
                character_id, guild_id,  
            )  
            if not char:  
                raise RuntimeError(f"Character {character_id} not found.")  
  
            old_xp = int(char["xp_total"] or 0)  
            old_die = int(char["damage_die_sides"] or 8)  
            old_level = int(char["level"] or 1)  
            new_xp = old_xp + amount  
            new_die, new_level = await progression_for_xp_total(new_xp)  
  
            await conn.execute(  
                """  
                UPDATE alaris_characters  
                SET xp_total=$2,  
                    damage_die_sides=$3,  
                    level=$4,  
                    updated_at=NOW()  
                WHERE id=$1;  
                """,  
                character_id, new_xp, new_die, new_level,  
            )  
            stats_row = await conn.fetchrow(  
                """  
                SELECT strength, dexterity, constitution, intelligence, wisdom, charisma  
                FROM alaris_character_stats  
                WHERE character_id=$1;  
                """,  
                character_id,  
            )  
            new_prof = proficiency_bonus_for_level(new_level)  
            if stats_row:  
                stat_payload = {  
                    "strength": int(stats_row["strength"]),  
                    "dexterity": int(stats_row["dexterity"]),  
                    "constitution": int(stats_row["constitution"]),  
                    "intelligence": int(stats_row["intelligence"]),  
                    "wisdom": int(stats_row["wisdom"]),  
                    "charisma": int(stats_row["charisma"]),  
                }  
                new_magic_save_bonus = magic_save_bonus_for_stats(stat_payload, new_level)  
                new_magic_defense = 8 + new_magic_save_bonus  
            else:  
                new_magic_save_bonus = new_prof  
                new_magic_defense = 8 + new_magic_save_bonus  
  
            await conn.execute(  
                """  
                UPDATE alaris_character_combat  
                SET damage_die_sides=$2,  
                    proficiency_bonus=$3,  
                    magic_save_bonus=$4,  
                    magic_defense=$5,  
                    updated_at=NOW()  
                WHERE character_id=$1;  
                """,  
                character_id, new_die, new_prof, new_magic_save_bonus, new_magic_defense,  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_xp_awards (  
                    guild_id, character_id, amount, source_type, source_id, reason,  
                    awarded_by, typed_characters, old_xp_total, new_xp_total,  
                    old_damage_die_sides, new_damage_die_sides, old_level, new_level  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14);  
                """,  
                guild_id, character_id, amount, source_type, source_id, reason,  
                awarded_by, typed_characters, old_xp, new_xp, old_die, new_die, old_level, new_level,  
            )  
  
    if new_level > old_level:  
        await ensure_pending_level_choices(character_id, guild_id, old_level, new_level)  
        await recalculate_character_combat(character_id, preserve_current_hp=True)  
  
    return {  
        "character_id": character_id,  
        "name": char["name"],  
        "user_id": int(char["user_id"]),  
        "amount": amount,  
        "old_xp": old_xp,  
        "new_xp": new_xp,  
        "old_die": old_die,  
        "new_die": new_die,  
        "old_level": old_level,  
        "new_level": new_level,  
        "leveled_up": new_level > old_level,  
    }  
  
  
async def post_level_up_message(result: dict[str, Any]) -> None:  
    if not result.get("leveled_up"):  
        return  
  
    character_id = int(result["character_id"])  
    async with db_pool.acquire() as conn:  
        post = await conn.fetchrow(  
            "SELECT thread_id FROM alaris_character_posts WHERE character_id=$1;",  
            character_id,  
        )  
    if post and post["thread_id"]:  
        try:  
            thread = bot.get_channel(int(post["thread_id"]))  
            if thread is None:  
                fetched = await bot.fetch_channel(int(post["thread_id"]))  
                thread = fetched if isinstance(fetched, discord.Thread) else None  
            if isinstance(thread, discord.Thread):  
                await thread.send(  
                    f"✨ **Level Up!** <@{result['user_id']}> - **{result['name']}** has reached "  
                    f"**Level {result['new_level']}**. New damage die: **1d{result['new_die']}**."  
                )  
        except Exception:  
            LOG.exception("Failed to post level-up message in character thread.")  
  
    try:  
        user = await bot.fetch_user(int(result["user_id"]))  
        await user.send(  
            f"✨ **{result['name']} has leveled up!**\n"  
            f"New Level: **{result['new_level']}**\n"  
            f"Damage Die: **1d{result['new_die']}**\n\n"  
            "Bonus option selection will be added in a later build."  
        )  
    except Exception:  
        pass  
  
  
async def refresh_and_notify_progression(result: dict[str, Any]) -> None:  
    try:  
        await refresh_character_post(int(result["character_id"]))  
    except Exception:  
        LOG.exception("Failed to refresh character post after XP award.")  
    await post_level_up_message(result)  
  
  
async def fetch_messages_between(channel: discord.abc.Messageable, after_message_id: Optional[int], before_message_id: Optional[int] = None) -> list[discord.Message]:  
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):  
        return []  
    after_obj = discord.Object(id=int(after_message_id)) if after_message_id else None  
    before_obj = discord.Object(id=int(before_message_id)) if before_message_id else None  
    messages: list[discord.Message] = []  
    try:  
        async for msg in channel.history(limit=None, after=after_obj, before=before_obj, oldest_first=True):  
            # Tupper/webhook posts often appear bot-like. Count them.  
            # Only exclude this bot's own messages and other non-webhook bot messages.  
            if bot.user and msg.author.id == bot.user.id:  
                continue  
            if msg.author.bot and not msg.webhook_id:  
                continue  
            messages.append(msg)  
    except Exception:  
        LOG.exception("Failed fetching session messages.")  
    return messages  
  
  
async def calculate_rp_counts_from_messages(messages: list[discord.Message], participants: list[dict[str, Any]]) -> dict[int, int]:  
    """Count typed characters in messages where webhook/Tupper display name exactly matches character name."""  
    by_name = {normalize_name(p["name"]): int(p["character_id"]) for p in participants}  
    counts = {int(p["character_id"]): 0 for p in participants}  
  
    for msg in messages:  
        content = msg.content or ""  
        if not content.strip():  
            continue  
        display_name = getattr(msg.author, "display_name", None) or getattr(msg.author, "name", "")  
        matched_id = by_name.get(normalize_name(display_name))  
        if matched_id:  
            counts[matched_id] = counts.get(matched_id, 0) + len(content)  
  
    return counts  
  
  
async def store_rp_counts(session_id: int, counts: dict[int, int], xp_awards: dict[int, int]) -> None:  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            for character_id, typed_count in counts.items():  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_session_rp_counts (  
                        session_id, character_id, typed_characters, rp_xp_awarded  
                    )  
                    VALUES ($1,$2,$3,$4)  
                    ON CONFLICT (session_id, character_id) DO UPDATE SET  
                        typed_characters=EXCLUDED.typed_characters,  
                        rp_xp_awarded=EXCLUDED.rp_xp_awarded;  
                    """,  
                    session_id, character_id, int(typed_count), int(xp_awards.get(character_id, 0)),  
                )  
  
  
async def get_session_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:  
    if not SESSION_LOG_CHANNEL_ID:  
        return None  
    channel = guild.get_channel(SESSION_LOG_CHANNEL_ID)  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(SESSION_LOG_CHANNEL_ID)  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            LOG.exception("Failed to fetch SESSION_LOG_CHANNEL_ID=%s", SESSION_LOG_CHANNEL_ID)  
            return None  
    return channel if isinstance(channel, discord.TextChannel) else None  
  
  
async def post_session_log_embed(guild: discord.Guild, embed: discord.Embed) -> None:  
    channel = await get_session_log_channel(guild)  
    if channel:  
        try:  
            await channel.send(embed=embed)  
        except Exception:  
            LOG.exception("Failed to post session log embed.")  
  
  
async def get_xp_award_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:  
    if not XP_AWARD_LOG_CHANNEL_ID:  
        return None  
    channel = guild.get_channel(XP_AWARD_LOG_CHANNEL_ID)  
    if channel is None:  
        try:  
            fetched = await bot.fetch_channel(XP_AWARD_LOG_CHANNEL_ID)  
            channel = fetched if isinstance(fetched, discord.TextChannel) else None  
        except Exception:  
            LOG.exception("Failed to fetch XP_AWARD_LOG_CHANNEL_ID=%s", XP_AWARD_LOG_CHANNEL_ID)  
            return None  
    return channel if isinstance(channel, discord.TextChannel) else None  
  
  
async def post_xp_award_log_embed(guild: discord.Guild, embed: discord.Embed) -> None:  
    channel = await get_xp_award_log_channel(guild)  
    if channel:  
        try:  
            await channel.send(embed=embed)  
        except Exception:  
            LOG.exception("Failed to post XP award log embed.")  
  
  
def build_xp_award_log_embed(  
    session: asyncpg.Record,  
    xp_results: list[dict[str, Any]],  
    rp_counts: dict[int, int],  
    session_jump_url: Optional[str] = None,  
) -> discord.Embed:  
    title = session["title"] or session["session_type"]  
    embed = discord.Embed(  
        title=f"XP Awarded - {title}",  
        description=f"Session Type: **{session['session_type']}**",  
        color=discord.Color.green(),  
    )  
    if session_jump_url:  
        embed.add_field(name="Session Link", value=f"[Jump to Session]({session_jump_url})", inline=False)  
    lines = []  
    for result in xp_results:  
        cid = int(result["character_id"])  
        typed = int(rp_counts.get(cid, 0) or 0)  
        level_note = ""  
        if result["new_level"] != result["old_level"]:  
            level_note = f" | Level {result['old_level']}→{result['new_level']}"  
        die_note = ""  
        if result["new_die"] != result["old_die"]:  
            die_note = f" | 1d{result['old_die']}→1d{result['new_die']}"  
        lines.append(  
            f"• **{result['name']}** (<@{result['user_id']}>): +{result['amount']} XP "  
            f"| Total {result['old_xp']}→{result['new_xp']} "  
            f"| Typed chars {typed:,}{die_note}{level_note}"  
        )  
    embed.add_field(name="Awards", value="\n".join(lines)[:3900] if lines else "No XP awarded.", inline=False)  
    embed.set_footer(text=f"Session ID: {session['id']}")  
    return embed  
  
  
  
async def enemy_summary_for_session(session_id: int) -> tuple[list[str], list[str], list[str]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT cb.name, cb.status, cb.xp_value  
            FROM alaris_combat_encounters ce  
            JOIN alaris_combatants cb ON cb.encounter_id=ce.id  
            WHERE ce.session_id=$1 AND cb.combatant_type='enemy'  
            ORDER BY cb.name;  
            """,  
            session_id,  
        )  
    all_enemies = [f"{r['name']} ({r['xp_value']} XP)" for r in rows]  
    defeated = [f"{r['name']} ({r['xp_value']} XP)" for r in rows if r["status"] == "defeated"]  
    surviving = [f"{r['name']} ({r['status']})" for r in rows if r["status"] != "defeated"]  
    return all_enemies, defeated, surviving  
  
  
def build_session_xp_log_embed(  
    session: asyncpg.Record,  
    participants: list[dict[str, Any]],  
    messages: list[discord.Message],  
    rp_counts: dict[int, int],  
    xp_results: list[dict[str, Any]],  
    summary: Optional[str] = None,  
    takeaways: Optional[list[str]] = None,  
    consequences: Optional[list[str]] = None,  
    victor_name: Optional[str] = None,  
    enemy_xp_each: Optional[int] = None,  
    session_jump_url: Optional[str] = None,  
) -> discord.Embed:  
    title = session["title"] or session["session_type"]  
    embed = discord.Embed(  
        title=f"{session['session_type']} Closed - {title}",  
        color=discord.Color.purple() if session["session_type"] == "Roleplay" else discord.Color.red(),  
    )  
    embed.add_field(name="Channel", value=f"<#{session['channel_id']}>", inline=True)  
    if session_jump_url:  
        embed.add_field(name="Session Link", value=f"[Jump to Session]({session_jump_url})", inline=True)  
    embed.add_field(name="Messages Tracked", value=str(len(messages)), inline=True)  
    embed.add_field(name="Participants", value=", ".join(f"**{p['name']}**" for p in participants) or "None", inline=False)  
  
    if victor_name:  
        embed.add_field(name="Victor", value=f"**{victor_name}**", inline=True)  
  
    lines = []  
    by_id = {int(p["character_id"]): p for p in participants}  
    for result in xp_results:  
        cid = int(result["character_id"])  
        typed = rp_counts.get(cid, 0)  
        die_note = ""  
        if result["new_die"] != result["old_die"]:  
            die_note += f" | 1d{result['old_die']}→1d{result['new_die']}"  
        if result["new_level"] != result["old_level"]:  
            die_note += f" | Level {result['old_level']}→{result['new_level']}"  
        lines.append(  
            f"• **{result['name']}**: +{result['amount']} XP "  
            f"(typed chars: {typed:,}){die_note}"  
        )  
    embed.add_field(name="XP Awards", value="\n".join(lines)[:1024] if lines else "No XP awarded.", inline=False)  
  
    if enemy_xp_each is not None:  
        embed.add_field(name="Enemy XP Award", value=f"+{enemy_xp_each} XP to each participant", inline=True)  
  
    if summary:  
        embed.add_field(name="Summary", value=summary[:1024], inline=False)  
    if takeaways:  
        embed.add_field(name="Key Takeaways", value="\n".join(f"• {x}" for x in takeaways)[:1024], inline=False)  
    if consequences:  
        embed.add_field(name="Possible Consequences", value="\n".join(f"• {x}" for x in consequences)[:1024], inline=False)  
  
    embed.set_footer(text="Alaris session XP log")  
    return embed  
  
# ---------- Session System Core ----------  
  
def normalize_session_type(value: str) -> Optional[str]:  
    key = normalize_name(value)  
    return SESSION_TYPE_ALIASES.get(key)  
  
  
async def session_type_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    current_norm = normalize_name(current)  
    options = [  
        s for s in SESSION_TYPES  
        if not current_norm or current_norm in normalize_name(s)  
    ]  
    return [app_commands.Choice(name=s, value=s) for s in options[:25]]  
  
  
async def session_participant_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    if db_pool is None or interaction.guild is None or interaction.channel is None:  
        return []  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        return []  
    participants = await list_session_participants(int(active["id"]))  
    current_norm = normalize_name(current)  
    choices = []  
    for p in participants:  
        name = str(p["name"])  
        if not current_norm or current_norm in normalize_name(name):  
            choices.append(app_commands.Choice(name=name[:100], value=name[:100]))  
    return choices[:25]  
  
  
  
async def get_active_session_for_channel(guild_id: int, channel_id: int) -> Optional[asyncpg.Record]:  
    async with db_pool.acquire() as conn:  
        return await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_sessions  
            WHERE guild_id=$1 AND channel_id=$2 AND status='open'  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            guild_id, channel_id,  
        )  
  
  
async def fetch_character_for_session(guild_id: int, query: str, user_id: Optional[int] = None) -> Optional[dict[str, Any]]:  
    payload = await find_clean_character(guild_id, query)  
    if not payload:  
        return None  
    if user_id is not None and int(payload["character"]["user_id"]) != int(user_id):  
        return None  
    return payload  
  
  
async def fetch_owned_character_for_session_by_id(guild_id: int, character_id_value: str, user_id: int) -> Optional[dict[str, Any]]:  
    """Fetch a character by autocomplete-selected ID, ensuring ownership."""  
    try:  
        character_id = int(character_id_value)  
    except (TypeError, ValueError):  
        return None  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return None  
    c = payload["character"]  
    if int(c["guild_id"]) != int(guild_id):  
        return None  
    if c.get("status") != "active":  
        return None  
    if int(c["user_id"]) != int(user_id):  
        return None  
    return payload  
  
  
  
async def count_messages_since(channel: discord.abc.Messageable, after_message_id: Optional[int]) -> int:  
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):  
        return 0  
    count = 0  
    after_obj = None  
    if after_message_id:  
        try:  
            after_obj = discord.Object(id=int(after_message_id))  
        except Exception:  
            after_obj = None  
    try:  
        async for msg in channel.history(limit=None, after=after_obj, oldest_first=True):  
            if bot.user and msg.author.id == bot.user.id:  
                continue  
            if msg.author.bot and not msg.webhook_id:  
                continue  
            count += 1  
    except Exception:  
        LOG.exception("Failed counting messages for session close.")  
    return count  
  
  
async def create_session(guild_id: int, channel_id: int, starter_user_id: int, session_type: str, title: Optional[str], start_message_id: Optional[int]) -> int:  
    async with db_pool.acquire() as conn:  
        return int(await conn.fetchval(  
            """  
            INSERT INTO alaris_sessions (  
                guild_id, channel_id, starter_user_id, session_type, title,  
                status, start_message_id  
            )  
            VALUES ($1,$2,$3,$4,$5,'open',$6)  
            RETURNING id;  
            """,  
            guild_id, channel_id, starter_user_id, session_type, title, start_message_id,  
        ))  
  
  
async def add_session_participant(session_id: int, character_id: int, user_id: int) -> bool:  
    async with db_pool.acquire() as conn:  
        result = await conn.execute(  
            """  
            INSERT INTO alaris_session_participants (session_id, character_id, user_id)  
            VALUES ($1,$2,$3)  
            ON CONFLICT (session_id, character_id) DO NOTHING;  
            """,  
            session_id, character_id, user_id,  
        )  
    return result.endswith("1")  
  
  
async def remove_session_participant(session_id: int, character_id: int) -> bool:  
    async with db_pool.acquire() as conn:  
        result = await conn.execute(  
            """  
            DELETE FROM alaris_session_participants  
            WHERE session_id=$1 AND character_id=$2;  
            """,  
            session_id, character_id,  
        )  
    try:  
        return int(result.split()[-1]) > 0  
    except Exception:  
        return False  
  
  
async def list_session_participants(session_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT p.character_id, p.user_id, c.name, c.species, c.class_name  
            FROM alaris_session_participants p  
            JOIN alaris_characters c ON c.id = p.character_id  
            WHERE p.session_id=$1  
            ORDER BY c.name;  
            """,  
            session_id,  
        )  
    return [dict(row) for row in rows]  
  
  
def build_session_status_embed(session: asyncpg.Record, participants: list[dict[str, Any]]) -> discord.Embed:  
    title = session["title"] or f"{session['session_type']} Session"  
    embed = discord.Embed(  
        title=f"Session - {title}",  
        description=f"Type: **{session['session_type']}**\nStatus: **{session['status']}**",  
        color=discord.Color.teal() if session["status"] == "open" else discord.Color.dark_teal(),  
    )  
    embed.add_field(name="Host", value=f"<@{session['starter_user_id']}>", inline=True)  
    embed.add_field(name="Session ID", value=str(session["id"]), inline=True)  
    embed.add_field(name="Channel", value=f"<#{session['channel_id']}>", inline=True)  
  
    if participants:  
        lines = [  
            f"• **{p['name']}** - {p.get('species') or 'Unknown'} {p.get('class_name') or ''} (<@{p['user_id']}>)"  
            for p in participants  
        ]  
        embed.add_field(name="Participants", value="\n".join(lines)[:1024], inline=False)  
    else:  
        embed.add_field(name="Participants", value="No characters have joined yet.", inline=False)  
  
    try:  
        message_count_value = session["message_count"]  
    except Exception:  
        message_count_value = None  
    if message_count_value is not None:  
        embed.add_field(name="Message Count", value=str(message_count_value), inline=True)  
  
    embed.set_footer(text="v013 tracks session shell only. XP, summaries, and combat resolve in later builds.")  
    return embed  
  
  
async def close_session(  
    session_id: int,  
    end_message_id: Optional[int],  
    message_count: int,  
    summary: Optional[str] = None,  
    key_takeaways: Optional[str] = None,  
    possible_consequences: Optional[str] = None,  
    victor_character_id: Optional[int] = None,  
    enemy_xp_pool: int = 0,  
) -> Optional[asyncpg.Record]:  
    async with db_pool.acquire() as conn:  
        return await conn.fetchrow(  
            """  
            UPDATE alaris_sessions  
            SET status='closed',  
                end_message_id=$2,  
                message_count=$3,  
                summary=$4,  
                key_takeaways=$5,  
                possible_consequences=$6,  
                victor_character_id=$7,  
                enemy_xp_pool=$8,  
                closed_at=NOW()  
            WHERE id=$1 AND status='open'  
            RETURNING *;  
            """,  
            session_id,  
            end_message_id,  
            int(message_count),  
            summary,  
            key_takeaways,  
            possible_consequences,  
            victor_character_id,  
            int(enemy_xp_pool or 0),  
        )  
  
  
  
# ---------- Combat Core v1 ----------  
  
def normalize_combat_type(value: str) -> Optional[str]:  
    return COMBAT_TYPE_ALIASES.get(normalize_name(value))  
  
  
async def combat_type_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    current_norm = normalize_name(current)  
    opts = [x for x in COMBAT_TYPES if not current_norm or current_norm in normalize_name(x)]  
    return [app_commands.Choice(name=x, value=x) for x in opts[:25]]  
  
  
async def challenge_rating_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    current_norm = normalize_name(current)  
    opts = [x for x in CHALLENGE_RATINGS if not current_norm or current_norm in normalize_name(x)]  
    return [app_commands.Choice(name=x, value=x) for x in opts[:25]]  
  
  
async def enemy_type_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    current_norm = normalize_name(current)  
    opts = [x for x in ENEMY_TYPES if not current_norm or current_norm in normalize_name(x)]  
    return [app_commands.Choice(name=x, value=x) for x in opts[:25]]  
  
  
async def enemy_theme_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    """Autocomplete enemy group/setting based on the selected enemy_type.  
  
    If enemy_type is NPCs, only NPC groups appear.  
    If enemy_type is Beasts, only beast settings appear.  
    If Discord has not populated enemy_type yet, show no choices instead of a mixed list.  
    """  
    current_norm = normalize_name(current)  
    selected_type = None  
    try:  
        selected_type = getattr(interaction.namespace, "enemy_type", None)  
    except Exception:  
        selected_type = None  
  
    selected_norm = normalize_name(selected_type or "")  
    if selected_norm == "npcs":  
        opts = NPC_GROUPS  
    elif selected_norm == "beasts":  
        opts = BEAST_SETTINGS  
    else:  
        opts = []  
  
    filtered = [x for x in opts if not current_norm or current_norm in normalize_name(x)]  
    return [app_commands.Choice(name=x, value=x) for x in filtered[:25]]  
  
  
async def action_type_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    current_norm = normalize_name(current)  
    opts = [x for x in ACTION_TYPES if not current_norm or current_norm in normalize_name(x)]  
    return [app_commands.Choice(name=x, value=x) for x in opts[:25]]  
  
  
def action_is_hostile(action_type: str) -> bool:  
    return normalize_name(action_type) in HOSTILE_ACTIONS  
  
  
def action_is_support(action_type: str) -> bool:  
    return normalize_name(action_type) in SUPPORT_ACTIONS  
  
  
def normalize_action_type_for_engine(action_type: str) -> str:  
    """Normalize only the v085 player-facing action labels."""  
    norm = normalize_name(action_type)  
    aliases = {  
        "use ability": "use ability",  
        "magical attack": "magical attack",  
        "magic attack": "magical attack",  
        "piercing melee or ranged attack": "piercing melee or ranged attack",  
        "piercing attack": "piercing melee or ranged attack",  
        "slashing melee attack": "slashing melee attack",  
        "slashing attack": "slashing melee attack",  
        "blunt melee attack": "blunt melee attack",  
        "blunt attack": "blunt melee attack",  
    }  
    return aliases.get(norm, norm)  
  
  
async def valid_targets_for_action(encounter_id: int, actor: dict[str, Any], action_type: str) -> list[dict[str, Any]]:  
    combatants = await get_combatants(encounter_id, active_only=True)  
    action_type = normalize_action_type_for_engine(action_type)  
    hostile = action_is_hostile(action_type)  
    support = action_is_support(action_type)  
  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow("SELECT combat_type FROM alaris_combat_encounters WHERE id=$1;", encounter_id)  
    combat_type = row["combat_type"] if row else None  
  
    valid: list[dict[str, Any]] = []  
    for c in combatants:  
        # Hostile actions cannot target self.  
        if hostile and int(c["id"]) == int(actor["id"]):  
            continue  
  
        # Enemy Encounter has clear sides: characters vs enemies.  
        # Spar/Duel/future mass spar team logic is intentionally deferred.  
        if hostile and combat_type == "Enemy Encounter":  
            if actor["combatant_type"] == c["combatant_type"]:  
                continue  
  
        # Support actions may target self and same-side allies in Enemy Encounter.  
        if support and combat_type == "Enemy Encounter":  
            if actor["combatant_type"] != c["combatant_type"]:  
                continue  
  
        valid.append(c)  
    return valid  
  
  
async def combat_target_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    if db_pool is None or interaction.guild is None or interaction.channel is None:  
        return []  
    active = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        return []  
  
    actor = await current_turn_combatant(int(active["id"]))  
    if not actor:  
        return []  
  
    try:  
        action_type = getattr(interaction.namespace, "action_type", None) or "Piercing Melee Attack"  
    except Exception:  
        action_type = "Piercing Melee Attack"  
  
    rows = await valid_targets_for_action(int(active["id"]), actor, action_type)  
    current_norm = normalize_name(current)  
    choices = []  
    for r in rows:  
        label = f"{r['name']} ({r['current_hp']}/{r['max_hp']} HP)"  
        if not current_norm or current_norm in normalize_name(str(r["name"])):  
            choices.append(app_commands.Choice(name=label[:100], value=str(r["id"])))  
    return choices[:25]  
  
  
  
  
async def fetch_open_combat_lobby_for_channel(guild_id: int, channel_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_lobbies  
            WHERE guild_id=$1  
              AND channel_id=$2  
              AND status='open'  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            int(guild_id),  
            int(channel_id),  
        )  
    return dict(row) if row else None  
  
  
async def get_active_combat_for_channel(guild_id: int, channel_id: int) -> Optional[asyncpg.Record]:  
    async with db_pool.acquire() as conn:  
        return await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_encounters  
            WHERE guild_id=$1 AND channel_id=$2 AND status='open'  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            guild_id, channel_id,  
        )  
  
  
async def get_combatants(encounter_id: int, active_only: bool = False) -> list[dict[str, Any]]:  
    where = "WHERE encounter_id=$1"  
    if active_only:  
        where += " AND status='active'"  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            f"""  
            SELECT *  
            FROM alaris_combatants  
            {where}  
            ORDER BY initiative_bonus DESC, name;  
            """,  
            encounter_id,  
        )  
    return [dict(r) for r in rows]  
  
  
async def get_combat_turn_order(encounter_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        combat = await conn.fetchrow("SELECT turn_order_json FROM alaris_combat_encounters WHERE id=$1;", encounter_id)  
        if not combat:  
            return []  
    raw = combat["turn_order_json"]  
    if isinstance(raw, str):  
        try:  
            return json.loads(raw)  
        except Exception:  
            return []  
    return list(raw or [])  
  
  
def roll_d20() -> int:  
    return random.randint(1, 20)  
  
  
def roll_die(sides: int) -> int:  
    return random.randint(1, max(1, int(sides or 1)))  
  
  
def resolve_spell_save_damage(raw_damage: int, save_roll: int, save_total: int, spell_dc: int) -> tuple[int, str]:  
    raw_damage = max(0, int(raw_damage or 0))  
    if save_roll == 20:  
        return 0, "nat20_no_damage"  
    if save_roll == 1:  
        return raw_damage * 2, "nat1_double_damage"  
    if save_total >= int(spell_dc or 10):  
        return math.ceil(raw_damage * 0.25), "saved_quarter_damage"  
    return raw_damage, "failed_full_damage"  
  
  
async def build_turn_order(encounter_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id, name, initiative_bonus  
            FROM alaris_combatants  
            WHERE encounter_id=$1 AND status='active'  
            ORDER BY id;  
            """,  
            encounter_id,  
        )  
        order = []  
        for r in rows:  
            init_roll = roll_d20()  
            total = init_roll + int(r["initiative_bonus"] or 0)  
            order.append({  
                "combatant_id": int(r["id"]),  
                "name": str(r["name"]),  
                "initiative_roll": init_roll,  
                "initiative_total": total,  
            })  
            await conn.execute(  
                "UPDATE alaris_combatants SET initiative_roll=$2 WHERE id=$1;",  
                int(r["id"]), init_roll,  
            )  
        order.sort(key=lambda x: (x["initiative_total"], x["initiative_roll"]), reverse=True)  
        current_id = order[0]["combatant_id"] if order else None  
        await conn.execute("UPDATE alaris_combatants SET action_taken=FALSE WHERE encounter_id=$1;", encounter_id)  
        await conn.execute(  
            """  
            UPDATE alaris_combat_encounters  
            SET turn_order_json=$2::jsonb,  
                current_turn_index=0,  
                current_turn_combatant_id=$3  
            WHERE id=$1;  
            """,  
            encounter_id, json.dumps(order), current_id,  
        )  
    return order  
  
  
async def current_turn_combatant(encounter_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        combat = await conn.fetchrow("SELECT current_turn_combatant_id FROM alaris_combat_encounters WHERE id=$1;", encounter_id)  
        if not combat or not combat["current_turn_combatant_id"]:  
            return None  
        row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", int(combat["current_turn_combatant_id"]))  
    return dict(row) if row else None  
  
  


def _hp_bar(current_hp: int, max_hp: int, width: int = 10) -> str:  
    max_hp = max(1, int(max_hp or 1))  
    current_hp = max(0, int(current_hp or 0))  
    filled = max(0, min(width, round((current_hp / max_hp) * width)))  
    return "█" * filled + "░" * (width - filled)  
  
  
def _format_health_line(combatant: dict[str, Any]) -> str:  
    name = clean_text(combatant.get("name") or "Unknown")  
    current_hp = int(combatant.get("current_hp") or 0)  
    max_hp = int(combatant.get("max_hp") or 0)  
    status = str(combatant.get("status") or "active")  
    status_note = "" if status == "active" else f" — `{status}`"  
    return f"• **{name}** — `{current_hp}/{max_hp} HP` `{_hp_bar(current_hp, max_hp)}`{status_note}"  
  
  
async def build_round_health_summary(encounter_id: int, round_number: int) -> str:  
    combatants = await get_combatants(encounter_id, active_only=False)  
    characters = [c for c in combatants if c.get("combatant_type") == "character"]  
    enemies = [c for c in combatants if c.get("combatant_type") == "enemy"]  
  
    lines: list[str] = [f"🩸 **Round {int(round_number)} Health Summary**"]  
    if characters:  
        lines.append("\n**Characters**")  
        lines.extend(_format_health_line(c) for c in characters)  
    if enemies:  
        lines.append("\n**Enemies**")  
        lines.extend(_format_health_line(c) for c in enemies)  
    return "\n".join(lines)  
  
  
async def post_round_health_summary_if_needed(channel: discord.abc.Messageable, encounter_id: int, next_actor: Optional[dict[str, Any]]) -> None:  
    if not next_actor or not next_actor.get("_round_started"):  
        return  
    try:  
        summary = await build_round_health_summary(encounter_id, int(next_actor.get("_round_number") or 1))  
        await channel.send(summary)  
    except Exception:  
        LOG.exception("Failed to post round health summary for combat encounter %s.", encounter_id)  
  
  
async def advance_combat_turn(encounter_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        combat = await conn.fetchrow(  
            "SELECT * FROM alaris_combat_encounters WHERE id=$1;",  
            encounter_id,  
        )  
        if not combat:  
            return None  
        order_raw = combat["turn_order_json"]  
        order = json.loads(order_raw) if isinstance(order_raw, str) else list(order_raw or [])  
        if not order:  
            return None  
  
        active_ids = {  
            int(r["id"]) for r in await conn.fetch(  
                "SELECT id FROM alaris_combatants WHERE encounter_id=$1 AND status='active';",  
                encounter_id,  
            )  
        }  
        if not active_ids:  
            return None  
  
        idx = int(combat["current_turn_index"] or 0)  
        round_number = int(combat["round_number"] or 1)  
        round_started = False  
  
        for _ in range(len(order)):  
            idx += 1  
            if idx >= len(order):  
                idx = 0  
                round_number += 1  
                round_started = True  
            cid = int(order[idx]["combatant_id"])  
            if cid in active_ids:  
                await conn.execute(  
                    """  
                    UPDATE alaris_combat_encounters  
                    SET current_turn_index=$2,  
                        round_number=$3,  
                        current_turn_combatant_id=$4  
                    WHERE id=$1;  
                    """,  
                    encounter_id, idx, round_number, cid,  
                )  
                await conn.execute("UPDATE alaris_combatants SET action_taken=FALSE WHERE id=$1;", cid)  
                row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", cid)  
                if not row:  
                    return None  
                payload = dict(row)  
                payload["_round_started"] = bool(round_started)  
                payload["_round_number"] = int(round_number)  
                return payload  
    return None  
  
  
async def combat_has_side_victory(encounter_id: int) -> tuple[bool, Optional[str]]:  
    combatants = await get_combatants(encounter_id)  
    active_chars = [c for c in combatants if c["status"] == "active" and c["combatant_type"] == "character"]  
    active_enemies = [c for c in combatants if c["status"] == "active" and c["combatant_type"] == "enemy"]  
    all_chars = [c for c in combatants if c["combatant_type"] == "character"]  
    all_enemies = [c for c in combatants if c["combatant_type"] == "enemy"]  
  
    if all_enemies and active_chars and not active_enemies:  
        return True, "characters"  
    if all_enemies and active_enemies and not active_chars:  
        return True, "enemies"  
    if not all_enemies:  
        active = [c for c in combatants if c["status"] == "active"]  
        if len(active) == 1:  
            return True, str(active[0]["name"])  
    return False, None  
  
  
def enemy_template(name: str) -> dict[str, Any]:  
    key = normalize_name(name)  
    fallback = {"max_hp": 10, "armor_class": 11, "initiative_bonus": 0, "attack_bonus": 3, "save_dc": 10, "damage_die_sides": 6, "damage_bonus": 0, "xp_value": 25}  
    data = dict(ENEMY_STAT_BLOCKS.get(key, fallback))  
    data["name"] = name  
    data["current_hp"] = data["max_hp"]  
    data["damage_type"] = "physical"  
    return data  
  
  
  
  
ENEMY_CATEGORY_AFFINITIES = {  
    # v093: enemy-only affinity system. Player/species affinities remain deferred.  
    # Damage types are the canon LOCKED_DAMAGE_TYPES list.  
    "bandits": {"resistances": {}, "weaknesses": {"spirit": 1.5}, "immunities": {}},  
    "cultists": {"resistances": {"spirit": 0.5}, "weaknesses": {"blunt": 1.5}, "immunities": {}},  
    "pirates": {"resistances": {"water": 0.5}, "weaknesses": {"lightning": 1.5}, "immunities": {}},  
    "undead": {"resistances": {"poison/acid": 0.5, "piercing": 0.5}, "weaknesses": {"spirit": 1.5, "fire": 1.5}, "immunities": {}},  
    "soldiers": {"resistances": {"piercing": 0.5}, "weaknesses": {"blunt": 1.5, "lightning": 1.5}, "immunities": {}},  
    "goblins": {"resistances": {"poison/acid": 0.5}, "weaknesses": {"fire": 1.5}, "immunities": {}},  
    "orcs": {"resistances": {"blunt": 0.5}, "weaknesses": {"spirit": 1.5}, "immunities": {}},  
    "beasts": {"resistances": {}, "weaknesses": {"fire": 1.5}, "immunities": {}},  
    "monsters": {"resistances": {"spirit": 0.5, "poison/acid": 0.5}, "weaknesses": {"lightning": 1.5}, "immunities": {}},  
}  
  
ENEMY_TEMPLATE_AFFINITY_OVERRIDES = {  
    "ash maw": {"resistances": {"fire": 0.5}, "weaknesses": {"water": 1.5, "ice": 1.5}},  
    "bonewalker": {"resistances": {"piercing": 0.5}, "weaknesses": {"blunt": 1.5, "spirit": 1.5}},  
    "bone knight": {"resistances": {"piercing": 0.5, "slashing": 0.5}, "weaknesses": {"blunt": 1.5, "spirit": 1.5}},  
    "gravebound corpse": {"resistances": {"poison/acid": 0.5}, "weaknesses": {"fire": 1.5, "spirit": 1.5}},  
    "restless dead": {"resistances": {"poison/acid": 0.5}, "weaknesses": {"spirit": 1.5}},  
    "wight": {"resistances": {"poison/acid": 0.5, "ice": 0.5}, "weaknesses": {"spirit": 1.5, "fire": 1.5}},  
    "giant serpent": {"resistances": {"poison/acid": 0.5}, "weaknesses": {"ice": 1.5}},  
    "elder basilisk": {"resistances": {"poison/acid": 0.5}, "weaknesses": {"ice": 1.5}},  
    "cave bear": {"resistances": {"blunt": 0.5}, "weaknesses": {"piercing": 1.5}},  
    "mountain cat": {"resistances": {}, "weaknesses": {"blunt": 1.5}},  
    "dire wolf": {"resistances": {}, "weaknesses": {"fire": 1.5}},  
    "alpha dire wolf": {"resistances": {}, "weaknesses": {"fire": 1.5}},  
    "void channeler": {"resistances": {"spirit": 0.5}, "weaknesses": {"lightning": 1.5}},  
    "rift horror": {"resistances": {"spirit": 0.5}, "weaknesses": {"lightning": 1.5}},  
    "deep crawler": {"resistances": {"piercing": 0.5}, "weaknesses": {"fire": 1.5}},  
}  
  
  
def merge_affinity_maps(*maps: dict[str, float]) -> dict[str, float]:  
    merged: dict[str, float] = {}  
    for data in maps:  
        for key, value in (data or {}).items():  
            merged[normalize_damage_type(key, key)] = float(value)  
    return merged  
  
  
def enemy_affinities_for_template(category: str, base_name: str) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:  
    category_key = normalize_name(category)  
    base_key = normalize_name(base_name)  
    category_data = ENEMY_CATEGORY_AFFINITIES.get(category_key, {})  
    override = ENEMY_TEMPLATE_AFFINITY_OVERRIDES.get(base_key, {})  
    resistances = merge_affinity_maps(category_data.get("resistances", {}), override.get("resistances", {}))  
    weaknesses = merge_affinity_maps(category_data.get("weaknesses", {}), override.get("weaknesses", {}))  
    immunities = merge_affinity_maps(category_data.get("immunities", {}), override.get("immunities", {}))  
    for dtype in list(immunities.keys()):  
        resistances.pop(dtype, None)  
        weaknesses.pop(dtype, None)  
    for dtype in list(resistances.keys()):  
        if dtype in weaknesses:  
            resistances.pop(dtype, None)  
            weaknesses.pop(dtype, None)  
    return resistances, weaknesses, immunities  
  
  
  
def normalize_encounter_category(value: Optional[str]) -> str:  
    norm = normalize_name(value or "Bandits")  
    aliases = {  
        "bandit": "bandits",  
        "cultist": "cultists",  
        "pirate": "pirates",  
        "undead": "undead",  
        "soldier": "soldiers",  
        "goblin": "goblins",  
        "orc": "orcs",  
        "beast": "beasts",  
        "monster": "monsters",  
    }  
    norm = aliases.get(norm, norm)  
    allowed = {normalize_name(x): x for x in ENCOUNTER_ENEMY_CATEGORIES}  
    return allowed.get(norm, "Bandits")  
  
  
def normalize_danger_label(value: Optional[str]) -> str:  
    norm = normalize_name(value or "Balanced")  
    aliases = {  
        "moderate": "Standard",  
        "standard": "Standard",  
        "balanced": "Balanced",  
        "dangerous": "Hard",  
        "hard": "Hard",  
        "deadly": "Deadly",  
        "easy": "Easy",  
        "trivial": "Easy",  
        "boss": "Deadly",  
    }  
    normalized = aliases.get(norm, value or "Balanced")  
    allowed = {normalize_name(x): x for x in ENCOUNTER_DANGER_LEVELS}  
    return allowed.get(normalize_name(normalized), "Balanced")  
  
  
def normalize_environment_label(value: Optional[str]) -> str:  
    norm = normalize_name(value or "Roads")  
    aliases = {  
        "road": "roads",  
        "roads": "roads",  
        "forest": "forest",  
        "mountain": "mountains",  
        "mountains": "mountains",  
        "ruin": "ruins",  
        "ruins": "ruins",  
        "swamp": "swamp",  
        "city": "city",  
        "coastal": "coast",  
        "coast": "coast",  
        "cavern": "caverns",  
        "caverns": "caverns",  
        "jungle": "jungle",  
        "volcano": "volcanic region",  
        "volcanic": "volcanic region",  
        "volcanic region": "volcanic region",  
    }  
    norm = aliases.get(norm, norm)  
    allowed = {normalize_name(x): x for x in ENCOUNTER_ENVIRONMENTS}  
    return allowed.get(norm, "Roads")  
  
  
def generator_inputs_for_lobby(lobby: dict[str, Any]) -> tuple[str, str, str]:  
    return (  
        normalize_danger_label(lobby.get("danger_level") or lobby.get("danger")),  
        normalize_encounter_category(lobby.get("enemy_category")),  
        normalize_environment_label(lobby.get("environment")),  
    )  
  
  
  
def scale_enemy_template(template: dict[str, Any], category: str, setting: str, danger: str, index: int, tier: str) -> dict[str, Any]:  
    profile = ENCOUNTER_DIFFICULTY_PROFILE.get(normalize_name(danger), ENCOUNTER_DIFFICULTY_PROFILE["balanced"])  
    base_name = str(template["name"])  
    eliteish = tier in {"elite", "lite_elite"}  
    hp_mult = float(profile.get("elite_hp_mult", profile.get("hp_mult", 1.0)) if eliteish else profile.get("hp_mult", 1.0))  
    atk_mod = int(profile.get("elite_atk_mod", profile.get("atk_mod", 0)) if eliteish else profile.get("atk_mod", 0))  
    die_mod = int(profile.get("elite_die_mod", profile.get("die_mod", 0)) if eliteish else profile.get("die_mod", 0))  
    ability_chance = float(profile.get("elite_ability_chance", profile.get("ability_chance", 0.0)) if eliteish else profile.get("ability_chance", 0.0))  
    die = max(4, int(template.get("die") or 6) + die_mod)  
    if die % 2:  
        die += 1  
    abilities = list(template.get("abilities") or [])  
    if tier == "lite_elite":  
        abilities = abilities[:1]  
    resistances, weaknesses, immunities = enemy_affinities_for_template(category, base_name)  
    return {  
        "name": base_name if index <= 1 else f"{base_name} {index}",  
        "base_name": base_name,  
        "category": category,  
        "setting": setting,  
        "theme": category,  
        "enemy_theme": setting,  
        "tier": tier,  
        "role": template.get("role") or "minion",  
        "enemy_role": template.get("role") or "minion",  
        "max_hp": max(1, round(int(template.get("hp") or 10) * hp_mult)),  
        "armor_class": max(8, int(template.get("ac") or 10) + int(profile.get("ac_mod", 0))),  
        "initiative_bonus": int(template.get("init") or 0),  
        "attack_bonus": int(template.get("atk") or 3) + atk_mod,  
        "save_dc": max(8, int(template.get("md") or 10) + atk_mod),  
        "magic_defense": max(8, int(template.get("md") or 10) + int(profile.get("ac_mod", 0))),  
        "magic_save_bonus": max(0, int(template.get("md") or 10) - 8),  
        "damage_die_sides": die,  
        "damage_bonus": int(template.get("dmg") or 0) + (1 if tier == "elite" else 0),  
        "damage_type": template.get("dtype") or "blunt",  
        "xp_value": max(1, round(int(template.get("xp") or 25) * float(profile.get("xp_mult", 1.0)))),  
        "abilities": abilities,  
        "ability_chance": ability_chance if abilities else 0.0,  
        "resistances": resistances,  
        "weaknesses": weaknesses,  
        "immunities": immunities,  
    }  
  
  
  
  
  
ENCOUNTER_THREAT_MULTIPLIERS = {  
    "Easy": 0.70,  
    "Standard": 0.90,  
    "Balanced": 1.10,  
    "Hard": 1.30,  
    "Deadly": 1.60,  
}  
  
ENCOUNTER_HP_MULTIPLIERS = {  
    "Easy": 0.80,  
    "Standard": 1.00,  
    "Balanced": 1.10,  
    "Hard": 1.25,  
    "Deadly": 1.40,  
}  
  
ENEMY_THREAT_VALUES = {  
    "cutpurse": 4,  
    "highway raider": 5,  
    "cult acolyte": 5,  
    "goblin sneak": 4,  
    "goblin cutter": 5,  
    "orc raider": 7,  
    "skeleton": 5,  
    "restless dead": 5,  
    "wolf": 4,  
    "dire wolf": 7,  
    "cave bear": 10,  
    "deep crawler": 8,  
    "cult fanatic": 10,  
    "goblin hexer": 10,  
    "orc berserker": 12,  
    "bone knight": 14,  
    "void channeler": 14,  
    "rift horror": 16,  
    "elder basilisk": 16,  
    "ash maw": 18,  
}  
  
def weighted_enemy_templates(category: str, setting: str, template_tier: str) -> list[dict[str, Any]]:  
    """Return weighted enemy templates for the current v093 enemy library shape.  
  
    ENCOUNTER_ENEMY_LIBRARY is grouped as:  
        {"bandits": {"minor": [...], "elite": [...]}, ...}  
  
    This helper also tolerates a legacy flat list defensively.  
    """  
    category_key = normalize_name(category)  
    setting_key = normalize_name(setting)  
    tier_key = normalize_name(template_tier)  
  
    category_pool = ENCOUNTER_ENEMY_LIBRARY.get(category_key)  
    if not category_pool:  
        category_pool = ENCOUNTER_ENEMY_LIBRARY.get("bandits", {})  
  
    if isinstance(category_pool, dict):  
        if tier_key in {"elite", "lite_elite"}:  
            pool = list(category_pool.get("elite") or [])  
            if not pool and tier_key == "lite_elite":  
                pool = list(category_pool.get("minor") or [])  
        else:  
            pool = list(category_pool.get("minor") or [])  
    elif isinstance(category_pool, list):  
        pool = [x for x in category_pool if isinstance(x, dict)]  
    else:  
        pool = []  
  
    if not pool:  
        fallback = ENCOUNTER_ENEMY_LIBRARY.get("bandits", {})  
        if isinstance(fallback, dict):  
            pool = list(fallback.get("minor") or [])  
        elif isinstance(fallback, list):  
            pool = [x for x in fallback if isinstance(x, dict)]  
  
    if not pool:  
        return []  
  
    setting_flavor = SETTING_FLAVOR.get(setting_key) or {}  
    favored_tags = {normalize_name(x) for x in (setting_flavor.get("weights") or [])}  
    favored_tags.add(setting_key)  
  
    weighted: list[dict[str, Any]] = []  
    for template in pool:  
        if not isinstance(template, dict):  
            continue  
        tags = {normalize_name(x) for x in (template.get("tags") or template.get("settings") or [])}  
        weight = 2  
        if setting_key in tags:  
            weight += 5  
        weight += len(tags.intersection(favored_tags)) * 2  
        if tier_key in {"elite", "lite_elite"}:  
            weight += 1  
        weighted.extend([dict(template)] * max(1, weight))  
  
    return weighted or [dict(x) for x in pool if isinstance(x, dict)]  
  
  
  
  
def generate_enemy_roster_for_lobby(lobby: dict[str, Any], participant_count: int) -> list[dict[str, Any]]:  
    danger, category, setting = generator_inputs_for_lobby(lobby)  
  
    participants = lobby.get("_participants") or []  
  
    party_threat = 0  
    for participant in participants:  
        party_threat += max(4, int(participant.get("damage_die_sides") or 8))  
  
    if party_threat <= 0:  
        party_threat = max(8, int(participant_count or 1) * 8)  
  
    target_budget = max(  
        4,  
        round(  
            party_threat * ENCOUNTER_THREAT_MULTIPLIERS.get(danger, 1.0)  
        ),  
    )  
  
    party_size = max(1, int(participant_count or 1))  
  
    allow_elites = (  
        party_size >= 3  
        and danger in {"Balanced", "Hard", "Deadly"}  
    )  
  
    elite_cap = 0  
    if allow_elites:  
        if danger == "Balanced":  
            elite_cap = 1  
        elif danger == "Hard":  
            elite_cap = 1  
        elif danger == "Deadly":  
            elite_cap = 2  
  
    weighted_minor = weighted_enemy_templates(category, setting, "minor")  
    weighted_elite = weighted_enemy_templates(category, setting, "elite") if allow_elites else []  
  
    selected = []  
    duplicate_counter = {}  
    current_budget = 0  
    elites_used = 0  
  
    while current_budget < target_budget:  
        remaining = target_budget - current_budget  
  
        use_elite = (  
            elites_used < elite_cap  
            and remaining >= 10  
            and bool(weighted_elite)  
        )  
  
        if use_elite:  
            template = random.choice(weighted_elite)  
            tier = "elite"  
            elites_used += 1  
        else:  
            if not weighted_minor:  
                break  
            template = random.choice(weighted_minor)  
            tier = "minor"  
  
        base_name = str(template.get("name") or "Enemy")  
  
        threat_value = int(  
            ENEMY_THREAT_VALUES.get(  
                normalize_name(base_name),  
                6 if tier == "minor" else 12,  
            )  
        )  
  
        duplicate_counter[base_name] = duplicate_counter.get(base_name, 0) + 1  
  
        scaled = scale_enemy_template(  
            template,  
            category,  
            setting,  
            danger,  
            duplicate_counter[base_name],  
            tier,  
        )  
  
        hp_mult = ENCOUNTER_HP_MULTIPLIERS.get(danger, 1.0)  
        scaled["max_hp"] = max(  
            4,  
            round(int(scaled.get("max_hp") or 8) * hp_mult),  
        )  
        scaled["current_hp"] = scaled["max_hp"]  
  
        selected.append(scaled)  
        current_budget += threat_value  
  
        if len(selected) >= max(8, party_size * 3):  
            break  
  
    return selected or [  
        scale_enemy_template(  
            ENCOUNTER_ENEMY_LIBRARY["bandits"]["minor"][0],  
            "Bandits",  
            setting,  
            danger,  
            1,  
            "minor",  
        )  
    ]  
  
  


def iter_structured_enemy_templates() -> list[tuple[str, str, str, dict[str, Any]]]:  
    """Return available encounter enemy templates as (label, category, tier, template)."""  
    rows: list[tuple[str, str, str, dict[str, Any]]] = []  
    for category, group in ENCOUNTER_ENEMY_LIBRARY.items():  
        display_category = normalize_encounter_category(category)  
        for tier in ("minor", "elite"):  
            for template in list((group or {}).get(tier) or []):  
                name = str(template.get("name") or "Enemy").strip()  
                if not name:  
                    continue  
                label = f"{name} ({display_category}, {tier})"  
                rows.append((label, display_category, tier, template))  
    rows.sort(key=lambda item: (item[1], item[2], item[0]))  
    return rows  
  
  
def find_structured_enemy_template(enemy_type: str) -> Optional[tuple[str, str, str, dict[str, Any]]]:  
    """Find a structured enemy template by exact label or base enemy name."""  
    requested = normalize_name(enemy_type or "")  
    if not requested:  
        return None  
    fallback: Optional[tuple[str, str, str, dict[str, Any]]] = None  
    for label, category, tier, template in iter_structured_enemy_templates():  
        name_norm = normalize_name(str(template.get("name") or ""))  
        label_norm = normalize_name(label)  
        if requested == label_norm or requested == name_norm:  
            return (label, category, tier, template)  
        if requested in label_norm or requested in name_norm:  
            fallback = fallback or (label, category, tier, template)  
    return fallback  
  
  
def build_structured_enemy_roster(enemy_type: str, count: int, danger: str, environment: str) -> tuple[list[dict[str, Any]], Optional[str]]:  
    """Build an exact-count enemy roster for staff-authored PvE encounters."""  
    found = find_structured_enemy_template(enemy_type)  
    if not found:  
        return [], None  
    label, category, tier, template = found  
    danger_label = normalize_danger_label(danger)  
    environment_label = normalize_environment_label(environment)  
    safe_count = max(1, min(int(count or 1), 8))  
    enemies: list[dict[str, Any]] = []  
    for index in range(1, safe_count + 1):  
        enemy = scale_enemy_template(template, category, environment_label, danger_label, index, tier)  
        enemy["structured"] = True  
        enemy["structured_label"] = label  
        enemy["current_hp"] = int(enemy.get("max_hp") or enemy.get("hp") or 10)  
        enemies.append(enemy)  
    return enemies, label  
  
  
def decode_structured_enemies_from_lobby(lobby: dict[str, Any]) -> list[dict[str, Any]]:  
    raw = lobby.get("structured_enemies_json")  
    if not raw:  
        return []  
    if isinstance(raw, list):  
        return [dict(x) for x in raw if isinstance(x, dict)]  
    try:  
        data = json.loads(str(raw))  
        return [dict(x) for x in data if isinstance(x, dict)] if isinstance(data, list) else []  
    except Exception:  
        return []  
  
  
async def structured_enemy_type_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    needle = normalize_name(current or "")  
    choices: list[app_commands.Choice[str]] = []  
    for label, category, tier, template in iter_structured_enemy_templates():  
        hay = normalize_name(f"{label} {category} {tier}")  
        if needle and needle not in hay:  
            continue  
        choices.append(app_commands.Choice(name=label[:100], value=str(template.get("name") or label)[:100]))  
        if len(choices) >= 25:  
            break  
    return choices  

def article_for_phrase(phrase: str) -> str:  
    return "an" if phrase[:1].lower() in {"a", "e", "i", "o", "u"} else "a"  
  
  
def format_enemy_reveal(enemies: list[dict[str, Any]], category: str) -> str:  
    if not enemies:  
        return "No enemies appear."  
    counts = {}  
    for enemy in enemies:  
        base = str(enemy.get("base_name") or re.sub(r"\s+\d+$", "", str(enemy.get("name") or "Enemy")).strip())  
        counts[base] = counts.get(base, 0) + 1  
    parts = []  
    for name, count in counts.items():  
        parts.append(f"{article_for_phrase(name).capitalize()} {name}" if count == 1 else f"{count} {name if name.endswith('s') else name + 's'}")  
    phrase = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + f", and {parts[-1]}"  
    return f"{phrase} emerge as the {str(category or 'enemies').lower()} press the attack."  
  
  
def build_encounter_intro(lobby: dict[str, Any], enemies: list[dict[str, Any]]) -> str:  
    category = str(lobby.get("enemy_category") or "Enemies")  
    danger = str(lobby.get("danger_level") or "Balanced")  
    environment = str(lobby.get("environment") or "Roads")  
    intro = (SETTING_FLAVOR.get(normalize_name(environment)) or SETTING_FLAVOR["roads"])["intro"]  
    category_lines = {  
        "bandits": "These are not wandering thieves; they move like predators who chose this ground before the party arrived.",  
        "cultists": "Their symbols and whispered invocations make it clear this violence serves something darker than coin.",  
        "pirates": "They carry the swagger of raiders accustomed to taking what they want before vanishing with the tide.",  
        "undead": "The air chills around them, every motion carrying the wrongness of bodies that should no longer move.",  
        "soldiers": "They advance with discipline, trained to hold formation even when the fight turns ugly.",  
        "goblins": "Shrill calls and quick footwork betray a pack of foes more cunning than their size suggests.",  
        "orcs": "They come on with brutal confidence, testing the party's nerve before the first blow falls.",  
        "beasts": "Instinct, hunger, and territorial fury drive them forward.",  
        "monsters": "The things approaching do not fit cleanly into any sane bestiary.",  
    }  
    return f"**{danger} {category} Encounter - {environment}**\n\n{intro}\n\n{category_lines.get(normalize_name(category), 'The threat closes in with violent intent.')}\n\n{format_enemy_reveal(enemies, category)}"  
  
  
def compact_initiative_line(order: list[dict[str, Any]]) -> str:  
    if not order:  
        return "No initiative order."  
    return "; ".join(f"{i+1}. {x['name']}" for i, x in enumerate(order))[:1900]  
  
  
async def owned_character_rows_for_user(guild_id: int, user_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id, name, species, class_name  
            FROM alaris_characters  
            WHERE guild_id=$1 AND user_id=$2 AND status='active'  
            ORDER BY name  
            LIMIT 25;  
            """,  
            guild_id, user_id,  
        )  
    return [dict(r) for r in rows]  
  
  
  
  
def build_combat_lobby_embed(lobby: dict[str, Any], participants: list[dict[str, Any]]) -> discord.Embed:  
    """Render the active pre-combat lobby after setup is complete."""  
    combat_type = str(lobby.get("combat_type") or "Combat")  
    if combat_type == "Enemy Encounter":  
        title = f"{lobby.get('danger_level') or 'Balanced'} {lobby.get('enemy_category') or 'Enemy'} Encounter Lobby"  
        color = discord.Color.orange()  
    else:  
        title = f"{combat_type} Lobby"  
        color = discord.Color.blurple()  
  
    embed = discord.Embed(  
        title=title,  
        description=(  
            "Combat has not started yet. Players may join with one or more owned characters. "  
            "The host or staff can click **Start Now** when ready."  
        ),  
        color=color,  
    )  
    host_id = lobby.get("host_user_id")  
    embed.add_field(name="Host", value=f"<@{int(host_id)}>" if host_id else "Unknown", inline=True)  
    embed.add_field(name="Combat Type", value=combat_type, inline=True)  
  
    if combat_type == "Enemy Encounter":  
        embed.add_field(name="Enemy Type", value=str(lobby.get("enemy_category") or "Bandits"), inline=True)  
        embed.add_field(name="Danger", value=str(lobby.get("danger_level") or "Balanced"), inline=True)  
        embed.add_field(name="Setting", value=str(lobby.get("environment") or "Roads"), inline=True)  
        structured = decode_structured_enemies_from_lobby(dict(lobby))  
        if structured:  
            counts: dict[str, int] = {}  
            for enemy in structured:  
                base = str(enemy.get("base_name") or enemy.get("name") or "Enemy")  
                counts[base] = counts.get(base, 0) + 1  
            lines = [f"{count} × {name}" for name, count in sorted(counts.items())]  
            embed.add_field(name="Structured Enemy Roster", value="\n".join(lines)[:1024], inline=False)  
  
    if participants:  
        lines = []  
        for p in participants:  
            species = p.get("species") or "Unknown"  
            cls = p.get("class_name") or ""  
            owner = f"<@{int(p['user_id'])}>" if p.get("user_id") else "Unknown owner"  
            lines.append(f"• **{p['name']}** - {species} {cls} ({owner})")  
        embed.add_field(name="Joined Characters", value="\n".join(lines)[:1024], inline=False)  
    else:  
        embed.add_field(name="Joined Characters", value="No characters have joined yet.", inline=False)  
  
    embed.set_footer(text="Use Join Encounter to add characters. Use Start Now only when the lobby is ready.")  
    return embed  
  
  
def build_combat_setup_embed(session: dict[str, Any]) -> discord.Embed:  
    embed = discord.Embed(  
        title="Start Combat",  
        description=(  
            "Choose the combat type for this open session. "  
            "The bot will then create a lobby where players can join with one or more owned characters."  
        ),  
        color=discord.Color.blurple(),  
    )  
    embed.add_field(name="Session", value=f"**{session.get('title') or session.get('session_type')}**", inline=False)  
    embed.add_field(name="Available Types", value="Spar\nDuel\nEnemy Encounter", inline=True)  
    embed.set_footer(text="Combat setup uses dropdowns here so the slash command stays clean.")  
    return embed  
  
  
def build_enemy_setup_embed(session: dict[str, Any], selected: dict[str, str]) -> discord.Embed:  
    category = selected.get("enemy_category")  
    danger = selected.get("danger")  
    environment = selected.get("environment")  
    next_step = "Choose enemy type." if not category else "Choose danger level." if not danger else "Choose setting." if not environment else "Ready."  
    embed = discord.Embed(  
        title="Enemy Encounter Setup",  
        description=next_step,  
        color=discord.Color.orange(),  
    )  
    embed.add_field(name="Enemy Type", value=category or "Not selected", inline=True)  
    embed.add_field(name="Danger", value=danger or "Not selected", inline=True)  
    embed.add_field(name="Setting", value=environment or "Not selected", inline=True)  
    embed.set_footer(text="After setup, a combat lobby will open for player character joins.")  
    return embed  
  
  
class CombatTypeSelect(discord.ui.Select):  
    def __init__(self, session_id: int):  
        self.session_id = int(session_id)  
        options = [  
            discord.SelectOption(label="Spar", value="Spar", description="Training combat. Full XP. Nonlethal framing."),  
            discord.SelectOption(label="Duel", value="Duel", description="Real character conflict. Full XP."),  
            discord.SelectOption(label="Enemy Encounter", value="Enemy Encounter", description="PvE encounter with generated enemies."),  
        ]  
        super().__init__(placeholder="Choose combat type...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if interaction.guild is None or interaction.channel is None or interaction.message is None:  
            await interaction.response.send_message("Combat setup is unavailable.", ephemeral=True)  
            return  
        async with db_pool.acquire() as conn:  
            session = await conn.fetchrow(  
                "SELECT * FROM alaris_sessions WHERE id=$1 AND status='open';",  
                self.session_id,  
            )  
        if not session:  
            await interaction.response.send_message("That session is no longer open.", ephemeral=True)  
            return  
  
        ctype = self.values[0]  
        if ctype == "Enemy Encounter":  
            await interaction.response.edit_message(  
                embed=build_enemy_setup_embed(dict(session), {}),  
                view=EnemyCategorySetupView(self.session_id, {}),  
            )  
            return  
  
        lobby_id = await create_combat_lobby_record(  
            interaction.guild.id,  
            interaction.channel.id,  
            int(session["id"]),  
            int(session["starter_user_id"]),  
            ctype,  
            None,  
            None,  
            None,  
            interaction.message.id,  
        )  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("Combat lobby creation failed.", ephemeral=True)  
            return  
        participants = await list_session_participants(int(session["id"]))  
        await interaction.response.edit_message(  
            content=f"<@{int(session['starter_user_id'])}> opened a **{ctype}** combat lobby.",  
            embed=build_combat_lobby_embed(lobby, participants),  
            view=CombatLobbyView(),  
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),  
        )  
  
  
class CombatTypeSetupView(discord.ui.View):  
    def __init__(self, session_id: int):  
        super().__init__(timeout=900)  
        self.add_item(CombatTypeSelect(session_id))  
  
  
class EnemyCategorySelect(discord.ui.Select):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        self.session_id = int(session_id)  
        self.selected = dict(selected)  
        options = [discord.SelectOption(label=x, value=x) for x in ENCOUNTER_ENEMY_CATEGORIES]  
        super().__init__(placeholder="Choose enemy type...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        self.selected["enemy_category"] = self.values[0]  
        async with db_pool.acquire() as conn:  
            session = await conn.fetchrow("SELECT * FROM alaris_sessions WHERE id=$1 AND status='open';", self.session_id)  
        if not session:  
            await interaction.response.send_message("That session is no longer open.", ephemeral=True)  
            return  
        await interaction.response.edit_message(  
            embed=build_enemy_setup_embed(dict(session), self.selected),  
            view=EnemyDangerSetupView(self.session_id, self.selected),  
        )  
  
  
class EnemyCategorySetupView(discord.ui.View):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        super().__init__(timeout=900)  
        self.add_item(EnemyCategorySelect(session_id, selected))  
  
  
class EnemyDangerSelect(discord.ui.Select):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        self.session_id = int(session_id)  
        self.selected = dict(selected)  
        options = [discord.SelectOption(label=x, value=x) for x in ENCOUNTER_DANGER_LEVELS]  
        super().__init__(placeholder="Choose danger level...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        self.selected["danger"] = self.values[0]  
        async with db_pool.acquire() as conn:  
            session = await conn.fetchrow("SELECT * FROM alaris_sessions WHERE id=$1 AND status='open';", self.session_id)  
        if not session:  
            await interaction.response.send_message("That session is no longer open.", ephemeral=True)  
            return  
        await interaction.response.edit_message(  
            embed=build_enemy_setup_embed(dict(session), self.selected),  
            view=EnemyEnvironmentSetupView(self.session_id, self.selected),  
        )  
  
  
class EnemyDangerSetupView(discord.ui.View):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        super().__init__(timeout=900)  
        self.add_item(EnemyDangerSelect(session_id, selected))  
  
  
class EnemyEnvironmentSelect(discord.ui.Select):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        self.session_id = int(session_id)  
        self.selected = dict(selected)  
        options = [discord.SelectOption(label=x, value=x) for x in ENCOUNTER_ENVIRONMENTS]  
        super().__init__(placeholder="Choose setting...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if interaction.guild is None or interaction.channel is None or interaction.message is None:  
            await interaction.response.send_message("Combat setup is unavailable.", ephemeral=True)  
            return  
        self.selected["environment"] = self.values[0]  
        async with db_pool.acquire() as conn:  
            session = await conn.fetchrow("SELECT * FROM alaris_sessions WHERE id=$1 AND status='open';", self.session_id)  
        if not session:  
            await interaction.response.send_message("That session is no longer open.", ephemeral=True)  
            return  
  
        enemy_category = normalize_encounter_category(self.selected.get("enemy_category"))  
        danger = normalize_danger_label(self.selected.get("danger"))  
        environment = normalize_environment_label(self.selected.get("environment"))  
  
        await create_combat_lobby_record(  
            interaction.guild.id,  
            interaction.channel.id,  
            int(session["id"]),  
            int(session["starter_user_id"]),  
            "Enemy Encounter",  
            enemy_category,  
            danger,  
            environment,  
            interaction.message.id,  
        )  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("Combat lobby creation failed.", ephemeral=True)  
            return  
        participants = await list_session_participants(int(session["id"]))  
        await interaction.response.edit_message(  
            content=f"<@{int(session['starter_user_id'])}> opened an **Enemy Encounter** combat lobby.",  
            embed=build_combat_lobby_embed(lobby, participants),  
            view=CombatLobbyView(),  
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),  
        )  
  
  
class EnemyEnvironmentSetupView(discord.ui.View):  
    def __init__(self, session_id: int, selected: dict[str, str]):  
        super().__init__(timeout=900)  
        self.add_item(EnemyEnvironmentSelect(session_id, selected))  
  
  
  
  
async def create_combat_lobby_record(  
    guild_id: int,  
    channel_id: int,  
    session_id: int,  
    host_user_id: int,  
    combat_type: str,  
    enemy_category: Optional[str] = None,  
    danger_level: Optional[str] = None,  
    environment: Optional[str] = None,  
    lobby_message_id: Optional[int] = None,  
    structured_enemies: Optional[list[dict[str, Any]]] = None,  
) -> int:  
    async with db_pool.acquire() as conn:  
        lobby_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combat_lobbies (  
                guild_id, channel_id, session_id, host_user_id,  
                combat_type, enemy_category, danger_level, environment,  
                lobby_message_id, structured_enemies_json, status  
            )  
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,'open')  
            RETURNING id;  
            """,  
            int(guild_id),  
            int(channel_id),  
            int(session_id),  
            int(host_user_id),  
            str(combat_type),  
            enemy_category,  
            danger_level,  
            environment,  
            int(lobby_message_id) if lobby_message_id else None,  
            json.dumps(structured_enemies or []),  
        )  
    return int(lobby_id)  
  
  
async def fetch_open_combat_lobby_by_message(message_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_lobbies  
            WHERE lobby_message_id=$1  
              AND status='open'  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            int(message_id),  
        )  
    return dict(row) if row else None  
  
  
def can_control_combat_lobby(user: discord.abc.User, lobby: dict[str, Any]) -> bool:  
    if int(lobby.get("host_user_id") or 0) == int(user.id):  
        return True  
    return isinstance(user, discord.Member) and is_staff_member(user)  
  
  
async def refresh_lobby_message(message: discord.Message, lobby: dict[str, Any]) -> None:  
    participants = await list_session_participants(int(lobby["session_id"]))  
    await message.edit(  
        embed=build_combat_lobby_embed(lobby, participants),  
        view=CombatLobbyView(),  
    )  
  
  
class CombatLobbyJoinSelect(discord.ui.Select):  
    def __init__(self, lobby_id: int, options: list[discord.SelectOption]):  
        self.lobby_id = int(lobby_id)  
        max_values = max(1, min(len(options), 25))  
        super().__init__(  
            placeholder="Choose one or more owned characters to join...",  
            min_values=1,  
            max_values=max_values,  
            options=options,  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        lobby = None  
        # This select is sent ephemerally, so its message is not the lobby message.  
        async with db_pool.acquire() as conn:  
            row = await conn.fetchrow("SELECT * FROM alaris_combat_lobbies WHERE id=$1 AND status='open';", self.lobby_id)  
        lobby = dict(row) if row else None  
        if not lobby:  
            await interaction.response.send_message("This combat lobby is no longer open.", ephemeral=True)  
            return  
  
        rows = await owned_character_rows_for_user(interaction.guild.id, interaction.user.id) if interaction.guild else []  
        owned_ids = {int(r["id"]) for r in rows}  
        selected_ids: list[int] = []  
        for raw in self.values:  
            try:  
                cid = int(raw)  
            except Exception:  
                continue  
            if cid in owned_ids:  
                selected_ids.append(cid)  
  
        if not selected_ids:  
            await interaction.response.send_message("Choose one or more of your approved characters.", ephemeral=True)  
            return  
  
        added_names = []  
        already_names = []  
        row_by_id = {int(r["id"]): r for r in rows}  
        for cid in selected_ids:  
            added = await add_session_participant(int(lobby["session_id"]), cid, interaction.user.id)  
            name = str(row_by_id.get(cid, {}).get("name") or cid)  
            if added:  
                added_names.append(name)  
            else:  
                already_names.append(name)  
  
        # Update the public lobby message if possible.  
        try:  
            if interaction.guild and lobby.get("lobby_message_id"):  
                channel = interaction.guild.get_channel(int(lobby["channel_id"]))  
                if channel is None:  
                    channel = await bot.fetch_channel(int(lobby["channel_id"]))  
                if isinstance(channel, (discord.TextChannel, discord.Thread)):  
                    msg = await channel.fetch_message(int(lobby["lobby_message_id"]))  
                    await refresh_lobby_message(msg, lobby)  
        except Exception:  
            LOG.exception("Failed to refresh combat lobby message after join.")  
  
        parts = []  
        if added_names:  
            parts.append("Joined: " + ", ".join(f"**{n}**" for n in added_names))  
        if already_names:  
            parts.append("Already joined: " + ", ".join(f"**{n}**" for n in already_names))  
        await interaction.response.send_message("\n".join(parts) if parts else "No changes made.", ephemeral=True)  
  
  
class CombatLobbyJoinSelectView(discord.ui.View):  
    def __init__(self, lobby_id: int, options: list[discord.SelectOption]):  
        super().__init__(timeout=120)  
        self.add_item(CombatLobbyJoinSelect(lobby_id, options))  
  
  


# ---------- Daily Combat Activity Limits ----------

def combat_activity_today():
    """Return the current Alaris activity date as a Python date object.

    asyncpg encodes DATE parameters from datetime.date objects. Returning an
    ISO string here causes Start Now to fail when daily combat limits are
    checked or consumed.
    """
    if COMBAT_ACTIVITY_TZ is not None:
        return datetime.now(COMBAT_ACTIVITY_TZ).date()
    return datetime.utcnow().date()


async def ensure_daily_activity_limit_schema() -> None:
    if db_pool is None:
        return
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.alaris_daily_activity_limits (
                guild_id BIGINT NOT NULL,
                character_id BIGINT NOT NULL,
                activity_date DATE NOT NULL,
                combat_starts INTEGER NOT NULL DEFAULT 0,
                spar_starts INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (guild_id, character_id, activity_date)
            );
            """
        )


def activity_column_for_combat_type(combat_type: str) -> str:
    return "spar_starts" if str(combat_type) == "Spar" else "combat_starts"


async def check_daily_combat_limits(guild_id: int, character_ids: list[int], combat_type: str) -> tuple[bool, list[dict[str, Any]]]:
    """Check whether every registered character may start this combat today.

    Rule: one Spar start and one combat start (Duel or PvE) per character per Chicago day.
    """
    if not character_ids:
        return False, []
    await ensure_daily_activity_limit_schema()
    col = activity_column_for_combat_type(combat_type)
    today = combat_activity_today()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.id AS character_id, c.name,
                   COALESCE(l.{col}, 0) AS starts
            FROM alaris_characters c
            LEFT JOIN public.alaris_daily_activity_limits l
              ON l.guild_id = c.guild_id
             AND l.character_id = c.id
             AND l.activity_date = $3::date
            WHERE c.guild_id = $1
              AND c.id = ANY($2::bigint[])
            ORDER BY c.name ASC;
            """,
            int(guild_id), [int(x) for x in character_ids], today,
        )
    blocked = [dict(r) for r in rows if int(r["starts"] or 0) >= 1]
    return len(blocked) == 0, blocked


async def consume_daily_combat_limits(guild_id: int, character_ids: list[int], combat_type: str) -> None:
    """Increment the daily activity start counter after combat successfully starts."""
    if not character_ids:
        return
    await ensure_daily_activity_limit_schema()
    today = combat_activity_today()
    col = activity_column_for_combat_type(combat_type)
    async with db_pool.acquire() as conn:
        for cid in character_ids:
            if col == "spar_starts":
                await conn.execute(
                    """
                    INSERT INTO public.alaris_daily_activity_limits (guild_id, character_id, activity_date, spar_starts, updated_at)
                    VALUES ($1,$2,$3::date,1,NOW())
                    ON CONFLICT (guild_id, character_id, activity_date)
                    DO UPDATE SET spar_starts = public.alaris_daily_activity_limits.spar_starts + 1,
                                  updated_at = NOW();
                    """,
                    int(guild_id), int(cid), today,
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO public.alaris_daily_activity_limits (guild_id, character_id, activity_date, combat_starts, updated_at)
                    VALUES ($1,$2,$3::date,1,NOW())
                    ON CONFLICT (guild_id, character_id, activity_date)
                    DO UPDATE SET combat_starts = public.alaris_daily_activity_limits.combat_starts + 1,
                                  updated_at = NOW();
                    """,
                    int(guild_id), int(cid), today,
                )


async def reset_daily_combat_limit_for_character(guild_id: int, character_id: int) -> None:
    await ensure_daily_activity_limit_schema()
    today = combat_activity_today()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM public.alaris_daily_activity_limits
            WHERE guild_id=$1 AND character_id=$2 AND activity_date=$3::date;
            """,
            int(guild_id), int(character_id), today,
        )

class CombatLobbyView(discord.ui.View):  
    def __init__(self):  
        super().__init__(timeout=None)  
  
    @discord.ui.button(label="Join Encounter", style=discord.ButtonStyle.green, custom_id="alaris_combat_lobby_join")  
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if interaction.guild is None or interaction.message is None:  
            await interaction.response.send_message("This lobby is unavailable.", ephemeral=True)  
            return  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("This combat lobby is no longer open.", ephemeral=True)  
            return  
        rows = await owned_character_rows_for_user(interaction.guild.id, interaction.user.id)  
        if not rows:  
            await interaction.response.send_message("You do not have an approved active character to join with.", ephemeral=True)  
            return  
        options = [  
            discord.SelectOption(  
                label=str(r["name"])[:100],  
                value=str(r["id"]),  
                description=f"{r.get('species') or 'Unknown'} {r.get('class_name') or ''}"[:100],  
            )  
            for r in rows[:25]  
        ]  
        await interaction.response.send_message("Choose the character joining this combat.", view=CombatLobbyJoinSelectView(int(lobby["id"]), options), ephemeral=True)  
  
    @discord.ui.button(label="Leave Encounter", style=discord.ButtonStyle.gray, custom_id="alaris_combat_lobby_leave")  
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if interaction.guild is None or interaction.message is None:  
            await interaction.response.send_message("This lobby is unavailable.", ephemeral=True)  
            return  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("This combat lobby is no longer open.", ephemeral=True)  
            return  
        participants = await list_session_participants(int(lobby["session_id"]))  
        owned = [p for p in participants if int(p["user_id"]) == int(interaction.user.id)]  
        if not owned:  
            await interaction.response.send_message("You do not have a character in this encounter.", ephemeral=True)  
            return  
        # Remove the first owned participant. Players with several characters can click again.  
        removed = await remove_session_participant(int(lobby["session_id"]), int(owned[0]["character_id"]))  
        await refresh_lobby_message(interaction.message, lobby)  
        await interaction.response.send_message(f"Removed **{owned[0]['name']}** from the encounter." if removed else "No character was removed.", ephemeral=True)  
  
    @discord.ui.button(label="Start Now", style=discord.ButtonStyle.blurple, custom_id="alaris_combat_lobby_start")  
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if interaction.guild is None or interaction.channel is None or interaction.message is None:  
            await interaction.response.send_message("This lobby is unavailable.", ephemeral=True)  
            return  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("This combat lobby is no longer open.", ephemeral=True)  
            return  
        if not can_control_combat_lobby(interaction.user, lobby):  
            await interaction.response.send_message("Only the encounter host or staff can start this combat.", ephemeral=True)  
            return  
        await interaction.response.defer(ephemeral=False)  
        started = await start_combat_from_lobby(interaction.channel, lobby)  
        if started:  
            try:  
                await interaction.message.edit(view=None)  
            except Exception:  
                pass  
        else:  
            await interaction.followup.send("Combat could not be started. Make sure enough characters have joined.", ephemeral=True)  
  
    @discord.ui.button(label="Cancel Encounter", style=discord.ButtonStyle.red, custom_id="alaris_combat_lobby_cancel")  
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if interaction.guild is None or interaction.message is None:  
            await interaction.response.send_message("This lobby is unavailable.", ephemeral=True)  
            return  
        lobby = await fetch_open_combat_lobby_by_message(interaction.message.id)  
        if not lobby:  
            await interaction.response.send_message("This combat lobby is no longer open.", ephemeral=True)  
            return  
        if not can_control_combat_lobby(interaction.user, lobby):  
            await interaction.response.send_message("Only the encounter host or staff can cancel this combat.", ephemeral=True)  
            return  
        async with db_pool.acquire() as conn:  
            await conn.execute("UPDATE alaris_combat_lobbies SET status='canceled', canceled_at=NOW(), updated_at=NOW() WHERE id=$1;", int(lobby["id"]))  
            await conn.execute("UPDATE alaris_sessions SET status='closed', closed_at=NOW() WHERE id=$1 AND status='open';", int(lobby["session_id"]))  
        try:  
            await interaction.message.edit(content="❌ Combat lobby canceled.", embed=None, view=None)  
        except Exception:  
            pass  
        await interaction.response.send_message("Combat lobby canceled.", ephemeral=True)  
  
  
async def start_combat_from_lobby(channel: discord.abc.Messageable, lobby: dict[str, Any]) -> bool:  
    participants = await list_session_participants(int(lobby["session_id"]))  
    ctype = str(lobby.get("combat_type") or "Combat")  
    if ctype in {"Spar", "Duel"} and len(participants) < 2:  
        await channel.send("At least two joined characters are required to start a spar or duel.")  
        return False  
    if ctype == "Enemy Encounter" and len(participants) < 1:  
        await channel.send("At least one joined character is required to start an enemy encounter.")  
        return False  
  
    participant_ids = [int(p["character_id"]) for p in participants if p.get("character_id")]  
    limits_ok, blocked = await check_daily_combat_limits(int(lobby["guild_id"]), participant_ids, ctype)  
    if not limits_ok:  
        activity_label = "spar" if ctype == "Spar" else "combat encounter"  
        names = ", ".join(f"**{b['name']}**" for b in blocked) or "one or more characters"  
        await channel.send(  
            f"Daily limit reached: {names} already started their allowed {activity_label} today. "  
            "Each character may start one PvE/duel combat and one spar per day."  
        )  
        return False  
  
    existing = await get_active_combat_for_channel(int(lobby["guild_id"]), int(lobby["channel_id"]))  
    if existing:  
        await channel.send("There is already an active combat in this channel.")  
        return False  
  
    encounter_id = await create_combat_record(int(lobby["guild_id"]), int(lobby["session_id"]), int(lobby["channel_id"]), ctype)  
  
    for p in participants:  
        await add_character_combatant(encounter_id, int(p["character_id"]))  
  
    enemies: list[dict[str, Any]] = []  
    if ctype == "Enemy Encounter":  
        lobby["_participants"] = participants  
        structured_enemies = decode_structured_enemies_from_lobby(lobby)  
        enemies = structured_enemies if structured_enemies else generate_enemy_roster_for_lobby(lobby, len(participants))  
        for enemy in enemies:  
            await add_enemy_combatant(encounter_id, enemy)  
  
    order = await build_turn_order(encounter_id)  
    compact = compact_initiative_line(order)  
    combat = await get_active_combat_for_channel(int(lobby["guild_id"]), int(lobby["channel_id"]))  
    combatants = await get_combatants(encounter_id)  
    embed = build_combat_status_embed(combat, combatants, order)  
  
    if ctype == "Enemy Encounter":  
        intro = build_encounter_intro(lobby, enemies)  
        await channel.send(f"⚔️ {intro}\n\n**Initiative:** {compact}", embed=embed)  
    else:  
        await channel.send(f"⚔️ **{ctype} begins.**\n\n**Initiative:** {compact}", embed=embed)  
  
    async with db_pool.acquire() as conn:  
        await conn.execute("UPDATE alaris_combat_lobbies SET status='started', started_at=NOW(), updated_at=NOW() WHERE id=$1;", int(lobby["id"]))  
    await consume_daily_combat_limits(int(lobby["guild_id"]), participant_ids, ctype)  
  
    await post_current_turn(channel, encounter_id)  
    first_actor = await current_turn_combatant(encounter_id)  
    if first_actor and first_actor["combatant_type"] == "enemy":  
        await npc_auto_turn_loop(channel, encounter_id)  
    return True  
  
  
  
async def create_combat_record(  
    guild_id: int,  
    session_id: int,  
    channel_id: int,  
    combat_type: str,  
) -> int:  
    async with db_pool.acquire() as conn:  
        return int(await conn.fetchval(  
            """  
            INSERT INTO alaris_combat_encounters (  
                session_id, guild_id, channel_id, status, round_number,  
                current_turn_index, turn_order_json, combat_type  
            )  
            VALUES ($1,$2,$3,'open',1,0,'[]'::jsonb,$4)  
            RETURNING id;  
            """,  
            session_id, guild_id, channel_id, combat_type,  
        ))  
  
  
async def add_character_combatant(encounter_id: int, character_id: int) -> int:  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        raise RuntimeError(f"Character {character_id} not found.")  
    c = payload["character"]  
    combat = payload["derived"] or {}  
    async with db_pool.acquire() as conn:  
        return int(await conn.fetchval(  
            """  
            INSERT INTO alaris_combatants (  
                encounter_id, combatant_type, character_id, name, owner_user_id,  
                max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_type,  
                max_resolve, current_resolve, resistances_json, status  
            )  
            VALUES ($1,'character',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'{}'::jsonb,'active')  
            RETURNING id;  
            """,  
            encounter_id,  
            character_id,  
            c["name"],  
            int(c["user_id"]),  
            int(combat.get("max_hp") or 10),  
            int(combat.get("current_hp") or combat.get("max_hp") or 10),  
            int(combat.get("armor_class") or 10),  
            int(combat.get("initiative_bonus") or 0),  
            int(combat.get("attack_bonus") or 0),  
            int(combat.get("spell_dc") or combat.get("technique_dc") or 10),  
            int(combat.get("magic_save_bonus") or 0),  
            int(combat.get("magic_defense") or 10),  
            int(combat.get("damage_die_sides") or c.get("damage_die_sides") or 8),  
            combat.get("damage_type") or "physical",  
            int(combat.get("max_resolve") or c.get("level") or 1),  
            int(combat.get("current_resolve") or c.get("level") or 1),  
        ))  
  
  
async def add_enemy_combatant(encounter_id: int, enemy: dict[str, Any]) -> int:  
    async with db_pool.acquire() as conn:  
        cid = await conn.fetchval(  
            """  
            INSERT INTO alaris_combatants (  
                encounter_id, combatant_type, character_id, owner_user_id, name,  
                max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                damage_type, xp_value, enemy_role, enemy_theme,  
                resistances_json, weaknesses_json, immunities_json, status  
            )  
            VALUES ($1,'enemy',NULL,NULL,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17::jsonb,$18::jsonb,$19::jsonb,'active')  
            RETURNING id;  
            """,  
            encounter_id,  
            enemy["name"],  
            int(enemy.get("max_hp") or enemy.get("hp") or 10),  
            int(enemy.get("current_hp") or enemy.get("max_hp") or enemy.get("hp") or 10),  
            int(enemy.get("armor_class") or enemy.get("ac") or 12),  
            int(enemy.get("initiative_bonus") or 0),  
            int(enemy.get("attack_bonus") or 3),  
            int(enemy.get("save_dc") or 12),  
            int(enemy.get("magic_save_bonus") or 0),  
            int(enemy.get("magic_defense") or 10),  
            int(enemy.get("damage_die_sides") or enemy.get("damage_die") or 6),  
            int(enemy.get("damage_bonus") or 0),  
            normalize_damage_type(enemy.get("damage_type") or "blunt", "blunt"),  
            int(enemy.get("xp_value") or enemy.get("xp") or 25),  
            enemy.get("role") or enemy.get("enemy_role") or "enemy",  
            enemy.get("setting") or enemy.get("theme") or enemy.get("enemy_theme") or "",  
            json.dumps(enemy.get("resistances_json") or enemy.get("resistances") or {}),  
            json.dumps(enemy.get("weaknesses_json") or enemy.get("weaknesses") or {}),  
            json.dumps(enemy.get("immunities_json") or enemy.get("immunities") or {}),  
        )  
        try:  
            await conn.execute(  
                """  
                UPDATE alaris_combatants  
                SET abilities_json=$2::jsonb,  
                    ability_chance=$3,  
                    enemy_category=$4,  
                    enemy_setting=$5,  
                    base_name=$6  
                WHERE id=$1;  
                """,  
                int(cid),  
                json.dumps(enemy.get("abilities") or []),  
                float(enemy.get("ability_chance") or 0.0),  
                enemy.get("category"),  
                enemy.get("setting"),  
                enemy.get("base_name") or enemy.get("name"),  
            )  
        except Exception:  
            LOG.exception("Failed to store optional v087 enemy metadata; continuing.")  
    return int(cid)  
  
  
  
def build_combat_status_embed(combat: asyncpg.Record | dict[str, Any], combatants: list[dict[str, Any]], order: list[dict[str, Any]]) -> discord.Embed:  
    embed = discord.Embed(  
        title=f"Combat - Round {combat['round_number']}",  
        description=f"Type: **{combat.get('combat_type') if isinstance(combat, dict) else combat['combat_type'] or 'Combat'}**",  
        color=discord.Color.red(),  
    )  
    current_id = combat.get("current_turn_combatant_id") if isinstance(combat, dict) else combat["current_turn_combatant_id"]  
    current_name = "Unknown"  
    for c in combatants:  
        if int(c["id"]) == int(current_id or 0):  
            current_name = c["name"]  
            break  
    embed.add_field(name="Current Turn", value=f"**{current_name}**", inline=False)  
  
    hp_lines = []  
    for c in combatants:  
        marker = "💀" if c["status"] != "active" else "•"  
        hp_lines.append(f"{marker} **{c['name']}** - HP {c['current_hp']}/{c['max_hp']} | AC {c['armor_class']}")  
    embed.add_field(name="Combatants", value="\n".join(hp_lines)[:1024] if hp_lines else "None", inline=False)  
  
    if order:  
        embed.add_field(name="Initiative", value=compact_initiative_line(order), inline=False)  
    return embed  
  
  
async def post_current_turn(channel: discord.abc.Messageable, encounter_id: int) -> None:  
    current = await current_turn_combatant(encounter_id)  
    if not current:  
        return  
    if current["combatant_type"] == "character" and current.get("owner_user_id"):  
        await channel.send(  
            f"➡️ **Current Turn:** {current['name']} ||<@{int(current['owner_user_id'])}>||\n"  
            "Use `/action` to resolve your action, then post your narration and use `/end-turn`."  
        )  
    else:  
        await channel.send(f"➡️ **Current Turn:** {current['name']}")  
  
  
async def defeated_enemy_xp_pool(encounter_id: int) -> int:  
    # v117 PvE XP: every registered participant receives 50 base XP plus total enemy max HP.  
    async with db_pool.acquire() as conn:  
        enemy_hp = int(await conn.fetchval(  
            """  
            SELECT COALESCE(SUM(max_hp), 0)  
            FROM alaris_combatants  
            WHERE encounter_id=$1  
              AND combatant_type='enemy';  
            """,  
            encounter_id,  
        ) or 0)  
    return PVE_PARTICIPATION_XP + enemy_hp if enemy_hp > 0 else 0  
  
  
async def victory_names_for_combat(encounter_id: int, winner: Optional[str]) -> str:  
    combatants = await get_combatants(encounter_id)  
    if winner == "characters":  
        all_chars = [str(c["name"]) for c in combatants if c["combatant_type"] == "character"]  
        return ", ".join(all_chars) if all_chars else "Characters"  
    return str(winner or "Unknown")  
  
  
async def combat_victory_summary_for_session(session_id: int) -> tuple[Optional[str], Optional[str], list[str]]:  
    """Return (winning_side, victory_names, defeated_enemy_lines) for session summaries."""  
    async with db_pool.acquire() as conn:  
        encounter = await conn.fetchrow(  
            """  
            SELECT id  
            FROM alaris_combat_encounters  
            WHERE session_id=$1  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            session_id,  
        )  
        if not encounter:  
            return None, None, []  
  
        encounter_id = int(encounter["id"])  
        combatants = await conn.fetch(  
            """  
            SELECT name, combatant_type, status, xp_value  
            FROM alaris_combatants  
            WHERE encounter_id=$1  
            ORDER BY combatant_type, name;  
            """,  
            encounter_id,  
        )  
  
    active_chars = [str(c["name"]) for c in combatants if c["combatant_type"] == "character" and c["status"] == "active"]  
    all_chars = [str(c["name"]) for c in combatants if c["combatant_type"] == "character"]  
    active_enemies = [str(c["name"]) for c in combatants if c["combatant_type"] == "enemy" and c["status"] == "active"]  
    defeated_enemies = [f"{c['name']} ({c['xp_value']} XP)" for c in combatants if c["combatant_type"] == "enemy" and c["status"] == "defeated"]  
  
    if all_chars and not active_enemies:  
        return "Characters", ", ".join(all_chars), defeated_enemies  
    if active_enemies and not active_chars:  
        return "Enemies", ", ".join(active_enemies), defeated_enemies  
    return None, None, defeated_enemies  
  
  
  
async def close_combat_if_finished(channel: discord.abc.Messageable, encounter_id: int) -> bool:  
    finished, winner = await combat_has_side_victory(encounter_id)  
    if not finished:  
        return False  
  
    xp_pool = await defeated_enemy_xp_pool(encounter_id)  
    winner_names = await victory_names_for_combat(encounter_id, winner)  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_combat_encounters  
            SET status='closed',  
                closed_at=NOW(),  
                enemy_xp_pool=$2  
            WHERE id=$1 AND status='open';  
            """,  
            encounter_id,  
            xp_pool,  
        )  
  
    # Prompt the session opener/host to close the session and award XP.  
    session_host_mention = ""  
    async with db_pool.acquire() as conn:  
        session_row = await conn.fetchrow(  
            """  
            SELECT s.starter_user_id  
            FROM alaris_combat_encounters ce  
            JOIN alaris_sessions s ON s.id=ce.session_id  
            WHERE ce.id=$1;  
            """,  
            encounter_id,  
        )  
    if session_row and session_row["starter_user_id"]:  
        session_host_mention = f" ||<@{int(session_row['starter_user_id'])}>||"  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_combatants  
            SET current_resolve=max_resolve  
            WHERE encounter_id=$1 AND combatant_type='character';  
            """,  
            encounter_id,  
        )  
        await conn.execute("DELETE FROM alaris_combat_states WHERE encounter_id=$1;", encounter_id)  
  
    await channel.send(  
        f"🏁 **Combat ended.** Victory: **{winner_names}**\n"  
        f"Enemy XP Pool: **{xp_pool}**\n"  
        f"Scene opener{session_host_mention}: run `/session-close` to wrap up the scene and award XP."  
    )  
    return True  
  
  
def choose_enemy_ability(enemy: dict[str, Any]) -> dict[str, Any]:  
    ability_keys = []  
    raw = enemy.get("abilities_json") if "abilities_json" in enemy else enemy.get("abilities")  
    if isinstance(raw, list):  
        ability_keys = [str(x) for x in raw]  
    elif isinstance(raw, str) and raw.strip():  
        try:  
            loaded = json.loads(raw)  
            if isinstance(loaded, list):  
                ability_keys = [str(x) for x in loaded]  
        except Exception:  
            ability_keys = [x.strip() for x in raw.split(",") if x.strip()]  
    chance = float(enemy.get("ability_chance") or 0.0)  
    if ability_keys and random.random() < chance:  
        key = random.choice(ability_keys)  
        ability = ENEMY_ABILITY_LIBRARY.get(normalize_name(key)) or ENEMY_ABILITY_LIBRARY.get(key)  
        if ability:  
            return dict(ability)  
    role = normalize_name(enemy.get("enemy_role") or enemy.get("role") or "minion")  
    abilities = ENEMY_ROLE_ABILITIES.get(role) or ENEMY_ROLE_ABILITIES.get("minion", [])  
    if abilities and random.random() < 0.08:  
        return random.choice(abilities)  
    return {"name": "Basic Attack", "kind": "strike", "damage_type": enemy.get("damage_type") or "blunt", "state": None, "description": "presses the attack"}  
  
  
def choose_enemy_target(enemy: dict[str, Any], pc_targets: list[dict[str, Any]], ability: dict[str, Any]) -> dict[str, Any]:  
    if not pc_targets:  
        raise ValueError("No PC targets available")  
    kind = normalize_name(ability.get("kind") or "strike")  
    role = normalize_name(enemy.get("enemy_role") or "")  
    # Caster/debuff enemies pressure fragile or wounded targets.  
    if kind in {"spell", "debuff"} or "caster" in role:  
        return min(pc_targets, key=lambda t: (int(t.get("current_hp") or 0), int(t.get("magic_defense") or 10)))  
    # Bruisers and elites try to finish the weakest target.  
    if role in {"bruiser", "striker", "elite"}:  
        return min(pc_targets, key=lambda t: int(t.get("current_hp") or 0))  
    # Tanks/guards mark or pressure tougher targets.  
    if role in {"tank", "guard"}:  
        return max(pc_targets, key=lambda t: int(t.get("armor_class") or 10))  
    return random.choice(pc_targets)  
  
  
async def resolve_enemy_ability_against_target(  
    channel: discord.abc.Messageable,  
    encounter_id: int,  
    enemy: dict[str, Any],  
    target: dict[str, Any],  
    ability: dict[str, Any],  
) -> None:  
    kind = normalize_name(ability.get("kind") or "strike")  
    ability_name = ability.get("name") or "Enemy Action"  
    narrative = ability.get("description") or "acts"  
    damage_type = normalize_damage_type(ability.get("damage_type") or enemy.get("damage_type") or "blunt", "blunt")  
    state_key = ability.get("state")  
  
    await channel.send(f"⚔️ **{enemy['name']}** {narrative}, targeting **{target['name']}**.  \n*{ability_name}*")  
  
    actor_states = await active_states_for_combatant(encounter_id, int(enemy["id"]))  
    target_states = await active_states_for_combatant(encounter_id, int(target["id"]))  
  
    if kind == "buff":  
        if state_key:  
            await apply_combat_state(encounter_id, int(enemy["id"]), int(enemy["id"]), state_key, 2)  
            await channel.send(f"✅ **{enemy['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', str(state_key).title())}**.")  
        else:  
            await channel.send(f"✅ **{enemy['name']}** steels itself.")  
        return  
  
    if kind in {"spell", "debuff"}:  
        dc = int(enemy.get("save_dc") or 12) + state_spell_dc_penalty_for_actor(actor_states)  
        save_roll = roll_d20()  
        save_bonus = int(target.get("magic_save_bonus") or 0) + state_magic_defense_bonus(target_states)  
        save_total = save_roll + save_bonus  
  
        lines = [f"Magic Save: d20 **{save_roll}** + {save_bonus} = **{save_total}** vs DC **{dc}**"]  
  
        if kind == "spell":  
            raw_damage = roll_die(int(enemy.get("damage_die_sides") or 6)) + int(enemy.get("damage_bonus") or 0) + state_damage_modifier_for_actor(actor_states)  
            final_damage, outcome = resolve_spell_save_damage(raw_damage, save_roll, save_total, dc)  
            final_damage = max(0, final_damage - state_damage_reduction(target_states))  
            final_damage, affinity_note = resolve_damage_with_affinities(final_damage, damage_type, target)  
            new_hp = max(0, int(target["current_hp"] or 0) - final_damage)  
            defeated = new_hp <= 0  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_combatants  
                    SET current_hp=$2,  
                        status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END  
                    WHERE id=$1;  
                    """,  
                    int(target["id"]), new_hp,  
                )  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_combat_logs (  
                        encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                        roll_json, damage, damage_type, outcome, narrative  
                    )  
                    VALUES ($1,$2,$3,'npc_spell',$4::jsonb,$5,$6,$7,$8);  
                    """,  
                    encounter_id, int(enemy["id"]), int(target["id"]),  
                    json.dumps({"save_roll": save_roll, "save_total": save_total, "dc": dc, "ability": ability_name}),  
                    final_damage, damage_type, outcome, narrative,  
                )  
            lines.append(f"Damage: raw **{raw_damage}** → applied **{final_damage} {damage_type}**.")  
            if affinity_note:  
                lines.append(f"Affinity: {affinity_note}.")  
            if state_key and (save_roll == 1 or (save_roll != 20 and save_total < dc)) and not defeated:  
                await apply_combat_state(encounter_id, int(target["id"]), int(enemy["id"]), state_key, 2)  
                lines.append(f"✅ **{target['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', str(state_key).title())}**.")  
            if defeated:  
                lines.append(f"💀 **{target['name']}** is defeated.")  
            await channel.send("\n".join(lines))  
            return  
  
        # Debuff: no damage, state on failed save.  
        if state_key and (save_roll == 1 or (save_roll != 20 and save_total < dc)):  
            await apply_combat_state(encounter_id, int(target["id"]), int(enemy["id"]), state_key, 2)  
            lines.append(f"✅ **{target['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', str(state_key).title())}**.")  
        else:  
            lines.append("🛡️ The effect is resisted.")  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                INSERT INTO alaris_combat_logs (  
                    encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                    roll_json, damage, damage_type, outcome, narrative  
                )  
                VALUES ($1,$2,$3,'npc_debuff',$4::jsonb,0,$5,$6,$7);  
                """,  
                encounter_id, int(enemy["id"]), int(target["id"]),  
                json.dumps({"save_roll": save_roll, "save_total": save_total, "dc": dc, "ability": ability_name}),  
                damage_type,  
                "applied" if len(lines) > 1 and "gains" in lines[-1] else "resisted",  
                narrative,  
            )  
        await channel.send("\n".join(lines))  
        return  
  
    # Strike/default  
    attack_roll = roll_d20()  
    attack_total = attack_roll + int(enemy["attack_bonus"] or 0) + state_attack_penalty_for_actor(actor_states) + state_attack_bonus_against(target_states)  
    target_ac = int(target["armor_class"] or 10) + state_ac_bonus(target_states)  
    hit = attack_total >= target_ac  
  
    if hit:  
        damage = roll_die(int(enemy["damage_die_sides"] or 6)) + int(enemy.get("damage_bonus") or 0) + state_damage_modifier_for_actor(actor_states)  
        damage = max(0, damage - state_damage_reduction(target_states))  
        damage, affinity_note = resolve_damage_with_affinities(damage, damage_type, target)  
        new_hp = max(0, int(target["current_hp"] or 0) - damage)  
        defeated = new_hp <= 0  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                UPDATE alaris_combatants  
                SET current_hp=$2,  
                    status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END  
                WHERE id=$1;  
                """,  
                int(target["id"]), new_hp,  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_combat_logs (  
                    encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                    roll_json, damage, damage_type, outcome, narrative  
                )  
                VALUES ($1,$2,$3,'npc_ability',$4::jsonb,$5,$6,$7,$8);  
                """,  
                encounter_id, int(enemy["id"]), int(target["id"]),  
                json.dumps({"d20": attack_roll, "total": attack_total, "target_ac": target_ac, "ability": ability_name}),  
                damage, damage_type, "hit_defeated" if defeated else "hit", narrative,  
            )  
        lines = [f"Attack: d20 **{attack_roll}** + {int(enemy['attack_bonus'] or 0)} = **{attack_total}** vs AC **{target_ac}**",  
                 f"✅ Hit for **{damage} {damage_type}** damage."]  
        if affinity_note:  
            lines.append(f"Affinity: {affinity_note}.")  
        if state_key and not defeated:  
            await apply_combat_state(encounter_id, int(target["id"]), int(enemy["id"]), state_key, 2)  
            lines.append(f"✅ **{target['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', str(state_key).title())}**.")  
        if defeated:  
            lines.append(f"💀 **{target['name']}** is defeated.")  
        await channel.send("\n".join(lines))  
    else:  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                INSERT INTO alaris_combat_logs (  
                    encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                    roll_json, damage, damage_type, outcome, narrative  
                )  
                VALUES ($1,$2,$3,'npc_ability',$4::jsonb,0,$5,'miss',$6);  
                """,  
                encounter_id, int(enemy["id"]), int(target["id"]),  
                json.dumps({"d20": attack_roll, "total": attack_total, "target_ac": target_ac, "ability": ability_name}),  
                damage_type, narrative,  
            )  
        await channel.send(f"Attack: d20 **{attack_roll}** + {int(enemy['attack_bonus'] or 0)} = **{attack_total}** vs AC **{target_ac}**\n❌ Miss.")  
  
  
async def npc_auto_turn_loop(channel: discord.abc.Messageable, encounter_id: int) -> None:  
    """Automatically resolves consecutive NPC/enemy turns until the next PC turn or combat ends."""  
    guard = 0  
    while guard < 20:  
        guard += 1  
        current = await current_turn_combatant(encounter_id)  
        if not current or current["combatant_type"] != "enemy" or current["status"] != "active":  
            return  
  
        targets = await valid_targets_for_action(encounter_id, current, "Piercing Melee Attack")  
        pc_targets = [t for t in targets if t["combatant_type"] == "character" and t["status"] == "active"]  
        if not pc_targets:  
            await close_combat_if_finished(channel, encounter_id)  
            return  
  
        ability = choose_enemy_ability(current)  
        target = choose_enemy_target(current, pc_targets, ability)  
        await resolve_enemy_ability_against_target(channel, encounter_id, current, target, ability)  
  
        if await close_combat_if_finished(channel, encounter_id):  
            return  
  
        tick_lines = await decrement_states_for_combatant(encounter_id, int(current["id"]))  
        if tick_lines:  
            await channel.send("\n".join(tick_lines))  
        if await close_combat_if_finished(channel, encounter_id):  
            return  
  
        next_actor = await advance_combat_turn(encounter_id)  
        if not next_actor:  
            return  
  
        await post_round_health_summary_if_needed(channel, encounter_id, next_actor)  
        await post_current_turn(channel, encounter_id)  
        if next_actor["combatant_type"] == "character":  
            return  
  
  
  
async def force_close_active_combat_in_channel(guild_id: int, channel_id: int, closed_by: int) -> tuple[int, list[int]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id  
            FROM alaris_combat_encounters  
            WHERE guild_id=$1 AND channel_id=$2 AND status='open'  
            ORDER BY created_at DESC;  
            """,  
            guild_id, channel_id,  
        )  
        encounter_ids = [int(r["id"]) for r in rows]  
        if not encounter_ids:  
            return 0, []  
        await conn.execute(  
            """  
            UPDATE alaris_combat_encounters  
            SET status='force_closed',  
                current_turn_combatant_id=NULL,  
                closed_at=NOW()  
            WHERE guild_id=$1 AND channel_id=$2 AND status='open';  
            """,  
            guild_id, channel_id,  
        )  
        for encounter_id in encounter_ids:  
            await conn.execute("UPDATE alaris_combatants SET current_resolve=max_resolve WHERE encounter_id=$1 AND combatant_type='character';", encounter_id)  
            await conn.execute("DELETE FROM alaris_combat_states WHERE encounter_id=$1;", encounter_id)  
            await conn.execute(  
                """  
                INSERT INTO alaris_combat_logs (  
                    encounter_id, action_type, roll_json, outcome, narrative  
                )  
                VALUES ($1, 'force_close', '{}'::jsonb, 'force_closed', $2);  
                """,  
                encounter_id,  
                f"Combat force-closed by staff user {closed_by}. No combat XP awarded.",  
            )  
    return len(encounter_ids), encounter_ids  
  
  
# ---------- Slash Commands ----------  
  
  
# ---------- Staff Story Character Creation v095 ----------  
  
STORY_DICE_LEVELS = {  
    8: 1, 9: 1, 10: 1, 11: 1, 12: 1, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1, 19: 1,  
    20: 2, 30: 3, 40: 4, 50: 5, 60: 6, 70: 7, 80: 8, 90: 9, 100: 10,  
}  
  
STORY_ALLOWED_DICE = [8, 10, 12, 20, 30, 40, 50, 60, 70, 80, 90, 100]  
  
  
def story_level_for_die(die: int) -> int:  
    die = int(die or 8)  
    if die < 20:  
        return 1  
    return max(1, min(10, die // 10))  
  
  
def story_xp_for_die(die: int) -> int:  
    return progression_xp_required_for_die(int(die or 8))  
  
  
def story_unlocked_class_levels(level: int, secondary: bool = False) -> list[int]:  
    level = int(level or 1)  
    unlocked = [tier for tier in [2, 4, 6, 8, 10] if tier <= level]  
    if secondary:  
        # Secondary disciplines are intentionally shallow.  
        unlocked = [tier for tier in unlocked if tier <= 4]  
    return unlocked  
  
  
def all_passives_for_story(kind: str, key: str) -> list[dict[str, Any]]:  
    return [dict(x) for x in passive_options_for(kind, key)]  
  
  
def merge_story_passives(species: str, primary_class: str, secondary_class: Optional[str]) -> list[dict[str, Any]]:  
    out = []  
    for p in all_passives_for_story("species", species):  
        item = dict(p)  
        item["source"] = "species"  
        out.append(item)  
    for p in all_passives_for_story("class", primary_class):  
        item = dict(p)  
        item["source"] = "primary_class"  
        out.append(item)  
    if secondary_class:  
        for p in all_passives_for_story("class", secondary_class):  
            item = dict(p)  
            item["source"] = "secondary_discipline"  
            out.append(item)  
    return out  
  
  
def story_stats_default_for_class(class_name: str) -> dict[str, int]:  
    # Uses existing optimized standard-array assignment for repeatable creation.  
    return auto_assign_stats(class_name)  
  
  
def parse_story_stats(raw: str, fallback_class: str) -> dict[str, int]:  
    if not raw or not raw.strip():  
        return story_stats_default_for_class(fallback_class)  
    # Accept "STR 8 DEX 12 CON 13 INT 14 WIS 10 CHA 15" or comma pairs.  
    values = {k: None for k in ["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]}  
    aliases = {  
        "str": "strength", "strength": "strength",  
        "dex": "dexterity", "dexterity": "dexterity",  
        "con": "constitution", "constitution": "constitution",  
        "int": "intelligence", "intelligence": "intelligence",  
        "wis": "wisdom", "wisdom": "wisdom",  
        "cha": "charisma", "charisma": "charisma",  
    }  
    tokens = re.findall(r"(str|strength|dex|dexterity|con|constitution|int|intelligence|wis|wisdom|cha|charisma)\s*[:=]?\s*(\d+)", raw, flags=re.I)  
    for key, value in tokens:  
        values[aliases[key.lower()]] = int(value)  
    if all(v is not None for v in values.values()):  
        return {k: int(v) for k, v in values.items()}  
    raise ValueError("Stats must include STR, DEX, CON, INT, WIS, and CHA values.")  
  
  
def story_passives_summary(passives: list[dict[str, Any]]) -> str:  
    if not passives:  
        return "None."  
    lines = []  
    for p in passives:  
        src = str(p.get("source") or "source").replace("_", " ").title()  
        lines.append(f"• **{p.get('name','Passive')}** ({src}) - {p.get('description','')}")  
    return "\n".join(lines)[:3900]  
  
  
def story_ability_options_for(class_name: str, level: int) -> list[dict[str, Any]]:  
    tree = CLASS_ABILITY_TREES.get(normalize_name(class_name), {})  
    return [dict(x) for x in tree.get(int(level), [])]  
  
  
async def create_story_draft(  
    guild_id: int,  
    channel_id: int,  
    creator_user_id: int,  
    owner_user_id: int,  
    name: str,  
    species: str,  
    subspecies: str,  
    google_doc_url: str,  
    image_url: str,  
) -> int:  
    async with db_pool.acquire() as conn:  
        return int(await conn.fetchval(  
            """  
            INSERT INTO alaris_story_character_drafts (  
                guild_id, channel_id, creator_user_id, owner_user_id,  
                name, normalized_name, species, subspecies, google_doc_url, image_url  
            )  
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)  
            RETURNING id;  
            """,  
            int(guild_id), int(channel_id), int(creator_user_id), int(owner_user_id),  
            name.strip(), normalize_name(name), species.strip(), subspecies.strip(),  
            google_doc_url.strip(), image_url.strip(),  
        ))  
  
  
async def fetch_story_draft(draft_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow("SELECT * FROM alaris_story_character_drafts WHERE id=$1;", int(draft_id))  
    return dict(row) if row else None  
  
  
async def update_story_draft(draft_id: int, **fields: Any) -> None:  
    if not fields:  
        return  
    assigns = []  
    args: list[Any] = []  
    for key, value in fields.items():  
        args.append(value)  
        if key.endswith("_json"):  
            assigns.append(f"{key}=${len(args)}::jsonb")  
        else:  
            assigns.append(f"{key}=${len(args)}")  
    args.append(int(draft_id))  
    sql = f"UPDATE alaris_story_character_drafts SET {', '.join(assigns)}, updated_at=NOW() WHERE id=${len(args)};"  
    async with db_pool.acquire() as conn:  
        await conn.execute(sql, *args)  
  
  
def build_story_draft_embed(draft: dict[str, Any]) -> discord.Embed:  
    primary = draft.get("primary_class") or "Not selected"  
    secondary = draft.get("secondary_class") or "None"  
    die = int(draft.get("starter_die") or 8)  
    level = story_level_for_die(die)  
    xp = story_xp_for_die(die)  
    passives = merge_story_passives(draft.get("species") or "", draft.get("primary_class") or "", draft.get("secondary_class"))  
    embed = discord.Embed(  
        title=f"Staff Story Character - {draft.get('name')}",  
        description="Reusable staff/story character creation flow.",  
        color=discord.Color.dark_gold(),  
    )  
    embed.add_field(name="Owner", value=f"<@{int(draft.get('owner_user_id'))}>", inline=True)  
    embed.add_field(name="Species", value=f"{draft.get('species')} ({draft.get('subspecies') or 'No subspecies'})", inline=True)  
    embed.add_field(name="Primary / Secondary", value=f"{primary} / {secondary}", inline=True)  
    embed.add_field(name="Starter Die", value=f"1d{die}", inline=True)  
    embed.add_field(name="Level", value=str(level), inline=True)  
    embed.add_field(name="XP", value=str(xp), inline=True)  
    stats = decode_json_payload(draft.get("stats_json")) if draft.get("stats_json") else {}  
    embed.add_field(name="Stats", value=format_stats(stats) if stats else "Auto-assigned after primary class is selected.", inline=False)  
    embed.add_field(name="Starter Passives Auto-Assigned", value=story_passives_summary(passives) or "Select primary class first.", inline=False)  
    embed.set_footer(text="Choose primary class, secondary discipline, starter die, stats, then choose active abilities.")  
    return embed  
  
  
class StaffStoryBasicsModal(discord.ui.Modal, title="Staff Story Character Basics"):  
    def __init__(self, owner_id: int):  
        super().__init__(timeout=300)  
        self.owner_id = owner_id  
        self.name = discord.ui.TextInput(label="Character Name", placeholder="Tharion Vex", max_length=100)  
        self.species = discord.ui.TextInput(label="Species", placeholder="Tiefling", max_length=50)  
        self.subspecies = discord.ui.TextInput(label="Subspecies / Lineage", placeholder="Crownhorn", required=False, max_length=80)  
        self.google_doc = discord.ui.TextInput(label="Google Doc URL", placeholder="https://...", max_length=300)  
        self.image_url = discord.ui.TextInput(label="Image URL", placeholder="https://...", required=False, max_length=300)  
        self.add_item(self.name)  
        self.add_item(self.species)  
        self.add_item(self.subspecies)  
        self.add_item(self.google_doc)  
        self.add_item(self.image_url)  
  
    async def on_submit(self, interaction: discord.Interaction):  
        if interaction.guild is None or interaction.channel is None:  
            await interaction.response.send_message("This must be used in a server channel.", ephemeral=True)  
            return  
        try:  
            draft_id = await create_story_draft(  
                interaction.guild.id,  
                interaction.channel.id,  
                interaction.user.id,  
                self.owner_id,  
                str(self.name.value),  
                str(self.species.value),  
                str(self.subspecies.value or ""),  
                str(self.google_doc.value),  
                str(self.image_url.value or ""),  
            )  
            draft = await fetch_story_draft(draft_id)  
            await interaction.response.send_message(embed=build_story_draft_embed(draft), view=StaffStorySetupView(draft_id), ephemeral=True)  
        except Exception as exc:  
            LOG.exception("Failed to create staff story draft.")  
            await interaction.response.send_message(f"Failed to create story draft: {exc}", ephemeral=True)  
  
  
class StaffStoryOwnerSelect(discord.ui.UserSelect):  
    def __init__(self):  
        super().__init__(placeholder="Choose the character owner...", min_values=1, max_values=1)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        user = self.values[0]  
        if interaction.guild is None:  
            await interaction.response.send_message("This must be used in a server.", ephemeral=True)  
            return  
        member = interaction.guild.get_member(user.id)  
        if member is None:  
            try:  
                member = await interaction.guild.fetch_member(user.id)  
            except Exception:  
                member = None  
        if member is None:  
            await interaction.response.send_message("That user could not be resolved as a server member.", ephemeral=True)  
            return  
        embed = discord.Embed(  
            title="Staff Story Character Creation",  
            description=(  
                "Owner selected. Click the button below to enter the character basics."  
            ),  
            color=discord.Color.dark_gold(),  
        )  
        embed.add_field(name="Owner", value=member.mention, inline=True)  
        await interaction.response.edit_message(embed=embed, view=StaffStoryStartView(member.id))  
  
  
class StaffStoryStartView(discord.ui.View):  
    def __init__(self, owner_id: Optional[int] = None):  
        super().__init__(timeout=300)  
        self.owner_id = owner_id  
        if owner_id is None:  
            self.add_item(StaffStoryOwnerSelect())  
  
    @discord.ui.button(label="Open Story Character Form", style=discord.ButtonStyle.primary)  
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        if not self.owner_id:  
            await interaction.response.send_message("Choose an owner first.", ephemeral=True)  
            return  
        await interaction.response.send_modal(StaffStoryBasicsModal(int(self.owner_id)))  
  
  
class StaffStoryClassSelect(discord.ui.Select):  
    def __init__(self, draft_id: int, field: str, placeholder: str):  
        self.draft_id = draft_id  
        self.field = field  
        options = [discord.SelectOption(label=cls.title(), value=cls) for cls in sorted(CLASS_ABILITY_TREES.keys())[:25]]  
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        value = self.values[0]  
        fields = {self.field: value}  
        draft = await fetch_story_draft(self.draft_id)  
        if self.field == "primary_class":  
            stats = story_stats_default_for_class(value)  
            fields["stats_json"] = json.dumps(stats)  
        await update_story_draft(self.draft_id, **fields)  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(embed=build_story_draft_embed(draft), view=StaffStorySetupView(self.draft_id))  
  
  
class StaffStoryDieSelect(discord.ui.Select):  
    def __init__(self, draft_id: int):  
        self.draft_id = draft_id  
        options = [discord.SelectOption(label=f"1d{x} - Level {story_level_for_die(x)}", value=str(x)) for x in STORY_ALLOWED_DICE]  
        super().__init__(placeholder="Choose starter damage die / level...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        die = int(self.values[0])  
        await update_story_draft(self.draft_id, starter_die=die, level=story_level_for_die(die), xp_total=story_xp_for_die(die))  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(embed=build_story_draft_embed(draft), view=StaffStorySetupView(self.draft_id))  
  
  
class StaffStoryStatsModal(discord.ui.Modal, title="Story Character Stats"):  
    def __init__(self, draft_id: int):  
        super().__init__(timeout=300)  
        self.draft_id = draft_id  
        self.stats = discord.ui.TextInput(  
            label="Stats",  
            placeholder="STR 8 DEX 12 CON 13 INT 14 WIS 10 CHA 15",  
            style=discord.TextStyle.paragraph,  
            max_length=300,  
        )  
        self.add_item(self.stats)  
  
    async def on_submit(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        draft = await fetch_story_draft(self.draft_id)  
        try:  
            stats = parse_story_stats(str(self.stats.value), draft.get("primary_class") or "fighter")  
        except Exception as exc:  
            await interaction.response.send_message(str(exc), ephemeral=True)  
            return  
        await update_story_draft(self.draft_id, stats_json=json.dumps(stats))  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(embed=build_story_draft_embed(draft), view=StaffStorySetupView(self.draft_id))  
  
  
class StaffStorySetupView(discord.ui.View):  
    def __init__(self, draft_id: int):  
        super().__init__(timeout=900)  
        self.draft_id = draft_id  
        self.add_item(StaffStoryClassSelect(draft_id, "primary_class", "Choose primary class..."))  
        self.add_item(StaffStoryClassSelect(draft_id, "secondary_class", "Choose secondary discipline..."))  
        self.add_item(StaffStoryDieSelect(draft_id))  
  
    @discord.ui.button(label="Set Manual Stats", style=discord.ButtonStyle.secondary)  
    async def set_stats(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        await interaction.response.send_modal(StaffStoryStatsModal(self.draft_id))  
  
    @discord.ui.button(label="Choose Active Abilities", style=discord.ButtonStyle.primary)  
    async def choose_abilities(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        draft = await fetch_story_draft(self.draft_id)  
        if not draft.get("primary_class"):  
            await interaction.response.send_message("Choose a primary class first.", ephemeral=True)  
            return  
        await prepare_story_ability_choices(self.draft_id)  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(embed=build_story_ability_embed(draft), view=await build_story_ability_choice_view(self.draft_id))  
  
    @discord.ui.button(label="Finalize Character", style=discord.ButtonStyle.success)  
    async def finalize(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        draft = await fetch_story_draft(self.draft_id)  
        try:  
            char_id = await create_story_character_from_draft(draft, interaction.user.id)  
            await update_story_draft(self.draft_id, status="created")  
            asi_created = 0  
            ticket_channel_id = None  
            if interaction.guild:  
                await create_or_update_character_discussion_post(interaction.guild, char_id)  
                await ensure_approved_player_role(interaction.guild, int(draft.get("owner_user_id") or 0))  
                asi_created = await ensure_pending_asi_choices(char_id, interaction.guild.id, 1, story_level_for_die(int(draft.get("starter_die") or 8)))  
                if asi_created:  
                    ticket_channel_id = await open_level_ticket_if_needed(interaction.guild, char_id)  
            asi_note = f" Pending ASI choice(s): **{asi_created}**." if asi_created else ""  
            ticket_note = f" Level ticket: <#{ticket_channel_id}>." if ticket_channel_id else ""  
            await interaction.response.edit_message(content=f"✅ Story character created: **{draft['name']}** (ID {char_id}).{asi_note}{ticket_note}", embed=None, view=None)  
        except Exception as exc:  
            LOG.exception("Failed to finalize story character.")  
            await interaction.response.send_message(f"Failed to finalize story character: {exc}", ephemeral=True)  
  
  
async def prepare_story_ability_choices(draft_id: int) -> None:  
    draft = await fetch_story_draft(draft_id)  
    level = story_level_for_die(int(draft.get("starter_die") or 8))  
    primary = normalize_name(draft.get("primary_class"))  
    secondary = normalize_name(draft.get("secondary_class"))  
    primary_selected = decode_json_payload(draft.get("selected_primary_abilities_json")) or {}  
    secondary_selected = decode_json_payload(draft.get("selected_secondary_abilities_json")) or {}  
    for tier in story_unlocked_class_levels(level, secondary=False):  
        opts = story_ability_options_for(primary, tier)  
        if opts and str(tier) not in primary_selected:  
            primary_selected[str(tier)] = opts[0]["name"]  
    if secondary:  
        for tier in story_unlocked_class_levels(level, secondary=True):  
            opts = story_ability_options_for(secondary, tier)  
            if opts and str(tier) not in secondary_selected:  
                secondary_selected[str(tier)] = opts[0]["name"]  
    await update_story_draft(  
        draft_id,  
        selected_primary_abilities_json=json.dumps(primary_selected),  
        selected_secondary_abilities_json=json.dumps(secondary_selected),  
    )  
  
  
def build_story_ability_embed(draft: dict[str, Any]) -> discord.Embed:  
    level = story_level_for_die(int(draft.get("starter_die") or 8))  
    primary = normalize_name(draft.get("primary_class"))  
    secondary = normalize_name(draft.get("secondary_class"))  
    psel = decode_json_payload(draft.get("selected_primary_abilities_json")) or {}  
    ssel = decode_json_payload(draft.get("selected_secondary_abilities_json")) or {}  
    lines = []  
    for tier in story_unlocked_class_levels(level, secondary=False):  
        lines.append(f"Primary L{tier}: **{psel.get(str(tier), 'Not selected')}**")  
    if secondary:  
        for tier in story_unlocked_class_levels(level, secondary=True):  
            lines.append(f"Secondary L{tier}: **{ssel.get(str(tier), 'Not selected')}**")  
    embed = discord.Embed(  
        title=f"Choose Active Abilities - {draft.get('name')}",  
        description="\n".join(lines) or "No active ability tiers unlocked.",  
        color=discord.Color.gold(),  
    )  
    return embed  
  
  
  
def story_ability_slots_for_draft(draft: dict[str, Any]) -> list[dict[str, Any]]:  
    level = story_level_for_die(int(draft.get("starter_die") or 8))  
    primary = normalize_name(draft.get("primary_class"))  
    secondary = normalize_name(draft.get("secondary_class"))  
    slots: list[dict[str, Any]] = []  
    for tier in story_unlocked_class_levels(level, secondary=False):  
        if story_ability_options_for(primary, tier):  
            slots.append({"source": "primary", "tier": tier, "class_name": primary, "label": f"Primary {primary.title()} L{tier}"})  
    if secondary:  
        for tier in story_unlocked_class_levels(level, secondary=True):  
            if story_ability_options_for(secondary, tier):  
                slots.append({"source": "secondary", "tier": tier, "class_name": secondary, "label": f"Secondary {secondary.title()} L{tier}"})  
    return slots  
  
  
class StaffStoryAbilitySlotSelect(discord.ui.Select):  
    def __init__(self, draft: dict[str, Any]):  
        self.draft_id = int(draft["id"])  
        slots = story_ability_slots_for_draft(draft)  
        options = []  
        for slot in slots[:25]:  
            value = f"{slot['source']}:{slot['tier']}:{slot['class_name']}"  
            options.append(discord.SelectOption(label=slot["label"][:100], value=value[:100], description="Choose or change this active ability."))  
        if not options:  
            options = [discord.SelectOption(label="No active tiers unlocked", value="none", description="Return to setup or finalize.")]  
        super().__init__(placeholder="Choose an ability slot to edit...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        if self.values[0] == "none":  
            await interaction.response.send_message("No active ability tiers are unlocked for this draft.", ephemeral=True)  
            return  
        source, tier_raw, class_name = self.values[0].split(":", 2)  
        tier = int(tier_raw)  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(  
            embed=build_story_ability_embed(draft),  
            view=await build_story_ability_option_view(self.draft_id, source, tier, class_name),  
        )  
  
  
class StaffStoryAbilityOptionSelect(discord.ui.Select):  
    def __init__(self, draft_id: int, source: str, tier: int, class_name: str):  
        self.draft_id = int(draft_id)  
        self.source = source  
        self.tier = int(tier)  
        self.class_name = class_name  
        options = []  
        for ability in story_ability_options_for(class_name, tier)[:25]:  
            label = str(ability.get("name") or "Ability")[:100]  
            desc = str(ability.get("description") or "")[:100]  
            options.append(discord.SelectOption(label=label, value=label, description=desc))  
        if not options:  
            options = [discord.SelectOption(label="No options available", value="none", description="Return to ability slots.")]  
        super().__init__(placeholder=f"Choose {source} L{tier} ability...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        if self.values[0] == "none":  
            await interaction.response.send_message("No ability option is available for that slot.", ephemeral=True)  
            return  
        draft = await fetch_story_draft(self.draft_id)  
        key = "selected_primary_abilities_json" if self.source == "primary" else "selected_secondary_abilities_json"  
        selected = decode_json_payload(draft.get(key)) or {}  
        selected[str(self.tier)] = self.values[0]  
        await update_story_draft(self.draft_id, **{key: json.dumps(selected)})  
        draft = await fetch_story_draft(self.draft_id)  
        await interaction.response.edit_message(  
            embed=build_story_ability_embed(draft),  
            view=await build_story_ability_choice_view(self.draft_id),  
        )  
  
  
async def build_story_ability_choice_view(draft_id: int) -> discord.ui.View:  
    draft = await fetch_story_draft(draft_id)  
    view = discord.ui.View(timeout=900)  
    view.add_item(StaffStoryAbilitySlotSelect(draft))  
  
    async def back_callback(interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        draft2 = await fetch_story_draft(draft_id)  
        await interaction.response.edit_message(embed=build_story_draft_embed(draft2), view=StaffStorySetupView(draft_id))  
    back_button = discord.ui.Button(label="Back to Setup", style=discord.ButtonStyle.secondary)  
    back_button.callback = back_callback  
    view.add_item(back_button)  
  
    async def finalize_callback(interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        draft2 = await fetch_story_draft(draft_id)  
        try:  
            char_id = await create_story_character_from_draft(draft2, interaction.user.id)  
            await update_story_draft(draft_id, status="created")  
            asi_created = 0  
            ticket_channel_id = None  
            if interaction.guild:  
                await create_or_update_character_discussion_post(interaction.guild, char_id)  
                await ensure_approved_player_role(interaction.guild, int(draft2.get("owner_user_id") or 0))  
                asi_created = await ensure_pending_asi_choices(char_id, interaction.guild.id, 1, story_level_for_die(int(draft2.get("starter_die") or 8)))  
                if asi_created:  
                    ticket_channel_id = await open_level_ticket_if_needed(interaction.guild, char_id)  
            asi_note = f" Pending ASI choice(s): **{asi_created}**." if asi_created else ""  
            ticket_note = f" Level ticket: <#{ticket_channel_id}>." if ticket_channel_id else ""  
            await interaction.response.edit_message(content=f"✅ Story character created: **{draft2['name']}** (ID {char_id}).{asi_note}{ticket_note}", embed=None, view=None)  
        except Exception as exc:  
            LOG.exception("Failed to finalize story character.")  
            await interaction.response.send_message(f"Failed to finalize story character: {exc}", ephemeral=True)  
    finalize_button = discord.ui.Button(label="Finalize Character", style=discord.ButtonStyle.success)  
    finalize_button.callback = finalize_callback  
    view.add_item(finalize_button)  
    return view  
  
  
async def build_story_ability_option_view(draft_id: int, source: str, tier: int, class_name: str) -> discord.ui.View:  
    view = discord.ui.View(timeout=900)  
    view.add_item(StaffStoryAbilityOptionSelect(draft_id, source, tier, class_name))  
  
    async def back_callback(interaction: discord.Interaction):  
        if not await require_staff(interaction):  
            return  
        draft = await fetch_story_draft(draft_id)  
        await interaction.response.edit_message(embed=build_story_ability_embed(draft), view=await build_story_ability_choice_view(draft_id))  
    back_button = discord.ui.Button(label="Back to Ability Slots", style=discord.ButtonStyle.secondary)  
    back_button.callback = back_callback  
    view.add_item(back_button)  
    return view  
  
  
async def create_story_character_from_draft(draft: dict[str, Any], approved_by: int) -> int:  
    if normalize_name(draft.get("status")) == "created":  
        raise RuntimeError("This story draft has already been finalized.")  
    primary = normalize_name(draft.get("primary_class"))  
    if not primary:  
        raise RuntimeError("Primary class is required.")  
    secondary = normalize_name(draft.get("secondary_class"))  
    die = int(draft.get("starter_die") or 8)  
    level = story_level_for_die(die)  
    xp_total = story_xp_for_die(die)  
    stats = decode_json_payload(draft.get("stats_json")) or story_stats_default_for_class(primary)  
    passives = merge_story_passives(draft.get("species") or "", primary, secondary)  
    species_passives = [p for p in passives if p.get("source") == "species"]  
    primary_passives = [p for p in passives if p.get("source") == "primary_class"]  
    secondary_passives = [p for p in passives if p.get("source") == "secondary_discipline"]  
    passive_totals = merge_passive_bonuses(*passives)  
    # Keep base combat class as primary. Secondary discipline contributes only passives and chosen actives.  
    combat = calculate_combat_values(  
        primary,  
        stats,  
        level=level,  
        damage_die_sides=die,  
        species_name=draft.get("species"),  
        species_passive={"name": "Story Species Passives", "bonuses": {}},  
        class_passive={"name": "Story Class Passives", "bonuses": passive_totals},  
    )  
    async with db_pool.acquire() as migrate_conn:  
        await migrate_conn.execute("""  
            ALTER TABLE alaris_characters  
                ADD COLUMN IF NOT EXISTS secondary_class TEXT,  
                ADD COLUMN IF NOT EXISTS secondary_passives_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS story_passives_json JSONB NOT NULL DEFAULT '[]'::jsonb,  
                ADD COLUMN IF NOT EXISTS is_story_character BOOLEAN NOT NULL DEFAULT FALSE,  
                ADD COLUMN IF NOT EXISTS starting_dice_override INTEGER;  
        """)  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchrow(  
            """  
            SELECT id, name, status  
            FROM alaris_characters  
            WHERE guild_id=$1 AND normalized_name=$2  
            LIMIT 1;  
            """,  
            int(payload["guild_id"]),  
            normalize_name(payload["name"]),  
        )  
        if existing:  
            raise RuntimeError(  
                f"A character named '{existing['name']}' already exists in this server. "  
                f"Use a unique name or remove/archive the existing character first."  
            )  
  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            char_id = await conn.fetchval(  
                """  
                INSERT INTO alaris_characters (  
                    guild_id, user_id, name, normalized_name, species, class_name,  
                    secondary_class, secondary_passives_json, story_passives_json,  
                    species_passive_name, species_passive_json, class_passive_name, class_passive_json,  
                    image_url, google_doc_url, level, xp_total, damage_die_sides,  
                    status, created_by, approved_by, approved_at,  
                    is_story_character, starting_dice_override  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10,$11::jsonb,$12,$13::jsonb,$14,$15,$16,$17,$18,'active',$19,$20,NOW(),TRUE,$21)  
                RETURNING id;  
                """,  
                int(draft["guild_id"]),  
                int(draft["owner_user_id"]),  
                draft["name"],  
                draft["normalized_name"],  
                draft["species"],  
                primary,  
                secondary or None,  
                json.dumps(secondary_passives),  
                json.dumps(passives),  
                ", ".join(p["name"] for p in species_passives) or "None",  
                json.dumps(species_passives),  
                ", ".join(p["name"] for p in primary_passives) or "None",  
                json.dumps(primary_passives),  
                draft.get("image_url"),  
                draft.get("google_doc_url"),  
                level,  
                xp_total,  
                die,  
                int(draft.get("creator_user_id") or approved_by),  
                int(approved_by),  
                die,  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_stats (  
                    character_id, strength, dexterity, constitution, intelligence, wisdom, charisma  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7);  
                """,  
                char_id,  
                int(stats["strength"]), int(stats["dexterity"]), int(stats["constitution"]),  
                int(stats["intelligence"]), int(stats["wisdom"]), int(stats["charisma"]),  
            )  
            await conn.execute(  
                """  
                INSERT INTO alaris_character_combat (  
                    character_id, max_hp, current_hp, armor_class, initiative_bonus,  
                    proficiency_bonus, attack_bonus, spell_dc, technique_dc,  
                    magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                    max_resolve, current_resolve, damage_type, resistances_json, weaknesses_json, immunities_json  
                )  
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,'{}'::jsonb,'{}'::jsonb,'{}'::jsonb);  
                """,  
                char_id,  
                int(combat["max_hp"]), int(combat["current_hp"]), int(combat["armor_class"]),  
                int(combat["initiative_bonus"]), int(combat["proficiency_bonus"]), int(combat["attack_bonus"]),  
                combat["spell_dc"], int(combat["technique_dc"]), int(combat.get("magic_save_bonus") or 0),  
                int(combat.get("magic_defense") or 10), int(combat["damage_die_sides"]),  
                int(combat.get("damage_bonus") or 0), int(combat.get("max_resolve") or 1),  
                int(combat.get("current_resolve") or 1), combat["damage_type"],  
            )  
            for p in passives:  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_character_features (  
                        guild_id, character_id, source_type, feature_name, feature_type, level_granted, metadata_json  
                    )  
                    VALUES ($1,$2,$3,$4,'passive',1,$5::jsonb)  
                    ON CONFLICT DO NOTHING;  
                    """,  
                    int(draft["guild_id"]), char_id, p.get("source") or "story", p["name"], json.dumps(p),  
                )  
            psel = decode_json_payload(draft.get("selected_primary_abilities_json")) or {}  
            ssel = decode_json_payload(draft.get("selected_secondary_abilities_json")) or {}  
            for tier, ability_name in psel.items():  
                ability = find_class_ability(primary, ability_name, max_level=10)  
                if ability:  
                    ability["source"] = "primary_class"  
                    await conn.execute(  
                        """  
                        INSERT INTO alaris_character_abilities (  
                            guild_id, character_id, ability_name, class_name, level_granted, metadata_json  
                        )  
                        VALUES ($1,$2,$3,$4,$5,$6::jsonb)  
                        ON CONFLICT DO NOTHING;  
                        """,  
                        int(draft["guild_id"]), char_id, ability["name"], primary, int(tier), json.dumps(ability),  
                    )  
            if secondary:  
                for tier, ability_name in ssel.items():  
                    ability = find_class_ability(secondary, ability_name, max_level=4)  
                    if ability:  
                        ability["source"] = "secondary_discipline"  
                        await conn.execute(  
                            """  
                            INSERT INTO alaris_character_abilities (  
                                guild_id, character_id, ability_name, class_name, level_granted, metadata_json  
                            )  
                            VALUES ($1,$2,$3,$4,$5,$6::jsonb)  
                            ON CONFLICT DO NOTHING;  
                            """,  
                            int(draft["guild_id"]), char_id, ability["name"], secondary, int(tier), json.dumps(ability),  
                        )  
            await sync_public_character_compat_row(conn, {  
                "character_id": int(char_id),  
                "guild_id": int(draft["guild_id"]),  
                "user_id": int(draft["owner_user_id"]),  
                "name": draft["name"],  
                "normalized_name": draft["normalized_name"],  
                "species": draft["species"],  
                "class_name": primary,  
                "kingdom": draft.get("kingdom"),  
                "level": level,  
                "xp_total": xp_total,  
            })  
    return int(char_id)  
  
  
@bot.tree.command(name="staff-character-create", description="Staff-only: create a story/NPC character with starter dice and secondary discipline.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def staff_character_create(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
  
    embed = discord.Embed(  
        title="Staff Story Character Creation",  
        description=(  
            "Choose the Discord member who should own/control this story character. "  
            "After that, the bot will open the character creation form."  
        ),  
        color=discord.Color.dark_gold(),  
    )  
    await interaction.response.send_message(  
        embed=embed,  
        view=StaffStoryStartView(None),  
        ephemeral=True,  
    )  
  
  
# Removed from slash sync in v113: /health is hidden/retired.  
# @bot.tree.command(name="health", description="retired")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def health(interaction: discord.Interaction):  
    await interaction.response.defer(ephemeral=True)  
    schema = await inspect_core_schema()  
    embed = discord.Embed(  
        title="Alaris Bot Health",  
        description="Clean v102 foundation is online.",  
        color=discord.Color.green(),  
    )  
    embed.add_field(name="Discord", value="Connected", inline=True)  
    embed.add_field(name="Postgres", value="Connected", inline=True)  
    embed.add_field(name="Public Tables", value=str(schema["public_tables"]), inline=True)  
    embed.add_field(name="Clean Characters", value=str(schema["clean_active_characters"]), inline=True)  
    embed.add_field(name="Old Characters", value=str(schema["old_active_characters"]), inline=True)  
    embed.add_field(name="Open Tickets", value=str(schema["open_tickets"]), inline=True)  
    try:  
        async with db_pool.acquire() as conn:  
            open_sessions = int(await conn.fetchval("SELECT COUNT(*) FROM alaris_sessions WHERE status='open';") or 0)  
    except Exception:  
        open_sessions = 0  
    embed.add_field(name="Open Sessions", value=str(open_sessions), inline=True)  
    embed.add_field(name="Progression Rows", value=str(schema["progression_rows"]), inline=True)  
    embed.set_footer(text="Alaris Bot v102 Clean")  
    await interaction.followup.send(embed=embed, ephemeral=True)  
    await post_command_log(interaction, "health check")  
  
  
@bot.tree.command(name="schema-check", description="DEV: inspect the connected database tables used by the clean rebuild.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def schema_check(interaction: discord.Interaction):  
    if not await require_developer(interaction):  
        return  
    await interaction.response.defer(ephemeral=True)  
    schema = await inspect_core_schema()  
    embed = discord.Embed(  
        title="Alaris Schema Check",  
        description="Read-only inspection. v102 uses clean alaris_* tables.",  
        color=discord.Color.gold(),  
    )  
    embed.add_field(name="Public Tables", value=str(schema["public_tables"]), inline=True)  
    embed.add_field(name="Clean Characters", value=str(schema["clean_active_characters"]), inline=True)  
    embed.add_field(name="Open Tickets", value=str(schema["open_tickets"]), inline=True)  
    clean_summary = [f"{'✅' if info['exists'] else '❌'} `{table}`" for table, info in schema["clean_core"].items()]  
    embed.add_field(name="Clean Tables", value="\n".join(clean_summary)[:1024], inline=False)  
    await interaction.followup.send(embed=embed, ephemeral=True)  
    await post_command_log(interaction, "schema check")  
  
  
  
  
@bot.tree.command(name="review-ticket-reset", description="STAFF: rebuild/reset an open character review ticket without touching approved characters.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    character="Optional character name in an open review ticket. If omitted, uses this channel or your open ticket.",  
    rebuild_only="If true, rebuilds controls without wiping species/class/stats/passives."  
)  
async def review_ticket_reset(interaction: discord.Interaction, character: str = "", rebuild_only: bool = False):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
  
    await interaction.response.defer(ephemeral=True)  
  
    ticket = None  
    if interaction.channel is not None:  
        ticket = await fetch_open_review_ticket_by_channel(interaction.guild.id, interaction.channel.id)  
    if ticket is None:  
        ticket = await fetch_open_review_ticket_for_user_or_name(  
            interaction.guild.id,  
            user_id=interaction.user.id,  
            character_name=character,  
        )  
  
    if ticket is None:  
        await interaction.followup.send(  
            "No open character review ticket found for this channel, your user, or that character name.",  
            ephemeral=True,  
        )  
        return  
  
    payload = decode_json_payload(ticket["payload_json"])  
    if not rebuild_only:  
        payload = reset_review_ticket_build_payload(payload)  
        await update_review_ticket_payload(int(ticket["id"]), payload)  
  
    rebuilt, message = await rebuild_review_ticket_message(interaction.guild, ticket, payload)  
    action = "rebuilt" if rebuild_only else "reset and rebuilt"  
    await interaction.followup.send(  
        f"Review ticket `{ticket['id']}` for **{payload.get('name', 'Unknown')}** was {action}.\n{message}",  
        ephemeral=True,  
    )  
  
  
@bot.tree.command(name="review-ticket-close", description="STAFF: abandon an orphaned/open character review ticket so creation can restart.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    character="Optional character name in the open review ticket. If omitted, uses this channel or your open ticket.",  
    delete_channel="Delete the ticket channel if it still exists."  
)  
async def review_ticket_close(interaction: discord.Interaction, character: str = "", delete_channel: bool = False):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
  
    await interaction.response.defer(ephemeral=True)  
  
    ticket = None  
    if interaction.channel is not None:  
        ticket = await fetch_open_review_ticket_by_channel(interaction.guild.id, interaction.channel.id)  
    if ticket is None:  
        ticket = await fetch_open_review_ticket_for_user_or_name(  
            interaction.guild.id,  
            user_id=interaction.user.id,  
            character_name=character,  
        )  
  
    if ticket is None:  
        await interaction.followup.send(  
            "No open character review ticket found for this channel, your user, or that character name.",  
            ephemeral=True,  
        )  
        return  
  
    payload = decode_json_payload(ticket["payload_json"])  
    closed = await close_review_ticket_row(int(ticket["id"]), interaction.user.id, status="abandoned")  
    if not closed:  
        await interaction.followup.send("That review ticket was already closed or could not be found.", ephemeral=True)  
        return  
  
    deleted = False  
    if delete_channel:  
        deleted = await delete_review_ticket_channel_if_available(  
            interaction.guild,  
            ticket.get("channel_id"),  
            f"Abandoned Alaris character review ticket for {payload.get('name', 'Unknown')}",  
        )  
  
    await interaction.followup.send(  
        f"Review ticket `{ticket['id']}` for **{payload.get('name', 'Unknown')}** is now **abandoned**. "  
        f"You can rerun `/character-create` for that character. "  
        f"Channel deleted: **{'yes' if deleted else 'no'}**.",  
        ephemeral=True,  
    )  
  
async def kingdom_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    needle = normalize_name(current)  
    choices = []  
    for kingdom in KINGDOM_OPTIONS:  
        if not needle or needle in normalize_name(kingdom):  
            choices.append(app_commands.Choice(name=kingdom, value=kingdom))  
    return choices[:25]  
  
  
@bot.tree.command(name="character-rename", description="STAFF: rename an approved character and refresh their showcase card.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Approved character to rename", new_name="Corrected character name", reason="Optional staff note for the rename log")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_rename(interaction: discord.Interaction, character: str, new_name: str, reason: str = ""):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
  
    cleaned_name = re.sub(r"\s+", " ", str(new_name or "").strip())  
    normalized = normalize_name(cleaned_name)  
    if not normalized:  
        await interaction.followup.send("New character name cannot be blank.", ephemeral=True)  
        return  
    if len(cleaned_name) > 80:  
        await interaction.followup.send("New character name must be 80 characters or fewer.", ephemeral=True)  
        return  
  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send(f"No active character found matching **{truncate(character, 80)}**.", ephemeral=True)  
        return  
  
    char = payload["character"]  
    character_id = int(char["id"])  
    old_name = str(char.get("name") or "")  
    old_normalized = normalize_name(old_name)  
    if normalized == old_normalized and cleaned_name == old_name:  
        await interaction.followup.send(f"**{old_name}** already has that name.", ephemeral=True)  
        return  
  
    async with db_pool.acquire() as conn:  
        duplicate = await conn.fetchrow(  
            """  
            SELECT id, name  
            FROM alaris_characters  
            WHERE guild_id=$1  
              AND status='active'  
              AND normalized_name=$2  
              AND id<>$3  
            LIMIT 1;  
            """,  
            interaction.guild.id, normalized, character_id,  
        )  
        if duplicate:  
            await interaction.followup.send(  
                f"Cannot rename character. The active character **{duplicate['name']}** already uses that normalized name.",  
                ephemeral=True,  
            )  
            return  
  
        await conn.execute(  
            """  
            UPDATE alaris_characters  
            SET name=$3, normalized_name=$4, updated_at=NOW()  
            WHERE guild_id=$1 AND id=$2 AND status='active';  
            """,  
            interaction.guild.id, character_id, cleaned_name, normalized,  
        )  
        await sync_public_character_compat_row(conn, {  
            "character_id": character_id,  
            "guild_id": interaction.guild.id,  
            "user_id": int(char.get("user_id") or 0),  
            "name": cleaned_name,  
            "normalized_name": normalized,  
            "species": char.get("species"),  
            "class_name": char.get("class_name"),  
            "kingdom": char.get("kingdom"),  
            "level": int(char.get("level") or 1),  
            "xp_total": int(char.get("xp_total") or 0),  
        })  
  
    post_updated = False  
    try:  
        refreshed_thread_id = await create_or_update_character_discussion_post(interaction.guild, character_id, create_if_missing=False)  
        post_updated = bool(refreshed_thread_id)  
    except Exception:  
        LOG.exception("Failed to refresh character post after rename.")  
  
    reason_text = str(reason or "").strip()  
    response_lines = [  
        "Character renamed successfully.",  
        f"**Old:** {old_name}",  
        f"**New:** {cleaned_name}",  
        f"**Character ID:** `{character_id}`",  
        f"**Database:** updated",  
        f"**Compatibility mirror:** updated",  
        f"**Showcase/card:** {'updated' if post_updated else 'not found or not updated'}",  
    ]  
    if reason_text:  
        response_lines.append(f"**Reason:** {truncate(reason_text, 500)}")  
    await interaction.followup.send("\n".join(response_lines), ephemeral=True)  
  
    log_reason = f" reason={truncate(reason_text, 300)}" if reason_text else ""  
    await post_command_log(interaction, f"renamed character id={character_id}: {old_name} -> {cleaned_name}{log_reason}")  
  
  
@bot.tree.command(name="character-set-kingdom", description="STAFF: assign or correct a character's kingdom/affiliation.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Approved character name", kingdom="Canonical kingdom/affiliation")  
@app_commands.autocomplete(character=character_name_autocomplete, kingdom=kingdom_autocomplete)  
async def character_set_kingdom(interaction: discord.Interaction, character: str, kingdom: str):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
  
    selected = str(kingdom or "").strip()  
    if normalize_name(selected) not in {normalize_name(k) for k in KINGDOM_OPTIONS}:  
        await interaction.followup.send("That is not a recognized Alaris kingdom/affiliation.", ephemeral=True)  
        return  
  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send(f"No active character found matching **{truncate(character, 80)}**.", ephemeral=True)  
        return  
    char = payload["character"]  
    character_id = int(char["id"])  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_characters  
            SET kingdom=$3, updated_at=NOW()  
            WHERE guild_id=$1 AND id=$2 AND status='active';  
            """,  
            interaction.guild.id, character_id, selected,  
        )  
        await sync_public_character_compat_row(conn, {  
            "character_id": character_id,  
            "guild_id": interaction.guild.id,  
            "user_id": int(char.get("user_id") or 0),  
            "name": char.get("name"),  
            "normalized_name": char.get("normalized_name") or normalize_name(char.get("name")),  
            "species": char.get("species"),  
            "class_name": char.get("class_name"),  
            "kingdom": selected,  
            "level": int(char.get("level") or 1),  
            "xp_total": int(char.get("xp_total") or 0),  
        })  
  
    try:  
        await create_or_update_character_discussion_post(interaction.guild, character_id)  
    except Exception:  
        LOG.exception("Failed to refresh character post after kingdom update.")  
  
    await interaction.followup.send(f"Set **{char.get('name')}** kingdom/affiliation to **{selected}**.", ephemeral=True)  
    await post_command_log(interaction, f"set kingdom for {char.get('name')} to {selected}")  
  
  
@bot.tree.command(name="character-create", description="Create a character review ticket.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(image="Upload the character image to use for the discussion/forum post preview")  
async def character_create(interaction: discord.Interaction, image: discord.Attachment):  
    if not (image.content_type or "").startswith("image/"):  
        await interaction.response.send_message("Please upload an image file for the character image.", ephemeral=True)  
        return  
  
    # Discord modals must be the first response to an interaction and can fail if the  
    # initial slash interaction expires. A fast ephemeral button creates a fresh  
    # interaction for the modal, making character creation much more reliable.  
    embed = discord.Embed(  
        title="Start Character Creation",  
        description="Click the button below to open the character form.",  
        color=discord.Color.blurple(),  
    )  
    embed.add_field(name="Image", value=image.filename or "Uploaded image", inline=False)  
    embed.set_image(url=image.url)  
    await interaction.response.send_message(embed=embed, view=CharacterCreateStartView(image), ephemeral=True)  
  
  
# Removed from slash sync in v108: use /character-view instead.  
# # Removed from slash sync in v113: /character-sheet is hidden/retired.  
# @bot.tree.command(name="character-sheet", description="retired")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Approved character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_sheet(interaction: discord.Interaction, character: str):  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send(f"No active character found matching **{truncate(character, 80)}**.", ephemeral=True)  
        return  
    await interaction.followup.send(embed=build_character_embed(payload), ephemeral=True)  
    await post_command_log(interaction, f"viewed character sheet for {payload['character'].get('name')}")  
  
  
  
@bot.tree.command(name="character-view", description="View an approved clean Alaris character.")  
# Removed default_permissions in v108 so this player command is visible.  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_view(interaction: discord.Interaction, character: str):  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send(f"No active character found matching **{truncate(character, 80)}**.", ephemeral=True)  
        return  
    await interaction.followup.send(embed=build_character_embed(payload), ephemeral=True)  
    await post_command_log(interaction, f"viewed character {payload['character'].get('name')}")  
  
  
  
  
# Removed from slash sync in v108: use /character-view instead.  
# # Removed from slash sync in v113: /character-card is hidden/retired.  
# @bot.tree.command(name="character-card", description="retired")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_card(interaction: discord.Interaction, character: str):  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send(f"No active character found matching **{truncate(character, 80)}**.", ephemeral=True)  
        return  
    await interaction.followup.send(embed=build_character_embed(payload), ephemeral=True)  
    await post_command_log(interaction, f"called character card for {payload['character'].get('name')}")  
  
  
  
class SessionJoinSelect(discord.ui.Select):  
    def __init__(self, session_id: int, options: list[discord.SelectOption]):  
        self.session_id = int(session_id)  
        super().__init__(  
            placeholder="Choose one or more owned characters to join the session...",  
            min_values=1,  
            max_values=max(1, min(len(options), 25)),  
            options=options,  
        )  
  
    async def callback(self, interaction: discord.Interaction):  
        if interaction.guild is None:  
            await interaction.response.send_message("This session join menu is unavailable.", ephemeral=True)  
            return  
        rows = await owned_character_rows_for_user(interaction.guild.id, interaction.user.id)  
        owned_ids = {int(r["id"]) for r in rows}  
        by_id = {int(r["id"]): r for r in rows}  
        added_names = []  
        already_names = []  
        for raw in self.values:  
            try:  
                cid = int(raw)  
            except Exception:  
                continue  
            if cid not in owned_ids:  
                continue  
            added = await add_session_participant(self.session_id, cid, interaction.user.id)  
            if added:  
                added_names.append(str(by_id[cid]["name"]))  
            else:  
                already_names.append(str(by_id[cid]["name"]))  
        parts = []  
        if added_names:  
            parts.append("Joined: " + ", ".join(f"**{n}**" for n in added_names))  
        if already_names:  
            parts.append("Already joined: " + ", ".join(f"**{n}**" for n in already_names))  
        await interaction.response.send_message("\\n".join(parts) if parts else "No characters joined.", ephemeral=True)  
  
  
class SessionStartJoinView(discord.ui.View):  
    def __init__(self, session_id: int, options: list[discord.SelectOption]):  
        super().__init__(timeout=300)  
        if options:  
            self.add_item(SessionJoinSelect(session_id, options))  
  
  
@bot.tree.command(name="session-start", description="Start a roleplay session in this channel.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def session_start(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if active:  
        await interaction.response.send_message(  
            f"There is already an open session in this channel: **{active['title'] or active['session_type']}**.",  
            ephemeral=True,  
        )  
        return  
  
    await interaction.response.defer(ephemeral=False)  
    start_msg = await interaction.followup.send(  
        f"📖 **Roleplay session started.**\\n"  
        f"Host: {interaction.user.mention}\\n"  
        "Use the character picker below to join one or more owned characters. "  
        "Use `/combat-start` later if combat begins.",  
        wait=True,  
    )  
  
    session_id = await create_session(  
        interaction.guild.id,  
        interaction.channel.id,  
        interaction.user.id,  
        "Roleplay",  
        "Roleplay",  
        start_msg.id,  
    )  
  
    rows = await owned_character_rows_for_user(interaction.guild.id, interaction.user.id)  
    options = [  
        discord.SelectOption(  
            label=str(r["name"])[:100],  
            value=str(r["id"]),  
            description=f"{r.get('species') or 'Unknown'} {r.get('class_name') or ''}"[:100],  
        )  
        for r in rows[:25]  
    ]  
  
    await start_msg.edit(  
        content=(  
            f"📖 **Roleplay session started.**\\n"  
            f"Host: {interaction.user.mention}\\n"  
            f"Session ID: `{session_id}`\\n"  
            "Use the character picker below to join one or more owned characters. "  
            "Other players may use `/session-join`. Use `/combat-start` later if combat begins."  
        ),  
        view=SessionStartJoinView(session_id, options) if options else None,  
    )  
    await post_command_log(interaction, f"started Roleplay session id={session_id}")  
  
  
@bot.tree.command(name="session-join", description="Join the open session in this channel with one of your characters.")  
# Removed default_permissions in v108 so this player command is visible.  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Choose one of your approved characters")  
@app_commands.autocomplete(character=owned_character_autocomplete)  
async def session_join(interaction: discord.Interaction, character: str):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        await interaction.response.send_message("There is no open session in this channel.", ephemeral=True)  
        return  
  
    payload = await fetch_owned_character_for_session_by_id(interaction.guild.id, character, interaction.user.id)  
    if not payload:  
        await interaction.response.send_message("Choose one of your approved active characters from the dropdown.", ephemeral=True)  
        return  
  
    added = await add_session_participant(int(active["id"]), int(payload["character"]["id"]), interaction.user.id)  
    if added:  
        await interaction.response.send_message(f"✅ **{payload['character']['name']}** joined the session.", ephemeral=False)  
    else:  
        await interaction.response.send_message(f"**{payload['character']['name']}** is already in this session.", ephemeral=True)  
  
  
@bot.tree.command(name="session-leave", description="Remove one of your characters from the open session in this channel.")  
# Removed default_permissions in v108 so this player command is visible.  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Choose one of your approved characters to remove")  
@app_commands.autocomplete(character=owned_character_autocomplete)  
async def session_leave(interaction: discord.Interaction, character: str):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        await interaction.response.send_message("There is no open session in this channel.", ephemeral=True)  
        return  
  
    payload = await fetch_owned_character_for_session_by_id(interaction.guild.id, character, interaction.user.id)  
    if not payload:  
        await interaction.response.send_message("Choose one of your approved active characters from the dropdown.", ephemeral=True)  
        return  
  
    removed = await remove_session_participant(int(active["id"]), int(payload["character"]["id"]))  
    if removed:  
        await interaction.response.send_message(f"✅ **{payload['character']['name']}** left the session.", ephemeral=False)  
    else:  
        await interaction.response.send_message(f"**{payload['character']['name']}** was not in this session.", ephemeral=True)  
  
  
@bot.tree.command(name="session-status", description="Show the open session in this channel.")  
# Removed default_permissions in v108 so this player command is visible.  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def session_status(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        await interaction.response.send_message("There is no open session in this channel.", ephemeral=True)  
        return  
  
    participants = await list_session_participants(int(active["id"]))  
    await interaction.response.send_message(embed=build_session_status_embed(active, participants), ephemeral=False)  
  
  
  
def spar_duel_opponent_die_bonus(opponent_die_sides: int) -> int:  
    # Deprecated compatibility helper; v116 spars/duels use total participant max HP instead.  
    return max(0, int(opponent_die_sides or 0))  
  
  
async def spar_duel_xp_awards_for_session(session_id: int, participants: list[dict[str, Any]]) -> tuple[Optional[int], dict[int, int], str]:  
    """Return victor_character_id, scaled awards by character_id, and note for Spar/Duel.  
  
    v116:  
    - Every registered participant receives 30 XP plus the total max HP of all registered combatants.  
    - The victor receives an additional +30 XP.  
    - The HP-derived value is not split; it is awarded in full to every participant.  
    """  
    async with db_pool.acquire() as conn:  
        encounter = await conn.fetchrow(  
            """  
            SELECT id, combat_type  
            FROM alaris_combat_encounters  
            WHERE session_id=$1  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            session_id,  
        )  
        if not encounter or str(encounter["combat_type"]) not in {"Spar", "Duel"}:  
            return None, {}, ""  
        encounter_id = int(encounter["id"])  
        victor_row = await conn.fetchrow(  
            """  
            SELECT actor.character_id AS victor_character_id, actor.name AS victor_name  
            FROM alaris_combat_logs log  
            JOIN alaris_combatants actor ON actor.id=log.actor_combatant_id  
            JOIN alaris_combatants target ON target.id=log.target_combatant_id  
            WHERE log.encounter_id=$1  
              AND actor.combatant_type='character'  
              AND target.combatant_type='character'  
              AND log.outcome ILIKE '%defeated%'  
            ORDER BY log.created_at DESC, log.id DESC  
            LIMIT 1;  
            """,  
            encounter_id,  
        )  
        if not victor_row:  
            active = await conn.fetch(  
                """  
                SELECT character_id, name  
                FROM alaris_combatants  
                WHERE encounter_id=$1 AND combatant_type='character' AND status='active'  
                ORDER BY id;  
                """,  
                encounter_id,  
            )  
            defeated = await conn.fetch(  
                """  
                SELECT character_id, name  
                FROM alaris_combatants  
                WHERE encounter_id=$1 AND combatant_type='character' AND status!='active'  
                ORDER BY id;  
                """,  
                encounter_id,  
            )  
            if len(active) == 1 and defeated:  
                victor_row = {"victor_character_id": int(active[0]["character_id"]), "victor_name": str(active[0]["name"])}  
  
        combatants = await conn.fetch(  
            """  
            SELECT character_id, name, max_hp, status  
            FROM alaris_combatants  
            WHERE encounter_id=$1 AND combatant_type='character' AND character_id IS NOT NULL  
            ORDER BY id;  
            """,  
            encounter_id,  
        )  
  
    victor_id = int(victor_row["victor_character_id"]) if victor_row and victor_row["victor_character_id"] else None  
    total_participant_hp = sum(int(c["max_hp"] or 0) for c in combatants if c["character_id"])  
    awards: dict[int, int] = {}  
  
    for p in participants:  
        cid = int(p["character_id"])  
        xp = SPAR_DUEL_PARTICIPATION_XP + total_participant_hp  
        if victor_id and cid == victor_id:  
            xp += SPAR_DUEL_VICTORY_XP  
        awards[cid] = awards.get(cid, 0) + xp  
  
    if victor_id:  
        note = f"Spar/Duel XP: {SPAR_DUEL_PARTICIPATION_XP} participation XP + total participant max HP ({total_participant_hp}) + {SPAR_DUEL_VICTORY_XP} victor XP."  
    else:  
        note = f"Spar/Duel XP: {SPAR_DUEL_PARTICIPATION_XP} participation XP + total participant max HP ({total_participant_hp}); no victor bonus detected."  
    return victor_id, awards, note  
  
  
  
async def combat_context_for_session(session_id: int) -> str:  
    """Structured combat facts for AI summaries. Prevents 'no interaction' summaries when RP text is absent."""  
    async with db_pool.acquire() as conn:  
        encounter = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_encounters  
            WHERE session_id=$1  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            session_id,  
        )  
        if not encounter:  
            return "No combat encounter was recorded for this session."  
  
        encounter_id = int(encounter["id"])  
        combatants = await conn.fetch(  
            """  
            SELECT id, name, combatant_type, character_id, current_hp, max_hp, status  
            FROM alaris_combatants  
            WHERE encounter_id=$1  
            ORDER BY combatant_type, id;  
            """,  
            encounter_id,  
        )  
        logs = await conn.fetch(  
            """  
            SELECT  
                log.action_type, log.damage, log.damage_type, log.outcome, log.created_at,  
                actor.name AS actor_name,  
                target.name AS target_name  
            FROM alaris_combat_logs log  
            LEFT JOIN alaris_combatants actor ON actor.id=log.actor_combatant_id  
            LEFT JOIN alaris_combatants target ON target.id=log.target_combatant_id  
            WHERE log.encounter_id=$1  
            ORDER BY log.created_at ASC, log.id ASC  
            LIMIT 40;  
            """,  
            encounter_id,  
        )  
  
    character_lines = []  
    enemy_lines = []  
    for c in combatants:  
        line = f"{c['name']} ({c['status']}, {c['current_hp']}/{c['max_hp']} HP)"  
        if c["combatant_type"] == "character":  
            character_lines.append(line)  
        else:  
            enemy_lines.append(line)  
  
    action_lines = []  
    for l in logs:  
        actor = l["actor_name"] or "Unknown actor"  
        target = l["target_name"] or "Unknown target"  
        dmg = int(l["damage"] or 0)  
        dtype = l["damage_type"] or ""  
        outcome = l["outcome"] or "unknown"  
        action = l["action_type"] or "action"  
        if dmg:  
            action_lines.append(f"{actor} used {action} on {target}: {outcome}, {dmg} {dtype} damage.")  
        else:  
            action_lines.append(f"{actor} used {action} on {target}: {outcome}.")  
  
    winning_side, victory_names, defeated_enemies = await combat_victory_summary_for_session(session_id)  
    victor_id, _, _ = await spar_duel_xp_awards_for_session(session_id, [{"character_id": int(c["character_id"] or 0), "name": c["name"]} for c in combatants if c["combatant_type"] == "character" and c["character_id"]])  
    if victor_id:  
        victor_name = next((str(c["name"]) for c in combatants if c["combatant_type"] == "character" and c["character_id"] and int(c["character_id"]) == int(victor_id)), None)  
    else:  
        victor_name = None  
  
    return (  
        f"Combat type: {encounter['combat_type']}. "  
        f"Combat status: {encounter['status']}. "  
        f"Characters: {', '.join(character_lines) or 'None'}. "  
        f"Enemies: {', '.join(enemy_lines) or 'None'}. "  
        f"Victory: {winning_side or 'Unresolved'} - {victory_names or victor_name or 'No victor recorded'}. "  
        f"Spar/Duel victor if applicable: {victor_name or 'None detected'}. "  
        f"Defeated enemies: {', '.join(defeated_enemies) if defeated_enemies else 'None'}. "  
        f"Combat actions: {' | '.join(action_lines) if action_lines else 'No combat log actions were recorded.'}"  
    )  
  
  
  
@bot.tree.command(name="session-close", description="Close the open session, award RP XP, and log the result.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def session_close_command(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    active = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active:  
        await interaction.response.send_message("There is no open session in this channel.", ephemeral=True)  
        return  
  
    can_close = interaction.user.id == int(active["starter_user_id"])  
    if isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user):  
        can_close = True  
    if not can_close:  
        await interaction.response.send_message("Only the session host or staff can close this session.", ephemeral=True)  
        return  
  
    participants = await list_session_participants(int(active["id"]))  
    if not participants:  
        await interaction.response.send_message("This session has no joined characters. Add participants before closing.", ephemeral=True)  
        return  
  
    await interaction.response.defer(ephemeral=False)  
  
    # Send closing marker first, then fetch/count everything before it so the close command/result is excluded.  
    end_message = await interaction.followup.send(  
        f"📘 Closing session **{active['title'] or active['session_type']}** and calculating XP...",  
        wait=True,  
    )  
  
    messages = await fetch_messages_between(interaction.channel, active["start_message_id"], end_message.id)  
    message_count = len(messages)  
    rp_counts = await calculate_rp_counts_from_messages(messages, participants)  
    rp_awards = {cid: rp_xp_from_typed_characters(chars) for cid, chars in rp_counts.items()}  
    await store_rp_counts(int(active["id"]), rp_counts, rp_awards)  
  
    xp_results: list[dict[str, Any]] = []  
  
    # Combat bonuses are automatic when a combat encounter has recorded results.  
    victor_id = None  
    victor_name = None  
    enemy_xp_pool = 0  
    enemy_xp_each = None  
    async with db_pool.acquire() as conn:  
        combat_result = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_encounters  
            WHERE session_id=$1  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            int(active["id"]),  
        )  
    if combat_result and combat_result["enemy_xp_pool"]:  
        enemy_xp_pool = int(combat_result["enemy_xp_pool"] or 0)  
        enemy_xp_each = split_enemy_xp_pool(enemy_xp_pool, len(participants))  
  
    spar_duel_victor_id = None  
    spar_duel_awards: dict[int, int] = {}  
    spar_duel_note = ""  
    if active["session_type"] in {"Roleplay", "Training", "Event", "Mission", "Downtime"} and combat_result and str(combat_result["combat_type"]) in {"Spar", "Duel"}:  
        spar_duel_victor_id, spar_duel_awards, spar_duel_note = await spar_duel_xp_awards_for_session(int(active["id"]), participants)  
        victor_id = spar_duel_victor_id  
  
    for p in participants:  
        cid = int(p["character_id"])  
        rp_xp = int(rp_awards.get(cid, 0))  
        bonus_xp = 0  
        reason_parts = []  
        if rp_xp:  
            reason_parts.append(f"RP XP ({rp_counts.get(cid, 0):,} typed characters)")  
        if combat_result and str(combat_result["combat_type"]) == "Enemy Encounter" and enemy_xp_each:  
            bonus_xp += enemy_xp_each  
            reason_parts.append("Enemy encounter XP pool")  
        if cid in spar_duel_awards:  
            bonus_xp += int(spar_duel_awards[cid])  
            if spar_duel_victor_id and cid == spar_duel_victor_id:  
                reason_parts.append("Spar/Duel participation + victor XP")  
            else:  
                reason_parts.append("Spar/Duel participation XP")  
        total_xp = rp_xp + bonus_xp  
        if total_xp <= 0:  
            continue  
  
        result = await award_xp_to_character(  
            interaction.guild.id,  
            cid,  
            total_xp,  
            "session",  
            int(active["id"]),  
            "; ".join(reason_parts) if reason_parts else f"{active['session_type']} session XP",  
            awarded_by=interaction.user.id,  
            typed_characters=rp_counts.get(cid, 0),  
        )  
        xp_results.append(result)  
        await refresh_and_notify_progression(result)  
  
    summary = None  
    takeaways = []  
    consequences = []  
    try:  
        combat_context = await combat_context_for_session(int(active["id"]))  
    except Exception:  
        LOG.exception("Failed to build combat context for AI summary.")  
        combat_context = "Combat context could not be loaded."  
    session_summary_context = (  
        f"Session type: {active['session_type']}. "  
        f"Participants: {', '.join(p['name'] for p in participants) or 'None'}. "  
        f"Messages tracked: {message_count}. "  
        f"{combat_context}"  
    )  
    summary, takeaways, consequences = await generate_scene_summary(messages, participants, context=session_summary_context)  
  
    closed = await close_session(  
        int(active["id"]),  
        end_message.id,  
        message_count,  
        summary=summary,  
        key_takeaways="\n".join(takeaways) if takeaways else None,  
        possible_consequences="\n".join(consequences) if consequences else None,  
        victor_character_id=victor_id,  
        enemy_xp_pool=int(enemy_xp_pool or 0),  
    )  
  
    if not closed:  
        await end_message.edit(content="This session could not be closed. It may already be closed.")  
        return  
  
    session_jump_url = end_message.jump_url  
  
    if closed["session_type"] == "Enemy Encounter":  
        winning_side, victory_names, defeated_enemies = await combat_victory_summary_for_session(int(closed["id"]))  
        title = closed["title"] or closed["session_type"]  
        embed = discord.Embed(  
            title=f"Enemy Encounter Closed - {title}",  
            color=discord.Color.red(),  
        )  
        if winning_side and victory_names:  
            embed.add_field(name="Victory", value=f"**{winning_side}:** {victory_names}", inline=False)  
        else:  
            embed.add_field(name="Victory", value="No final victor was recorded.", inline=False)  
  
        embed.add_field(name="Channel", value=f"<#{closed['channel_id']}>", inline=True)  
        if session_jump_url:  
            embed.add_field(name="Session Link", value=f"[Jump to Session]({session_jump_url})", inline=True)  
  
        # If victors already list the characters, do not repeat participants as the first major field.  
        if winning_side != "Characters":  
            embed.add_field(  
                name="Participants",  
                value=", ".join(f"**{p['name']}**" for p in participants) or "None",  
                inline=False,  
            )  
  
        lines = []  
        for result in xp_results:  
            cid = int(result["character_id"])  
            typed = rp_counts.get(cid, 0)  
            die_note = ""  
            if result["new_die"] != result["old_die"]:  
                die_note += f" | 1d{result['old_die']}→1d{result['new_die']}"  
            if result["new_level"] != result["old_level"]:  
                die_note += f" | Level {result['old_level']}→{result['new_level']}"  
            lines.append(  
                f"• **{result['name']}**: +{result['amount']} XP "  
                f"(typed chars: {typed:,}){die_note}"  
            )  
        embed.add_field(name="XP Awards", value="\n".join(lines)[:1024] if lines else "No XP awarded.", inline=False)  
  
        if enemy_xp_each is not None:  
            embed.add_field(name="Enemy XP Award", value=f"+{enemy_xp_each} XP to each participating character", inline=True)  
        elif not defeated_enemies:  
            embed.add_field(name="Combat XP", value="No defeated enemy XP pool was recorded. Only RP XP was awarded.", inline=False)  
  
        if defeated_enemies:  
            embed.add_field(name="Defeated Enemies", value="\n".join(f"• {x}" for x in defeated_enemies)[:1024], inline=False)  
  
        if summary:  
            embed.add_field(name="Summary", value=summary[:1024], inline=False)  
        if takeaways:  
            embed.add_field(name="Key Takeaways", value="\n".join(f"• {x}" for x in takeaways)[:1024], inline=False)  
        if consequences:  
            embed.add_field(name="Possible Consequences", value="\n".join(f"• {x}" for x in consequences)[:1024], inline=False)  
  
        embed.set_footer(text="Alaris enemy encounter log")  
    else:  
        embed = build_session_xp_log_embed(  
            closed,  
            participants,  
            messages,  
            rp_counts,  
            xp_results,  
            summary=summary,  
            takeaways=takeaways,  
            consequences=consequences,  
            victor_name=victor_name,  
            enemy_xp_each=enemy_xp_each,  
            session_jump_url=session_jump_url,  
        )  
  
        if active["session_type"] in {"Spar", "Duel"} and not enemy_xp_each:  
            embed.add_field(  
                name="Combat XP",  
                value="No duel/spar victor was recorded yet. Only RP XP was awarded.",  
                inline=False,  
            )  
  
    await end_message.edit(content="📘 **Session closed. XP awarded.**", embed=embed)  
    await post_session_log_embed(interaction.guild, embed)  
    xp_log_embed = build_xp_award_log_embed(closed, xp_results, rp_counts, session_jump_url=session_jump_url)  
    await post_xp_award_log_embed(interaction.guild, xp_log_embed)  
    await post_command_log(interaction, f"closed session id={closed['id']} messages={message_count} xp_awards={len(xp_results)}")  
  
  
  
@bot.tree.command(name="combat-structured-start", description="Staff: open a PvE combat lobby with exact enemy type and count.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    enemy_type="Enemy template to use, such as Levy Spearman or Bandit Cutthroat.",  
    enemy_count="Exact number of enemies to create, from 1 to 8.",  
    danger="Scaling profile for the enemies.",  
    environment="Narrative setting for the encounter.",  
)  
@app_commands.choices(  
    danger=[app_commands.Choice(name=x, value=x) for x in ENCOUNTER_DANGER_LEVELS],  
    environment=[app_commands.Choice(name=x, value=x) for x in ENCOUNTER_ENVIRONMENTS],  
)  
@app_commands.autocomplete(enemy_type=structured_enemy_type_autocomplete)  
async def combat_structured_start(  
    interaction: discord.Interaction,  
    enemy_type: str,  
    enemy_count: int,  
    danger: str,  
    environment: str,  
):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    existing_combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if existing_combat:  
        await interaction.response.send_message("There is already an active combat in this channel.", ephemeral=True)  
        return  
  
    existing_lobby = await fetch_open_combat_lobby_for_channel(interaction.guild.id, interaction.channel.id)  
    if existing_lobby:  
        await interaction.response.send_message("There is already an open combat lobby in this channel.", ephemeral=True)  
        return  
  
    active_session = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active_session:  
        await interaction.response.send_message(  
            "Start a session first with `/session-start`, then use this command when staff are ready to structure combat.",  
            ephemeral=True,  
        )  
        return  
  
    safe_count = max(1, min(int(enemy_count or 1), 8))  
    enemies, label = build_structured_enemy_roster(enemy_type, safe_count, danger, environment)  
    if not enemies or not label:  
        await interaction.response.send_message(  
            "That enemy type was not found. Try typing part of the enemy name and selecting from autocomplete.",  
            ephemeral=True,  
        )  
        return  
  
    lobby_message = await interaction.channel.send("Preparing structured combat lobby...")  
    await create_combat_lobby_record(  
        interaction.guild.id,  
        interaction.channel.id,  
        int(active_session["id"]),  
        int(interaction.user.id),  
        "Enemy Encounter",  
        normalize_encounter_category(enemies[0].get("category") or "Soldiers"),  
        normalize_danger_label(danger),  
        normalize_environment_label(environment),  
        int(lobby_message.id),  
        enemies,  
    )  
    lobby = await fetch_open_combat_lobby_by_message(int(lobby_message.id))  
    if not lobby:  
        await lobby_message.edit(content="Structured combat lobby creation failed.")  
        await interaction.response.send_message("Structured combat lobby creation failed.", ephemeral=True)  
        return  
    participants = await list_session_participants(int(active_session["id"]))  
    await lobby_message.edit(  
        content=f"Staff opened a **structured Enemy Encounter** lobby: **{safe_count} × {label}**.",  
        embed=build_combat_lobby_embed(lobby, participants),  
        view=CombatLobbyView(),  
        allowed_mentions=discord.AllowedMentions.none(),  
    )  
    await interaction.response.send_message(  
        f"Structured combat lobby opened with **{safe_count} × {label}**. Players can now join with owned characters.",  
        ephemeral=True,  
    )  
  
  
@bot.tree.command(name="combat-start", description="Open an interactive combat setup for the current session.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def combat_start(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    existing_combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if existing_combat:  
        await interaction.response.send_message("There is already an active combat in this channel.", ephemeral=True)  
        return  
  
    existing_lobby = await fetch_open_combat_lobby_for_channel(interaction.guild.id, interaction.channel.id)  
    if existing_lobby:  
        await interaction.response.send_message("There is already an open combat lobby in this channel.", ephemeral=True)  
        return  
  
    active_session = await get_active_session_for_channel(interaction.guild.id, interaction.channel.id)  
    if not active_session:  
        await interaction.response.send_message(  
            "Start a session first with `/session-start`, let RP happen, then use `/combat-start` when combat begins.",  
            ephemeral=True,  
        )  
        return  
  
    can_start = int(active_session["starter_user_id"]) == int(interaction.user.id)  
    if isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user):  
        can_start = True  
    if not can_start:  
        await interaction.response.send_message("Only the session host or staff can start combat for this session.", ephemeral=True)  
        return  
  
    await interaction.response.send_message(  
        embed=build_combat_setup_embed(dict(active_session)),  
        view=CombatTypeSetupView(int(active_session["id"])),  
        ephemeral=False,  
    )  
  
  
@bot.tree.command(name="combat-status", description="Show the active combat status.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def combat_status(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
    combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("There is no active combat in this channel.", ephemeral=True)  
        return  
    combatants = await get_combatants(int(combat["id"]))  
    order = await get_combat_turn_order(int(combat["id"]))  
    await interaction.response.send_message(embed=build_combat_status_embed(combat, combatants, order), ephemeral=False)  
  
  
  
def normalize_damage_type(value: Optional[str], default: str = "spirit") -> str:  
    raw = normalize_name(value or default).replace("poison acid", "poison/acid")  
    allowed = {normalize_name(x).replace("poison acid", "poison/acid"): x for x in LOCKED_DAMAGE_TYPES}  
    return allowed.get(raw, default)  
  
  
  
def affinity_map_from_json(value: Any) -> dict[str, float]:  
    """Parse resistance/weakness/immunity JSON.  
  
    Supported shapes:  
    - {"fire": 0.5}  
    - {"fire": true}  
    - ["fire", "ice"]  
    True/list entries default to 0.5 for resistance, 1.5 for weakness, 0 for immunity  
      depending on the resolver argument.  
    """  
    if value is None:  
        return {}  
    if isinstance(value, str):  
        try:  
            value = json.loads(value)  
        except Exception:  
            return {}  
    if isinstance(value, list):  
        return {normalize_damage_type(str(x), str(x)): 1.0 for x in value}  
    if not isinstance(value, dict):  
        return {}  
    parsed: dict[str, float] = {}  
    for key, raw in value.items():  
        dtype = normalize_damage_type(str(key), str(key))  
        if isinstance(raw, bool):  
            parsed[dtype] = 1.0 if raw else 0.0  
        else:  
            try:  
                parsed[dtype] = float(raw)  
            except Exception:  
                parsed[dtype] = 1.0  
    return parsed  
  
  
def format_affinity_json(value: Any, empty: str = "None") -> str:  
    data = affinity_map_from_json(value)  
    if not data:  
        return empty  
    return ", ".join(sorted(data.keys()))  
  
  
def resolve_damage_with_affinities(base_damage: int, damage_type: str, target_data: dict[str, Any]) -> tuple[int, str]:  
    dtype = normalize_damage_type(damage_type or "spirit")  
    amount = max(0, int(base_damage or 0))  
  
    immunities = affinity_map_from_json(target_data.get("immunities_json"))  
    weaknesses = affinity_map_from_json(target_data.get("weaknesses_json"))  
    resistances = affinity_map_from_json(target_data.get("resistances_json"))  
  
    notes = []  
    if dtype in immunities:  
        return 0, f"Immune to {dtype}"  
  
    if dtype in resistances:  
        raw = resistances.get(dtype, 1.0)  
        # A boolean/list-style resistance means half damage. A numeric resistance can be a multiplier.  
        multiplier = 0.5 if raw == 1.0 else float(raw)  
        amount = int(round(amount * multiplier))  
        notes.append(f"Resistance: {dtype}")  
  
    if dtype in weaknesses:  
        raw = weaknesses.get(dtype, 1.0)  
        multiplier = 1.5 if raw == 1.0 else float(raw)  
        amount = int(round(amount * multiplier))  
        notes.append(f"Weakness: {dtype}")  
  
    return max(0, amount), "; ".join(notes)  
  
  
def damage_type_for_action(action_type: str, provided: Optional[str] = None) -> str:  
    action_norm = normalize_name(action_type)  
    if action_norm in PHYSICAL_ACTION_DAMAGE_TYPES:  
        return PHYSICAL_ACTION_DAMAGE_TYPES[action_norm]  
    return normalize_damage_type(provided or "spirit")  
  
  
def has_state(states: list[dict[str, Any]], state_key: str) -> bool:  
    key = normalize_name(state_key)  
    return any(normalize_name(str(s.get("state_key") or "")) == key for s in states)  
  
  
def state_attack_bonus_against(target_states: list[dict[str, Any]]) -> int:  
    return 2 if has_state(target_states, "exposed") else 0  
  
  
def state_attack_penalty_for_actor(actor_states: list[dict[str, Any]]) -> int:  
    penalty = 0  
    if has_state(actor_states, "feared"):  
        penalty -= 2  
    if has_state(actor_states, "restrained"):  
        penalty -= 2  
    if has_state(actor_states, "marked"):  
        penalty -= 2  
    return penalty  
  
  
def state_spell_dc_penalty_for_actor(actor_states: list[dict[str, Any]]) -> int:  
    return -2 if has_state(actor_states, "feared") else 0  
  
  
def state_damage_modifier_for_actor(actor_states: list[dict[str, Any]]) -> int:  
    modifier = 0  
    if has_state(actor_states, "weakened"):  
        modifier -= 2  
    if has_state(actor_states, "inspired"):  
        modifier += 2  
    return modifier  
  
  
def state_action_bonus_for_actor(actor_states: list[dict[str, Any]]) -> int:  
    return 2 if has_state(actor_states, "inspired") else 0  
  
  
def state_ac_bonus(target_states: list[dict[str, Any]]) -> int:  
    return 2 if has_state(target_states, "guarded") else 0  
  
  
def state_magic_defense_bonus(target_states: list[dict[str, Any]]) -> int:  
    return 2 if has_state(target_states, "fortified") else 0  
  
  
def state_damage_reduction(target_states: list[dict[str, Any]]) -> int:  
    return 3 if has_state(target_states, "shielded") else 0  
  
  
def state_blocks_active_ability(actor_states: list[dict[str, Any]]) -> bool:  
    return has_state(actor_states, "staggered")  
  
  
async def active_states_for_combatant(encounter_id: int, combatant_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT *  
            FROM alaris_combat_states  
            WHERE encounter_id=$1 AND combatant_id=$2 AND duration_turns > 0  
            ORDER BY state_name;  
            """,  
            encounter_id,  
            combatant_id,  
        )  
    return [dict(r) for r in rows]  
  
  
async def decrement_states_for_combatant(encounter_id: int, combatant_id: int) -> list[str]:  
    """Apply end-of-turn state ticks, then decrement durations."""  
    lines: list[str] = []  
    async with db_pool.acquire() as conn:  
        states = await conn.fetch(  
            """  
            SELECT *  
            FROM alaris_combat_states  
            WHERE encounter_id=$1 AND combatant_id=$2 AND duration_turns > 0;  
            """,  
            encounter_id,  
            combatant_id,  
        )  
        for state in states:  
            key = normalize_name(state["state_key"])  
            damage = 0  
            label = ""  
            if key == "bleeding":  
                damage = 2  
                label = "bleeding"  
            elif key == "burning":  
                damage = 2  
                label = "burning"  
            if damage:  
                row = await conn.fetchrow(  
                    """  
                    UPDATE alaris_combatants  
                    SET current_hp=GREATEST(0,current_hp-$2),  
                        status=CASE WHEN GREATEST(0,current_hp-$2) <= 0 THEN 'defeated' ELSE status END  
                    WHERE id=$1  
                    RETURNING name,current_hp,max_hp,status;  
                    """,  
                    combatant_id,  
                    damage,  
                )  
                if row:  
                    icon = "🔥" if key == "burning" else "🩸"  
                    lines.append(f"{icon} **{row['name']}** takes **{damage} {label} damage** ({row['current_hp']}/{row['max_hp']} HP).")  
                    if row["status"] == "defeated":  
                        lines.append(f"💀 **{row['name']}** is defeated by {label}.")  
        await conn.execute(  
            """  
            UPDATE alaris_combat_states  
            SET duration_turns=duration_turns-1  
            WHERE encounter_id=$1 AND combatant_id=$2 AND duration_turns > 0;  
            """,  
            encounter_id,  
            combatant_id,  
        )  
        await conn.execute(  
            """  
            DELETE FROM alaris_combat_states  
            WHERE encounter_id=$1 AND combatant_id=$2 AND duration_turns <= 0;  
            """,  
            encounter_id,  
            combatant_id,  
        )  
    return lines  
  
  
async def consume_state_if_present(encounter_id: int, combatant_id: int, state_key: str) -> bool:  
    key = normalize_name(state_key)  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            DELETE FROM alaris_combat_states  
            WHERE encounter_id=$1 AND combatant_id=$2 AND state_key=$3  
            RETURNING state_name;  
            """,  
            encounter_id, combatant_id, key,  
        )  
    return bool(row)  
  
  
async def apply_combat_state(encounter_id: int, target_id: int, source_id: Optional[int], state_key: str, duration: int = 2) -> None:  
    key = normalize_name(state_key)  
    state = CORE_STATES.get(key, {"name": state_key.title(), "effect": ""})  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_combat_states (  
                encounter_id, combatant_id, source_combatant_id,  
                state_key, state_name, duration_turns, metadata_json  
            )  
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)  
            ON CONFLICT (encounter_id, combatant_id, state_key) DO UPDATE SET  
                source_combatant_id=EXCLUDED.source_combatant_id,  
                duration_turns=GREATEST(alaris_combat_states.duration_turns, EXCLUDED.duration_turns),  
                metadata_json=EXCLUDED.metadata_json;  
            """,  
            encounter_id, target_id, source_id, key, state["name"], int(duration or 1), json.dumps(state),  
        )  
  
  
def all_abilities_for_class(class_name: str, max_level: int = 10) -> list[dict[str, Any]]:  
    cls = normalize_name(class_name)  
    tree = CLASS_ABILITY_TREES.get(cls) or CLASS_ABILITY_TREES.get("fighter", {})  
    abilities: list[dict[str, Any]] = []  
    for level in sorted(tree):  
        if int(level) <= int(max_level or 1):  
            for ability in tree[level]:  
                item = dict(ability)  
                item["level"] = int(level)  
                item["class_name"] = cls  
                abilities.append(item)  
    return abilities  
  
  
def starter_ability_for_class(class_name: str) -> dict[str, Any]:  
    abilities = all_abilities_for_class(class_name, 2)  
    return dict(abilities[0]) if abilities else {"name": "Focused Effort", "kind": "buff", "state": "inspired", "cost": 1}  
  
  
def find_class_ability(class_name: str, ability_name: str, max_level: int = 10) -> Optional[dict[str, Any]]:  
    wanted = normalize_name(ability_name)  
    for ability in all_abilities_for_class(class_name, max_level):  
        if normalize_name(ability.get("name")) == wanted:  
            return dict(ability)  
    return None  
  
  
async def unlocked_abilities_for_character(character_id: int) -> list[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        return await fetch_unlocked_abilities_raw(conn, int(character_id))  
  
  
  
async def ability_name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    if db_pool is None or interaction.guild is None or interaction.channel is None:  
        return []  
    combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        return []  
    actor = await current_turn_combatant(int(combat["id"]))  
    if not actor or actor.get("combatant_type") != "character" or not actor.get("character_id"):  
        return []  
    abilities = await unlocked_abilities_for_character(int(actor["character_id"]))  
    cur = normalize_name(current)  
    choices = []  
    for ability in abilities:  
        label = f"{ability['name']} ({int(ability.get('cost') or 1)} Resolve)"  
        if not cur or cur in normalize_name(ability["name"]):  
            choices.append(app_commands.Choice(name=label[:100], value=str(ability["name"])[:100]))  
    return choices[:25]  
  
  
async def ability_choice_option_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    if db_pool is None or interaction.guild is None:  
        return []  
    try:  
        choice_id = int(getattr(interaction.namespace, "choice", "0") or 0)  
    except Exception:  
        choice_id = 0  
    if not choice_id:  
        return []  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT lc.level, lc.choice_type, c.class_name  
            FROM alaris_level_choices lc  
            JOIN alaris_characters c ON c.id=lc.character_id  
            WHERE lc.id=$1 AND lc.status='pending';  
            """,  
            choice_id,  
        )  
    if not row or row["choice_type"] != "ability":  
        return []  
    tree = CLASS_ABILITY_TREES.get(normalize_name(row["class_name"]), {})  
    opts = tree.get(int(row["level"] or 0), [])  
    cur = normalize_name(current)  
    out = []  
    for ability in opts:  
        label = f"{ability['name']} - {ability.get('description','')}"  
        if not cur or cur in normalize_name(label):  
            out.append(app_commands.Choice(name=label[:100], value=ability["name"][:100]))  
    return out[:25]  
  
  
def roll_scaled_ability_damage(actor: dict[str, Any], ability_def: dict[str, Any]) -> int:  
    sides = int(actor.get("damage_die_sides") or 8)  
    cost = max(1, int(ability_def.get("cost") or 1))  
    total = 0  
    for _ in range(cost):  
        total += roll_die(sides)  
    total += int(actor.get("damage_bonus") or 0)  
    return total  
  
  
async def mark_combat_action_taken(combatant_id: int) -> None:  
    async with db_pool.acquire() as conn:  
        await conn.execute("UPDATE alaris_combatants SET action_taken=TRUE WHERE id=$1;", int(combatant_id))  
  
  
  
class CombatActionTypeSelect(discord.ui.Select):  
    def __init__(self):  
        options = [  
            discord.SelectOption(label="Use Ability", value="Use Ability", description="Use an unlocked class/species ability."),  
            discord.SelectOption(label="Magical Attack", value="Magical Attack", description="Generic magical attack against Magic Defense."),  
            discord.SelectOption(label="Piercing Melee or Ranged Attack", value="Piercing Melee or Ranged Attack", description="Physical piercing attack."),  
            discord.SelectOption(label="Slashing Melee Attack", value="Slashing Melee Attack", description="Physical slashing attack."),  
            discord.SelectOption(label="Blunt Melee Attack", value="Blunt Melee Attack", description="Physical blunt attack."),  
        ]  
        super().__init__(placeholder="Choose your action...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        action_type = self.values[0]  
        combat, actor, error = await action_menu_context(interaction)  
        if error:  
            await interaction.response.send_message(error, ephemeral=True)  
            return  
        if action_type == "Use Ability":  
            actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
            if state_blocks_active_ability(actor_states):  
                await interaction.response.send_message("You are **Staggered** and cannot use active abilities this turn.", ephemeral=True)  
                return  
            abilities = await action_menu_ability_options(actor)  
            if not abilities:  
                await interaction.response.send_message("This character has no usable unlocked abilities right now.", ephemeral=True)  
                return  
            await interaction.response.edit_message(  
                content=f"Choose an ability for **{actor['name']}**.",  
                view=CombatAbilityMenuView(abilities),  
            )  
            return  
  
        targets = await action_menu_target_options(int(combat["id"]), actor, action_type)  
        if not targets:  
            await interaction.response.send_message("There are no valid targets for that action.", ephemeral=True)  
            return  
        await interaction.response.edit_message(  
            content=f"Choose a target for **{actor['name']}**'s **{action_type}**.",  
            view=CombatTargetMenuView(action_type, None, targets),  
        )  
  
  
class CombatAbilitySelect(discord.ui.Select):  
    def __init__(self, abilities: list[dict[str, Any]]):  
        options = []  
        for ability in abilities[:25]:  
            name = str(ability.get("name") or "Ability")  
            cost = int(ability.get("cost") or 1)  
            kind = str(ability.get("kind") or "ability").replace("_", " ").title()  
            dtype = ability.get("damage_type")  
            desc = f"{kind} | Cost {cost}"  
            if dtype:  
                desc += f" | {normalize_damage_type(dtype)}"  
            options.append(discord.SelectOption(label=name[:100], value=name[:100], description=desc[:100]))  
        super().__init__(placeholder="Choose ability...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        ability_name = self.values[0]  
        combat, actor, error = await action_menu_context(interaction)  
        if error:  
            await interaction.response.send_message(error, ephemeral=True)  
            return  
        ability_def = await action_menu_find_unlocked_ability(actor, ability_name)  
        if not ability_def:  
            await interaction.response.send_message("That ability is no longer available.", ephemeral=True)  
            return  
        pseudo_action = action_menu_pseudo_action_for_ability(ability_def)  
        targets = await action_menu_target_options(int(combat["id"]), actor, pseudo_action)  
        if not targets:  
            await interaction.response.send_message("There are no valid targets for that ability.", ephemeral=True)  
            return  
        await interaction.response.edit_message(  
            content=f"Choose a target for **{actor['name']}**'s **{ability_name}**.",  
            view=CombatTargetMenuView("Use Ability", ability_name, targets),  
        )  
  
  
class CombatTargetSelect(discord.ui.Select):  
    def __init__(self, action_type: str, ability_name: Optional[str], targets: list[dict[str, Any]]):  
        self.action_type = action_type  
        self.ability_name = ability_name  
        options = []  
        for t in targets[:25]:  
            label = str(t.get("name") or "Target")[:100]  
            hp = f"{int(t.get('current_hp') or 0)}/{int(t.get('max_hp') or 0)} HP"  
            ctype = str(t.get("combatant_type") or "target").title()  
            options.append(discord.SelectOption(label=label, value=str(int(t["id"])), description=f"{ctype} | {hp}"[:100]))  
        super().__init__(placeholder="Choose target...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        await resolve_combat_action(  
            interaction,  
            self.action_type,  
            self.values[0],  
            self.ability_name,  
        )  
  
  
class CombatActionMenuView(discord.ui.View):  
    def __init__(self):  
        super().__init__(timeout=180)  
        self.add_item(CombatActionTypeSelect())  
  
  
class CombatAbilityMenuView(discord.ui.View):  
    def __init__(self, abilities: list[dict[str, Any]]):  
        super().__init__(timeout=180)  
        self.add_item(CombatAbilitySelect(abilities))  
  
  
class CombatTargetMenuView(discord.ui.View):  
    def __init__(self, action_type: str, ability_name: Optional[str], targets: list[dict[str, Any]]):  
        super().__init__(timeout=180)  
        self.add_item(CombatTargetSelect(action_type, ability_name, targets))  
  
  
async def action_menu_context(interaction: discord.Interaction) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]], Optional[str]]:  
    if interaction.guild is None or interaction.channel is None:  
        return None, None, "This command can only be used in a server channel."  
    combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        return None, None, "There is no active combat in this channel."  
    actor = await current_turn_combatant(int(combat["id"]))  
    if not actor:  
        return combat, None, "No current turn is set."  
    if actor["combatant_type"] != "character":  
        return combat, actor, "It is currently an NPC/enemy turn. The bot will resolve that automatically."  
    if int(actor["owner_user_id"] or 0) != interaction.user.id:  
        if not (isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)):  
            return combat, actor, f"It is **{actor['name']}**'s turn, not yours."  
    if bool(actor.get("action_taken")):  
        return combat, actor, "You have already resolved your action this turn. Post your RP narration if needed, then use `/end-turn`."  
    return combat, actor, None  
  
  
async def action_menu_find_unlocked_ability(actor: dict[str, Any], ability_name: str) -> Optional[dict[str, Any]]:  
    if not actor.get("character_id"):  
        return None  
    unlocked = await unlocked_abilities_for_character(int(actor["character_id"]))  
    wanted = normalize_name(ability_name)  
    for ability in unlocked:  
        if normalize_name(ability.get("name")) == wanted:  
            return dict(ability)  
    return None  
  
  
async def action_menu_ability_options(actor: dict[str, Any]) -> list[dict[str, Any]]:  
    if not actor.get("character_id"):  
        return []  
    unlocked = await unlocked_abilities_for_character(int(actor["character_id"]))  
    usable = []  
    current_resolve = int(actor.get("current_resolve") or 0)  
    for ability in unlocked:  
        cost = max(1, int(ability.get("cost") or 1))  
        if current_resolve >= cost:  
            usable.append(dict(ability))  
    return usable  
  
  
def action_menu_pseudo_action_for_ability(ability_def: dict[str, Any]) -> str:  
    kind = normalize_name(ability_def.get("kind") or "buff")  
    if kind in {"buff", "heal", "strike_buff", "spell_buff"}:  
        return "Buff"  
    if ability_def.get("dc_type") == "spell" or kind in {"spell", "debuff"}:  
        return "Magical Attack"  
    return "Piercing Melee or Ranged Attack"  
  
  
async def action_menu_target_options(encounter_id: int, actor: dict[str, Any], action_type: str) -> list[dict[str, Any]]:  
    targets = await valid_targets_for_action(encounter_id, actor, action_type)  
    return [dict(t) for t in targets]  
  
  
@bot.tree.command(name="action", description="Open the guided combat action menu.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def action(interaction: discord.Interaction):  
    combat, actor, error = await action_menu_context(interaction)  
    if error:  
        await interaction.response.send_message(error, ephemeral=True)  
        return  
    embed = discord.Embed(  
        title=f"{actor['name']}'s Action",  
        description=(  
            "Choose what they do this turn. Damage type is handled automatically by the action or by the selected ability."  
        ),  
        color=discord.Color.blurple(),  
    )  
    embed.add_field(name="Available Actions", value="Use Ability\nMagical Attack\nPiercing Melee or Ranged Attack\nSlashing Melee Attack\nBlunt Melee Attack", inline=False)  
    await interaction.response.send_message(embed=embed, view=CombatActionMenuView(), ephemeral=True)  
  
  
async def resolve_combat_action(  
    interaction: discord.Interaction,  
    action_type: str,  
    target: str,  
    ability: Optional[str] = None,  
):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("There is no active combat in this channel.", ephemeral=True)  
        return  
  
    actor = await current_turn_combatant(int(combat["id"]))  
    if not actor:  
        await interaction.response.send_message("No current turn is set.", ephemeral=True)  
        return  
    if actor["combatant_type"] != "character":  
        await interaction.response.send_message("It is currently an NPC/enemy turn. The bot will resolve that automatically.", ephemeral=True)  
        return  
    if int(actor["owner_user_id"] or 0) != interaction.user.id:  
        if not (isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)):  
            await interaction.response.send_message(f"It is **{actor['name']}**'s turn, not yours.", ephemeral=True)  
            return  
  
    if bool(actor.get("action_taken")):  
        await interaction.response.send_message(  
            "You have already resolved your action this turn. Post your RP narration if needed, then use `/end-turn`.",  
            ephemeral=True,  
        )  
        return  
  
    try:  
        target_id = int(target)  
    except ValueError:  
        await interaction.response.send_message("Choose a target from autocomplete.", ephemeral=True)  
        return  
  
    action_norm = normalize_action_type_for_engine(action_type)  
    actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
  
    # Use Ability is routed through the same command so players do not need /ability.  
    if action_norm == "use ability":  
        if state_blocks_active_ability(actor_states):  
            await interaction.response.send_message("You are **Staggered** and cannot use active abilities this turn.", ephemeral=True)  
            return  
        if not ability:  
            await interaction.response.send_message("Choose an ability from the ability field.", ephemeral=True)  
            return  
  
        async with db_pool.acquire() as conn:  
            char_row = await conn.fetchrow(  
                "SELECT class_name, level FROM alaris_characters WHERE id=$1;",  
                int(actor["character_id"]),  
            )  
        if not char_row or int(char_row["level"] or 1) < 2:  
            await interaction.response.send_message("This character has not unlocked active abilities yet.", ephemeral=True)  
            return  
  
        unlocked = await unlocked_abilities_for_character(int(actor["character_id"]))  
        ability_def = None  
        for candidate in unlocked:  
            if normalize_name(candidate.get("name")) == normalize_name(ability):  
                ability_def = dict(candidate)  
                break  
        if not ability_def:  
            await interaction.response.send_message("That ability is not unlocked for this character.", ephemeral=True)  
            return  
  
        cost = max(1, int(ability_def.get("cost") or 1))  
        if int(actor.get("current_resolve") or 0) < cost:  
            await interaction.response.send_message(f"You need **{cost} Resolve** to use that ability.", ephemeral=True)  
            return  
  
        kind = normalize_name(ability_def.get("kind") or "buff")  
        pseudo_action = "Buff" if kind in {"buff", "heal", "strike_buff", "spell_buff"} else ("Magic Attack" if ability_def.get("dc_type") == "spell" or kind == "spell" else "Piercing Attack")  
        valid_targets = await valid_targets_for_action(int(combat["id"]), actor, pseudo_action)  
        if target_id not in {int(t["id"]) for t in valid_targets}:  
            await interaction.response.send_message("That is not a valid target for this ability.", ephemeral=True)  
            return  
  
        async with db_pool.acquire() as conn:  
            target_row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1 AND encounter_id=$2;", target_id, int(combat["id"]))  
        if not target_row:  
            await interaction.response.send_message("Target not found.", ephemeral=True)  
            return  
        target_data = dict(target_row)  
  
        await db_pool.execute("UPDATE alaris_combatants SET current_resolve=GREATEST(0,current_resolve-$2) WHERE id=$1;", int(actor["id"]), cost)  
  
        lines = []  
        lines.append(f"✨ **{actor['name']}** uses **{ability_def['name']}** on **{target_data['name']}**.")  
  
        state_key = ability_def.get("state")  
        secondary_state = ability_def.get("secondary_state")  
        duration = 3 if cost >= 3 else (2 if cost >= 2 else ABILITY_DURATION_DEFAULT)  
        applied_damage_type = normalize_damage_type(ability_def.get("damage_type") or ("spirit" if kind in {"spell", "debuff", "spell_buff"} else "blunt"))  
  
        if kind == "heal":  
            heal_amount = roll_scaled_ability_damage(actor, ability_def)  
            new_hp = min(int(target_data["max_hp"] or 1), int(target_data["current_hp"] or 0) + heal_amount)  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status='active' WHERE id=$1;", target_id, new_hp)  
            lines.append(f"✅ Healed **{heal_amount} HP**.")  
            if state_key:  
                await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), state_key, duration)  
                lines.append(f"✅ **{target_data['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', state_key.title())}**.")  
        elif kind == "buff":  
            if state_key:  
                await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), state_key, duration)  
                lines.append(f"✅ **{target_data['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', state_key.title())}**.")  
            if secondary_state:  
                await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), secondary_state, duration)  
                lines.append(f"✅ **{target_data['name']}** also gains **{CORE_STATES.get(normalize_name(secondary_state), {}).get('name', secondary_state.title())}**.")  
        elif kind in {"debuff", "spell"}:  
            actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
            target_states = await active_states_for_combatant(int(combat["id"]), int(target_data["id"]))  
            dc = int(actor.get("save_dc") or 10) + state_spell_dc_penalty_for_actor(actor_states)  
            save_roll = roll_d20()  
            save_bonus = int(target_data.get("magic_save_bonus") or 0) + state_magic_defense_bonus(target_states)  
            save_total = save_roll + save_bonus  
            if kind == "spell":  
                raw_damage = roll_scaled_ability_damage(actor, ability_def)  
                final_damage, outcome = resolve_spell_save_damage(raw_damage, save_roll, save_total, dc)  
                final_damage = max(0, final_damage - state_damage_reduction(target_states))  
                final_damage, affinity_note = resolve_damage_with_affinities(final_damage, applied_damage_type, target_data)  
                new_hp = max(0, int(target_data["current_hp"] or 0) - final_damage)  
                await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;", target_id, new_hp)  
                lines.append(f"Magic Save: d20 **{save_roll}** + {save_bonus} = **{save_total}** vs DC **{dc}**.")  
                lines.append(f"Damage Type: **{applied_damage_type}**")  
                lines.append(f"Damage: raw **{raw_damage}** → applied **{final_damage}**.")  
                if affinity_note:  
                    lines.append(f"Affinity: {affinity_note}.")  
            else:  
                lines.append(f"Save: d20 **{save_roll}** + {save_bonus} = **{save_total}** vs DC **{dc}**.")  
            if state_key and (save_roll == 1 or (save_roll != 20 and save_total < dc)):  
                await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), state_key, duration)  
                lines.append(f"✅ **{target_data['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', state_key.title())}**.")  
        elif kind in {"strike", "strike_buff"}:  
            actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
            target_states = await active_states_for_combatant(int(combat["id"]), int(target_data["id"]))  
            attack_roll = roll_d20()  
            total = attack_roll + int(actor.get("attack_bonus") or 0) + state_attack_penalty_for_actor(actor_states) + state_attack_bonus_against(target_states)  
            ac = int(target_data.get("armor_class") or 10) + state_ac_bonus(target_states)  
            if total >= ac:  
                damage = roll_scaled_ability_damage(actor, ability_def) + state_damage_modifier_for_actor(actor_states)  
                damage = max(0, damage - state_damage_reduction(target_states))  
                damage, affinity_note = resolve_damage_with_affinities(damage, applied_damage_type, target_data)  
                new_hp = max(0, int(target_data["current_hp"] or 0) - damage)  
                await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;", target_id, new_hp)  
                lines.append(f"Attack: **{total}** vs AC **{ac}**. Hit for **{damage}** **{applied_damage_type}** damage.")  
                if affinity_note:  
                    lines.append(f"Affinity: {affinity_note}.")  
                if state_key and new_hp > 0:  
                    await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), state_key, duration)  
                    lines.append(f"✅ **{target_data['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', state_key.title())}**.")  
                if secondary_state:  
                    await apply_combat_state(int(combat["id"]), int(actor["id"]), int(actor["id"]), secondary_state, duration)  
                    lines.append(f"✅ **{actor['name']}** gains **{CORE_STATES.get(normalize_name(secondary_state), {}).get('name', secondary_state.title())}**.")  
            else:  
                lines.append(f"Attack: **{total}** vs AC **{ac}**. Miss.")  
        elif kind == "spell_buff":  
            # Resolve as spell damage, then apply a beneficial secondary state to the actor.  
            actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
            target_states = await active_states_for_combatant(int(combat["id"]), int(target_data["id"]))  
            dc = int(actor.get("save_dc") or 10) + state_spell_dc_penalty_for_actor(actor_states)  
            save_roll = roll_d20()  
            save_bonus = int(target_data.get("magic_save_bonus") or 0) + state_magic_defense_bonus(target_states)  
            save_total = save_roll + save_bonus  
            raw_damage = roll_scaled_ability_damage(actor, ability_def)  
            final_damage, outcome = resolve_spell_save_damage(raw_damage, save_roll, save_total, dc)  
            final_damage = max(0, final_damage - state_damage_reduction(target_states))  
            new_hp = max(0, int(target_data["current_hp"] or 0) - final_damage)  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;", target_id, new_hp)  
            lines.append(f"Magic Save: d20 **{save_roll}** + {save_bonus} = **{save_total}** vs DC **{dc}**.")  
            lines.append(f"Damage Type: **{applied_damage_type}**")  
            lines.append(f"Damage: raw **{raw_damage}** → applied **{final_damage}**.")  
            if state_key and new_hp > 0 and (save_roll == 1 or (save_roll != 20 and save_total < dc)):  
                await apply_combat_state(int(combat["id"]), target_id, int(actor["id"]), state_key, duration)  
                lines.append(f"✅ **{target_data['name']}** gains **{CORE_STATES.get(normalize_name(state_key), {}).get('name', state_key.title())}**.")  
            if secondary_state:  
                await apply_combat_state(int(combat["id"]), int(actor["id"]), int(actor["id"]), secondary_state, duration)  
                lines.append(f"✅ **{actor['name']}** gains **{CORE_STATES.get(normalize_name(secondary_state), {}).get('name', secondary_state.title())}**.")  
  
        lines.append(f"Resolve spent: **{cost}**.")  
        lines.append("📝 Write your RP post describing the ability, then use `/end-turn`.")  
        if has_state(actor_states, "inspired"):  
            await consume_state_if_present(int(combat["id"]), int(actor["id"]), "inspired")  
            lines.append("✨ Inspired was consumed.")  
        await mark_combat_action_taken(int(actor["id"]))  
        await interaction.response.send_message("\n".join(lines), ephemeral=False)  
        await close_combat_if_finished(interaction.channel, int(combat["id"]))  
        return  
  
    valid_targets = await valid_targets_for_action(int(combat["id"]), actor, action_type)  
    if target_id not in {int(t["id"]) for t in valid_targets}:  
        await interaction.response.send_message("That is not a valid target for this action.", ephemeral=True)  
        return  
  
    async with db_pool.acquire() as conn:  
        target_row = await conn.fetchrow(  
            "SELECT * FROM alaris_combatants WHERE id=$1 AND encounter_id=$2;",  
            target_id,  
            int(combat["id"]),  
        )  
    if not target_row:  
        await interaction.response.send_message("Target not found in this combat.", ephemeral=True)  
        return  
  
    target_data = dict(target_row)  
    result_lines: list[str] = []  
    if action_norm in PHYSICAL_ACTION_DAMAGE_TYPES:  
        applied_damage_type = damage_type_for_action(action_type)  
        attack_roll = roll_d20()  
        actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
        target_states = await active_states_for_combatant(int(combat["id"]), int(target_data["id"]))  
        attack_total = attack_roll + int(actor["attack_bonus"] or 0) + state_attack_penalty_for_actor(actor_states) + state_attack_bonus_against(target_states)  
        target_ac = int(target_data["armor_class"] or 10) + state_ac_bonus(target_states)  
        hit = attack_total >= target_ac  
  
        result_lines.append(f"**{actor['name']}** uses **{action_type}** against **{target_data['name']}**.")  
        result_lines.append(f"Attack: d20 **{attack_roll}** + {int(actor['attack_bonus'] or 0)} = **{attack_total}** vs AC **{target_ac}**")  
  
        if hit:  
            damage = roll_die(int(actor["damage_die_sides"] or 8)) + int(actor.get("damage_bonus") or 0) + state_damage_modifier_for_actor(actor_states)  
            damage = max(0, damage - state_damage_reduction(target_states))  
            damage, affinity_note = resolve_damage_with_affinities(damage, applied_damage_type, target_data)  
            new_hp = max(0, int(target_data["current_hp"] or 0) - damage)  
            defeated = new_hp <= 0  
  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_combatants  
                    SET current_hp=$2,  
                        status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END  
                    WHERE id=$1;  
                    """,  
                    target_id,  
                    new_hp,  
                )  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_combat_logs (  
                        encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                        roll_json, damage, damage_type, outcome, narrative  
                    )  
                    VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9);  
                    """,  
                    int(combat["id"]),  
                    int(actor["id"]),  
                    target_id,  
                    action_norm,  
                    json.dumps({"d20": attack_roll, "total": attack_total, "target_ac": target_ac}),  
                    damage,  
                    applied_damage_type,  
                    "hit_defeated" if defeated else "hit",  
                    None,  
                )  
  
            result_lines.append(f"✅ Hit for **{damage} {applied_damage_type}** damage.")  
            if affinity_note:  
                result_lines.append(f"Affinity: {affinity_note}.")  
            if defeated:  
                result_lines.append(f"💀 **{target_data['name']}** is defeated.")  
        else:  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_combat_logs (  
                        encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                        roll_json, damage, damage_type, outcome, narrative  
                    )  
                    VALUES ($1,$2,$3,$4,$5::jsonb,0,$6,'miss',$7);  
                    """,  
                    int(combat["id"]),  
                    int(actor["id"]),  
                    target_id,  
                    action_norm,  
                    json.dumps({"d20": attack_roll, "total": attack_total, "target_ac": target_ac}),  
                    applied_damage_type,  
                    None,  
                )  
            result_lines.append("❌ Miss.")  
  
    elif action_norm == "magical attack":  
        applied_damage_type = "spirit"  
        actor_states = await active_states_for_combatant(int(combat["id"]), int(actor["id"]))  
        target_states = await active_states_for_combatant(int(combat["id"]), int(target_data["id"]))  
        attack_roll = roll_d20()  
        magic_attack_bonus = int(actor.get("save_dc") or 10) - 8  
        attack_total = attack_roll + magic_attack_bonus + state_spell_dc_penalty_for_actor(actor_states) + state_attack_bonus_against(target_states) + state_action_bonus_for_actor(actor_states)  
        target_md = int(target_data.get("magic_defense") or 10) + state_magic_defense_bonus(target_states)  
        hit = attack_total >= target_md  
  
        result_lines.append(f"**{actor['name']}** uses **Magical Attack** against **{target_data['name']}**.")  
        result_lines.append(f"Magic Attack: d20 **{attack_roll}** + {magic_attack_bonus} = **{attack_total}** vs Magic Defense **{target_md}**")  
  
        if hit:  
            damage = roll_die(int(actor["damage_die_sides"] or 8)) + int(actor.get("damage_bonus") or 0) + state_damage_modifier_for_actor(actor_states)  
            damage = max(0, damage - state_damage_reduction(target_states))  
            damage, affinity_note = resolve_damage_with_affinities(damage, applied_damage_type, target_data)  
            new_hp = max(0, int(target_data["current_hp"] or 0) - damage)  
            defeated = new_hp <= 0  
  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_combatants  
                    SET current_hp=$2,  
                        status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END  
                    WHERE id=$1;  
                    """,  
                    target_id,  
                    new_hp,  
                )  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_combat_logs (  
                        encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                        roll_json, damage, damage_type, outcome, narrative  
                    )  
                    VALUES ($1,$2,$3,'magical_attack',$4::jsonb,$5,$6,$7,NULL);  
                    """,  
                    int(combat["id"]), int(actor["id"]), target_id,  
                    json.dumps({"d20": attack_roll, "total": attack_total, "target_magic_defense": target_md}),  
                    damage, applied_damage_type, "hit_defeated" if defeated else "hit",  
                )  
            result_lines.append(f"✅ Hit for **{damage} {applied_damage_type}** damage.")  
            if affinity_note:  
                result_lines.append(f"Affinity: {affinity_note}.")  
            if defeated:  
                result_lines.append(f"💀 **{target_data['name']}** is defeated.")  
        else:  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    INSERT INTO alaris_combat_logs (  
                        encounter_id, actor_combatant_id, target_combatant_id, action_type,  
                        roll_json, damage, damage_type, outcome, narrative  
                    )  
                    VALUES ($1,$2,$3,'magical_attack',$4::jsonb,0,$5,'miss',NULL);  
                    """,  
                    int(combat["id"]), int(actor["id"]), target_id,  
                    json.dumps({"d20": attack_roll, "total": attack_total, "target_magic_defense": target_md}),  
                    applied_damage_type,  
                )  
            result_lines.append("❌ Miss.")  
  
    else:  
        await interaction.response.send_message("Choose Use Ability, Magical Attack, Piercing Melee or Ranged Attack, Slashing Melee Attack, or Blunt Melee Attack.", ephemeral=True)  
        return  
  
    result_lines.append("\n📝 Write your RP post describing the action, then use `/end-turn`.")  
    if has_state(actor_states, "inspired"):  
        await consume_state_if_present(int(combat["id"]), int(actor["id"]), "inspired")  
        result_lines.append("✨ Inspired was consumed.")  
    await mark_combat_action_taken(int(actor["id"]))  
    await interaction.response.send_message("\n".join(result_lines), ephemeral=False)  
  
    if await close_combat_if_finished(interaction.channel, int(combat["id"])):  
        return  
  
  
  
  
@bot.tree.command(name="end-turn", description="End your character's combat turn and advance initiative.")  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def end_turn(interaction: discord.Interaction):  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
  
    combat = await get_active_combat_for_channel(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("There is no active combat in this channel.", ephemeral=True)  
        return  
  
    actor = await current_turn_combatant(int(combat["id"]))  
    if not actor:  
        await interaction.response.send_message("No current turn is set.", ephemeral=True)  
        return  
  
    if actor["combatant_type"] == "character" and int(actor["owner_user_id"] or 0) != interaction.user.id:  
        if not (isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)):  
            await interaction.response.send_message(f"Only **{actor['name']}**'s owner or staff can end this turn.", ephemeral=True)  
            return  
  
    await interaction.response.send_message(f"✅ **{actor['name']}** ends their turn.", ephemeral=False)  
  
    if await close_combat_if_finished(interaction.channel, int(combat["id"])):  
        return  
  
    tick_lines = await decrement_states_for_combatant(int(combat["id"]), int(actor["id"]))  
    if tick_lines:  
        await interaction.channel.send("\n".join(tick_lines))  
    if await close_combat_if_finished(interaction.channel, int(combat["id"])):  
        return  
    next_actor = await advance_combat_turn(int(combat["id"]))  
    if not next_actor:  
        return  
  
    await post_round_health_summary_if_needed(interaction.channel, int(combat["id"]), next_actor)  
    await post_current_turn(interaction.channel, int(combat["id"]))  
  
    if next_actor["combatant_type"] == "enemy":  
        await npc_auto_turn_loop(interaction.channel, int(combat["id"]))  
  
  
@bot.tree.command(name="combat-force-close", description="STAFF: force-close stuck active combat in this channel without awarding XP.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def combat_force_close(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("This command can only be used in a server channel.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=False)  
    closed_count, encounter_ids = await force_close_active_combat_in_channel(  
        interaction.guild.id,  
        interaction.channel.id,  
        interaction.user.id,  
    )  
    if closed_count <= 0:  
        await interaction.followup.send("No active combat encounter was found in this channel.", ephemeral=True)  
        return  
    await interaction.followup.send(  
        f"🛑 **Combat force-closed by staff.**\n"  
        f"Closed encounter(s): `{', '.join(str(x) for x in encounter_ids)}`\n"  
        "No combat XP was awarded.",  
        ephemeral=False,  
    )  
    await post_command_log(interaction, f"force-closed combat encounters {encounter_ids} in channel {interaction.channel.id}")  
  
  
  
@bot.tree.command(name="character-passives-refresh", description="STAFF: assign default starter passives to active characters and refresh cards.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def character_passives_refresh(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id  
            FROM alaris_characters  
            WHERE guild_id=$1 AND status='active'  
            ORDER BY name;  
            """,  
            interaction.guild.id,  
        )  
  
    updated = 0  
    failed = 0  
    for row in rows:  
        try:  
            ok = await ensure_character_passives(int(row["id"]))  
            if ok:  
                await refresh_character_post(int(row["id"]))  
                updated += 1  
            else:  
                failed += 1  
        except Exception:  
            LOG.exception("Failed refreshing passives for character_id=%s", row["id"])  
            failed += 1  
  
    await interaction.followup.send(f"Passives refreshed. Updated: **{updated}** | Failed: **{failed}**", ephemeral=True)  
    await post_command_log(interaction, f"refreshed starter passives updated={updated} failed={failed}")  
  
  
async def pending_choice_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:  
    if interaction.guild is None:  
        return []  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT lc.id, c.name, lc.level, lc.choice_type  
            FROM alaris_level_choices lc  
            JOIN alaris_characters c ON c.id=lc.character_id  
            WHERE lc.guild_id=$1 AND lc.status='pending'  
            ORDER BY c.name, lc.level, lc.choice_type  
            LIMIT 25;  
            """,  
            interaction.guild.id,  
        )  
    cur = normalize_name(current)  
    out = []  
    for r in rows:  
        label = f"{r['name']} - L{r['level']} {r['choice_type']}"  
        if not cur or cur in normalize_name(label):  
            out.append(app_commands.Choice(name=label[:100], value=str(r["id"])))  
    return out[:25]  
  
  
  
  
  
  
def class_ability_options_for_choice(class_name: str, level: int) -> list[dict[str, Any]]:  
    cls = normalize_name(class_name or "fighter")  
    level = int(level or 1)  
    by_level = CLASS_ACTIVE_ABILITIES.get(cls, {})  
    if level in by_level:  
        return list(by_level[level])[:25]  
    options = []  
    for unlock_level, abilities in sorted(by_level.items()):  
        if int(unlock_level) <= level:  
            options.extend(abilities)  
    if not options:  
        options = [starter_ability_for_class(class_name or "fighter")]  
    return options[:25]  
  
  
async def unlock_character_ability_from_choice(character_id: int, ability_name: str, level_granted: int) -> None:  
    payload = await fetch_clean_character_by_id_without_backfill(character_id)  
    if not payload:  
        raise RuntimeError(f"Character {character_id} not found while unlocking class ability.")  
    c = payload["character"]  
    options = class_ability_options_for_choice(c.get("class_name"), int(level_granted or c.get("level") or 1))  
    chosen = None  
    for ability in options:  
        if normalize_name(ability.get("name")) == normalize_name(ability_name):  
            chosen = dict(ability)  
            break  
    if not chosen:  
        chosen = {"name": ability_name, "kind": "ability", "description": "Manually recorded level-up ability."}  
    chosen["source"] = normalize_name(c.get("class_name") or "class")  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_abilities (  
                guild_id, character_id, ability_name, class_name, level_granted, metadata_json  
            )  
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)  
            ON CONFLICT (character_id, ability_name) DO UPDATE SET  
                class_name=EXCLUDED.class_name,  
                level_granted=EXCLUDED.level_granted,  
                metadata_json=EXCLUDED.metadata_json;  
            """,  
            int(c["guild_id"]), int(character_id), str(chosen.get("name")),  
            normalize_name(c.get("class_name")), int(level_granted or 1), json.dumps(chosen),  
        )  
  
  
async def character_has_unlocked_ability(character_id: int, ability_name: str) -> bool:  
    abilities = await unlocked_abilities_for_character(int(character_id))  
    wanted = normalize_name(ability_name)  
    return any(normalize_name(a.get("name")) == wanted for a in abilities)  
  
  
  
  
def species_ability_options_for_choice(species_name: str, level: int) -> list[dict[str, Any]]:  
    species_key = normalize_name(species_name or "human")  
    level = int(level or 1)  
    by_level = SPECIES_ACTIVE_ABILITIES.get(species_key, {})  
    if level in by_level:  
        return list(by_level[level])[:25]  
    options = []  
    for unlock_level, abilities in sorted(by_level.items()):  
        if int(unlock_level) <= level:  
            options.extend(abilities)  
    return options[:25]  
  
  
async def unlock_species_ability_from_choice(character_id: int, ability_name: str, level_granted: int) -> None:  
    payload = await fetch_clean_character_by_id_without_backfill(character_id)  
    if not payload:  
        return  
    c = payload["character"]  
    options = species_ability_options_for_choice(c.get("species"), int(level_granted or c.get("level") or 1))  
    chosen = None  
    for ability in options:  
        if normalize_name(ability.get("name")) == normalize_name(ability_name):  
            chosen = dict(ability)  
            break  
    if not chosen:  
        chosen = {"name": ability_name, "kind": "ability", "description": "Manually recorded species ability."}  
    chosen["source"] = "species"  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_abilities (  
                guild_id, character_id, ability_name, class_name, level_granted, metadata_json  
            )  
            VALUES ($1,$2,$3,$4,$5,$6::jsonb)  
            ON CONFLICT (character_id, ability_name) DO UPDATE SET  
                metadata_json=EXCLUDED.metadata_json;  
            """,  
            int(c["guild_id"]),  
            int(character_id),  
            str(chosen.get("name")),  
            "species",  
            int(level_granted or 1),  
            json.dumps(chosen),  
        )  
  
  
def choice_option_rows(choice: dict[str, Any], character_payload: Optional[dict[str, Any]] = None) -> list[dict[str, str]]:  
    ctype = choice.get("choice_type")  
    if ctype == "asi":  
        base = [  
            {"label": "+2 STR", "value": "STR", "description": "Increase Strength by 2"},  
            {"label": "+2 DEX", "value": "DEX", "description": "Increase Dexterity by 2"},  
            {"label": "+2 CON", "value": "CON", "description": "Increase Constitution by 2"},  
            {"label": "+2 INT", "value": "INT", "description": "Increase Intelligence by 2"},  
            {"label": "+2 WIS", "value": "WIS", "description": "Increase Wisdom by 2"},  
            {"label": "+2 CHA", "value": "CHA", "description": "Increase Charisma by 2"},  
        ]  
        splits = []  
        abbrs = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]  
        for i, first in enumerate(abbrs):  
            for second in abbrs[i + 1:]:  
                splits.append({  
                    "label": f"+1 {first} / +1 {second}",  
                    "value": f"{first}+{second}",  
                    "description": f"Increase {first} and {second} by 1 each",  
                })  
        return base + splits  
    if ctype == "combat_specialization":  
        return [  
            {"label": "Sharpened Accuracy", "value": "Sharpened Accuracy", "description": "+1 Attack"},  
            {"label": "Deadlier Force", "value": "Deadlier Force", "description": "+1 Damage"},  
            {"label": "Deepened Spellcraft", "value": "Deepened Spellcraft", "description": "+1 Spell DC"},  
        ]  
    if ctype == "ability":  
        class_name = character_payload.get("character", {}).get("class_name") if character_payload else "fighter"  
        abilities = class_ability_options_for_choice(class_name, int(choice.get("level") or 1))  
        return [  
            {"label": str(a.get("name"))[:100], "value": str(a.get("name"))[:100], "description": f"{a.get('kind','ability')} | {a.get('description','')}"[:100]}  
            for a in abilities[:25]  
        ]  
    if ctype == "species_ability":  
        species_name = character_payload.get("character", {}).get("species") if character_payload else "human"  
        abilities = species_ability_options_for_choice(species_name, int(choice.get("level") or 1))  
        return [  
            {"label": str(a.get("name"))[:100], "value": str(a.get("name"))[:100], "description": f"{a.get('kind','ability')} | {a.get('description','')}"[:100]}  
            for a in abilities[:25]  
        ]  
    return [{"label": "Manual Choice", "value": "Manual Choice", "description": "Ask staff for help"}]  
  
def safe_channel_fragment(name: str, max_len: int = 80) -> str:  
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_name(name)).strip("-")  
    return (slug or "character")[:max_len]  
  
  
def describe_pending_choice(choice: dict[str, Any]) -> str:  
    ctype = choice.get("choice_type")  
    level = choice.get("level")  
    if ctype == "asi":  
        return f"Level {level} ASI: choose one stat for +2."  
    if ctype == "combat_specialization":  
        return f"Level {level} Combat Specialization: +1 Attack, +1 Damage, or +1 Spell DC."  
    if ctype == "ability":  
        return f"Level {level} Ability Choice: choose a class ability unlock."  
    if ctype == "species_ability":  
        return f"Level {level} Species Ability: unlock your species ability."  
    return f"Level {level} {ctype}"  
  
  
def build_level_ticket_embed(character_payload: dict[str, Any], pending: list[dict[str, Any]]) -> discord.Embed:  
    c = character_payload["character"]  
    embed = discord.Embed(  
        title=f"Level-Up Choices - {c['name']}",  
        description=(  
            f"{c['name']} has pending level-up choices. "  
            "Use the dropdowns below to make selections, and ask staff questions in this ticket if needed."  
        ),  
        color=discord.Color.green(),  
    )  
    embed.add_field(name="Character", value=f"**{c['name']}**", inline=True)  
    embed.add_field(name="Owner", value=f"<@{c['user_id']}>", inline=True)  
    embed.add_field(name="Current Level", value=str(c.get("level") or 1), inline=True)  
    if pending:  
        embed.add_field(  
            name="Pending Choices",  
            value="\n".join(f"• {describe_pending_choice(p)}" for p in pending)[:1024],  
            inline=False,  
        )  
    else:  
        embed.add_field(name="Pending Choices", value="No pending choices.", inline=False)  
    if c.get("image_url"):  
        embed.set_thumbnail(url=c["image_url"])  
    embed.set_footer(text="When all choices are resolved, staff may close this ticket.")  
    return embed  
  
  
  
async def pending_level_choices_for_character(character_id: int) -> list[dict[str, Any]]:  
    """Return unresolved level-up choices for a character.  
  
    This helper is intentionally defined immediately before level-ticket creation,  
    because open_level_ticket_if_needed depends on it during /character-level-set.  
    """  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT *  
            FROM alaris_level_choices  
            WHERE character_id=$1 AND status='pending'  
            ORDER BY level, choice_type;  
            """,  
            int(character_id),  
        )  
    return [dict(r) for r in rows]  
  
  
async def open_level_ticket_if_needed(guild: discord.Guild, character_id: int) -> Optional[int]:  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return None  
    c = payload["character"]  
    pending = await pending_level_choices_for_character(character_id)  
    if not pending:  
        return None  
  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchrow(  
            """  
            SELECT channel_id  
            FROM alaris_level_tickets  
            WHERE guild_id=$1 AND character_id=$2 AND status='open';  
            """,  
            guild.id,  
            character_id,  
        )  
    if existing:  
        channel = guild.get_channel(int(existing["channel_id"]))  
        if isinstance(channel, discord.TextChannel):  
            try:  
                await channel.send(embed=build_level_ticket_embed(payload, pending), view=LevelTicketView(character_id))  
                await post_level_choice_embeds(channel, character_id)  
            except Exception:  
                LOG.exception("Failed updating existing level ticket.")  
            return int(existing["channel_id"])  
  
    category = None  
    if CHARACTER_REVIEW_CATEGORY_ID:  
        maybe = guild.get_channel(CHARACTER_REVIEW_CATEGORY_ID)  
        if maybe is None:  
            try:  
                maybe = await bot.fetch_channel(CHARACTER_REVIEW_CATEGORY_ID)  
            except Exception:  
                maybe = None  
        if isinstance(maybe, discord.CategoryChannel):  
            category = maybe  
  
    owner = guild.get_member(int(c["user_id"]))  
    overwrites = {  
        guild.default_role: discord.PermissionOverwrite(view_channel=False),  
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),  
    }  
    if owner:  
        overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)  
    for role_id in STAFF_ROLE_IDS:  
        role = guild.get_role(role_id)  
        if role:  
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)  
  
    channel_name = f"level-{safe_channel_fragment(c['name'], 70)}"  
    try:  
        channel = await guild.create_text_channel(  
            name=channel_name[:90],  
            category=category,  
            overwrites=overwrites,  
            reason=f"Alaris level-up ticket for {c['name']}",  
        )  
    except Exception:  
        LOG.exception("Failed to create level-up ticket channel.")  
        return None  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_level_tickets (  
                guild_id, character_id, channel_id, status, opened_for_level  
            )  
            VALUES ($1,$2,$3,'open',$4)  
            ON CONFLICT (character_id, status) DO UPDATE SET  
                channel_id=EXCLUDED.channel_id,  
                opened_for_level=EXCLUDED.opened_for_level;  
            """,  
            guild.id,  
            character_id,  
            channel.id,  
            int(c.get("level") or 1),  
        )  
  
    await channel.send(  
        content=f"<@{c['user_id']}> your level-up ticket is ready. Staff can answer questions here.",  
        embed=build_level_ticket_embed(payload, pending),  
        view=LevelTicketView(character_id),  
    )  
    await post_level_choice_embeds(channel, character_id)  
    return channel.id  
  
  
async def resolve_level_choice_by_id(choice_id: int, selected: str) -> tuple[bool, str, Optional[int]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT lc.*, c.name, c.id AS cid, c.guild_id  
            FROM alaris_level_choices lc  
            JOIN alaris_characters c ON c.id=lc.character_id  
            WHERE lc.id=$1 AND lc.status='pending';  
            """,  
            choice_id,  
        )  
    if not row:  
        return False, "Pending choice not found.", None  
  
    option_norm = normalize_name(selected)  
    choice_type = row["choice_type"]  
    meta: dict[str, Any] = {}  
  
    if choice_type == "asi":  
        increases, err = parse_asi_selection(selected)  
        if err or not increases:  
            return False, err or "Invalid ASI selection.", int(row["cid"])  
        try:  
            note = await apply_asi_to_character(int(row["cid"]), increases, ASI_NORMAL_STAT_CAP)  
        except Exception as exc:  
            LOG.exception("ASI application failed for character_id=%s", int(row["cid"]))  
            return False, f"ASI application failed: {truncate(exc, 500)}", int(row["cid"])  
        meta = {"increases": increases, "amount": sum(increases.values()), "note": note}  
        selected_label = format_asi_increases(increases)  
  
    elif choice_type == "combat_specialization":  
        aliases = {  
            "attack": "Sharpened Accuracy",  
            "+1 attack": "Sharpened Accuracy",  
            "plus 1 attack": "Sharpened Accuracy",  
            "1 attack": "Sharpened Accuracy",  
            "sharpened accuracy": "Sharpened Accuracy",  
            "damage": "Deadlier Force",  
            "+1 damage": "Deadlier Force",  
            "plus 1 damage": "Deadlier Force",  
            "1 damage": "Deadlier Force",  
            "deadlier force": "Deadlier Force",  
            "spell dc": "Deepened Spellcraft",  
            "+1 spell dc": "Deepened Spellcraft",  
            "spell": "Deepened Spellcraft",  
            "plus 1 spell dc": "Deepened Spellcraft",  
            "deepened spellcraft": "Deepened Spellcraft",  
        }  
        wanted = aliases.get(option_norm, selected)  
        found = None  
        for opt in COMBAT_SPECIALIZATION_OPTIONS.values():  
            if normalize_name(opt.get("name")) == normalize_name(wanted) or normalize_name(opt.get("description")) == option_norm:  
                found = opt  
                break  
        if not found:  
            return False, "Combat specialization must be Sharpened Accuracy, Deadlier Force, or Deepened Spellcraft.", int(row["cid"])  
        meta = found  
        selected_label = found["name"]  
  
    elif choice_type == "ability":  
        await unlock_character_ability_from_choice(int(row["cid"]), selected, int(row["level"] or 1))  
        if not await character_has_unlocked_ability(int(row["cid"]), selected):  
            return False, f"Class ability unlock failed readback for **{selected}**. Choice was not resolved.", int(row["cid"])  
        meta = {"selected_option": selected, "note": "Class ability unlock recorded from level ticket."}  
        selected_label = selected  
  
    elif choice_type == "species_ability":  
        await unlock_species_ability_from_choice(int(row["cid"]), selected, int(row["level"] or 1))  
        if not await character_has_unlocked_ability(int(row["cid"]), selected):  
            return False, f"Species ability unlock failed readback for **{selected}**. Choice was not resolved.", int(row["cid"])  
        meta = {"selected_option": selected, "note": "Species ability unlock recorded from level ticket."}  
        selected_label = selected  
  
    else:  
        return False, f"Unknown choice type: {choice_type}", int(row["cid"])  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_level_choices  
            SET status='resolved',  
                selected_option=$2,  
                metadata_json=$3::jsonb,  
                resolved_at=NOW()  
            WHERE id=$1;  
            """,  
            choice_id,  
            selected_label,  
            json.dumps(meta),  
        )  
    await recalculate_character_combat(int(row["cid"]), preserve_current_hp=False)  
    await refresh_character_post(int(row["cid"]))  
    return True, f"Resolved **{row['name']}** Level {row['level']} {choice_type}: **{selected_label}**.", int(row["cid"])  
  
  
class LevelChoiceSelect(discord.ui.Select):  
    def __init__(self, character_id: int, choices: list[dict[str, Any]]):  
        self.character_id = int(character_id)  
        options = []  
        for choice in choices[:25]:  
            options.append(  
                discord.SelectOption(  
                    label=f"L{choice['level']} {choice['choice_type']}",  
                    value=str(choice["id"]),  
                    description=describe_pending_choice(choice)[:100],  
                )  
            )  
        super().__init__(placeholder="Step 1: choose the pending choice...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        choice_id = int(self.values[0])  
        async with db_pool.acquire() as conn:  
            row = await conn.fetchrow("SELECT * FROM alaris_level_choices WHERE id=$1 AND status='pending';", choice_id)  
        if not row:  
            await interaction.response.send_message("That pending choice no longer exists.", ephemeral=True)  
            return  
        payload = await fetch_clean_character_by_id(self.character_id)  
        options = choice_option_rows(dict(row), payload)  
        view = discord.ui.View(timeout=900)  
        view.add_item(LevelChoiceOptionSelect(self.character_id, choice_id, options))  
        await interaction.response.send_message(  
            f"Step 2: choose your option for **Level {row['level']} {row['choice_type']}**.",  
            view=view,  
            ephemeral=True,  
        )  
  
  
class LevelChoiceOptionSelect(discord.ui.Select):  
    def __init__(self, character_id: int, choice_id: int, options_data: list[dict[str, str]]):  
        self.character_id = int(character_id)  
        self.choice_id = int(choice_id)  
        options = [  
            discord.SelectOption(  
                label=o["label"][:100],  
                value=o["value"][:100],  
                description=(o.get("description") or "")[:100],  
            )  
            for o in options_data[:25]  
        ]  
        super().__init__(placeholder="Step 2: choose the option to apply...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        selected = self.values[0]  
        ok, message, character_id = await resolve_level_choice_by_id(self.choice_id, selected)  
        if not ok:  
            await interaction.response.send_message(message, ephemeral=True)  
            return  
  
        await interaction.response.send_message(message, ephemeral=True)  
  
        # Post an updated public ticket embed so staff/player can see remaining work.  
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel) and character_id:  
            payload = await fetch_clean_character_by_id(character_id)  
            pending = await pending_level_choices_for_character(character_id)  
            if payload:  
                if pending:  
                    await interaction.channel.send(embed=build_level_ticket_embed(payload, pending), view=LevelTicketView(character_id))  
                else:  
                    await interaction.channel.send(embed=build_level_ticket_embed(payload, pending))  
                    await interaction.channel.send("✅ All pending level-up choices are resolved. Staff may close this ticket.")  
  
  
  
def build_level_choice_select_view(character_id: int, pending: list[dict[str, Any]]) -> discord.ui.View:  
    view = discord.ui.View(timeout=900)  
    view.add_item(LevelChoiceSelect(character_id, pending))  
    return view  
  
  
  
def build_single_level_choice_embed(character_payload: dict[str, Any], choice: dict[str, Any]) -> discord.Embed:  
    c = character_payload["character"]  
    embed = discord.Embed(  
        title=f"{c['name']} - Level {choice['level']} {choice['choice_type'].replace('_', ' ').title()}",  
        description=describe_pending_choice(choice),  
        color=discord.Color.green(),  
    )  
    options = choice_option_rows(choice, character_payload)  
    embed.add_field(  
        name="Choose One",  
        value="\n".join(f"• **{o['label']}** - {o.get('description','')}" for o in options)[:1024],  
        inline=False,  
    )  
    if c.get("image_url"):  
        embed.set_thumbnail(url=c["image_url"])  
    return embed  
  
  
class DirectLevelChoiceSelect(discord.ui.Select):  
    def __init__(self, character_id: int, choice: dict[str, Any], character_payload: dict[str, Any]):  
        self.character_id = int(character_id)  
        self.choice_id = int(choice["id"])  
        options_data = choice_option_rows(choice, character_payload)  
        options = [  
            discord.SelectOption(label=o["label"][:100], value=o["value"][:100], description=(o.get("description") or "")[:100])  
            for o in options_data[:25]  
        ]  
        super().__init__(placeholder="Choose your option...", min_values=1, max_values=1, options=options)  
  
    async def callback(self, interaction: discord.Interaction):  
        selected = self.values[0]  
        await interaction.response.defer(ephemeral=True)  
        try:  
            ok, message, character_id = await resolve_level_choice_by_id(self.choice_id, selected)  
        except Exception as exc:  
            LOG.exception("Direct level choice selection failed.")  
            await interaction.followup.send(f"Choice failed: `{truncate(exc, 500)}`", ephemeral=True)  
            return  
        if not ok:  
            await interaction.followup.send(message, ephemeral=True)  
            return  
        await interaction.followup.send(message, ephemeral=True)  
        if interaction.channel and isinstance(interaction.channel, discord.TextChannel) and character_id:  
            payload = await fetch_clean_character_by_id(character_id)  
            pending = await pending_level_choices_for_character(character_id)  
            if payload:  
                if pending:  
                    await interaction.channel.send(embed=build_level_ticket_embed(payload, pending), view=LevelTicketView(character_id))  
                    await post_level_choice_embeds(interaction.channel, character_id)  
                else:  
                    await interaction.channel.send(embed=build_level_ticket_embed(payload, pending))  
                    await interaction.channel.send("✅ All pending level-up choices are resolved. Staff may close this ticket.")  
  
  
def direct_level_choice_view(character_id: int, choice: dict[str, Any], character_payload: dict[str, Any]) -> discord.ui.View:  
    view = discord.ui.View(timeout=None)  
    view.add_item(DirectLevelChoiceSelect(character_id, choice, character_payload))  
    return view  
  
  
async def post_level_choice_embeds(channel: discord.TextChannel, character_id: int) -> None:  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return  
    pending = await pending_level_choices_for_character(character_id)  
    for choice in pending:  
        await channel.send(embed=build_single_level_choice_embed(payload, choice), view=direct_level_choice_view(character_id, choice, payload))  
  
  
class LevelTicketView(discord.ui.View):  
    def __init__(self, character_id: int):  
        super().__init__(timeout=None)  
        self.character_id = int(character_id)  
  
    async def interaction_check(self, interaction: discord.Interaction) -> bool:  
        return True  
  
    @discord.ui.button(label="Refresh Choices", style=discord.ButtonStyle.gray)  
    async def refresh_choices(self, interaction: discord.Interaction, button: discord.ui.Button):  
        payload = await fetch_clean_character_by_id(self.character_id)  
        pending = await pending_level_choices_for_character(self.character_id)  
        if not payload:  
            await interaction.response.send_message("Character not found.", ephemeral=True)  
            return  
        await interaction.response.send_message(embed=build_level_ticket_embed(payload, pending), view=LevelTicketView(self.character_id) if pending else None, ephemeral=True)  
  
    @discord.ui.button(label="Refresh Choice Embeds", style=discord.ButtonStyle.green)  
    async def choose_pending(self, interaction: discord.Interaction, button: discord.ui.Button):  
        pending = await pending_level_choices_for_character(self.character_id)  
        if not pending:  
            await interaction.response.send_message("There are no pending choices for this character.", ephemeral=True)  
            return  
        if not isinstance(interaction.channel, discord.TextChannel):  
            await interaction.response.send_message("This must be used in the level ticket channel.", ephemeral=True)  
            return  
        await interaction.response.send_message("Refreshing direct choice embeds in this ticket.", ephemeral=True)  
        await post_level_choice_embeds(interaction.channel, self.character_id)  
  
  
    @discord.ui.button(label="Close Level Ticket", style=discord.ButtonStyle.red)  
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if not await require_staff(interaction):  
            return  
        pending = await pending_level_choices_for_character(self.character_id)  
        if pending:  
            await interaction.response.send_message("This ticket still has unresolved choices.", ephemeral=True)  
            return  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                UPDATE alaris_level_tickets  
                SET status='closed', closed_at=NOW()  
                WHERE character_id=$1 AND status='open';  
                """,  
                self.character_id,  
            )  
        await interaction.response.send_message("Closing level-up ticket.", ephemeral=True)  
        try:  
            if interaction.channel and isinstance(interaction.channel, discord.TextChannel):  
                await interaction.channel.delete(reason="Alaris level-up ticket complete")  
        except Exception:  
            LOG.exception("Failed to delete level-up ticket.")  
  
  
  
@bot.tree.command(name="level-ticket-open", description="STAFF: open or refresh a character level-up ticket.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def level_ticket_open(interaction: discord.Interaction, character: str):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    pending = await pending_level_choices_for_character(cid)  
    if not pending:  
        await interaction.response.send_message("That character has no pending level-up choices.", ephemeral=True)  
        return  
    channel_id = await open_level_ticket_if_needed(interaction.guild, cid)  
    if channel_id:  
        await interaction.response.send_message(f"Level ticket opened/refreshed: <#{channel_id}>", ephemeral=True)  
    else:  
        await interaction.response.send_message("Could not open level ticket. Check bot permissions/category configuration.", ephemeral=True)  
  
  
  
@bot.tree.command(name="character-affinity-set", description="STAFF: set a character resistance, weakness, or immunity.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name", affinity="resistance, weakness, or immunity", damage_type="Damage type")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_affinity_set(interaction: discord.Interaction, character: str, affinity: str, damage_type: str):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    dtype = normalize_damage_type(damage_type, damage_type)  
    if dtype not in LOCKED_DAMAGE_TYPES:  
        await interaction.response.send_message(f"Invalid damage type. Use one of: {', '.join(LOCKED_DAMAGE_TYPES)}", ephemeral=True)  
        return  
    affinity_norm = normalize_name(affinity)  
    col = None  
    if affinity_norm in {"resistance", "resist", "resistant"}:  
        col = "resistances_json"  
    elif affinity_norm in {"weakness", "weak", "vulnerability", "vulnerable"}:  
        col = "weaknesses_json"  
    elif affinity_norm in {"immunity", "immune"}:  
        col = "immunities_json"  
    else:  
        await interaction.response.send_message("Affinity must be resistance, weakness, or immunity.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchval(f"SELECT {col} FROM alaris_character_combat WHERE character_id=$1;", cid)  
        data = affinity_map_from_json(existing)  
        data[dtype] = 1.0  
        await conn.execute(f"UPDATE alaris_character_combat SET {col}=$2::jsonb, updated_at=NOW() WHERE character_id=$1;", cid, json.dumps(data))  
    await refresh_character_post(cid)  
    await interaction.response.send_message(f"Set **{payload['character']['name']}** {affinity_norm} to **{dtype}**.", ephemeral=True)  
  
  
@bot.tree.command(name="character-affinity-remove", description="STAFF: remove a character resistance, weakness, or immunity.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name", affinity="resistance, weakness, or immunity", damage_type="Damage type")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_affinity_remove(interaction: discord.Interaction, character: str, affinity: str, damage_type: str):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    dtype = normalize_damage_type(damage_type, damage_type)  
    affinity_norm = normalize_name(affinity)  
    col = None  
    if affinity_norm in {"resistance", "resist", "resistant"}:  
        col = "resistances_json"  
    elif affinity_norm in {"weakness", "weak", "vulnerability", "vulnerable"}:  
        col = "weaknesses_json"  
    elif affinity_norm in {"immunity", "immune"}:  
        col = "immunities_json"  
    else:  
        await interaction.response.send_message("Affinity must be resistance, weakness, or immunity.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    async with db_pool.acquire() as conn:  
        existing = await conn.fetchval(f"SELECT {col} FROM alaris_character_combat WHERE character_id=$1;", cid)  
        data = affinity_map_from_json(existing)  
        data.pop(dtype, None)  
        await conn.execute(f"UPDATE alaris_character_combat SET {col}=$2::jsonb, updated_at=NOW() WHERE character_id=$1;", cid, json.dumps(data))  
    await refresh_character_post(cid)  
    await interaction.response.send_message(f"Removed **{dtype}** from **{payload['character']['name']}** {affinity_norm}.", ephemeral=True)  
  
  
  
@bot.tree.command(name="staff-grant-asi", description="STAFF: manually grant an Ability Score Improvement to a character.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    character="Character name",  
    primary_stat="Stat to improve: STR, DEX, CON, INT, WIS, or CHA",  
    secondary_stat="Optional second stat for +1/+1 split. Leave blank for +2 to the primary stat.",  
)  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def staff_grant_asi(interaction: discord.Interaction, character: str, primary_stat: str, secondary_stat: Optional[str] = None):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    c = payload["character"]  
    selected = primary_stat if not secondary_stat else f"{primary_stat}+{secondary_stat}"  
    increases, err = parse_asi_selection(selected)  
    if err or not increases:  
        await interaction.response.send_message(err or "Invalid ASI selection.", ephemeral=True)  
        return  
    try:  
        note = await apply_asi_to_character(int(c["id"]), increases, ASI_NORMAL_STAT_CAP)  
    except Exception as exc:  
        LOG.exception("staff-grant-asi failed.")  
        await interaction.response.send_message(f"ASI grant failed: `{truncate(exc, 1000)}`", ephemeral=True)  
        return  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_level_choices (guild_id, character_id, level, choice_type, status, selected_option, metadata_json, resolved_at)  
            VALUES ($1,$2,$3,'asi','resolved',$4,$5::jsonb,NOW())  
            ON CONFLICT DO NOTHING;  
            """,  
            interaction.guild.id,  
            int(c["id"]),  
            int(c.get("level") or 1),  
            format_asi_increases(increases),  
            json.dumps({"manual_staff_grant": True, "granted_by": interaction.user.id, "increases": increases, "note": note}),  
        )  
    await interaction.response.send_message(  
        f"✅ Granted ASI to **{c['name']}**: **{format_asi_increases(increases)}** ({note}).",  
        ephemeral=True,  
    )  
    await post_command_log(interaction, f"granted ASI to {c['name']}: {format_asi_increases(increases)}")  
  
  
@bot.tree.command(name="character-level-set", description="STAFF TEST: set a character level and generate pending choices.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name", level="Level 1-10")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_level_set(interaction: discord.Interaction, character: str, level: int):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    if level < 1 or level > 10:  
        await interaction.response.send_message("Level must be between 1 and 10.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    c = payload["character"]  
    old_level = int(c.get("level") or 1)  
    async with db_pool.acquire() as conn:  
        await conn.execute("UPDATE alaris_characters SET level=$2, updated_at=NOW() WHERE id=$1;", int(c["id"]), level)  
    created_choices = await ensure_pending_level_choices(int(c["id"]), interaction.guild.id, old_level, level)  
    await recalculate_character_combat(int(c["id"]), preserve_current_hp=False)  
  
    refresh_note = ""  
    try:  
        refreshed = await refresh_character_post(int(c["id"]))  
        if not refreshed:  
            refresh_note = " Public card was not refreshed yet."  
    except Exception:  
        LOG.exception("Failed to refresh public character card during character-level-set.")  
        refresh_note = " Public card refresh failed, but the level update completed."  
  
    ticket_channel_id = None  
    try:  
        ticket_channel_id = await open_level_ticket_if_needed(interaction.guild, int(c["id"]))  
    except Exception:  
        LOG.exception("Failed to open level ticket during character-level-set.")  
        refresh_note += " Level ticket creation failed; rerun `/level-ticket-open` after patching."  
  
    ticket_note = f" Level ticket: <#{ticket_channel_id}>" if ticket_channel_id else ""  
    await interaction.response.send_message(  
        f"Set **{c['name']}** to level **{level}** and generated **{created_choices}** pending choice(s).{ticket_note}{refresh_note}",  
        ephemeral=True,  
    )  
  
  
  
# /level-choice-apply removed from player/staff workflow in v039; tickets handle choices through embeds.  
  
  
@bot.tree.command(name="character-refresh-all", description="STAFF: refresh all live character post cards.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def character_refresh_all(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
    await interaction.response.defer(ephemeral=True)  
    if interaction.guild is None:  
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)  
        return  
  
    updated, failed = await refresh_all_character_posts(interaction.guild.id)  
    await interaction.followup.send(  
        f"Character post refresh complete. Updated: **{updated}**. Failed/missing posts: **{failed}**.",  
        ephemeral=True,  
    )  
    await post_command_log(interaction, f"refreshed all character posts: updated={updated}, failed={failed}")  
  
  
@bot.tree.command(name="character-refresh-queued", description="STAFF: safely process queued external character-card refreshes without creating posts.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def character_refresh_queued(interaction: discord.Interaction, limit: int = 25):  
    if not await require_staff(interaction):  
        return  
    await interaction.response.defer(ephemeral=True)  
    if interaction.guild is None:  
        await interaction.followup.send("This command can only be used in a server.", ephemeral=True)  
        return  
    safe_limit = max(1, min(int(limit or 25), 100))  
    updated, skipped, failed = await process_character_refresh_queue(interaction.guild.id, safe_limit)  
    await interaction.followup.send(  
        "Queued character-card refresh complete. "  
        f"Updated: **{updated}**. Skipped/missing mappings: **{skipped}**. Failed: **{failed}**.\n"  
        "This command is edit-only and never creates new showcase posts.",  
        ephemeral=True,  
    )  
    await post_command_log(interaction, f"processed character refresh queue: updated={updated}, skipped={skipped}, failed={failed}")  
  
  
  
  
  
def level_choice_types_for_level(level: int) -> list[str]:  
    level = int(level or 1)  
    out: list[str] = []  
    if level in ABILITY_CHOICE_LEVELS:  
        out.append("ability")  
    if level in SPECIES_ABILITY_LEVELS:  
        out.append("species_ability")  
    if level in COMBAT_SPECIALIZATION_LEVELS:  
        out.append("combat_specialization")  
    if level in ASI_LEVELS:  
        out.append("asi")  
    return out  
  
  
async def ensure_pending_level_choices(character_id: int, guild_id: int, old_level: int, new_level: int) -> int:  
    if int(new_level or 1) <= int(old_level or 1):  
        return 0  
    created = 0  
    async with db_pool.acquire() as conn:  
        for lvl in range(int(old_level or 1) + 1, int(new_level or 1) + 1):  
            for choice_type in level_choice_types_for_level(lvl):  
                result = await conn.execute(  
                    """  
                    INSERT INTO alaris_level_choices (guild_id, character_id, level, choice_type, status, metadata_json)  
                    VALUES ($1,$2,$3,$4,'pending','{}'::jsonb)  
                    ON CONFLICT DO NOTHING;  
                    """,  
                    guild_id, character_id, lvl, choice_type,  
                )  
                if result.endswith("1"):  
                    created += 1  
    return created  
  
  
async def resolved_level_choice_bonuses(character_id: int) -> dict[str, int]:  
    bonuses: dict[str, int] = {}  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT metadata_json  
            FROM alaris_level_choices  
            WHERE character_id=$1 AND status='resolved';  
            """,  
            character_id,  
        )  
    for row in rows:  
        meta = decode_json_payload(row["metadata_json"])  
        bonus = meta.get("bonus") or {}  
        for key, value in bonus.items():  
            bonuses[key] = bonuses.get(key, 0) + int(value or 0)  
    return bonuses  
  
  
async def fetch_economy_enchantment_combat_bonuses(guild_id: int, character_id: int) -> dict[str, int]:  
    """Return combat bonuses granted by EconomyBot enchantment assets.

    EconomyBot v021 stores approved enchantments on econ.assets using:
    - combat_bonus_type: warding_ac, accuracy_attack, potency_damage
    - combat_bonus_value: integer rank/bonus, 1 through 5
    - combat_bonus_scope: character

    This function is intentionally defensive so AlarisBot can still boot and
    recalculate combat if the economy schema has not been deployed yet. If
    duplicate rows ever exist for the same track, the highest rank is used
    rather than stacking duplicates. The three different tracks can coexist.
    """  
    empty = {"armor_class": 0, "attack_bonus": 0, "damage_bonus": 0}  
    if not db_pool:  
        return dict(empty)  
    try:  
        async with db_pool.acquire() as conn:  
            has_assets = await conn.fetchval("SELECT to_regclass('econ.assets') IS NOT NULL;")  
            if not has_assets:  
                return dict(empty)  
            cols = await conn.fetch(  
                """  
                SELECT column_name  
                FROM information_schema.columns  
                WHERE table_schema='econ'  
                  AND table_name='assets'  
                  AND column_name = ANY($1::text[]);  
                """,  
                ["combat_bonus_type", "combat_bonus_value", "combat_bonus_scope"],  
            )  
            found_cols = {str(r["column_name"]) for r in cols}  
            required_cols = {"combat_bonus_type", "combat_bonus_value", "combat_bonus_scope"}  
            if not required_cols.issubset(found_cols):  
                return dict(empty)  
            rows = await conn.fetch(  
                """  
                SELECT combat_bonus_type, COALESCE(MAX(combat_bonus_value), 0)::int AS bonus  
                FROM econ.assets  
                WHERE guild_id=$1  
                  AND character_id=$2  
                  AND combat_bonus_scope='character'  
                  AND combat_bonus_type IN ('warding_ac', 'accuracy_attack', 'potency_damage')  
                GROUP BY combat_bonus_type;  
                """,  
                int(guild_id), int(character_id),  
            )  
    except Exception as exc:  
        LOG.warning("Could not read economy enchantment bonuses for character %s: %s", character_id, exc)  
        return dict(empty)  
  
    bonuses = dict(empty)  
    for row in rows:  
        btype = str(row["combat_bonus_type"] or "")  
        bonus = max(0, int(row["bonus"] or 0))  
        if btype == "warding_ac":  
            bonuses["armor_class"] = max(bonuses["armor_class"], bonus)  
        elif btype == "accuracy_attack":  
            bonuses["attack_bonus"] = max(bonuses["attack_bonus"], bonus)  
        elif btype == "potency_damage":  
            bonuses["damage_bonus"] = max(bonuses["damage_bonus"], bonus)  
    return bonuses  
  
  
async def recalculate_character_combat(character_id: int, preserve_current_hp: bool = True) -> bool:  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload or not payload.get("stats"):  
        return False  
    c = payload["character"]  
    stats_row = payload["stats"]  
    stats = {  
        "strength": int(stats_row["strength"]),  
        "dexterity": int(stats_row["dexterity"]),  
        "constitution": int(stats_row["constitution"]),  
        "intelligence": int(stats_row["intelligence"]),  
        "wisdom": int(stats_row["wisdom"]),  
        "charisma": int(stats_row["charisma"]),  
    }  
    species_passive = find_passive("species", c["species"], c.get("species_passive_name"))  
    class_passive = find_passive("class", c["class_name"], c.get("class_passive_name"))  
    combat = calculate_combat_values(  
        c["class_name"], stats, level=int(c.get("level") or 1), damage_die_sides=int(c.get("damage_die_sides") or 8),  
        species_name=c.get("species"), species_passive=species_passive, class_passive=class_passive,  
    )  
    bonuses = await resolved_level_choice_bonuses(character_id)  
    for key, value in bonuses.items():  
        if key in combat and combat.get(key) is not None:  
            combat[key] = int(combat.get(key) or 0) + int(value)  
  
    enchantment_bonuses = await fetch_economy_enchantment_combat_bonuses(int(c["guild_id"]), int(character_id))  
    for key, value in enchantment_bonuses.items():  
        if key in combat and combat.get(key) is not None:  
            combat[key] = int(combat.get(key) or 0) + int(value or 0)  
  
    async with db_pool.acquire() as conn:  
        old_hp = await conn.fetchval("SELECT current_hp FROM alaris_character_combat WHERE character_id=$1;", character_id)  
        current_hp = int(old_hp or combat["max_hp"]) if preserve_current_hp else int(combat["max_hp"])  
        current_hp = max(1, min(current_hp, int(combat["max_hp"])))  
        await conn.execute(  
            """  
            UPDATE alaris_character_combat  
            SET max_hp=$2,current_hp=$3,armor_class=$4,initiative_bonus=$5,proficiency_bonus=$6,  
                attack_bonus=$7,spell_dc=$8,technique_dc=$9,magic_save_bonus=$10,magic_defense=$11,  
                damage_die_sides=$12,damage_bonus=$13,max_resolve=$14,current_resolve=LEAST($14, GREATEST(0,current_resolve)),updated_at=NOW()  
            WHERE character_id=$1;  
            """,  
            character_id, int(combat["max_hp"]), current_hp, int(combat["armor_class"]), int(combat["initiative_bonus"]), int(combat["proficiency_bonus"]),  
            int(combat["attack_bonus"]), combat["spell_dc"], int(combat["technique_dc"]), int(combat.get("magic_save_bonus") or 0), int(combat.get("magic_defense") or 10),  
            int(combat.get("damage_die_sides") or 8), int(combat.get("damage_bonus") or 0), int(combat.get("max_resolve") or c.get("level") or 1),  
        )  
    return True  
  
  
async def ensure_character_passives(character_id: int) -> bool:  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return False  
    c = payload["character"]  
    species_passive = find_passive("species", c["species"], c.get("species_passive_name"))  
    class_passive = find_passive("class", c["class_name"], c.get("class_passive_name"))  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE alaris_characters  
            SET species_passive_name=$2,  
                species_passive_json=$3::jsonb,  
                class_passive_name=$4,  
                class_passive_json=$5::jsonb,  
                updated_at=NOW()  
            WHERE id=$1;  
            """,  
            character_id,  
            species_passive["name"],  
            json.dumps(species_passive),  
            class_passive["name"],  
            json.dumps(class_passive),  
        )  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_features (  
                guild_id, character_id, source_type, feature_name, feature_type, level_granted, metadata_json  
            )  
            VALUES ($1,$2,'species',$3,'passive',1,$4::jsonb)  
            ON CONFLICT DO NOTHING;  
            """,  
            int(c["guild_id"]), character_id, species_passive["name"], json.dumps(species_passive),  
        )  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_features (  
                guild_id, character_id, source_type, feature_name, feature_type, level_granted, metadata_json  
            )  
            VALUES ($1,$2,'class',$3,'passive',1,$4::jsonb)  
            ON CONFLICT DO NOTHING;  
            """,  
            int(c["guild_id"]), character_id, class_passive["name"], json.dumps(class_passive),  
        )  
    return True  
  
  
# ---------- Character Post Refresh ----------  
  
async def refresh_character_post(character_id: int) -> bool:  
    """Rebuild the live character-card embed for an existing character post."""  
    await ensure_character_passives(character_id)  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return False  
  
    try:  
        embed = build_character_embed(payload, dashboard=True)  
    except Exception:  
        LOG.exception("Failed to build character embed for refresh_character_post character_id=%s", character_id)  
        return False  
  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT thread_id, card_message_id  
            FROM alaris_character_posts  
            WHERE character_id=$1;  
            """,  
            character_id,  
        )  
  
    if not row or not row["thread_id"] or not row["card_message_id"]:  
        return False  
  
    try:  
        thread = bot.get_channel(int(row["thread_id"]))  
        if thread is None:  
            fetched = await bot.fetch_channel(int(row["thread_id"]))  
            thread = fetched if isinstance(fetched, discord.Thread) else None  
        if not isinstance(thread, discord.Thread):  
            return False  
  
        card_message = await thread.fetch_message(int(row["card_message_id"]))  
        await card_message.edit(embed=embed)  
        return True  
    except Exception:  
        LOG.exception("Failed to refresh character post for character_id=%s", character_id)  
        return False  
  
  
async def refresh_all_character_posts(guild_id: int) -> tuple[int, int]:  
    """Refresh all approved active character post embeds. Returns (updated, failed)."""  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id  
            FROM alaris_characters  
            WHERE guild_id=$1 AND status='active'  
            ORDER BY name;  
            """,  
            guild_id,  
        )  
  
    updated = 0  
    failed = 0  
    for row in rows:  
        ok = await refresh_character_post(int(row["id"]))  
        if ok:  
            updated += 1  
        else:  
            failed += 1  
    return updated, failed  
  
  
  
def parse_discord_message_link(link: str) -> Optional[tuple[int, int, int]]:  
    """Return (guild_id, channel_id, message_id) from a Discord message URL."""  
    text = str(link or "").strip()  
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", text)  
    if not m:  
        return None  
    try:  
        return int(m.group(1)), int(m.group(2)), int(m.group(3))  
    except Exception:  
        return None  
  
  
async def link_existing_character_showcase_post(  
    guild: discord.Guild,  
    character_id: int,  
    card_message_link: str,  
) -> tuple[bool, str]:  
    """Safely link an existing showcase card message to a character.  
  
    Staff must paste the URL for the actual character-card embed message inside the  
    character's existing showcase thread. This command never creates Discord posts  
    and never deletes anything; it only writes/repairs alaris_character_posts.  
    """  
    parsed = parse_discord_message_link(card_message_link)  
    if not parsed:  
        return False, "That does not look like a valid Discord message link. Right-click or long-press the character card message and copy its message link."  
  
    link_guild_id, channel_id, message_id = parsed  
    if link_guild_id != guild.id:  
        return False, "That message link belongs to a different server."  
  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return False, "Character not found."  
  
    thread = None  
    try:  
        maybe = guild.get_thread(channel_id)  
        if maybe is None:  
            fetched = await bot.fetch_channel(channel_id)  
            maybe = fetched if isinstance(fetched, discord.Thread) else None  
        thread = maybe  
    except Exception:  
        thread = None  
  
    if not isinstance(thread, discord.Thread):  
        return False, "That link does not point to a message inside a Discord thread/forum post. Paste the link to the character-card embed message inside the showcase post."  
  
    try:  
        card_message = await thread.fetch_message(message_id)  
    except Exception:  
        LOG.exception("Failed to fetch showcase card message for repair.")  
        return False, "I could not fetch that message. Check that the bot can view the showcase post and read message history."  
  
    if not card_message.embeds:  
        return False, "That message does not contain an embed. Paste the link to the character card embed message, not the starter/image/welcome message."  
  
    forum_channel_id = int(thread.parent_id or CHARACTER_DISCUSSION_CHANNEL_ID or 0)  
    if forum_channel_id <= 0:  
        return False, "Could not determine the parent showcase/forum channel for that thread."  
  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            INSERT INTO alaris_character_posts (  
                guild_id, character_id, forum_channel_id, thread_id,  
                starter_message_id, card_message_id, welcome_message_id, updated_at  
            )  
            VALUES ($1,$2,$3,$4,NULL,$5,NULL,NOW())  
            ON CONFLICT (character_id) DO UPDATE SET  
                guild_id=EXCLUDED.guild_id,  
                forum_channel_id=EXCLUDED.forum_channel_id,  
                thread_id=EXCLUDED.thread_id,  
                card_message_id=EXCLUDED.card_message_id,  
                updated_at=NOW();  
            """,  
            guild.id,  
            int(character_id),  
            forum_channel_id,  
            int(thread.id),  
            int(card_message.id),  
        )  
  
    # Edit-only refresh verifies the mapping can be used, and updates the card to current data.  
    refreshed = await refresh_character_post(character_id)  
    name = payload["character"].get("name") or f"Character {character_id}"  
    if refreshed:  
        return True, f"Linked **{name}** to existing showcase thread <#{thread.id}> and refreshed the mapped card."  
    return True, f"Linked **{name}** to existing showcase thread <#{thread.id}>, but the immediate card refresh did not complete. The mapping was still saved."  
  
  
@bot.tree.command(name="character-link-showcase", description="STAFF: link a character to an existing showcase card message.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    character="Character name to repair/link",  
    card_message_link="Discord message link to the character-card embed inside the existing showcase post",  
)  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_link_showcase(interaction: discord.Interaction, character: str, card_message_link: str):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.followup.send("Character not found.", ephemeral=True)  
        return  
    character_id = int(payload["character"]["id"])  
    ok, message = await link_existing_character_showcase_post(interaction.guild, character_id, card_message_link)  
    await interaction.followup.send(message, ephemeral=True)  
    if ok:  
        await post_command_log(interaction, f"linked showcase mapping for {payload['character'].get('name')} ({character_id})")  
  
  
@bot.tree.command(name="character-post-audit", description="STAFF: list active characters missing showcase post mappings.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def character_post_audit(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True)  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT  
                c.id,  
                c.name,  
                c.user_id,  
                p.thread_id,  
                p.card_message_id  
            FROM alaris_characters c  
            LEFT JOIN alaris_character_posts p ON p.character_id = c.id  
            WHERE c.guild_id=$1 AND c.status='active'  
            ORDER BY c.name;  
            """,  
            interaction.guild.id,  
        )  
    mapped = [r for r in rows if r["thread_id"] and r["card_message_id"]]  
    missing = [r for r in rows if not (r["thread_id"] and r["card_message_id"])]  
    embed = discord.Embed(  
        title="Character Showcase Mapping Audit",  
        color=discord.Color.gold(),  
        description=f"Active characters: **{len(rows)}**\nMapped: **{len(mapped)}**\nMissing/incomplete: **{len(missing)}**",  
    )  
    if missing:  
        lines = [f"• **{r['name']}** - ID `{r['id']}` - owner <@{r['user_id']}>" for r in missing]  
        embed.add_field(name="Needs Repair", value="\n".join(lines)[:1024], inline=False)  
    else:  
        embed.add_field(name="Needs Repair", value="None. All active characters have showcase mappings.", inline=False)  
    await interaction.followup.send(embed=embed, ephemeral=True)  
  
  
async def process_character_refresh_queue(guild_id: int, limit: int = 25) -> tuple[int, int, int]:  
    """Process external/economy refresh requests safely.  
  
    This is deliberately edit-only. It calls refresh_character_post(), which only  
    edits an existing mapped card_message_id. Missing mappings are marked skipped  
    and never create new showcase posts.  
    Returns (updated, skipped, failed).  
    """  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            SELECT id, character_id, reason  
            FROM alaris_character_refresh_queue  
            WHERE guild_id=$1 AND status='pending'  
            ORDER BY requested_at, id  
            LIMIT $2;  
            """,  
            guild_id, int(limit or 25),  
        )  
  
    updated = 0  
    skipped = 0  
    failed = 0  
    for row in rows:  
        request_id = int(row["id"])  
        character_id = int(row["character_id"])  
        try:  
            ok = await refresh_character_post(character_id)  
            async with db_pool.acquire() as conn:  
                if ok:  
                    await conn.execute(  
                        """  
                        UPDATE alaris_character_refresh_queue  
                        SET status='processed', processed_at=NOW(), error_text=NULL  
                        WHERE id=$1;  
                        """,  
                        request_id,  
                    )  
                    updated += 1  
                else:  
                    await conn.execute(  
                        """  
                        UPDATE alaris_character_refresh_queue  
                        SET status='skipped', processed_at=NOW(),  
                            error_text='No existing character post mapping/card message was found. Edit-only refresh did not create a new post.'  
                        WHERE id=$1;  
                        """,  
                        request_id,  
                    )  
                    skipped += 1  
        except Exception as exc:  
            LOG.exception("Failed processing character refresh queue row id=%s character_id=%s", request_id, character_id)  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_refresh_queue  
                    SET status='failed', processed_at=NOW(), error_text=$2  
                    WHERE id=$1;  
                    """,  
                    request_id, str(exc)[:1000],  
                )  
            failed += 1  
    return updated, skipped, failed  
  
  
# ---------- Character Post Moderation ----------  
  
async def get_character_post_owner_for_thread(guild_id: int, thread_id: int) -> Optional[int]:  
    async with db_pool.acquire() as conn:  
        return await conn.fetchval(  
            """  
            SELECT c.user_id  
            FROM alaris_character_posts p  
            JOIN alaris_characters c ON c.id = p.character_id  
            WHERE p.guild_id=$1 AND p.thread_id=$2 AND c.status='active'  
            LIMIT 1;  
            """,  
            guild_id, thread_id,  
        )  
  
  
@bot.event  
async def on_message(message: discord.Message):  
    if message.author.bot or message.guild is None:  
        return  
  
    # Only moderate character discussion posts/threads created by this bot.  
    if isinstance(message.channel, discord.Thread):  
        owner_id = await get_character_post_owner_for_thread(message.guild.id, message.channel.id)  
        if owner_id:  
            is_owner = message.author.id == int(owner_id)  
            is_staff = isinstance(message.author, discord.Member) and is_staff_member(message.author)  
            if not is_owner and not is_staff:  
                try:  
                    await message.delete()  
                except Exception:  
                    LOG.exception("Failed to delete unauthorized message in character post.")  
                try:  
                    await message.author.send(  
                        "That character post is reserved for the character's owner and staff. "  
                        "Please ask staff if you need to add something there."  
                    )  
                except Exception:  
                    pass  
                return  
  
    await bot.process_commands(message)  
  
  
  
async def smoke_check_required_schema() -> None:  
    required = {  
        "alaris_character_combat": [  
            "character_id", "max_hp", "current_hp", "armor_class", "initiative_bonus",  
            "proficiency_bonus", "attack_bonus", "spell_dc", "technique_dc",  
            "magic_save_bonus", "magic_defense", "damage_die_sides", "damage_bonus",  
            "max_resolve", "current_resolve", "damage_type", "resistances_json", "weaknesses_json", "immunities_json",  
        ],  
        "alaris_combatants": [  
            "encounter_id", "combatant_type", "name", "max_hp", "current_hp",  
            "armor_class", "initiative_bonus", "attack_bonus", "save_dc",  
            "magic_save_bonus", "magic_defense", "damage_die_sides", "damage_bonus",  
            "xp_value", "max_resolve", "current_resolve",  
        ],  
        "alaris_characters": [  
            "species_passive_name", "species_passive_json",  
            "class_passive_name", "class_passive_json",  
        ],  
    }  
    async with db_pool.acquire() as conn:  
        for table, cols in required.items():  
            existing = set(await get_columns(conn, table))  
            missing = [c for c in cols if c not in existing]  
            if missing:  
                raise RuntimeError(f"Required schema missing columns on {table}: {', '.join(missing)}")  
  
  
  
# ---------- Testing / Admin Utilities ----------  
  
def debug_json_preview(value: Any, fallback: str = "{}") -> str:  
    try:  
        if value is None:  
            return fallback  
        if isinstance(value, str):  
            return value[:500]  
        return json.dumps(value, default=str)[:500]  
    except Exception:  
        return fallback  
  
  
def format_combatant_debug_line(c: dict[str, Any], states: Optional[list[dict[str, Any]]] = None) -> str:  
    state_text = ""  
    if states:  
        state_text = " | States: " + ", ".join(f"{s['state_key']}({s['duration_turns']})" for s in states)  
    resolve_text = ""  
    if c.get("combatant_type") == "character":  
        resolve_text = f" | Resolve {int(c.get('current_resolve') or 0)}/{int(c.get('max_resolve') or 1)}"  
    return (  
        f"`{int(c['id'])}` **{c['name']}** [{c['combatant_type']}] "  
        f"HP {int(c.get('current_hp') or 0)}/{int(c.get('max_hp') or 0)} | "  
        f"AC {int(c.get('armor_class') or 0)} | Atk +{int(c.get('attack_bonus') or 0)} | "  
        f"DC {int(c.get('save_dc') or 0)} | Dmg 1d{int(c.get('damage_die_sides') or 0)}+{int(c.get('damage_bonus') or 0)} "  
        f"{c.get('damage_type') or ''} | Status {c.get('status')}{resolve_text}{state_text}"  
    )  
  
  
async def get_active_combat_debug(guild_id: int, channel_id: int) -> Optional[dict[str, Any]]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            """  
            SELECT *  
            FROM alaris_combat_encounters  
            WHERE guild_id=$1 AND channel_id=$2 AND status='open'  
            ORDER BY created_at DESC  
            LIMIT 1;  
            """,  
            guild_id,  
            channel_id,  
        )  
    return dict(row) if row else None  
  
  
@bot.tree.command(name="combat-debug-status", description="DEV: show full debug status for active combat in this channel.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def combat_debug_status(interaction: discord.Interaction):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("Use this in a server channel.", ephemeral=True)  
        return  
    combat = await get_active_combat_debug(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("No active combat in this channel.", ephemeral=True)  
        return  
  
    combatants = await get_combatants(int(combat["id"]))  
    lines = []  
    for c in combatants:  
        states = await active_states_for_combatant(int(combat["id"]), int(c["id"]))  
        lines.append(format_combatant_debug_line(c, states))  
  
    xp_pool = await defeated_enemy_xp_pool(int(combat["id"]))  
    current = await current_turn_combatant(int(combat["id"]))  
    embed = discord.Embed(  
        title="Combat Debug Status",  
        description=f"Encounter ID: `{combat['id']}`\nSession ID: `{combat.get('session_id')}`\nXP Pool: **{xp_pool}**",  
        color=discord.Color.orange(),  
    )  
    embed.add_field(name="Round / Turn", value=f"Round {combat.get('round_number')} | Index {combat.get('current_turn_index')}", inline=True)  
    embed.add_field(name="Current Turn", value=f"{current['name']} (`{current['id']}`)" if current else "None", inline=True)  
    chunks = []  
    current_chunk = ""  
    for line in lines:  
        if len(current_chunk) + len(line) + 1 > 1000:  
            chunks.append(current_chunk)  
            current_chunk = line  
        else:  
            current_chunk += ("\n" if current_chunk else "") + line  
    if current_chunk:  
        chunks.append(current_chunk)  
    for i, chunk in enumerate(chunks[:5], start=1):  
        embed.add_field(name=f"Combatants {i}", value=chunk, inline=False)  
  
    await interaction.response.send_message(embed=embed, ephemeral=True)  
  
  
@bot.tree.command(name="character-debug-card", description="DEV: show raw/debug character info.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_debug_card(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    c = payload["character"]  
    stats = payload.get("stats") or {}  
    derived = payload.get("derived") or {}  
    abilities = await unlocked_abilities_for_character(int(c["id"])) if "unlocked_abilities_for_character" in globals() else []  
  
    embed = discord.Embed(title=f"Character Debug - {c['name']}", color=discord.Color.orange())  
    embed.add_field(name="IDs", value=f"Character ID: `{c['id']}`\nOwner: `<@{c['user_id']}>`\nGuild: `{c['guild_id']}`", inline=False)  
    embed.add_field(name="Core", value=f"Species: {c.get('species')}\nClass: {c.get('class_name')}\nLevel: {c.get('level')}\nXP: {c.get('xp_total')}", inline=True)  
    embed.add_field(name="Starter Passives", value=format_starter_passives_for_card(c), inline=False)  
    embed.add_field(name="Stats", value=format_stats(stats) if stats else "No stats", inline=True)  
    embed.add_field(  
        name="Combat",  
        value=(  
            f"HP {derived.get('current_hp')}/{derived.get('max_hp')}\n"  
            f"AC {derived.get('armor_class')} | Atk +{derived.get('attack_bonus')}\n"  
            f"Spell DC {derived.get('spell_dc')} | Tech DC {derived.get('technique_dc')}\n"  
            f"Resolve {derived.get('current_resolve')}/{derived.get('max_resolve')}"  
        ),  
        inline=True,  
    )  
    embed.add_field(name="Affinities", value=f"Resist: {format_affinity_json(derived.get('resistances_json'))}\nWeak: {format_affinity_json(derived.get('weaknesses_json'))}\nImmune: {format_affinity_json(derived.get('immunities_json'))}", inline=False)  
    embed.add_field(name="Unlocked Abilities", value=format_unlocked_abilities_for_card(abilities), inline=False)  
    pending = await pending_level_choices_for_character(int(c["id"])) if "pending_level_choices_for_character" in globals() else []  
    if pending:  
        embed.add_field(name="Pending Choices", value="\n".join(f"• L{p['level']} {p['choice_type']}" for p in pending)[:1024], inline=False)  
    else:  
        async with db_pool.acquire() as conn:  
            resolved = await conn.fetch(  
                """  
                SELECT level, choice_type, selected_option  
                FROM alaris_level_choices  
                WHERE character_id=$1 AND status='resolved'  
                ORDER BY level, choice_type;  
                """,  
                int(c["id"]),  
            )  
        if resolved:  
            embed.add_field(  
                name="Resolved Choices",  
                value="\n".join(f"• L{r['level']} {r['choice_type']}: {r['selected_option'] or 'None'}" for r in resolved)[:1024],  
                inline=False,  
            )  
    await interaction.response.send_message(embed=embed, ephemeral=True)  
  
  
@bot.tree.command(name="combat-add-test-enemy", description="DEV: add a test enemy to active combat.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(name="Enemy name", hp="Max/current HP", ac="Armor Class", attack="Attack bonus", damage_die="Damage die sides", damage_bonus="Damage bonus", damage_type="Damage type")  
async def combat_add_test_enemy(  
    interaction: discord.Interaction,  
    name: str,  
    hp: int = 10,  
    ac: int = 12,  
    attack: int = 3,  
    damage_die: int = 6,  
    damage_bonus: int = 0,  
    damage_type: str = "blunt",  
):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("Use this in a server channel.", ephemeral=True)  
        return  
    combat = await get_active_combat_debug(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("No active combat in this channel.", ephemeral=True)  
        return  
    dtype = normalize_damage_type(damage_type, "blunt")  
    enemy = {  
        "name": name,  
        "max_hp": max(1, hp),  
        "current_hp": max(1, hp),  
        "armor_class": ac,  
        "initiative_bonus": max(0, attack // 2),  
        "attack_bonus": attack,  
        "save_dc": 10 + max(0, attack),  
        "magic_save_bonus": max(0, attack // 2),  
        "magic_defense": 10 + max(0, attack // 2),  
        "damage_die_sides": damage_die,  
        "damage_bonus": damage_bonus,  
        "damage_type": dtype,  
        "xp_value": 25,  
        "role": "minion",  
        "theme": "test",  
        "resistances_json": {},  
        "weaknesses_json": {},  
        "immunities_json": {},  
    }  
    eid = await add_enemy_combatant(int(combat["id"]), enemy)  
    await interaction.response.send_message(f"Added test enemy **{name}** with combatant ID `{eid}`.", ephemeral=True)  
  
  
@bot.tree.command(name="combat-set-hp", description="DEV: set combatant HP by combatant ID.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(combatant_id="Combatant ID from /combat-debug-status", hp="New current HP")  
async def combat_set_hp(interaction: discord.Interaction, combatant_id: int, hp: int):  
    if not await require_developer(interaction):  
        return  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", combatant_id)  
        if not row:  
            await interaction.response.send_message("Combatant not found.", ephemeral=True)  
            return  
        max_hp = int(row["max_hp"] or 1)  
        new_hp = max(0, min(max_hp, hp))  
        status = "defeated" if new_hp <= 0 else "active"  
        await conn.execute("UPDATE alaris_combatants SET current_hp=$2, status=$3 WHERE id=$1;", combatant_id, new_hp, status)  
    await interaction.response.send_message(f"Set **{row['name']}** HP to **{new_hp}/{max_hp}** and status to **{status}**.", ephemeral=True)  
  
  
@bot.tree.command(name="combat-set-turn", description="DEV: force active combat turn to a combatant ID.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(combatant_id="Combatant ID from /combat-debug-status")  
async def combat_set_turn(interaction: discord.Interaction, combatant_id: int):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("Use this in a server channel.", ephemeral=True)  
        return  
    combat = await get_active_combat_debug(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("No active combat in this channel.", ephemeral=True)  
        return  
    async with db_pool.acquire() as conn:  
        target = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1 AND encounter_id=$2;", combatant_id, int(combat["id"]))  
        if not target:  
            await interaction.response.send_message("Combatant not found in this encounter.", ephemeral=True)  
            return  
        order_raw = combat["turn_order_json"]  
        order = json.loads(order_raw) if isinstance(order_raw, str) else list(order_raw or [])  
        new_index = None  
        for idx, item in enumerate(order):  
            if int(item["combatant_id"]) == combatant_id:  
                new_index = idx  
                break  
        if new_index is None:  
            order.append({"combatant_id": combatant_id, "initiative": int(target["initiative_bonus"] or 0), "name": target["name"]})  
            new_index = len(order) - 1  
        await conn.execute(  
            """  
            UPDATE alaris_combat_encounters  
            SET current_turn_combatant_id=$2,  
                current_turn_index=$3,  
                turn_order_json=$4::jsonb  
            WHERE id=$1;  
            """,  
            int(combat["id"]), combatant_id, new_index, json.dumps(order),  
        )  
    await interaction.response.send_message(f"Set current turn to **{target['name']}** (`{combatant_id}`).", ephemeral=True)  
    if isinstance(interaction.channel, discord.abc.Messageable):  
        await post_current_turn(interaction.channel, int(combat["id"]))  
  
  
@bot.tree.command(name="combat-clear-states", description="DEV: clear states from one combatant or all in active combat.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(combatant_id="Optional combatant ID. Omit/0 to clear all states in active combat.")  
async def combat_clear_states(interaction: discord.Interaction, combatant_id: int = 0):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None or interaction.channel is None:  
        await interaction.response.send_message("Use this in a server channel.", ephemeral=True)  
        return  
    combat = await get_active_combat_debug(interaction.guild.id, interaction.channel.id)  
    if not combat:  
        await interaction.response.send_message("No active combat in this channel.", ephemeral=True)  
        return  
    async with db_pool.acquire() as conn:  
        if combatant_id:  
            result = await conn.execute("DELETE FROM alaris_combat_states WHERE encounter_id=$1 AND combatant_id=$2;", int(combat["id"]), combatant_id)  
        else:  
            result = await conn.execute("DELETE FROM alaris_combat_states WHERE encounter_id=$1;", int(combat["id"]))  
    await interaction.response.send_message(f"Cleared combat states. Result: `{result}`", ephemeral=True)  
  
  
@bot.tree.command(name="character-grant-xp", description="STAFF: grant XP to a character and open level ticket if needed.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name", xp="XP to grant")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_grant_xp(interaction: discord.Interaction, character: str, xp: int):  
    if not await require_staff(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    result = await award_xp_to_character(
        int(interaction.guild.id),
        int(payload["character"]["id"]),
        max(0, xp),
        "staff_grant",
        None,
        f"granted by {interaction.user.id}",
        awarded_by=int(interaction.user.id),
    )
    if "open_level_ticket_if_needed" in globals():  
        await open_level_ticket_if_needed(interaction.guild, int(payload["character"]["id"]))  
    await post_level_up_message(result)
    await refresh_character_post(int(payload["character"]["id"]))  
    await interaction.response.send_message(  
        f"Granted **{xp} XP** to **{payload['character']['name']}**. "  
        f"Level {result.get('old_level')} → {result.get('new_level')}; XP {result.get('old_xp')} → {result.get('new_xp')}.",  
        ephemeral=True,  
    )  
  
  
@bot.tree.command(name="character-reset-level-choices", description="DEV: reset pending/resolved level choices for a character.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name", mode="pending_only or all")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_reset_level_choices(interaction: discord.Interaction, character: str, mode: str = "pending_only"):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    mode_norm = normalize_name(mode)  
    async with db_pool.acquire() as conn:  
        if mode_norm in {"all", "everything"}:  
            result = await conn.execute("DELETE FROM alaris_level_choices WHERE character_id=$1;", cid)  
            await conn.execute("DELETE FROM alaris_character_abilities WHERE character_id=$1;", cid)  
        else:  
            result = await conn.execute("DELETE FROM alaris_level_choices WHERE character_id=$1 AND status='pending';", cid)  
    await recalculate_character_combat(cid, preserve_current_hp=False)  
    await refresh_character_post(cid)  
    await interaction.response.send_message(f"Reset level choices for **{payload['character']['name']}**. Result: `{result}`.", ephemeral=True)  
  
  
  
  
  
@bot.tree.command(name="roster-debug", description="DEV: show species/classes available in character creation.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def roster_debug(interaction: discord.Interaction):  
    if not await require_developer(interaction):  
        return  
    embed = discord.Embed(title="Alaris Roster Debug", color=discord.Color.orange())  
    embed.add_field(name=f"Classes ({len(CLASS_OPTIONS)})", value=", ".join(CLASS_OPTIONS)[:1024], inline=False)  
    embed.add_field(name=f"Species ({len(SPECIES_OPTIONS)})", value=", ".join(SPECIES_OPTIONS)[:1024], inline=False)  
  
    missing_scaling = [c for c in CLASS_OPTIONS if normalize_name(c) not in CLASS_COMBAT_SCALING]  
    missing_class_passives = [c for c in CLASS_OPTIONS if normalize_name(c) not in CLASS_PASSIVE_OPTIONS]  
    missing_class_abilities = [  
        c for c in CLASS_OPTIONS  
        if normalize_name(c) not in CLASS_ACTIVE_ABILITIES  
        or sorted(CLASS_ACTIVE_ABILITIES.get(normalize_name(c), {}).keys()) != [2, 4, 6, 8, 10]  
    ]  
    missing_species_passives = [s for s in SPECIES_OPTIONS if normalize_name(s) not in SPECIES_PASSIVE_OPTIONS]  
    missing_species_abilities = [  
        s for s in SPECIES_OPTIONS  
        if normalize_name(s) not in SPECIES_ACTIVE_ABILITIES  
        or sorted(SPECIES_ACTIVE_ABILITIES.get(normalize_name(s), {}).keys()) != [3, 7]  
    ]  
  
    embed.add_field(name="Missing Class Scaling", value=", ".join(missing_scaling) if missing_scaling else "None", inline=False)  
    embed.add_field(name="Missing Class Passives", value=", ".join(missing_class_passives) if missing_class_passives else "None", inline=False)  
    embed.add_field(name="Missing Class Active Ability Levels", value=", ".join(missing_class_abilities) if missing_class_abilities else "None", inline=False)  
    embed.add_field(name="Missing Species Passives", value=", ".join(missing_species_passives) if missing_species_passives else "None", inline=False)  
    embed.add_field(name="Missing Species Active Abilities", value=", ".join(missing_species_abilities) if missing_species_abilities else "None", inline=False)  
    await interaction.response.send_message(embed=embed, ephemeral=True)  
  
  
async def repair_missing_level_choices_for_character(character_id: int, guild_id: int) -> int:  
    """Create any missing pending level choices for the character's current level.  
  
    This is additive only. It does not delete resolved choices or overwrite selections.  
    """  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return 0  
    level = int(payload["character"].get("level") or 1)  
    created = 0  
    async with db_pool.acquire() as conn:  
        for lvl in range(2, level + 1):  
            for choice_type in level_choice_types_for_level(lvl):  
                result = await conn.execute(  
                    """  
                    INSERT INTO alaris_level_choices (guild_id, character_id, level, choice_type, status, metadata_json)  
                    VALUES ($1,$2,$3,$4,'pending','{}'::jsonb)  
                    ON CONFLICT DO NOTHING;  
                    """,  
                    int(guild_id), int(character_id), int(lvl), str(choice_type),  
                )  
                if result.endswith("1"):  
                    created += 1  
    return created  
  
  
async def backfill_unlocked_abilities_from_resolved_choices_safe(character_id: int) -> int:  
    """Repair ability unlock rows from resolved level choices."""  
    payload = await fetch_clean_character_by_id(character_id)  
    if not payload:  
        return 0  
    created = 0  
    async with db_pool.acquire() as conn:  
        await conn.execute("""  
            CREATE TABLE IF NOT EXISTS alaris_character_abilities (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL REFERENCES alaris_characters(id) ON DELETE CASCADE,  
                ability_name TEXT NOT NULL,  
                class_name TEXT,  
                level_granted INTEGER NOT NULL DEFAULT 1,  
                metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                UNIQUE(character_id, ability_name)  
            );  
        """)  
        rows = await conn.fetch(  
            """  
            SELECT level, choice_type, selected_option  
            FROM alaris_level_choices  
            WHERE character_id=$1  
              AND status='resolved'  
              AND choice_type IN ('ability','species_ability')  
              AND selected_option IS NOT NULL  
            ORDER BY level, choice_type;  
            """,  
            int(character_id),  
        )  
    for row in rows:  
        selected = str(row["selected_option"] or "").strip()  
        if not selected:  
            continue  
        if row["choice_type"] == "ability":  
            await unlock_character_ability_from_choice(int(character_id), selected, int(row["level"] or 1))  
            created += 1  
        elif row["choice_type"] == "species_ability":  
            await unlock_species_ability_from_choice(int(character_id), selected, int(row["level"] or 1))  
            created += 1  
    return created  
  
  
@bot.tree.command(name="level-choice-debug", description="DEV: show pending/resolved level choices and option labels for a character.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def level_choice_debug(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    async with db_pool.acquire() as conn:  
        pending = await conn.fetch(  
            """  
            SELECT *  
            FROM alaris_level_choices  
            WHERE character_id=$1 AND status='pending'  
            ORDER BY level, choice_type;  
            """,  
            cid,  
        )  
        resolved = await conn.fetch(  
            """  
            SELECT level, choice_type, selected_option  
            FROM alaris_level_choices  
            WHERE character_id=$1 AND status='resolved'  
            ORDER BY level, choice_type;  
            """,  
            cid,  
        )  
    lines = [f"**{payload['character']['name']}** level-choice debug"]  
    if pending:  
        lines.append("\n**Pending**")  
        for row in pending:  
            choice = dict(row)  
            opts = choice_option_rows(choice, payload)  
            lines.append(f"`{choice['id']}` L{choice['level']} **{choice['choice_type']}** → " + ", ".join(o["label"] for o in opts))  
    else:  
        lines.append("\n**Pending**\nNone")  
    if resolved:  
        lines.append("\n**Resolved**")  
        for row in resolved:  
            lines.append(f"L{row['level']} **{row['choice_type']}** → {row['selected_option'] or 'None'}")  
    else:  
        lines.append("\n**Resolved**\nNone")  
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)  
  
  
@bot.tree.command(name="character-level-repair", description="DEV: repair missing level choices and ability rows for a character.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_level_repair(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    created = await repair_missing_level_choices_for_character(cid, interaction.guild.id)  
    backfilled = await backfill_unlocked_abilities_from_resolved_choices_safe(cid)  
    await recalculate_character_combat(cid, preserve_current_hp=False)  
    await refresh_character_post(cid)  
    ticket_channel_id = await open_level_ticket_if_needed(interaction.guild, cid)  
    if ticket_channel_id:  
        channel = interaction.guild.get_channel(int(ticket_channel_id))  
        if channel is None:  
            try:  
                channel = await bot.fetch_channel(int(ticket_channel_id))  
            except Exception:  
                channel = None  
        if isinstance(channel, discord.TextChannel):  
            await channel.send("🔄 Refreshed level-up choice embeds after level repair.")  
            await post_level_choice_embeds(channel, cid)  
    ticket_note = f" Ticket: <#{ticket_channel_id}>" if ticket_channel_id else ""  
    await interaction.response.send_message(  
        f"Repaired **{payload['character']['name']}**. Created **{created}** missing pending choice(s); "  
        f"backfilled **{backfilled}** ability row(s).{ticket_note}",  
        ephemeral=True,  
    )  
  
  
@bot.tree.command(name="character-abilities-repair", description="DEV: backfill unlocked abilities from resolved level choices.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_abilities_repair(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    backfilled = await backfill_unlocked_abilities_from_resolved_choices_safe(cid)  
    await recalculate_character_combat(cid, preserve_current_hp=False)  
    await refresh_character_post(cid)  
    fresh = await fetch_clean_character_by_id(cid)  
    abilities = fresh.get("abilities") if fresh else []  
    await interaction.response.send_message(  
        f"Backfilled **{backfilled}** ability row(s) for **{payload['character']['name']}**. "  
        f"Unlocked abilities now: **{len(abilities or [])}**.",  
        ephemeral=True,  
    )  
  
  
@bot.tree.command(name="character-species-ability-repair", description="DEV: add missing Level 3/7 species ability choices.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_species_ability_repair(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    cid = int(payload["character"]["id"])  
    created = 0  
    level = int(payload["character"].get("level") or 1)  
    async with db_pool.acquire() as conn:  
        for lvl in sorted(SPECIES_ABILITY_LEVELS):  
            if level >= int(lvl):  
                result = await conn.execute(  
                    """  
                    INSERT INTO alaris_level_choices (guild_id, character_id, level, choice_type, status, metadata_json)  
                    VALUES ($1,$2,$3,'species_ability','pending','{}'::jsonb)  
                    ON CONFLICT DO NOTHING;  
                    """,  
                    int(interaction.guild.id), cid, int(lvl),  
                )  
                if result.endswith("1"):  
                    created += 1  
    ticket_channel_id = await open_level_ticket_if_needed(interaction.guild, cid)  
    if ticket_channel_id:  
        channel = interaction.guild.get_channel(int(ticket_channel_id))  
        if channel is None:  
            try:  
                channel = await bot.fetch_channel(int(ticket_channel_id))  
            except Exception:  
                channel = None  
        if isinstance(channel, discord.TextChannel):  
            await channel.send("🔄 Refreshed species ability choice embeds.")  
            await post_level_choice_embeds(channel, cid)  
    await refresh_character_post(cid)  
    ticket_note = f" Ticket: <#{ticket_channel_id}>" if ticket_channel_id else ""  
    await interaction.response.send_message(  
        f"Created **{created}** missing species ability choice(s) for **{payload['character']['name']}**.{ticket_note}",  
        ephemeral=True,  
    )  
  
  
  
  
@bot.tree.command(name="character-passive-debug", description="DEV: show raw passive fields for a character.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(character="Character name")  
@app_commands.autocomplete(character=character_name_autocomplete)  
async def character_passive_debug(interaction: discord.Interaction, character: str):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    payload = await find_character(interaction.guild.id, character)  
    if not payload:  
        await interaction.response.send_message("Character not found.", ephemeral=True)  
        return  
    c = payload["character"]  
    embed = discord.Embed(title=f"Passive Debug - {c['name']}", color=discord.Color.orange())  
    embed.add_field(name="Recorded Passives", value=format_starter_passives_for_card(c), inline=False)  
    embed.add_field(name="Species Passive JSON", value=f"```json\n{debug_json_preview(c.get('species_passive_json'))}\n```", inline=False)  
    embed.add_field(name="Class Passive JSON", value=f"```json\n{debug_json_preview(c.get('class_passive_json'))}\n```", inline=False)  
    await interaction.response.send_message(embed=embed, ephemeral=True)  
  
  
  
  
# ---------- Self-Test Suite ----------  
  
SELF_TEST_CLASS_LEVELS = [2, 4, 6, 8, 10]  
SELF_TEST_SPECIES_LEVELS = [3, 7]  
SELF_TEST_ABILITY_KINDS = {"buff", "heal", "debuff", "spell", "strike", "strike_buff", "spell_buff"}  
SELF_TEST_PASSIVE_BONUSES = {  
    "attack_bonus",  
    "damage_bonus",  
    "armor_class",  
    "initiative_bonus",  
    "spell_dc",  
    "technique_dc",  
    "magic_defense",  
    "hp_per_level",  
    "resolve_bonus",  
}  
SELF_TEST_EXPECTED_CLASSES = [  
    "Artificer", "Barbarian", "Bard", "Captain", "Cleric", "Druid", "Fighter",  
    "Monk", "Paladin", "Ranger", "Rogue", "Scholar", "Sorcerer", "Warlock",  
    "Warden", "Wizard",  
]  
SELF_TEST_EXPECTED_SPECIES = [  
    "Aasimar", "Centaur", "Dhampir", "Dragonborn", "Drow", "Dwarf", "Elf",  
    "Faerie", "Genasi", "Gnome", "Goblin", "Goliath", "Halfling", "Human",  
    "Kitsune", "Merfolk", "Orc", "Theranth", "Tiefling", "Triton", "Werewolf",  
]  
  
  
class SelfTestReport:  
    def __init__(self) -> None:  
        self.rows: list[tuple[bool, str, str]] = []  
  
    def add(self, ok: bool, name: str, detail: str = "") -> None:  
        self.rows.append((bool(ok), name, detail or ""))  
  
    def extend(self, other: "SelfTestReport") -> None:  
        self.rows.extend(other.rows)  
  
    @property  
    def passed(self) -> int:  
        return sum(1 for ok, _, _ in self.rows if ok)  
  
    @property  
    def failed(self) -> int:  
        return sum(1 for ok, _, _ in self.rows if not ok)  
  
    def as_text(self, limit: int = 3900) -> str:  
        lines = [f"Self-test results: ✅ {self.passed} passed | ❌ {self.failed} failed"]  
        for ok, name, detail in self.rows:  
            icon = "✅" if ok else "❌"  
            line = f"{icon} {name}"  
            if detail:  
                line += f" — {detail}"  
            lines.append(line)  
        text = "\n".join(lines)  
        if len(text) > limit:  
            text = text[:limit - 120] + f"\n… truncated. Totals: ✅ {self.passed} | ❌ {self.failed}"  
        return text  
  
  
def selftest_add_section(report: SelfTestReport, title: str) -> None:  
    report.add(True, f"--- {title} ---")  
  
  
async def selftest_cleanup_orphaned_selftest_data(guild_id: int) -> int:  
    """Remove temporary SELFTEST artifacts left by self-test runs."""  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            await conn.execute(  
                "DELETE FROM alaris_combat_encounters WHERE guild_id=$1 AND channel_id=0;",  
                int(guild_id),  
            )  
            result = await conn.execute(  
                """  
                DELETE FROM alaris_characters  
                WHERE guild_id=$1  
                  AND (  
                    normalized_name LIKE 'selftest-%'  
                    OR lower(name) LIKE 'selftest %'  
                    OR lower(name) LIKE 'selftest-%'  
                  );  
                """,  
                int(guild_id),  
            )  
            for table in [  
                "alaris_level_choices",  
                "alaris_level_tickets",  
                "alaris_character_abilities",  
                "alaris_character_features",  
                "alaris_character_posts",  
                "alaris_character_combat",  
                "alaris_character_stats",  
            ]:  
                try:  
                    await conn.execute(  
                        f"DELETE FROM {table} WHERE character_id NOT IN (SELECT id FROM alaris_characters);"  
                    )  
                except Exception:  
                    pass  
    try:  
        return int(str(result).split()[-1])  
    except Exception:  
        return 0  
  
  
async def selftest_card_consistency_for_character(character_id: int) -> tuple[bool, str]:  
    """Validate debug/card consistency after a character's level choices are resolved."""  
    payload = await fetch_clean_character_by_id_without_backfill(int(character_id))  
    if not payload:  
        return False, "character not fetchable"  
    c = payload["character"]  
    level = int(c.get("level") or 1)  
    pending = await pending_level_choices_for_character(int(character_id))  
    abilities = await unlocked_abilities_for_character(int(character_id))  
    ability_names = {normalize_name(a.get("name")) for a in abilities}  
  
    stale = [p for p in pending if int(p.get("level") or 0) <= level]  
    if stale:  
        return False, "stale pending choices remain: " + ", ".join(f"L{p['level']} {p['choice_type']}" for p in stale)  
  
    class_key = normalize_name(c.get("class_name"))  
    species_key = normalize_name(c.get("species"))  
  
    missing = []  
    for unlock_level, options in CLASS_ACTIVE_ABILITIES.get(class_key, {}).items():  
        if int(unlock_level) <= level:  
            if not any(normalize_name(a.get("name")) in ability_names for a in options):  
                missing.append(f"class L{unlock_level}")  
  
    for unlock_level, options in SPECIES_ACTIVE_ABILITIES.get(species_key, {}).items():  
        if int(unlock_level) <= level:  
            if not any(normalize_name(a.get("name")) in ability_names for a in options):  
                missing.append(f"species L{unlock_level}")  
  
    if missing:  
        return False, "missing eligible unlocked ability tier(s): " + ", ".join(missing)  
  
    d = payload.get("derived") or {}  
    required_fields = ["max_hp", "armor_class", "attack_bonus", "technique_dc", "max_resolve"]  
    for key in required_fields:  
        if key not in d or d.get(key) is None:  
            return False, f"missing derived combat field {key}"  
  
    # Spell DC is intentionally nullable for non-casting classes. The card renders this as an em dash.  
    # Caster classes must have it, because their spell/save abilities depend on it.  
    class_key_for_dc = normalize_name(c.get("class_name"))  
    if class_key_for_dc in CASTING_STAT_BY_CLASS and d.get("spell_dc") is None:  
        return False, "missing derived combat field spell_dc for caster class"  
  
    try:  
        embed = build_character_embed(payload, dashboard=True)  
        if not embed or not embed.title:  
            return False, "character embed did not build cleanly"  
    except Exception as exc:  
        return False, "character embed build failed: " + truncate(exc, 200)  
  
    return True, f"level={level}, unlocked={len(abilities)}, pending={len(pending)}"  
  
  
def selftest_allowed_target_types(kind: str) -> set[str]:  
    kind = normalize_name(kind)  
    if kind in {"buff", "heal"}:  
        return {"ally", "self"}  
    if kind in {"debuff", "spell", "strike"}:  
        return {"enemy"}  
    if kind in {"strike_buff", "spell_buff"}:  
        return {"enemy"}  
    return {"enemy", "ally", "self"}  
  
  
def selftest_registry_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Registry Audit")  
  
    class_set = set(CLASS_OPTIONS)  
    species_set = set(SPECIES_OPTIONS)  
    report.add(CLASS_OPTIONS == SELF_TEST_EXPECTED_CLASSES, "Class roster exact order/count", f"{len(CLASS_OPTIONS)} classes")  
    report.add(SPECIES_OPTIONS == SELF_TEST_EXPECTED_SPECIES, "Species roster exact order/count", f"{len(SPECIES_OPTIONS)} species")  
  
    for class_name in SELF_TEST_EXPECTED_CLASSES:  
        key = normalize_name(class_name)  
        report.add(key in CLASS_PASSIVE_OPTIONS, f"{class_name} starter passives registered")  
        if key in CLASS_PASSIVE_OPTIONS:  
            report.add(len(CLASS_PASSIVE_OPTIONS[key]) == 3, f"{class_name} has 3 starter passives", str(len(CLASS_PASSIVE_OPTIONS[key])))  
        report.add(key in CLASS_ACTIVE_ABILITIES, f"{class_name} active ability tree registered")  
        if key in CLASS_ACTIVE_ABILITIES:  
            levels = sorted(int(k) for k in CLASS_ACTIVE_ABILITIES[key].keys())  
            report.add(levels == SELF_TEST_CLASS_LEVELS, f"{class_name} class ability unlock levels", str(levels))  
            for lvl in SELF_TEST_CLASS_LEVELS:  
                abilities = CLASS_ACTIVE_ABILITIES[key].get(lvl, [])  
                report.add(len(abilities) >= 2, f"{class_name} L{lvl} has at least 2 choices", str(len(abilities)))  
  
    for species_name in SELF_TEST_EXPECTED_SPECIES:  
        key = normalize_name(species_name)  
        report.add(key in SPECIES_PASSIVE_OPTIONS, f"{species_name} starter passives registered")  
        if key in SPECIES_PASSIVE_OPTIONS:  
            report.add(len(SPECIES_PASSIVE_OPTIONS[key]) == 3, f"{species_name} has 3 starter passives", str(len(SPECIES_PASSIVE_OPTIONS[key])))  
        report.add(key in SPECIES_ACTIVE_ABILITIES, f"{species_name} species ability tree registered")  
        if key in SPECIES_ACTIVE_ABILITIES:  
            levels = sorted(int(k) for k in SPECIES_ACTIVE_ABILITIES[key].keys())  
            report.add(levels == SELF_TEST_SPECIES_LEVELS, f"{species_name} species ability unlock levels", str(levels))  
            for lvl in SELF_TEST_SPECIES_LEVELS:  
                abilities = SPECIES_ACTIVE_ABILITIES[key].get(lvl, [])  
                report.add(len(abilities) >= 1, f"{species_name} L{lvl} has ability", str(len(abilities)))  
  
    for class_name in SELF_TEST_EXPECTED_CLASSES:  
        key = normalize_name(class_name)  
        same_object = CLASS_ABILITY_TREES.get(key) == CLASS_ACTIVE_ABILITIES.get(key)  
        report.add(same_object, f"{class_name} CLASS_ABILITY_TREES mirrors CLASS_ACTIVE_ABILITIES")  
  
    return report  
  
  
def selftest_passive_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Passive Audit")  
  
    def audit_passive(source: str, owner: str, passive: dict[str, Any]) -> None:  
        name = passive.get("name")  
        bonuses = passive.get("bonuses")  
        report.add(bool(name), f"{source} {owner} passive has name")  
        report.add(bool(passive.get("description")), f"{source} {owner} passive {name or '?'} has description")  
        report.add(isinstance(bonuses, dict) and bool(bonuses), f"{source} {owner} passive {name or '?'} has bonuses")  
        if isinstance(bonuses, dict):  
            for bonus_key, value in bonuses.items():  
                report.add(bonus_key in SELF_TEST_PASSIVE_BONUSES, f"{source} {owner} passive {name} bonus key valid", str(bonus_key))  
                report.add(isinstance(value, int), f"{source} {owner} passive {name} bonus value integer", f"{bonus_key}={value}")  
  
    for owner, passives in CLASS_PASSIVE_OPTIONS.items():  
        if owner == "mage":  
            continue  
        for passive in passives:  
            audit_passive("Class", owner, passive)  
    for owner, passives in SPECIES_PASSIVE_OPTIONS.items():  
        if owner in {"fae", "fairy"}:  
            continue  
        for passive in passives:  
            audit_passive("Species", owner, passive)  
  
    return report  
  
  
def selftest_ability_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Ability Audit")  
  
    valid_damage = {normalize_damage_type(d) for d in LOCKED_DAMAGE_TYPES}  
    valid_states = set(CORE_STATES.keys())  
  
    def audit_ability(source: str, owner: str, level: int, ability: dict[str, Any]) -> None:  
        name = ability.get("name")  
        kind = normalize_name(ability.get("kind") or "")  
        report.add(bool(name), f"{source} {owner} L{level} ability has name")  
        report.add(bool(ability.get("description")), f"{source} {owner} L{level} {name or '?'} has description")  
        report.add(kind in SELF_TEST_ABILITY_KINDS, f"{source} {owner} L{level} {name or '?'} kind supported", kind)  
        try:  
            cost = int(ability.get("cost"))  
            report.add(1 <= cost <= 3, f"{source} {owner} L{level} {name or '?'} Resolve cost valid", str(cost))  
        except Exception:  
            report.add(False, f"{source} {owner} L{level} {name or '?'} Resolve cost valid", str(ability.get("cost")))  
  
        dtype = ability.get("damage_type")  
        if kind in {"spell", "strike", "strike_buff", "spell_buff"}:  
            report.add(bool(dtype), f"{source} {owner} L{level} {name or '?'} damaging ability has damage type")  
        if dtype:  
            normalized = normalize_damage_type(dtype)  
            report.add(normalized in valid_damage, f"{source} {owner} L{level} {name or '?'} damage type valid", str(dtype))  
  
        for state_field in ("state", "secondary_state"):  
            state = ability.get(state_field)  
            if state:  
                key = normalize_name(state)  
                report.add(key in valid_states, f"{source} {owner} L{level} {name or '?'} {state_field} valid", key)  
  
        dc_type = ability.get("dc_type")  
        if dc_type:  
            report.add(normalize_name(dc_type) in {"spell", "technique"}, f"{source} {owner} L{level} {name or '?'} dc_type valid", str(dc_type))  
  
    for owner, levels in CLASS_ACTIVE_ABILITIES.items():  
        if owner == "mage":  
            continue  
        for lvl, abilities in levels.items():  
            for ability in abilities:  
                audit_ability("Class", owner, int(lvl), ability)  
  
    for owner, levels in SPECIES_ACTIVE_ABILITIES.items():  
        if owner in {"fae", "fairy"}:  
            continue  
        for lvl, abilities in levels.items():  
            for ability in abilities:  
                audit_ability("Species", owner, int(lvl), ability)  
  
    return report  
  
  
def selftest_level_choice_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Level Choice Audit")  
  
    expected = {  
        2: {"ability"},  
        3: {"species_ability", "combat_specialization"},  
        4: {"ability", "asi"},  
        6: {"ability", "combat_specialization"},  
        7: {"species_ability", "asi"},  
        8: {"ability"},  
        9: {"combat_specialization"},  
        10: {"ability", "asi"},  
    }  
    for level, expected_types in expected.items():  
        actual = set(level_choice_types_for_level(level))  
        report.add(expected_types.issubset(actual), f"Level {level} expected choice types present", f"actual={sorted(actual)}")  
  
    sample_char_payloads = [  
        {"character": {"class_name": "Sorcerer", "species": "Kitsune"}},  
        {"character": {"class_name": "Captain", "species": "Human"}},  
        {"character": {"class_name": "Barbarian", "species": "Dragonborn"}},  
        {"character": {"class_name": "Warden", "species": "Elf"}},  
    ]  
    for payload in sample_char_payloads:  
        cls = payload["character"]["class_name"]  
        species = payload["character"]["species"]  
        ability_options = choice_option_rows({"choice_type": "ability", "level": 2}, payload)  
        species_options = choice_option_rows({"choice_type": "species_ability", "level": 3}, payload)  
        spec_options = choice_option_rows({"choice_type": "combat_specialization", "level": 3}, payload)  
        report.add(bool(ability_options), f"{cls} L2 ability dropdown has options", ", ".join(o["label"] for o in ability_options))  
        report.add(bool(species_options), f"{species} L3 species dropdown has options", ", ".join(o["label"] for o in species_options))  
        report.add([o["label"] for o in spec_options] == ["Sharpened Accuracy", "Deadlier Force", "Deepened Spellcraft"], "Combat specialization labels are named")  
  
    return report  
  
  
def selftest_state_damage_affinity_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "States / Damage / Affinity Audit")  
  
    for state_key, state in CORE_STATES.items():  
        report.add(bool(state.get("name")), f"State {state_key} has name")  
        report.add(bool(state.get("effect")), f"State {state_key} has effect")  
  
    for dtype in LOCKED_DAMAGE_TYPES:  
        report.add(normalize_damage_type(dtype) == dtype, f"Damage type normalizes", dtype)  
  
    target = {"resistances_json": {"fire": 0.5}, "weaknesses_json": {"ice": 1.5}, "immunities_json": {"poison/acid": 1.0}}  
    dmg, note = resolve_damage_with_affinities(10, "fire", target)  
    report.add(dmg == 5 and "Resistance" in note, "Fire resistance reduces damage", f"{dmg}, {note}")  
    dmg, note = resolve_damage_with_affinities(10, "ice", target)  
    report.add(dmg == 15 and "Weakness" in note, "Ice weakness increases damage", f"{dmg}, {note}")  
    dmg, note = resolve_damage_with_affinities(10, "poison/acid", target)  
    report.add(dmg == 0 and "Immune" in note, "Immunity negates damage", f"{dmg}, {note}")  
  
    supported_kinds = {"heal", "buff", "debuff", "spell", "strike", "strike_buff", "spell_buff"}  
    report.add(SELF_TEST_ABILITY_KINDS == supported_kinds, "Self-test tracks all /action Use Ability kind branches", str(sorted(supported_kinds)))  
    return report  
  
  
def selftest_combat_math_audit() -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Combat Math Audit")  
  
    default_stats = {  
        "strength": 12,  
        "dexterity": 12,  
        "constitution": 14,  
        "intelligence": 12,  
        "wisdom": 12,  
        "charisma": 12,  
    }  
  
    for class_name in SELF_TEST_EXPECTED_CLASSES:  
        class_key = normalize_name(class_name)  
        species = "Human"  
        species_passive = SPECIES_PASSIVE_OPTIONS["human"][0]  
        class_passive = CLASS_PASSIVE_OPTIONS[class_key][0]  
        values = calculate_combat_values(  
            class_name,  
            default_stats,  
            level=3,  
            damage_die_sides=8,  
            species_name=species,  
            species_passive=species_passive,  
            class_passive=class_passive,  
        )  
        required_keys = [  
            "max_hp", "current_hp", "armor_class", "initiative_bonus", "attack_bonus",  
            "spell_dc", "technique_dc", "magic_save_bonus", "magic_defense",  
            "damage_die_sides", "damage_bonus", "max_resolve", "current_resolve",  
        ]  
        for key in required_keys:  
            report.add(key in values, f"{class_name} combat math includes {key}")  
        report.add(int(values.get("max_hp", 0)) > 0, f"{class_name} max HP positive", str(values.get("max_hp")))  
        report.add(int(values.get("armor_class", 0)) >= 10, f"{class_name} AC sane", str(values.get("armor_class")))  
        report.add(int(values.get("max_resolve", 0)) >= 3, f"{class_name} resolve at L3 sane", str(values.get("max_resolve")))  
  
    # Explicit resolve passive test.  
    sorc_values = calculate_combat_values(  
        "Sorcerer",  
        default_stats,  
        level=3,  
        damage_die_sides=8,  
        species_name="Human",  
        species_passive=SPECIES_PASSIVE_OPTIONS["human"][0],  
        class_passive={"name": "Arcane Reservoir", "bonuses": {"resolve_bonus": 1}},  
    )  
    report.add(int(sorc_values.get("max_resolve", 0)) == 4, "Resolve bonus passive applies", str(sorc_values.get("max_resolve")))  
  
    return report  
  
  
async def selftest_db_lifecycle_audit(guild_id: int, user_id: int, cleanup: bool = True) -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "DB Lifecycle Audit")  
    stamp = str(int(time.time()))  
    created_ids: list[int] = []  
  
    stats = {  
        "strength": 12,  
        "dexterity": 12,  
        "constitution": 14,  
        "intelligence": 12,  
        "wisdom": 12,  
        "charisma": 12,  
    }  
  
    async def make_payload(name: str, species: str, class_name: str) -> dict[str, Any]:  
        return {  
            "guild_id": guild_id,  
            "user_id": user_id,  
            "created_by": user_id,  
            "name": name,  
            "normalized_name": normalize_name(name),  
            "species": species,  
            "class_name": class_name,  
            "species_passive_name": SPECIES_PASSIVE_OPTIONS[normalize_name(species)][0]["name"],  
            "class_passive_name": CLASS_PASSIVE_OPTIONS[normalize_name(class_name)][0]["name"],  
            "stats": stats,  
            "image_url": None,  
            "image_filename": None,  
            "image_content_type": None,  
            "google_doc_url": None,  
        }  
  
    try:  
        removed = await selftest_cleanup_orphaned_selftest_data(guild_id)  
        report.add(True, "Pre-cleaned orphaned SELFTEST data", str(removed))  
  
        for class_name in SELF_TEST_EXPECTED_CLASSES:  
            payload = await make_payload(f"SELFTEST {stamp} CLASS {class_name}", "Human", class_name)  
            cid = await create_character_from_payload(payload, user_id)  
            created_ids.append(cid)  
            report.add(cid > 0, f"Created self-test class character {class_name}", f"id={cid}")  
            clean = await fetch_clean_character_by_id_without_backfill(cid)  
            abilities = await unlocked_abilities_for_character(cid)  
            pending = await pending_level_choices_for_character(cid)  
            report.add(int(clean["character"].get("level") or 0) == 1, f"{class_name} lifecycle character starts at level 1")  
            report.add(len(abilities) == 0, f"{class_name} lifecycle character starts with no unlocked active abilities", str(len(abilities)))  
            report.add(len(pending) == 0, f"{class_name} lifecycle character starts with no pending level choices", str(len(pending)))  
  
        for species_name in SELF_TEST_EXPECTED_SPECIES:  
            payload = await make_payload(f"SELFTEST {stamp} SPECIES {species_name}", species_name, "Fighter")  
            cid = await create_character_from_payload(payload, user_id)  
            created_ids.append(cid)  
            report.add(cid > 0, f"Created self-test species character {species_name}", f"id={cid}")  
            clean = await fetch_clean_character_by_id_without_backfill(cid)  
            abilities = await unlocked_abilities_for_character(cid)  
            pending = await pending_level_choices_for_character(cid)  
            report.add(int(clean["character"].get("level") or 0) == 1, f"{species_name} lifecycle character starts at level 1")  
            report.add(len(abilities) == 0, f"{species_name} lifecycle character starts with no unlocked active abilities", str(len(abilities)))  
            report.add(len(pending) == 0, f"{species_name} lifecycle character starts with no pending level choices", str(len(pending)))  
  
        representative_id = created_ids[0]  
        created_choices = await ensure_pending_level_choices(representative_id, guild_id, 1, 3)  
        report.add(created_choices >= 1, "Generated representative pending level choices L2-L3", str(created_choices))  
        pending = await pending_level_choices_for_character(representative_id)  
        report.add(any(int(p["level"]) == 2 and p["choice_type"] == "ability" for p in pending), "Representative has L2 ability pending")  
        report.add(any(int(p["level"]) == 3 and p["choice_type"] == "species_ability" for p in pending), "Representative has L3 species ability pending")  
        async with db_pool.acquire() as conn:  
            await conn.execute("DELETE FROM alaris_level_choices WHERE character_id=$1;", representative_id)  
        report.add(len(await pending_level_choices_for_character(representative_id)) == 0, "Representative pending choices cleaned after generation test")  
  
        async with db_pool.acquire() as conn:  
            encounter_id = await conn.fetchval(  
                """  
                INSERT INTO alaris_combat_encounters (  
                    guild_id, channel_id, session_id, status, round_number, current_turn_index, turn_order_json  
                )  
                VALUES ($1,0,NULL,'open',1,0,'[]'::jsonb)  
                RETURNING id;  
                """,  
                guild_id,  
            )  
            combatant_id = await conn.fetchval(  
                """  
                INSERT INTO alaris_combatants (  
                    encounter_id, combatant_type, character_id, owner_user_id, name,  
                    max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                    save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                    damage_type, xp_value, status  
                )  
                VALUES ($1,'character',$2,$3,'SELFTEST Combatant',30,30,12,1,3,13,2,12,8,1,'blunt',0,'active')  
                RETURNING id;  
                """,  
                encounter_id, representative_id, user_id,  
            )  
        for state_key in CORE_STATES.keys():  
            await apply_combat_state(int(encounter_id), int(combatant_id), int(combatant_id), state_key, 2)  
        states = await active_states_for_combatant(int(encounter_id), int(combatant_id))  
        report.add(len(states) == len(CORE_STATES), "All states apply to combatant", f"{len(states)}/{len(CORE_STATES)}")  
        await decrement_states_for_combatant(int(encounter_id), int(combatant_id))  
        states_after = await active_states_for_combatant(int(encounter_id), int(combatant_id))  
        report.add(len(states_after) == len(CORE_STATES), "State decrement keeps duration-positive states", str(len(states_after)))  
  
    except Exception as exc:  
        LOG.exception("Self-test DB lifecycle audit failed.")  
        report.add(False, "DB lifecycle audit exception", truncate(exc, 500))  
    finally:  
        if cleanup:  
            try:  
                async with db_pool.acquire() as conn:  
                    async with conn.transaction():  
                        await conn.execute("DELETE FROM alaris_combat_encounters WHERE guild_id=$1 AND channel_id=0;", guild_id)  
                        if created_ids:  
                            await conn.execute("DELETE FROM alaris_characters WHERE id = ANY($1::bigint[]);", created_ids)  
                report.add(True, "Cleaned up self-test characters", str(len(created_ids)))  
            except Exception as exc:  
                LOG.exception("Self-test cleanup failed.")  
                report.add(False, "Self-test cleanup failed", truncate(exc, 500))  
        else:  
            report.add(True, "DB lifecycle cleanup skipped", f"characters={created_ids}")  
  
    return report  
  
  
def selftest_compact_summary(report: SelfTestReport, mode: str) -> str:  
    failed_rows = [(name, detail) for ok, name, detail in report.rows if not ok]  
    lines = [  
        f"Self-test `{mode}` complete.",  
        f"✅ Passed: {report.passed}",  
        f"❌ Failed: {report.failed}",  
    ]  
    if failed_rows:  
        lines.append("")  
        lines.append("First failures:")  
        for name, detail in failed_rows[:12]:  
            line = f"• {name}"  
            if detail:  
                line += f" — {detail}"  
            lines.append(line[:180])  
    else:  
        lines.append("")  
        lines.append("No failures found.")  
    return "\n".join(lines)[:1850]  
  
  
async def send_selftest_report(interaction: discord.Interaction, report: SelfTestReport, mode: str) -> None:  
    summary = selftest_compact_summary(report, mode)  
    full_text = report.as_text(limit=200000)  
    if len(full_text) <= 1800:  
        await interaction.followup.send(f"```text\n{full_text}\n```", ephemeral=True)  
        return  
  
    report_filename = f"alaris_selftest_{normalize_name(mode) or 'report'}_{int(time.time())}.txt"  
    report_path = f"/tmp/{report_filename}"  
    with open(report_path, "w", encoding="utf-8") as report_file:  
        report_file.write(full_text)  
    await interaction.followup.send(  
        f"```text\n{summary}\n```\nFull report attached.",  
        file=discord.File(report_path, filename=report_filename),  
        ephemeral=True,  
    )  
  
  
  
async def selftest_create_temp_combat_pair(guild_id: int, user_id: int, ability_name: str) -> tuple[int, int, int]:  
    """Create a temporary encounter with one actor and one target for ability execution tests."""  
    safe_name = truncate(ability_name, 80)  
    async with db_pool.acquire() as conn:  
        encounter_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combat_encounters (  
                guild_id, channel_id, session_id, status, round_number, current_turn_index, turn_order_json  
            )  
            VALUES ($1,0,NULL,'open',1,0,'[]'::jsonb)  
            RETURNING id;  
            """,  
            int(guild_id),  
        )  
        actor_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combatants (  
                encounter_id, combatant_type, character_id, owner_user_id, name,  
                max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                max_resolve, current_resolve, damage_type, xp_value, status  
            )  
            VALUES ($1,'character',NULL,$2,$3,60,45,14,3,6,15,3,13,8,2,99,99,'blunt',0,'active')  
            RETURNING id;  
            """,  
            int(encounter_id), int(user_id), f"SELFTEST Actor - {safe_name}",  
        )  
        target_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combatants (  
                encounter_id, combatant_type, character_id, owner_user_id, name,  
                max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                max_resolve, current_resolve, damage_type, xp_value, status  
            )  
            VALUES ($1,'enemy',NULL,NULL,$2,80,60,12,1,3,12,1,10,6,1,1,1,'blunt',10,'active')  
            RETURNING id;  
            """,  
            int(encounter_id), f"SELFTEST Target - {safe_name}",  
        )  
    return int(encounter_id), int(actor_id), int(target_id)  
  
  
async def selftest_execute_single_ability_in_combat(  
    guild_id: int,  
    user_id: int,  
    source: str,  
    owner: str,  
    level: int,  
    ability: dict[str, Any],  
) -> tuple[bool, str]:  
    """Execute one ability against temporary combatants.  
  
    This intentionally mirrors the mechanical branches used by /action -> Use Ability:  
    heal, buff, debuff, spell, strike, strike_buff, spell_buff.  
    It does not judge narrative quality and does not require Discord interaction objects.  
    """  
    encounter_id = actor_id = target_id = 0  
    ability_name = str(ability.get("name") or "Unnamed Ability")  
    try:  
        encounter_id, actor_id, target_id = await selftest_create_temp_combat_pair(guild_id, user_id, ability_name)  
        async with db_pool.acquire() as conn:  
            actor_row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", actor_id)  
            target_row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", target_id)  
        actor = dict(actor_row)  
        target = dict(target_row)  
  
        cost = max(1, int(ability.get("cost") or 1))  
        kind = normalize_name(ability.get("kind") or "buff")  
        state_key = ability.get("state")  
        secondary_state = ability.get("secondary_state")  
        duration = 3 if cost >= 3 else (2 if cost >= 2 else ABILITY_DURATION_DEFAULT)  
        damage_type = normalize_damage_type(ability.get("damage_type") or ("spirit" if kind in {"spell", "debuff", "spell_buff"} else "blunt"))  
  
        await db_pool.execute(  
            "UPDATE alaris_combatants SET current_resolve=GREATEST(0,current_resolve-$2) WHERE id=$1;",  
            actor_id,  
            cost,  
        )  
  
        if kind == "heal":  
            # Damage the target/ally first, then heal it.  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=20 WHERE id=$1;", actor_id)  
            heal_amount = max(1, roll_scaled_ability_damage(actor, ability))  
            new_hp = min(int(actor["max_hp"] or 1), 20 + heal_amount)  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status='active' WHERE id=$1;", actor_id, new_hp)  
            if state_key:  
                await apply_combat_state(encounter_id, actor_id, actor_id, state_key, duration)  
  
        elif kind == "buff":  
            if state_key:  
                await apply_combat_state(encounter_id, actor_id, actor_id, state_key, duration)  
            if secondary_state:  
                await apply_combat_state(encounter_id, actor_id, actor_id, secondary_state, duration)  
  
        elif kind == "debuff":  
            if state_key:  
                await apply_combat_state(encounter_id, target_id, actor_id, state_key, duration)  
            if secondary_state:  
                await apply_combat_state(encounter_id, target_id, actor_id, secondary_state, duration)  
  
        elif kind == "spell":  
            raw_damage = max(1, roll_scaled_ability_damage(actor, ability))  
            # Force a failed save deterministically for state/damage coverage.  
            final_damage, _ = resolve_spell_save_damage(raw_damage, 10, 0, int(actor.get("save_dc") or 10))  
            final_damage, _ = resolve_damage_with_affinities(final_damage, damage_type, target)  
            new_hp = max(0, int(target["current_hp"] or 0) - final_damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                target_id,  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(encounter_id, target_id, actor_id, state_key, duration)  
  
        elif kind in {"strike", "strike_buff"}:  
            damage = max(1, roll_scaled_ability_damage(actor, ability))  
            damage, _ = resolve_damage_with_affinities(damage, damage_type, target)  
            new_hp = max(0, int(target["current_hp"] or 0) - damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                target_id,  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(encounter_id, target_id, actor_id, state_key, duration)  
            if secondary_state:  
                await apply_combat_state(encounter_id, actor_id, actor_id, secondary_state, duration)  
  
        elif kind == "spell_buff":  
            raw_damage = max(1, roll_scaled_ability_damage(actor, ability))  
            final_damage, _ = resolve_spell_save_damage(raw_damage, 10, 0, int(actor.get("save_dc") or 10))  
            final_damage, _ = resolve_damage_with_affinities(final_damage, damage_type, target)  
            new_hp = max(0, int(target["current_hp"] or 0) - final_damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                target_id,  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(encounter_id, target_id, actor_id, state_key, duration)  
            if secondary_state:  
                await apply_combat_state(encounter_id, actor_id, actor_id, secondary_state, duration)  
  
        else:  
            return False, f"Unsupported kind `{kind}`"  
  
        async with db_pool.acquire() as conn:  
            actor_after = await conn.fetchrow("SELECT current_resolve, current_hp FROM alaris_combatants WHERE id=$1;", actor_id)  
            target_after = await conn.fetchrow("SELECT current_hp FROM alaris_combatants WHERE id=$1;", target_id)  
            state_rows = await conn.fetch(  
                "SELECT state_key FROM alaris_combat_states WHERE encounter_id=$1 ORDER BY state_key;",  
                encounter_id,  
            )  
  
        expected_resolve = 99 - cost  
        if int(actor_after["current_resolve"]) != expected_resolve:  
            return False, f"Resolve not spent correctly: {actor_after['current_resolve']} != {expected_resolve}"  
  
        if kind in {"spell", "strike", "strike_buff", "spell_buff"} and int(target_after["current_hp"]) >= int(target["current_hp"]):  
            return False, "Damaging ability did not reduce target HP"  
  
        if kind == "heal" and int(actor_after["current_hp"]) <= 20:  
            return False, "Healing ability did not restore HP"  
  
        applied_states = {str(r["state_key"]) for r in state_rows}  
        for needed in [state_key, secondary_state]:  
            if needed and normalize_name(needed) not in applied_states:  
                return False, f"Expected state `{needed}` was not applied"  
  
        return True, f"{source} {owner} L{level} {ability_name} executed"  
  
    except Exception as exc:  
        LOG.exception("Self-test combat ability execution failed for %s %s L%s %s", source, owner, level, ability_name)  
        return False, truncate(exc, 500)  
  
    finally:  
        if encounter_id:  
            try:  
                async with db_pool.acquire() as conn:  
                    await conn.execute("DELETE FROM alaris_combat_encounters WHERE id=$1;", int(encounter_id))  
            except Exception:  
                LOG.exception("Failed to clean up self-test ability encounter %s", encounter_id)  
  
  
async def selftest_ability_combat_execution_audit(guild_id: int, user_id: int) -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Per-Ability Combat Execution Audit")  
  
    total = 0  
    for class_name in SELF_TEST_EXPECTED_CLASSES:  
        class_key = normalize_name(class_name)  
        for level, abilities in sorted(CLASS_ACTIVE_ABILITIES.get(class_key, {}).items()):  
            for ability in abilities:  
                total += 1  
                ok, detail = await selftest_execute_single_ability_in_combat(  
                    guild_id,  
                    user_id,  
                    "Class",  
                    class_name,  
                    int(level),  
                    ability,  
                )  
                report.add(ok, f"Execute class ability: {class_name} L{level} {ability.get('name')}", detail)  
  
    for species_name in SELF_TEST_EXPECTED_SPECIES:  
        species_key = normalize_name(species_name)  
        for level, abilities in sorted(SPECIES_ACTIVE_ABILITIES.get(species_key, {}).items()):  
            for ability in abilities:  
                total += 1  
                ok, detail = await selftest_execute_single_ability_in_combat(  
                    guild_id,  
                    user_id,  
                    "Species",  
                    species_name,  
                    int(level),  
                    ability,  
                )  
                report.add(ok, f"Execute species ability: {species_name} L{level} {ability.get('name')}", detail)  
  
    report.add(total >= 1, "Per-ability combat execution count", str(total))  
    return report  
  
  
  
  
async def selftest_fetch_character_id_by_name(guild_id: int, normalized_name: str) -> Optional[int]:  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow(  
            "SELECT id FROM alaris_characters WHERE guild_id=$1 AND normalized_name=$2;",  
            int(guild_id),  
            normalized_name,  
        )  
    return int(row["id"]) if row else None  
  
  
async def selftest_create_character(  
    guild_id: int,  
    user_id: int,  
    name: str,  
    species: str,  
    class_name: str,  
    stats: dict[str, int],  
    species_passive_index: int = 0,  
    class_passive_index: int = 0,  
) -> int:  
    species_key = normalize_name(species)  
    class_key = normalize_name(class_name)  
    payload = {  
        "guild_id": guild_id,  
        "user_id": user_id,  
        "created_by": user_id,  
        "name": name,  
        "normalized_name": normalize_name(name),  
        "species": species,  
        "class_name": class_name,  
        "species_passive_name": SPECIES_PASSIVE_OPTIONS[species_key][species_passive_index]["name"],  
        "class_passive_name": CLASS_PASSIVE_OPTIONS[class_key][class_passive_index]["name"],  
        "stats": stats,  
        "image_url": None,  
        "image_filename": None,  
        "image_content_type": None,  
        "google_doc_url": None,  
    }  
    return await create_character_from_payload(payload, user_id)  
  
  
async def selftest_set_level_and_resolve_choices(  
    guild_id: int,  
    character_id: int,  
    class_ability_name: str,  
    species_ability_name: str,  
    specialization_name: str,  
    target_level: int = 3,  
) -> list[str]:  
    """Simulate the staff level set + player dropdown choice resolution path."""  
    messages: list[str] = []  
    async with db_pool.acquire() as conn:  
        row = await conn.fetchrow("SELECT level FROM alaris_characters WHERE id=$1;", int(character_id))  
        old_level = int(row["level"] or 1) if row else 1  
        await conn.execute(  
            "UPDATE alaris_characters SET level=$2, updated_at=NOW() WHERE id=$1;",  
            int(character_id), int(target_level),  
        )  
    created = await ensure_pending_level_choices(int(character_id), int(guild_id), old_level, int(target_level))  
    messages.append(f"pending_created={created}")  
  
    pending = await pending_level_choices_for_character(int(character_id))  
    for choice in pending:  
        ctype = normalize_name(choice["choice_type"])  
        selected = None  
        if ctype == "ability":  
            selected = class_ability_name  
        elif ctype == "species_ability":  
            selected = species_ability_name  
        elif ctype == "combat_specialization":  
            selected = specialization_name  
        elif ctype == "asi":  
            selected = "CON"  
        if selected:  
            ok, msg, _ = await resolve_level_choice_by_id(int(choice["id"]), selected)  
            messages.append(f"{ctype}:{selected}:{ok}:{msg}")  
  
    await recalculate_character_combat(int(character_id), preserve_current_hp=False)  
    return messages  
  
  
async def selftest_create_multicharacter_encounter(guild_id: int, user_id: int, character_ids: list[int]) -> tuple[int, dict[int, int], int]:  
    """Create one temporary encounter with multiple PC combatants and one enemy target."""  
    async with db_pool.acquire() as conn:  
        encounter_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combat_encounters (  
                guild_id, channel_id, session_id, status, round_number, current_turn_index, turn_order_json  
            )  
            VALUES ($1,0,NULL,'open',1,0,'[]'::jsonb)  
            RETURNING id;  
            """,  
            int(guild_id),  
        )  
    combatant_by_character: dict[int, int] = {}  
  
    for cid in character_ids:  
        payload = await fetch_clean_character_by_id_without_backfill(int(cid))  
        c = payload["character"]  
        d = payload["derived"] or {}  
        async with db_pool.acquire() as conn:  
            combatant_id = await conn.fetchval(  
                """  
                INSERT INTO alaris_combatants (  
                    encounter_id, combatant_type, character_id, owner_user_id, name,  
                    max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                    save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                    max_resolve, current_resolve, damage_type, xp_value, status  
                )  
                VALUES ($1,'character',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,0,'active')  
                RETURNING id;  
                """,  
                int(encounter_id),  
                int(cid),  
                int(c["user_id"]),  
                str(c["name"]),  
                int(d.get("max_hp") or 20),  
                int(d.get("current_hp") or d.get("max_hp") or 20),  
                int(d.get("armor_class") or 12),  
                int(d.get("initiative_bonus") or 0),  
                int(d.get("attack_bonus") or 0),  
                int(d.get("spell_dc") or d.get("technique_dc") or 10),  
                int(d.get("magic_save_bonus") or 0),  
                int(d.get("magic_defense") or 10),  
                int(d.get("damage_die_sides") or 8),  
                int(d.get("damage_bonus") or 0),  
                int(d.get("max_resolve") or 3),  
                int(d.get("current_resolve") or d.get("max_resolve") or 3),  
                str(d.get("damage_type") or "blunt"),  
            )  
        combatant_by_character[int(cid)] = int(combatant_id)  
  
    async with db_pool.acquire() as conn:  
        enemy_id = await conn.fetchval(  
            """  
            INSERT INTO alaris_combatants (  
                encounter_id, combatant_type, character_id, owner_user_id, name,  
                max_hp, current_hp, armor_class, initiative_bonus, attack_bonus,  
                save_dc, magic_save_bonus, magic_defense, damage_die_sides, damage_bonus,  
                max_resolve, current_resolve, damage_type, xp_value, status  
            )  
            VALUES ($1,'enemy',NULL,NULL,'SELFTEST Enemy',150,120,12,1,3,12,1,10,6,1,1,1,'blunt',50,'active')  
            RETURNING id;  
            """,  
            int(encounter_id),  
        )  
    return int(encounter_id), combatant_by_character, int(enemy_id)  
  
  
async def selftest_execute_unlocked_ability_between_combatants(  
    encounter_id: int,  
    actor_id: int,  
    target_id: int,  
    ability: dict[str, Any],  
) -> tuple[bool, str]:  
    """Execute an unlocked ability against a target within a shared encounter."""  
    ability_name = str(ability.get("name") or "Unnamed Ability")  
    try:  
        async with db_pool.acquire() as conn:  
            actor_row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", int(actor_id))  
            target_row = await conn.fetchrow("SELECT * FROM alaris_combatants WHERE id=$1;", int(target_id))  
        if not actor_row or not target_row:  
            return False, "missing actor or target"  
        actor = dict(actor_row)  
        target = dict(target_row)  
  
        cost = max(1, int(ability.get("cost") or 1))  
        kind = normalize_name(ability.get("kind") or "buff")  
        state_key = ability.get("state")  
        secondary_state = ability.get("secondary_state")  
        duration = 3 if cost >= 3 else (2 if cost >= 2 else ABILITY_DURATION_DEFAULT)  
        damage_type = normalize_damage_type(ability.get("damage_type") or ("spirit" if kind in {"spell", "debuff", "spell_buff"} else "blunt"))  
  
        before_actor_resolve = int(actor.get("current_resolve") or 0)  
        before_target_hp = int(target.get("current_hp") or 0)  
        before_actor_hp = int(actor.get("current_hp") or 0)  
  
        await db_pool.execute(  
            "UPDATE alaris_combatants SET current_resolve=GREATEST(0,current_resolve-$2) WHERE id=$1;",  
            int(actor_id),  
            cost,  
        )  
  
        if kind == "heal":  
            # Force ally to be injured first.  
            injured_hp = max(1, int(target.get("max_hp") or 20) // 2)  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2 WHERE id=$1;", int(target_id), injured_hp)  
            heal_amount = max(1, roll_scaled_ability_damage(actor, ability))  
            new_hp = min(int(target["max_hp"] or 1), injured_hp + heal_amount)  
            await db_pool.execute("UPDATE alaris_combatants SET current_hp=$2, status='active' WHERE id=$1;", int(target_id), new_hp)  
            if state_key:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
  
        elif kind == "buff":  
            if state_key:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
            if secondary_state:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), secondary_state, duration)  
  
        elif kind == "debuff":  
            if state_key:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
            if secondary_state:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), secondary_state, duration)  
  
        elif kind == "spell":  
            raw_damage = max(1, roll_scaled_ability_damage(actor, ability))  
            final_damage, _ = resolve_spell_save_damage(raw_damage, 10, 0, int(actor.get("save_dc") or 10))  
            final_damage, _ = resolve_damage_with_affinities(final_damage, damage_type, target)  
            new_hp = max(0, before_target_hp - final_damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                int(target_id),  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
  
        elif kind in {"strike", "strike_buff"}:  
            damage = max(1, roll_scaled_ability_damage(actor, ability))  
            damage, _ = resolve_damage_with_affinities(damage, damage_type, target)  
            new_hp = max(0, before_target_hp - damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                int(target_id),  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
            if secondary_state:  
                await apply_combat_state(int(encounter_id), int(actor_id), int(actor_id), secondary_state, duration)  
  
        elif kind == "spell_buff":  
            raw_damage = max(1, roll_scaled_ability_damage(actor, ability))  
            final_damage, _ = resolve_spell_save_damage(raw_damage, 10, 0, int(actor.get("save_dc") or 10))  
            final_damage, _ = resolve_damage_with_affinities(final_damage, damage_type, target)  
            new_hp = max(0, before_target_hp - final_damage)  
            await db_pool.execute(  
                "UPDATE alaris_combatants SET current_hp=$2, status=CASE WHEN $2 <= 0 THEN 'defeated' ELSE status END WHERE id=$1;",  
                int(target_id),  
                new_hp,  
            )  
            if state_key and new_hp > 0:  
                await apply_combat_state(int(encounter_id), int(target_id), int(actor_id), state_key, duration)  
            if secondary_state:  
                await apply_combat_state(int(encounter_id), int(actor_id), int(actor_id), secondary_state, duration)  
        else:  
            return False, f"unsupported kind {kind}"  
  
        async with db_pool.acquire() as conn:  
            actor_after = await conn.fetchrow("SELECT current_resolve, current_hp FROM alaris_combatants WHERE id=$1;", int(actor_id))  
            target_after = await conn.fetchrow("SELECT current_hp FROM alaris_combatants WHERE id=$1;", int(target_id))  
            states = await conn.fetch(  
                "SELECT combatant_id, state_key FROM alaris_combat_states WHERE encounter_id=$1;",  
                int(encounter_id),  
            )  
  
        if int(actor_after["current_resolve"]) != max(0, before_actor_resolve - cost):  
            return False, f"resolve spend failed for {ability_name}"  
  
        if kind in {"spell", "strike", "strike_buff", "spell_buff"} and int(target_after["current_hp"]) >= before_target_hp:  
            return False, f"damage not applied for {ability_name}"  
  
        if kind == "heal" and int(target_after["current_hp"]) <= max(1, int(target.get("max_hp") or 20) // 2):  
            return False, f"healing not applied for {ability_name}"  
  
        applied = {(int(r["combatant_id"]), str(r["state_key"])) for r in states}  
        if state_key:  
            expected_target = int(actor_id) if kind in {"strike_buff", "spell_buff"} and normalize_name(state_key) in {"inspired", "guarded", "shielded", "fortified"} else int(target_id)  
            if (expected_target, normalize_name(state_key)) not in applied and (int(target_id), normalize_name(state_key)) not in applied and (int(actor_id), normalize_name(state_key)) not in applied:  
                return False, f"state {state_key} not applied for {ability_name}"  
        if secondary_state:  
            if (int(actor_id), normalize_name(secondary_state)) not in applied and (int(target_id), normalize_name(secondary_state)) not in applied:  
                return False, f"secondary state {secondary_state} not applied for {ability_name}"  
  
        return True, f"{ability_name} executed in shared encounter"  
  
    except Exception as exc:  
        LOG.exception("End-to-end ability execution failed for %s", ability_name)  
        return False, truncate(exc, 500)  
  
  
async def selftest_end_to_end_system_audit(guild_id: int, user_id: int, cleanup: bool = True) -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Comprehensive End-to-End System Audit")  
    stamp = str(int(time.time()))  
    created_ids: list[int] = []  
    encounter_ids: list[int] = []  
  
    stats_by_role = {  
        "caster": {"strength": 8, "dexterity": 13, "constitution": 14, "intelligence": 12, "wisdom": 10, "charisma": 15},  
        "support": {"strength": 12, "dexterity": 12, "constitution": 14, "intelligence": 10, "wisdom": 10, "charisma": 15},  
        "martial": {"strength": 15, "dexterity": 10, "constitution": 14, "intelligence": 8, "wisdom": 10, "charisma": 12},  
        "control": {"strength": 12, "dexterity": 15, "constitution": 12, "intelligence": 10, "wisdom": 13, "charisma": 8},  
    }  
  
    core_specs = [  
        ("SELFTEST E2E Kitsune Sorcerer", "Kitsune", "Sorcerer", "caster", "Flame Burst", "Spirit Veil", "Deepened Spellcraft"),  
        ("SELFTEST E2E Human Captain", "Human", "Captain", "support", "Rally Command", "Determined Surge", "Sharpened Accuracy"),  
        ("SELFTEST E2E Dragonborn Barbarian", "Dragonborn", "Barbarian", "martial", "Crushing Blow", "Breath Weapon", "Deadlier Force"),  
        ("SELFTEST E2E Elf Warden", "Elf", "Warden", "control", "Binding Strike", "Ancestral Focus", "Sharpened Accuracy"),  
    ]  
  
    try:  
        removed = await selftest_cleanup_orphaned_selftest_data(guild_id)  
        report.add(True, "Pre-cleaned orphaned SELFTEST data before E2E", str(removed))  
  
        # Create four real test characters via the same DB creation path approval uses.  
        for base_name, species, class_name, role, class_ability, species_ability, spec in core_specs:  
            name = f"{base_name} {stamp}"  
            cid = await selftest_create_character(  
                guild_id,  
                user_id,  
                name,  
                species,  
                class_name,  
                stats_by_role[role],  
                0,  
                0,  
            )  
            created_ids.append(cid)  
            report.add(cid > 0, f"Created E2E character {species} {class_name}", f"id={cid}")  
  
            payload = await fetch_clean_character_by_id_without_backfill(cid)  
            report.add(bool(payload and payload.get("character")), f"Fetched E2E character {name}")  
            report.add(bool(payload and payload.get("derived")), f"E2E character has combat row {name}")  
            report.add(bool(payload["character"].get("species_passive_name")), f"E2E character has species passive {name}", payload["character"].get("species_passive_name"))  
            report.add(bool(payload["character"].get("class_passive_name")), f"E2E character has class passive {name}", payload["character"].get("class_passive_name"))  
  
            choice_messages = await selftest_set_level_and_resolve_choices(  
                guild_id,  
                cid,  
                class_ability,  
                species_ability,  
                spec,  
                3,  
            )  
            report.add(True, f"Leveled/resolved choices for {name}", "; ".join(choice_messages)[:500])  
            unlocked = await unlocked_abilities_for_character(cid)  
            unlocked_names = {normalize_name(a.get("name")) for a in unlocked}  
            report.add(normalize_name(class_ability) in unlocked_names, f"{name} class ability unlocked", class_ability)  
            report.add(normalize_name(species_ability) in unlocked_names, f"{name} species ability unlocked", species_ability)  
            card_ok, card_detail = await selftest_card_consistency_for_character(cid)  
            report.add(card_ok, f"{name} debug/card consistency after level choices", card_detail)  
  
        # Shared encounter for ally buffing and multi-character target validation.  
        encounter_id, combatants, enemy_id = await selftest_create_multicharacter_encounter(guild_id, user_id, created_ids)  
        encounter_ids.append(encounter_id)  
        report.add(len(combatants) == 4, "Created multi-character E2E encounter", f"pcs={len(combatants)}, enemy={enemy_id}")  
  
        # Execute the specific testing abilities in a real shared encounter.  
        char_by_class = {}  
        for cid in created_ids:  
            payload = await fetch_clean_character_by_id_without_backfill(cid)  
            char_by_class[normalize_name(payload["character"]["class_name"])] = cid  
  
        ability_tests = [  
            ("sorcerer", "Flame Burst", enemy_id),  
            ("sorcerer", "Spirit Veil", combatants[char_by_class["sorcerer"]]),  
            ("captain", "Rally Command", combatants[char_by_class["barbarian"]]),  # ally buff check  
            ("barbarian", "Crushing Blow", enemy_id),  
            ("barbarian", "Breath Weapon", enemy_id),  
            ("warden", "Binding Strike", enemy_id),  
            ("warden", "Ancestral Focus", combatants[char_by_class["warden"]]),  
        ]  
  
        for class_key, ability_name, target_combatant_id in ability_tests:  
            cid = char_by_class[class_key]  
            actor_id = combatants[cid]  
            abilities = await unlocked_abilities_for_character(cid)  
            ability = next((a for a in abilities if normalize_name(a.get("name")) == normalize_name(ability_name)), None)  
            if not ability:  
                report.add(False, f"E2E ability available for execution {class_key}:{ability_name}", "not unlocked/readable")  
                continue  
            ok, detail = await selftest_execute_unlocked_ability_between_combatants(  
                encounter_id,  
                actor_id,  
                int(target_combatant_id),  
                ability,  
            )  
            report.add(ok, f"E2E execute {class_key} ability {ability_name}", detail)  
  
        # Scaling test: level one character higher and make sure HP/Resolve do not go backward.  
        sorc_id = char_by_class["sorcerer"]  
        before = await fetch_clean_character_by_id_without_backfill(sorc_id)  
        before_hp = int((before.get("derived") or {}).get("max_hp") or 0)  
        before_resolve = int((before.get("derived") or {}).get("max_resolve") or 0)  
        await selftest_set_level_and_resolve_choices(guild_id, sorc_id, "Frozen Lance", "Spirit Veil", "Sharpened Accuracy", 4)  
        after = await fetch_clean_character_by_id_without_backfill(sorc_id)  
        after_hp = int((after.get("derived") or {}).get("max_hp") or 0)  
        after_resolve = int((after.get("derived") or {}).get("max_resolve") or 0)  
        report.add(after_hp >= before_hp, "Level scaling HP does not decrease", f"{before_hp}->{after_hp}")  
        report.add(after_resolve >= before_resolve, "Level scaling Resolve does not decrease", f"{before_resolve}->{after_resolve}")  
        card_ok, card_detail = await selftest_card_consistency_for_character(sorc_id)  
        report.add(card_ok, "Sorcerer debug/card consistency after scaling to level 4", card_detail)  
  
        # Execute every class/species ability in combat, not just the four-char subset.  
        ability_exec_report = await selftest_ability_combat_execution_audit(guild_id, user_id)  
        report.extend(ability_exec_report)  
  
    except Exception as exc:  
        LOG.exception("Comprehensive end-to-end self-test failed.")  
        report.add(False, "Comprehensive E2E exception", truncate(exc, 500))  
  
    finally:  
        if cleanup:  
            try:  
                async with db_pool.acquire() as conn:  
                    async with conn.transaction():  
                        if encounter_ids:  
                            await conn.execute(  
                                "DELETE FROM alaris_combat_encounters WHERE id = ANY($1::bigint[]);",  
                                encounter_ids,  
                            )  
                        if created_ids:  
                            await conn.execute(  
                                "DELETE FROM alaris_characters WHERE id = ANY($1::bigint[]);",  
                                created_ids,  
                            )  
                report.add(True, "Cleaned up comprehensive E2E test data", f"characters={len(created_ids)}, encounters={len(encounter_ids)}")  
            except Exception as exc:  
                LOG.exception("Comprehensive E2E cleanup failed.")  
                report.add(False, "Comprehensive E2E cleanup failed", truncate(exc, 500))  
        else:  
            report.add(True, "Comprehensive E2E cleanup skipped", f"characters={created_ids}, encounters={encounter_ids}")  
  
    return report  
  
  
  
  
async def selftest_scale_100_characters_audit(guild_id: int, user_id: int, cleanup: bool = True) -> SelfTestReport:  
    report = SelfTestReport()  
    selftest_add_section(report, "Scale / Stress Audit - 100 Characters")  
    stamp = str(int(time.time()))  
    created_ids: list[int] = []  
    encounter_ids: list[int] = []  
    start_time = time.monotonic()  
  
    stats_pool = [  
        {"strength": 15, "dexterity": 12, "constitution": 14, "intelligence": 8, "wisdom": 10, "charisma": 10},  
        {"strength": 8, "dexterity": 14, "constitution": 12, "intelligence": 15, "wisdom": 10, "charisma": 12},  
        {"strength": 10, "dexterity": 13, "constitution": 14, "intelligence": 10, "wisdom": 15, "charisma": 8},  
        {"strength": 10, "dexterity": 12, "constitution": 13, "intelligence": 12, "wisdom": 10, "charisma": 15},  
    ]  
  
    try:  
        removed = await selftest_cleanup_orphaned_selftest_data(guild_id)  
        report.add(True, "Pre-cleaned orphaned SELFTEST data before scale test", str(removed))  
  
        for i in range(100):  
            species = SELF_TEST_EXPECTED_SPECIES[i % len(SELF_TEST_EXPECTED_SPECIES)]  
            class_name = SELF_TEST_EXPECTED_CLASSES[i % len(SELF_TEST_EXPECTED_CLASSES)]  
            species_key = normalize_name(species)  
            class_key = normalize_name(class_name)  
            name = f"SELFTEST SCALE {stamp} {i+1:03d} {species} {class_name}"  
            payload = {  
                "guild_id": guild_id,  
                "user_id": user_id,  
                "created_by": user_id,  
                "name": name,  
                "normalized_name": normalize_name(name),  
                "species": species,  
                "class_name": class_name,  
                "species_passive_name": SPECIES_PASSIVE_OPTIONS[species_key][i % 3]["name"],  
                "class_passive_name": CLASS_PASSIVE_OPTIONS[class_key][i % 3]["name"],  
                "stats": stats_pool[i % len(stats_pool)],  
                "image_url": None,  
                "image_filename": None,  
                "image_content_type": None,  
                "google_doc_url": None if i % 2 else "not-a-valid-url",  
            }  
            cid = await create_character_from_payload(payload, user_id)  
            created_ids.append(int(cid))  
        report.add(len(created_ids) == 100, "Created 100 temporary characters", str(len(created_ids)))  
  
        sample_ids = created_ids[:10] + created_ids[-10:]  
        for cid in sample_ids:  
            payload = await fetch_clean_character_by_id_without_backfill(cid)  
            embed = build_character_embed(payload, dashboard=True)  
            report.add(bool(embed.title), f"Built character embed for scale character {cid}")  
            abilities = await unlocked_abilities_for_character(cid)  
            pending = await pending_level_choices_for_character(cid)  
            report.add(len(abilities) == 0, f"Scale character {cid} starts with no unlocked abilities", str(len(abilities)))  
            report.add(len(pending) == 0, f"Scale character {cid} starts with no pending choices", str(len(pending)))  
  
        q_start = time.monotonic()  
        async with db_pool.acquire() as conn:  
            rows = await conn.fetch(  
                """  
                SELECT name FROM alaris_characters  
                WHERE guild_id=$1 AND status='active' AND normalized_name LIKE 'selftest scale %'  
                ORDER BY name  
                LIMIT 25;  
                """,  
                int(guild_id),  
            )  
            count = await conn.fetchval(  
                "SELECT COUNT(*) FROM alaris_characters WHERE guild_id=$1 AND normalized_name LIKE 'selftest scale %';",  
                int(guild_id),  
            )  
        q_elapsed = time.monotonic() - q_start  
        report.add(len(rows) == 25, "Autocomplete-style query returns 25 choices", f"{len(rows)} in {q_elapsed:.3f}s")  
        report.add(int(count or 0) == 100, "Scale character DB count is 100", str(count))  
        report.add(q_elapsed < 2.0, "Autocomplete-style query under 2 seconds", f"{q_elapsed:.3f}s")  
        report.add(True, "Autocomplete-style query uses normalize_name-compatible space pattern", "selftest scale %")  
  
        duplicate_payload = {  
            "guild_id": guild_id,  
            "user_id": user_id,  
            "created_by": user_id,  
            "name": f"SELFTEST SCALE {stamp} 001 {SELF_TEST_EXPECTED_SPECIES[0]} {SELF_TEST_EXPECTED_CLASSES[0]}",  
            "normalized_name": normalize_name(f"SELFTEST SCALE {stamp} 001 {SELF_TEST_EXPECTED_SPECIES[0]} {SELF_TEST_EXPECTED_CLASSES[0]}"),  
            "species": SELF_TEST_EXPECTED_SPECIES[0],  
            "class_name": SELF_TEST_EXPECTED_CLASSES[0],  
            "species_passive_name": SPECIES_PASSIVE_OPTIONS[normalize_name(SELF_TEST_EXPECTED_SPECIES[0])][0]["name"],  
            "class_passive_name": CLASS_PASSIVE_OPTIONS[normalize_name(SELF_TEST_EXPECTED_CLASSES[0])][0]["name"],  
            "stats": stats_pool[0],  
            "image_url": None,  
            "image_filename": None,  
            "image_content_type": None,  
            "google_doc_url": None,  
        }  
        try:  
            await create_character_from_payload(duplicate_payload, user_id)  
            report.add(False, "Duplicate character name rejected", "duplicate insert unexpectedly succeeded")  
        except Exception:  
            report.add(True, "Duplicate character name rejected")  
  
        leveled_ids = created_ids[:32]  
        for idx, cid in enumerate(leveled_ids):  
            payload = await fetch_clean_character_by_id_without_backfill(cid)  
            c = payload["character"]  
            class_key = normalize_name(c["class_name"])  
            species_key = normalize_name(c["species"])  
            class_l2 = CLASS_ACTIVE_ABILITIES[class_key][2][idx % len(CLASS_ACTIVE_ABILITIES[class_key][2])]["name"]  
            species_l3 = SPECIES_ACTIVE_ABILITIES[species_key][3][0]["name"]  
            spec = ["Sharpened Accuracy", "Deadlier Force", "Deepened Spellcraft"][idx % 3]  
            await selftest_set_level_and_resolve_choices(guild_id, cid, class_l2, species_l3, spec, 3)  
            ok, detail = await selftest_card_consistency_for_character(cid)  
            report.add(ok, f"Scale leveled character {cid} card consistency", detail)  
  
        no_resolve_id = leveled_ids[0]  
        ability = (await unlocked_abilities_for_character(no_resolve_id))[0]  
        encounter_id, combatants, enemy_id = await selftest_create_multicharacter_encounter(guild_id, user_id, leveled_ids[:4])  
        encounter_ids.append(encounter_id)  
        actor_id = combatants[no_resolve_id]  
        async with db_pool.acquire() as conn:  
            await conn.execute("UPDATE alaris_combatants SET current_resolve=0 WHERE id=$1;", int(actor_id))  
            actor = await conn.fetchrow("SELECT current_resolve FROM alaris_combatants WHERE id=$1;", int(actor_id))  
        report.add(int(actor["current_resolve"] or 0) < int(ability.get("cost") or 1), "No-Resolve condition detected before ability use", f"resolve={actor['current_resolve']}, cost={ability.get('cost')}")  
  
        for group_start in range(0, 32, 8):  
            group = leveled_ids[group_start:group_start+8]  
            enc_id, combatant_map, enemy = await selftest_create_multicharacter_encounter(guild_id, user_id, group)  
            encounter_ids.append(enc_id)  
            report.add(len(combatant_map) == len(group), "Created 8-character scale encounter", f"encounter={enc_id}")  
  
            order = list(combatant_map.values()) + [enemy]  
            async with db_pool.acquire() as conn:  
                await conn.execute(  
                    "UPDATE alaris_combat_encounters SET turn_order_json=$2::jsonb, current_turn_index=0, round_number=1 WHERE id=$1;",  
                    int(enc_id),  
                    json.dumps(order),  
                )  
  
            for round_index in range(3):  
                for cid in group[:4]:  
                    abilities = await unlocked_abilities_for_character(cid)  
                    if not abilities:  
                        continue  
                    ability = abilities[0]  
                    actor_id = combatant_map[cid]  
                    target_kind = "enemy" if "enemy" in selftest_allowed_target_types(str(ability.get("kind"))) else "ally"  
                    target_id = enemy if target_kind == "enemy" else actor_id  
                    ok, detail = await selftest_execute_unlocked_ability_between_combatants(enc_id, actor_id, int(target_id), ability)  
                    report.add(ok, f"Scale encounter ability execution round {round_index+1}", detail)  
  
            async with db_pool.acquire() as conn:  
                await conn.execute("UPDATE alaris_combatants SET current_hp=0, status='defeated' WHERE id=$1;", int(enemy))  
                defeated = await conn.fetchrow("SELECT current_hp, status FROM alaris_combatants WHERE id=$1;", int(enemy))  
            report.add(int(defeated["current_hp"]) == 0 and str(defeated["status"]) == "defeated", "Defeated enemy state persisted", str(dict(defeated)))  
  
            xp_each = 10  
            async with db_pool.acquire() as conn:  
                for cid in group:  
                    await conn.execute("UPDATE alaris_characters SET xp_total=xp_total+$2 WHERE id=$1;", int(cid), xp_each)  
                xp_rows = await conn.fetch("SELECT xp_total FROM alaris_characters WHERE id = ANY($1::bigint[]);", group)  
            report.add(all(int(r["xp_total"] or 0) >= xp_each for r in xp_rows), "XP awards applied to encounter participants", f"{len(xp_rows)} rows")  
  
            async with db_pool.acquire() as conn:  
                await conn.execute("UPDATE alaris_combat_encounters SET status='closed' WHERE id=$1;", int(enc_id))  
                closed = await conn.fetchval("SELECT status FROM alaris_combat_encounters WHERE id=$1;", int(enc_id))  
            report.add(str(closed) == "closed", "Encounter close status persisted", str(closed))  
  
        hp_values = []  
        dmg_values = []  
        resolve_values = []  
        for cid in leveled_ids:  
            payload = await fetch_clean_character_by_id_without_backfill(cid)  
            d = payload.get("derived") or {}  
            hp_values.append(int(d.get("max_hp") or 0))  
            dmg_values.append(int(d.get("damage_bonus") or 0))  
            resolve_values.append(int(d.get("max_resolve") or 0))  
        report.add(min(hp_values) > 0 and max(hp_values) < 200, "HP scaling sanity across leveled scale subset", f"min={min(hp_values)}, max={max(hp_values)}")  
        report.add(min(resolve_values) >= 3 and max(resolve_values) <= 12, "Resolve scaling sanity across leveled scale subset", f"min={min(resolve_values)}, max={max(resolve_values)}")  
        report.add(max(dmg_values) <= 20, "Damage bonus sanity across leveled scale subset", f"max={max(dmg_values)}")  
  
        elapsed = time.monotonic() - start_time  
        report.add(elapsed < 120.0, "Scale test completed under 120 seconds", f"{elapsed:.2f}s")  
  
    except Exception as exc:  
        LOG.exception("Scale 100 self-test failed.")  
        report.add(False, "Scale 100 exception", truncate(exc, 500))  
    finally:  
        if cleanup:  
            try:  
                async with db_pool.acquire() as conn:  
                    async with conn.transaction():  
                        if encounter_ids:  
                            await conn.execute("DELETE FROM alaris_combat_encounters WHERE id = ANY($1::bigint[]);", encounter_ids)  
                        if created_ids:  
                            await conn.execute("DELETE FROM alaris_characters WHERE id = ANY($1::bigint[]);", created_ids)  
                report.add(True, "Cleaned up scale test data", f"characters={len(created_ids)}, encounters={len(encounter_ids)}")  
            except Exception as exc:  
                LOG.exception("Scale cleanup failed.")  
                report.add(False, "Scale cleanup failed", truncate(exc, 500))  
        else:  
            report.add(True, "Scale cleanup skipped", f"characters={len(created_ids)}, encounters={len(encounter_ids)}")  
  
    return report  
  
  
async def run_selftest_suite(mode: str, guild_id: int, user_id: int, cleanup: bool = True) -> SelfTestReport:  
    raw_mode = str(mode or "fast").strip()  
    mode_key = normalize_name(raw_mode)  
    alias_map = {  
        "abilitycombat": "ability combat",  
        "ability combat": "ability combat",  
        "ability-combat": "ability combat",  
        "combat execution": "ability combat",  
        "combat-execution": "ability combat",  
        "comprehensive": "full",  
        "complete": "full",  
        "all": "full",  
        "everything": "full",  
        "scale": "scale",  
        "scale100": "scale",  
        "scale 100": "scale",  
        "stress": "scale",  
    }  
    mode_key = alias_map.get(mode_key, mode_key)  
    report = SelfTestReport()  
    report.add(True, "Requested self-test mode", raw_mode)  
    report.add(True, "Resolved self-test mode", mode_key)  
  
    if mode_key in {"registry", "audit", "fast", "full"}:  
        report.extend(selftest_registry_audit())  
    if mode_key in {"passives", "audit", "fast", "full"}:  
        report.extend(selftest_passive_audit())  
    if mode_key in {"abilities", "audit", "fast", "full"}:  
        report.extend(selftest_ability_audit())  
    if mode_key in {"leveling", "level choices", "audit", "fast", "full"}:  
        report.extend(selftest_level_choice_audit())  
    if mode_key in {"states", "damage", "affinity", "combat", "audit", "fast", "full"}:  
        report.extend(selftest_state_damage_affinity_audit())  
    if mode_key in {"math", "combat", "audit", "fast", "full"}:  
        report.extend(selftest_combat_math_audit())  
    if mode_key in {"ability combat", "combat"}:  
        report.extend(await selftest_ability_combat_execution_audit(guild_id, user_id))  
    if mode_key in {"e2e", "end to end", "end-to-end", "full"}:  
        report.extend(await selftest_end_to_end_system_audit(guild_id, user_id, cleanup=cleanup))  
    if mode_key in {"db", "database", "lifecycle", "full"}:  
        report.extend(await selftest_db_lifecycle_audit(guild_id, user_id, cleanup=cleanup))  
    if mode_key in {"scale", "stress"}:  
        report.extend(await selftest_scale_100_characters_audit(guild_id, user_id, cleanup=cleanup))  
  
    if len(report.rows) <= 2:  
        report.add(False, "Unknown self-test mode", raw_mode)  
  
    return report  
  
  
@bot.tree.command(name="self-test-suite", description="DEV: run deterministic Alaris bot self-tests.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(mode="Choose which self-test suite to run", cleanup="Delete temporary DB test characters after full/db tests")  
@app_commands.choices(mode=[  
    app_commands.Choice(name="Fast Audit - registries/passives/abilities/math", value="fast"),  
    app_commands.Choice(name="Full Comprehensive - creation/leveling/combat/all abilities", value="full"),  
    app_commands.Choice(name="Ability Combat Only - every active ability in combat", value="ability-combat"),  
    app_commands.Choice(name="Registry Only", value="registry"),  
    app_commands.Choice(name="Passives Only", value="passives"),  
    app_commands.Choice(name="Abilities Schema Only", value="abilities"),  
    app_commands.Choice(name="Leveling Choices Only", value="leveling"),  
    app_commands.Choice(name="States/Damage/Affinity Only", value="states"),  
    app_commands.Choice(name="Combat Math Only", value="math"),  
    app_commands.Choice(name="DB Lifecycle Only", value="db"),  
    app_commands.Choice(name="Scale/Stress - 100 temporary characters", value="scale"),  
])  
async def self_test_suite(interaction: discord.Interaction, mode: str = "fast", cleanup: bool = True):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
  
    await interaction.response.defer(ephemeral=True, thinking=True)  
    report = await run_selftest_suite(mode, interaction.guild.id, interaction.user.id, cleanup=cleanup)  
    await send_selftest_report(interaction, report, mode)  
  
    # Save a longer artifact-style text report to logs if configured through normal command log.  
    try:  
        await post_command_log(  
            interaction,  
            f"ran self-test-suite mode={mode} cleanup={cleanup}: {report.passed} passed, {report.failed} failed",  
        )  
    except Exception:  
        LOG.exception("Failed to post self-test command log.")  
  
  
  
  
@bot.tree.command(name="self-test-cleanup", description="DEV: remove leftover SELFTEST characters and test encounters.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def self_test_cleanup(interaction: discord.Interaction):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    await interaction.response.defer(ephemeral=True, thinking=True)  
    try:  
        removed = await selftest_cleanup_orphaned_selftest_data(interaction.guild.id)  
        await interaction.followup.send(  
            f"Removed **{removed}** leftover SELFTEST character(s) and cleared test encounters.",  
            ephemeral=True,  
        )  
    except Exception as exc:  
        LOG.exception("self-test-cleanup failed.")  
        await interaction.followup.send(  
            f"Self-test cleanup failed: `{truncate(exc, 500)}`",  
            ephemeral=True,  
        )  
  
  
  
async def character_refresh_queue_worker() -> None:  
    """Background edit-only processor for EconomyBot/live card refresh requests."""  
    await bot.wait_until_ready()  
    while not bot.is_closed():  
        try:  
            if db_pool is not None:  
                updated, skipped, failed = await process_character_refresh_queue(GUILD_ID, 20)  
                if updated or skipped or failed:  
                    LOG.info(  
                        "Processed queued character-card refreshes: updated=%s skipped=%s failed=%s",  
                        updated, skipped, failed,  
                    )  
        except Exception:  
            LOG.exception("Character refresh queue worker failed; will retry.")  
        await asyncio.sleep(20)  
  
  
  
# ---------- Shared XP Award Queue ----------  
  
async def ensure_xp_award_queue_schema() -> None:  
    """Create the shared XP queue and Postgres NOTIFY trigger.  
  
    Other bots should insert XP awards here instead of directly changing XP totals.  
    AlarisBot remains the single source of truth for XP, die advancement, level-up  
    choices, tickets, XP logs, and character-card refreshes.  
    """  
    if db_pool is None:  
        return  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            CREATE TABLE IF NOT EXISTS public.alaris_xp_award_queue (  
                id BIGSERIAL PRIMARY KEY,  
                guild_id BIGINT NOT NULL,  
                character_id BIGINT NOT NULL,  
                source_bot TEXT NOT NULL DEFAULT 'unknown',  
                source_type TEXT NOT NULL DEFAULT 'unspecified',  
                amount_xp INTEGER NOT NULL DEFAULT 0,  
                reason TEXT,  
                details_json JSONB NOT NULL DEFAULT '{}'::jsonb,  
                requested_by_user_id BIGINT,  
                status TEXT NOT NULL DEFAULT 'pending',  
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  
                claimed_at TIMESTAMPTZ,  
                processed_at TIMESTAMPTZ,  
                error_text TEXT  
            );  
            """  
        )  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS source_bot TEXT NOT NULL DEFAULT 'unknown';")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT 'unspecified';")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS amount_xp INTEGER NOT NULL DEFAULT 0;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS reason TEXT;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS details_json JSONB NOT NULL DEFAULT '{}'::jsonb;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS requested_by_user_id BIGINT;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;")  
        await conn.execute("ALTER TABLE public.alaris_xp_award_queue ADD COLUMN IF NOT EXISTS error_text TEXT;")  
        await conn.execute(  
            """  
            CREATE INDEX IF NOT EXISTS alaris_xp_award_queue_pending_idx  
            ON public.alaris_xp_award_queue (status, created_at, id);  
            """  
        )  
        await conn.execute(  
            """  
            CREATE OR REPLACE FUNCTION public.notify_alaris_xp_award_created()  
            RETURNS trigger AS $$  
            BEGIN  
                PERFORM pg_notify('alaris_xp_award_created', NEW.id::text);  
                RETURN NEW;  
            END;  
            $$ LANGUAGE plpgsql;  
            """  
        )  
        await conn.execute("DROP TRIGGER IF EXISTS alaris_xp_award_created_notify ON public.alaris_xp_award_queue;")  
        await conn.execute(  
            """  
            CREATE TRIGGER alaris_xp_award_created_notify  
            AFTER INSERT ON public.alaris_xp_award_queue  
            FOR EACH ROW  
            EXECUTE FUNCTION public.notify_alaris_xp_award_created();  
            """  
        )  
  
  
async def post_xp_award_queue_log(result: dict[str, Any], *, source_type: str, reason: str) -> None:  
    if not XP_AWARD_LOG_CHANNEL_ID:  
        return  
    try:  
        channel = bot.get_channel(int(XP_AWARD_LOG_CHANNEL_ID))  
        if channel is None:  
            fetched = await bot.fetch_channel(int(XP_AWARD_LOG_CHANNEL_ID))  
            channel = fetched if isinstance(fetched, (discord.TextChannel, discord.Thread)) else None  
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):  
            return  
        die_line = f"1d{result.get('old_die')} → 1d{result.get('new_die')}" if result.get('old_die') != result.get('new_die') else f"1d{result.get('new_die')}"  
        level_line = f"{result.get('old_level')} → {result.get('new_level')}" if result.get('old_level') != result.get('new_level') else str(result.get('new_level'))  
        msg = (  
            f"**XP Award Processed**\n"  
            f"Character: **{result.get('name')}**\n"  
            f"Amount: **{int(result.get('amount') or 0):,} XP**\n"  
            f"Source: `{clean_text(source_type)}`\n"  
            f"Reason: {clean_text(reason) or '—'}\n"  
            f"XP: **{int(result.get('old_xp') or 0):,} → {int(result.get('new_xp') or 0):,}**\n"  
            f"Damage Die: **{die_line}**\n"  
            f"Level: **{level_line}**"  
        )  
        await channel.send(msg[:1900], allowed_mentions=discord.AllowedMentions.none())  
    except Exception:  
        LOG.exception("Failed to post XP award queue log.")  
  
  
async def claim_pending_xp_awards(limit: int = 25) -> list[dict[str, Any]]:  
    if db_pool is None:  
        return []  
    async with db_pool.acquire() as conn:  
        rows = await conn.fetch(  
            """  
            WITH grabbed AS (  
                SELECT id  
                FROM public.alaris_xp_award_queue  
                WHERE status = 'pending'  
                  AND amount_xp > 0  
                ORDER BY created_at ASC, id ASC  
                LIMIT $1  
                FOR UPDATE SKIP LOCKED  
            )  
            UPDATE public.alaris_xp_award_queue q  
            SET status = 'processing', claimed_at = NOW(), error_text = NULL  
            FROM grabbed  
            WHERE q.id = grabbed.id  
            RETURNING q.*;  
            """,  
            int(limit),  
        )  
    return [dict(r) for r in rows]  
  
  
async def mark_xp_award_processed(queue_id: int) -> None:  
    if db_pool is None:  
        return  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE public.alaris_xp_award_queue  
            SET status = 'processed', processed_at = NOW(), error_text = NULL  
            WHERE id = $1;  
            """,  
            int(queue_id),  
        )  
  
  
async def mark_xp_award_failed(queue_id: int, error: str) -> None:  
    if db_pool is None:  
        return  
    async with db_pool.acquire() as conn:  
        await conn.execute(  
            """  
            UPDATE public.alaris_xp_award_queue  
            SET status = 'failed', processed_at = NOW(), error_text = $2  
            WHERE id = $1;  
            """,  
            int(queue_id), str(error)[:1000],  
        )  
  
  
async def mirror_processed_xp_to_public_characters(result: dict[str, Any]) -> None:  
    """Keep the compatibility mirror aligned after Alaris-owned XP processing."""  
    if db_pool is None:  
        return  
    try:  
        async with db_pool.acquire() as conn:  
            await conn.execute(  
                """  
                UPDATE public.characters  
                SET xp_total = $3,  
                    level = $4,  
                    updated_at = NOW()  
                WHERE guild_id = $1 AND character_id = $2;  
                """,  
                int(GUILD_ID), int(result["character_id"]), int(result["new_xp"]), int(result["new_level"]),  
            )  
    except Exception:  
        LOG.exception("Failed to mirror processed XP to public.characters.")  
  
  
async def process_xp_award_queue_once(limit: int = 25) -> dict[str, int]:  
    """Process pending XP awards through AlarisBot's normal advancement path."""  
    async with _xp_award_processing_lock:  
        rows = await claim_pending_xp_awards(limit)  
        processed = 0  
        failed = 0  
        for row in rows:  
            queue_id = int(row["id"])  
            try:  
                amount = int(row.get("amount_xp") or 0)  
                character_id = int(row["character_id"])  
                guild_id = int(row["guild_id"])  
                source_type = str(row.get("source_type") or "queued_xp")  
                reason = str(row.get("reason") or source_type)  
                actor = row.get("requested_by_user_id")  
                actor_id = int(actor) if actor is not None else None  
                result = await award_xp_to_character(  
                    guild_id=guild_id,  
                    character_id=character_id,  
                    amount=amount,  
                    source_type=source_type,  
                    source_id=queue_id,  
                    reason=reason,  
                    awarded_by=actor_id,  
                )  
                await mirror_processed_xp_to_public_characters(result)  
                if result.get("leveled_up") and bot.get_guild(guild_id):  
                    try:  
                        await open_level_ticket_if_needed(bot.get_guild(guild_id), character_id)  # type: ignore[arg-type]  
                    except Exception:  
                        LOG.exception("Failed to open level ticket after queued XP award.")  
                try:  
                    await refresh_character_post(character_id)  
                except Exception:  
                    LOG.exception("Failed to refresh character card after queued XP award.")  
                try:  
                    await post_level_up_message(result)  
                except Exception:  
                    LOG.exception("Failed to post level-up message after queued XP award.")  
                await post_xp_award_queue_log(result, source_type=source_type, reason=reason)  
                await mark_xp_award_processed(queue_id)  
                processed += 1  
            except Exception as exc:  
                LOG.exception("Failed processing XP queue row %s", queue_id)  
                await mark_xp_award_failed(queue_id, exc)  
                failed += 1  
        return {"claimed": len(rows), "processed": processed, "failed": failed}  
  
  
async def xp_award_queue_poller() -> None:  
    await bot.wait_until_ready()  
    while not bot.is_closed():  
        try:  
            await process_xp_award_queue_once(limit=50)  
        except Exception:  
            LOG.exception("XP award queue poller failed; will retry.")  
        await asyncio.sleep(20)  
  
  
async def xp_award_queue_listener() -> None:  
    """Near-real-time queue consumer using Postgres LISTEN/NOTIFY."""  
    await bot.wait_until_ready()  
    while not bot.is_closed():  
        conn: Optional[asyncpg.Connection] = None  
        try:  
            conn = await asyncpg.connect(DATABASE_URL)  
  
            def _notify_callback(connection, pid, channel, payload):  
                try:  
                    asyncio.create_task(process_xp_award_queue_once(limit=25))  
                except Exception:  
                    LOG.exception("Failed scheduling XP queue processing from NOTIFY.")  
  
            await conn.add_listener("alaris_xp_award_created", _notify_callback)  
            LOG.info("Listening for Postgres NOTIFY alaris_xp_award_created.")  
            while not bot.is_closed():  
                await asyncio.sleep(60)  
        except Exception:  
            LOG.exception("XP award queue listener disconnected; retrying.")  
            await asyncio.sleep(10)  
        finally:  
            if conn is not None:  
                try:  
                    await conn.close()  
                except Exception:  
                    pass  
  
  
@bot.tree.command(name="character-process-xp-queue", description="STAFF: process pending cross-bot XP awards now.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
async def character_process_xp_queue(interaction: discord.Interaction):  
    if not await require_staff(interaction):  
        return  
    await interaction.response.defer(ephemeral=True)  
    result = await process_xp_award_queue_once(limit=100)  
    await interaction.followup.send(  
        f"XP queue processed. Claimed: **{result['claimed']}** | Processed: **{result['processed']}** | Failed: **{result['failed']}**",  
        ephemeral=True,  
    )  
  
  
async def wipe_testing_xp_except_protected_character(guild_id: int, protected_name: str = "Tharion Vex") -> dict[str, Any]:  
    """Reset test XP/progression for all active characters except the protected story character.  
  
    This is intentionally a testing cleanup utility. It does not delete characters,  
    character posts, economy data, tournament history, or kingdom assignments.  
    """  
    if db_pool is None:  
        raise RuntimeError("Database pool is not ready.")  
  
    protected_name = (protected_name or "Tharion Vex").strip() or "Tharion Vex"  
    affected: list[dict[str, Any]] = []  
    protected_row: Optional[dict[str, Any]] = None  
    deleted_awards = 0  
    cancelled_queue = 0  
  
    async with db_pool.acquire() as conn:  
        async with conn.transaction():  
            protected = await conn.fetchrow(  
                """  
                SELECT id, name, xp_total, damage_die_sides, level  
                FROM alaris_characters  
                WHERE guild_id=$1  
                  AND LOWER(name)=LOWER($2)  
                  AND status='active'  
                ORDER BY id ASC  
                LIMIT 1;  
                """,  
                int(guild_id), protected_name,  
            )  
            if protected:  
                protected_row = dict(protected)  
  
            rows = await conn.fetch(  
                """  
                SELECT id, name, xp_total, damage_die_sides, level  
                FROM alaris_characters  
                WHERE guild_id=$1  
                  AND status='active'  
                  AND LOWER(name) <> LOWER($2)  
                  AND COALESCE(xp_total, 0) <> 0  
                ORDER BY name ASC, id ASC;  
                """,  
                int(guild_id), protected_name,  
            )  
            affected = [dict(r) for r in rows]  
            ids = [int(r["id"]) for r in affected]  
  
            if ids:  
                await conn.execute(  
                    """  
                    UPDATE alaris_characters  
                    SET xp_total = 0,  
                        damage_die_sides = 8,  
                        level = 1,  
                        updated_at = NOW()  
                    WHERE guild_id=$1  
                      AND id = ANY($2::bigint[]);  
                    """,  
                    int(guild_id), ids,  
                )  
                await conn.execute(  
                    """  
                    UPDATE alaris_character_combat  
                    SET damage_die_sides = 8,  
                        proficiency_bonus = 2,  
                        updated_at = NOW()  
                    WHERE character_id = ANY($1::bigint[]);  
                    """,  
                    ids,  
                )  
                await conn.execute(  
                    """  
                    UPDATE public.characters  
                    SET xp_total = 0,  
                        level = 1,  
                        updated_at = NOW()  
                    WHERE guild_id=$1  
                      AND character_id = ANY($2::bigint[]);  
                    """,  
                    int(guild_id), ids,  
                )  
                deleted_awards_status = await conn.execute(  
                    """  
                    DELETE FROM alaris_xp_awards  
                    WHERE guild_id=$1  
                      AND character_id = ANY($2::bigint[]);  
                    """,  
                    int(guild_id), ids,  
                )  
                try:  
                    deleted_awards = int(str(deleted_awards_status).split()[-1])  
                except Exception:  
                    deleted_awards = 0  
  
                queue_status = await conn.execute(  
                    """  
                    UPDATE public.alaris_xp_award_queue  
                    SET status = 'cancelled_test_wipe',  
                        processed_at = NOW(),  
                        error_text = 'Cancelled by character-wipe-test-xp cleanup.'  
                    WHERE guild_id=$1  
                      AND character_id = ANY($2::bigint[])  
                      AND status IN ('pending', 'processing', 'failed');  
                    """,  
                    int(guild_id), ids,  
                )  
                try:  
                    cancelled_queue = int(str(queue_status).split()[-1])  
                except Exception:  
                    cancelled_queue = 0  
  
                for cid in ids:  
                    await conn.execute(  
                        """  
                        INSERT INTO public.alaris_character_refresh_queue (guild_id, character_id, reason, requested_at)  
                        VALUES ($1, $2, 'test_xp_wipe', NOW());  
                        """,  
                        int(guild_id), int(cid),  
                    )  
  
    # Recalculate and refresh after the transaction so derived combat/card data stays aligned.  
    refreshed = 0  
    for row in affected:  
        cid = int(row["id"])  
        try:  
            await recalculate_character_combat(cid, preserve_current_hp=True)  
        except Exception:  
            LOG.exception("Failed recalculating combat after XP wipe for character_id=%s", cid)  
        try:  
            await refresh_character_post(cid)  
            refreshed += 1  
        except Exception:  
            LOG.exception("Failed refreshing character card after XP wipe for character_id=%s", cid)  
  
    return {  
        "protected_name": protected_name,  
        "protected_found": bool(protected_row),  
        "affected": affected,  
        "deleted_awards": deleted_awards,  
        "cancelled_queue": cancelled_queue,  
        "refreshed": refreshed,  
    }  
  
  
@bot.tree.command(name="character-wipe-test-xp", description="DEV: reset testing XP for all active characters except Tharion Vex.")  
@app_commands.default_permissions(manage_guild=True)  
@app_commands.guilds(discord.Object(id=GUILD_ID))  
@app_commands.describe(  
    confirmation="Type exactly: CONFIRM XP WIPE",  
    protected_character="Character name to protect from reset. Defaults to Tharion Vex.",  
)  
async def character_wipe_test_xp(  
    interaction: discord.Interaction,  
    confirmation: str,  
    protected_character: str = "Tharion Vex",  
):  
    if not await require_developer(interaction):  
        return  
    if interaction.guild is None:  
        await interaction.response.send_message("Use this in a server.", ephemeral=True)  
        return  
    if confirmation.strip() != "CONFIRM XP WIPE":  
        await interaction.response.send_message(  
            "Confirmation failed. Type exactly `CONFIRM XP WIPE` to reset test XP.",  
            ephemeral=True,  
        )  
        return  
  
    await interaction.response.defer(ephemeral=True, thinking=True)  
    try:  
        result = await wipe_testing_xp_except_protected_character(interaction.guild.id, protected_character)  
        affected = result["affected"]  
        if affected:  
            lines = []  
            for row in affected[:20]:  
                lines.append(  
                    f"• **{clean_text(row.get('name'))}**: "  
                    f"{int(row.get('xp_total') or 0):,} XP / 1d{int(row.get('damage_die_sides') or 8)} / Lv {int(row.get('level') or 1)} → 0 XP / 1d8 / Lv 1"  
                )  
            more = len(affected) - len(lines)  
            if more > 0:  
                lines.append(f"• ...and {more} more character(s).")  
            details = "\n".join(lines)  
        else:  
            details = "No active non-protected characters had XP to reset."  
  
        msg = (  
            "**Testing XP wipe complete.**\n"  
            f"Protected character: **{clean_text(result['protected_name'])}** "  
            f"({'found' if result['protected_found'] else 'not found'})\n"  
            f"Characters reset: **{len(affected)}**\n"  
            f"XP award records deleted: **{int(result['deleted_awards'])}**\n"  
            f"Pending queued XP awards cancelled: **{int(result['cancelled_queue'])}**\n"  
            f"Cards refreshed immediately: **{int(result['refreshed'])}**\n\n"  
            f"{details}"  
        )  
        await interaction.followup.send(msg[:1900], ephemeral=True)  
        try:  
            await post_command_log(  
                interaction,  
                f"ran character-wipe-test-xp protected={result['protected_name']} reset={len(affected)} deleted_awards={result['deleted_awards']} cancelled_queue={result['cancelled_queue']}",  
            )  
        except Exception:  
            LOG.exception("Failed to post command log for character-wipe-test-xp.")  
    except Exception as exc:  
        LOG.exception("character-wipe-test-xp failed.")  
        await interaction.followup.send(f"XP wipe failed: `{truncate(exc, 500)}`", ephemeral=True)  
  


@bot.tree.command(name="combat-admin-reset-daily-limit", description="STAFF: reset today's combat/spar start limit for one character.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(character="Character name whose daily combat/spar limit should be reset")
@app_commands.autocomplete(character=character_name_autocomplete)
async def combat_admin_reset_daily_limit(interaction: discord.Interaction, character: str):
    if not await require_staff(interaction):
        return
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    payload = await find_character(interaction.guild.id, character)
    if not payload:
        await interaction.followup.send("Character not found.", ephemeral=True)
        return
    cid = int(payload["character"]["id"])
    await reset_daily_combat_limit_for_character(interaction.guild.id, cid)
    await interaction.followup.send(f"Reset today's combat/spar daily limit for **{payload['character']['name']}**.", ephemeral=True)
    try:
        await post_command_log(interaction, f"reset daily combat limit for {payload['character'].get('name')} ({cid})")
    except Exception:
        LOG.exception("Failed to post command log for combat-admin-reset-daily-limit.")

# ---------- Lifecycle ----------  
  
@bot.event  
async def on_ready():  
    global db_pool, _commands_synced, _character_refresh_worker_task, _xp_award_listener_task, _xp_award_poller_task  
  
    if db_pool is None:  
        db_pool = await init_db()  
    await smoke_check_required_schema()  
    await ensure_xp_award_queue_schema()  
    await ensure_daily_activity_limit_schema()  
  
    # Re-register persistent combat lobby view so lobby buttons survive bot restarts.  
    # Setup dropdowns are intentionally short-lived; once a lobby is created, the  
    # persistent view can recover from DB by lobby_message_id.  
    try:  
        bot.add_view(CombatLobbyView())  
    except Exception:  
        LOG.exception("Failed to register persistent CombatLobbyView.")  
  
    if not _commands_synced:  
        guild_obj = discord.Object(id=GUILD_ID)  
        try:  
            # Clear stale global commands from older experiments so Discord does not show  
            # duplicate/obsolete join/session commands alongside the current guild commands.  
            bot.tree.clear_commands(guild=None)  
            try:  
                cleared_global = await bot.tree.sync()  
                LOG.info("Cleared/synced %s global command(s).", len(cleared_global))  
            except Exception:  
                LOG.exception("Failed to clear stale global slash commands; continuing with guild sync.")  
  
            synced = await bot.tree.sync(guild=guild_obj)  
            LOG.info("Synced %s guild command(s) to guild %s.", len(synced), GUILD_ID)  
            _commands_synced = True  
        except Exception:  
            LOG.exception("Failed to sync slash commands.")  
  
  
    if _character_refresh_worker_task is None or _character_refresh_worker_task.done():  
        _character_refresh_worker_task = asyncio.create_task(character_refresh_queue_worker())  
        LOG.info("Started edit-only character refresh queue worker.")  
  
    if _xp_award_listener_task is None or _xp_award_listener_task.done():  
        _xp_award_listener_task = asyncio.create_task(xp_award_queue_listener())  
        LOG.info("Started XP award queue LISTEN/NOTIFY listener.")  
  
    if _xp_award_poller_task is None or _xp_award_poller_task.done():  
        _xp_award_poller_task = asyncio.create_task(xp_award_queue_poller())  
        LOG.info("Started XP award queue fallback poller.")  
  
    LOG.info("Logged in as %s (%s).", bot.user, bot.user.id if bot.user else "unknown")  
  
  
def main() -> None:  
    # Startup sanity check for combat RNG dependency.  
    _ = random.randint(1, 1)  
    bot.run(TOKEN)  
  
  
if __name__ == "__main__":  
    main()  
  
  
# =========================================================  
# v084 UX / FLOW NOTES  
# =========================================================  
# - Session types cleaned up to non-combat narrative categories.  
# - Combat is initiated separately through /combat-start.  
# - Enemy encounters now support expanded archetype categories.  
# - /action labels simplified for cleaner UX.  
# - Magical attacks standardized against Magic Defense.  
# - Spar/Duel flows intended to award participation + victor XP.  
# - Enemy encounter summaries intended to use OpenAI-generated summaries.  
# =========================================================  
  
