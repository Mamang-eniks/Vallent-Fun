import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import copy
import json
import os
import random
import re
import time
import datetime
import zoneinfo
import hashlib
import aiohttp
import io
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Top.gg vote system
try:
    import topgg
    TOPGG_AVAILABLE = True
except ImportError:
    TOPGG_AVAILABLE = False
    print("⚠️  topggpy tidak terinstall. Jalankan: pip install topggpy")

# Webhook server (Flask)
try:
    from flask import Flask, request as flask_request, abort
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    print("⚠️  Flask tidak terinstall. Jalankan: pip install flask")

# Timezone WIB (UTC+7)
WIB = zoneinfo.ZoneInfo("Asia/Jakarta")

# ===================== CONFIG =====================
PREFIX = "d"
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DARK_RED = 0x8B0000

# ===================== TOP.GG CONFIG =====================
TOPGG_TOKEN      = os.getenv("TOPGG_TOKEN", "")
WEBHOOK_PASSWORD = os.getenv("WEBHOOK_PASSWORD", "")
PORT             = int(os.getenv("PORT", "8080"))
BOT_ID           = os.getenv("BOT_ID", "")  # Discord Bot ID untuk Top.gg link

VOTE_REWARD_MIN  = 500
VOTE_REWARD_MAX  = 1000
VOTE_COOLDOWN_H  = 12   # jam
VOTE_BONUS_PCTS  = 20   # % bonus coin dari mancing setelah vote
VOTE_BONUS_MINS  = 10   # durasi bonus mancing (menit)

# Cache vote webhook in-memory (backup sebelum tulis JSON)
_vote_cache: set = set()

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

def load_json(filename, default=None):
    path = DATA_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(filename, data):
    path = DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ===================== INTENTS =====================
intents = discord.Intents.all()

def get_prefix(bot, message):
    return ["d", "D", "!Kingdoom ", "!kingdoom "]

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None, case_insensitive=True)
tree = bot.tree

# ===================== FISHING DATA (Default - bisa di-override dari JSON) =====================
DEFAULT_FISHES = [
    {"name": "Ikan Lele",     "sell_price": 15,   "luck": 32.0, "emoji": "🐟"},
    {"name": "Ikan Mas",      "sell_price": 25,   "luck": 26.0, "emoji": "🐠"},
    {"name": "Ikan Gurame",   "sell_price": 40,   "luck": 14.0, "emoji": "🐡"},
    {"name": "Ikan Salmon",   "sell_price": 60,   "luck": 9.0,  "emoji": "🐟"},
    {"name": "Ikan Tuna",     "sell_price": 100,  "luck": 5.0,  "emoji": "🐟"},
    {"name": "Ikan Hiu",      "sell_price": 200,  "luck": 2.2,  "emoji": "🦈"},
    {"name": "Ikan Duyung",   "sell_price": 500,  "luck": 0.9,  "emoji": "🧜"},
    {"name": "Ikan Naga",     "sell_price": 1200, "luck": 0.35, "emoji": "🐉"},
    {"name": "Ikan Phoenix",  "sell_price": 3000, "luck": 0.08, "emoji": "🔥"},
    {"name": "Ikan Kraken",   "sell_price": 6000, "luck": 0.015,"emoji": "🐙"},
    {"name": "Sampah",        "sell_price": 0,    "luck": 0.0,  "emoji": "🗑️"},  # luck 0 = sampah slot khusus
]

DEFAULT_RODS = [
    {"name": "Pancing Bambu",   "tier": 1, "price": 50,   "luck_bonus": 0.0,  "emoji": "🎋"},
    {"name": "Pancing Kayu",    "tier": 2, "price": 150,  "luck_bonus": 2.0,  "emoji": "🪵"},
    {"name": "Pancing Besi",    "tier": 3, "price": 400,  "luck_bonus": 5.0,  "emoji": "🔩"},
    {"name": "Pancing Karbon",  "tier": 4, "price": 900,  "luck_bonus": 10.0, "emoji": "⚫"},
    {"name": "Pancing Titan",   "tier": 5, "price": 2000, "luck_bonus": 20.0, "emoji": "🔱"},
    {"name": "Pancing Legenda", "tier": 6, "price": 5000, "luck_bonus": 40.0, "emoji": "⚡"},
]

DEFAULT_BAITS = [
    {"name": "Cacing Biasa", "price": 10,  "luck_bonus": 0.0,  "emoji": "🪱"},
    {"name": "Cacing Gemuk", "price": 25,  "luck_bonus": 3.0,  "emoji": "🐛"},
    {"name": "Jangkrik",     "price": 40,  "luck_bonus": 6.0,  "emoji": "🦗"},
    {"name": "Udang Kecil",  "price": 60,  "luck_bonus": 10.0, "emoji": "🦐"},
    {"name": "Ikan Kecil",   "price": 100, "luck_bonus": 20.0, "emoji": "🐟"},
]

# Rarity tier berdasarkan luck %
# luck >= 20%    → common
# 9-20%          → uncommon
# 3-9%           → rare
# 0.3-3%         → epic
# 0.05-0.3%      → legendary
# < 0.05%        → mythic   (SUSAH BANGET, ini tier paling langka)
def get_rarity_from_luck(luck: float) -> str:
    if luck <= 0:
        return "trash"
    elif luck < 0.05:
        return "mythic"
    elif luck < 0.3:
        return "legendary"
    elif luck < 3.0:
        return "epic"
    elif luck < 9.0:
        return "rare"
    elif luck < 20.0:
        return "uncommon"
    else:
        return "common"

RARITY_LABELS = {
    "mythic":    "MYTHIC",
    "legendary": "LEGENDARY",
    "epic":      "Epic",
    "rare":      "Rare",
    "uncommon":  "Uncommon",
    "common":    "Common",
    "trash":     "Trash",
}
RARITY_COLORS = {
    "mythic":    0xE91E9C,
    "legendary": 0xFFD700,
    "epic":      0x9B59B6,
    "rare":      0x3498DB,
    "uncommon":  0x2ECC71,
    "common":    DARK_RED,
    "trash":     0x6B6B6B,
}

def get_rarity_display(rarity: str):
    """Bangun (label, color) buat 1 rarity. Emoji-nya diambil dari emoji_config
    (bisa diatur owner lewat `dsetemoji`), bukan hardcoded, biar
    `setemoji legendary/rare/uncommon/common/trash` beneran ngefek."""
    label = RARITY_LABELS.get(rarity, "Common")
    color = RARITY_COLORS.get(rarity, DARK_RED)
    return f"{emoji(rarity)} {label}", color

def get_fishing_config():
    """Load fishing config (ikan, rod, bait) dari JSON, fallback ke default.
    Pakai `or` (bukan cuma .get) supaya kalau value-nya ADA tapi kosong ([]/None),
    tetap fallback ke default — mencegah Select dropdown dikirim tanpa option
    (yang bikin Discord tolak dengan error 'Must be between 1 and 25 in length')."""
    cfg = load_json("fishing_config.json", {})
    fishes = cfg.get("fishes") or DEFAULT_FISHES
    rods   = cfg.get("rods")   or DEFAULT_RODS
    baits  = cfg.get("baits")  or DEFAULT_BAITS
    return fishes, rods, baits

def save_fishing_config(fishes, rods, baits):
    save_json("fishing_config.json", {"fishes": fishes, "rods": rods, "baits": baits})

def do_fish_roll(rod_name: str, bait_name: str | None, extra_luck_pct: float = 0.0):
    """Lakukan roll mancing. Return (fish_dict, rarity_str).
    extra_luck_pct = bonus tambahan dari Tempa (upgrade rod) + luck boost lootbox."""
    fishes, rods, baits = get_fishing_config()

    # Cari rod
    rod = next((r for r in rods if r["name"] == rod_name), rods[0])
    rod_bonus = rod.get("luck_bonus", 0.0)

    # Cari bait
    bait_bonus = 0.0
    if bait_name:
        bait = next((b for b in baits if b["name"] == bait_name), None)
        if bait:
            bait_bonus = bait.get("luck_bonus", 0.0)

    total_bonus = rod_bonus + bait_bonus + extra_luck_pct

    # Pisah ikan normal & sampah
    normal_fishes = [f for f in fishes if f.get("luck", 0) > 0]
    trash_fishes  = [f for f in fishes if f.get("luck", 0) <= 0]

    # Hitung weight per ikan dengan luck bonus dari rod+bait+tempa+lootbox
    # luck_bonus menambah luck semua ikan secara proporsional
    weights = []
    for f in normal_fishes:
        base_luck = f.get("luck", 1.0)
        adjusted  = base_luck + (base_luck * total_bonus / 100.0)
        weights.append(max(adjusted, 0.01))

    # Tambah slot "sampah" dengan weight tetap = max(0, 100 - sum_normal)
    total_normal = sum(weights)
    trash_weight = max(5.0, 100.0 - total_normal)

    pool    = normal_fishes + [random.choice(trash_fishes) if trash_fishes else {"name": "Sampah", "sell_price": 0, "luck": 0, "emoji": "🗑️"}]
    weights = weights + [trash_weight]

    caught = random.choices(pool, weights=weights, k=1)[0]
    rarity = get_rarity_from_luck(caught.get("luck", 0))
    return caught, rarity

# ===================== TEMPA (ROD UPGRADE) SYSTEM =====================
MATERIAL_NAME  = "Serpihan Tempa"
MATERIAL_EMOJI = "⚒️"
ROD_UPGRADE_LUCK_PER_LEVEL = 2.0   # +2% luck tiap level
ROD_UPGRADE_MAX_LEVEL      = 10

def rod_upgrade_cost(level: int) -> dict:
    """Biaya buat naikin rod dari `level` ke `level+1`."""
    return {"materials": (level + 1) * 5, "coins": (level + 1) * 150}

def get_rod_tempa_bonus(udata: dict, rod_name: str) -> float:
    """Bonus luck dari LEVEL TEMPA doang (base luck_bonus rod udah dihandle
    sendiri di dalam do_fish_roll, jadi ini gak boleh ikut nambahin base)."""
    level = udata.get("rod_levels", {}).get(rod_name, 0)
    return level * ROD_UPGRADE_LUCK_PER_LEVEL

def get_rod_effective_luck(udata: dict, rod_name: str) -> float:
    """Luck bonus rod TERMASUK hasil Tempa (base + level*bonus) — buat DITAMPILIN
    di UI (Equipment/Inventori), BUKAN buat dipassing ke do_fish_roll."""
    _, rods, _ = get_fishing_config()
    rod   = next((r for r in rods if r["name"] == rod_name), {})
    base  = rod.get("luck_bonus", 0.0)
    return base + get_rod_tempa_bonus(udata, rod_name)

def upgrade_rod(uid: str, rod_name: str) -> dict:
    """Coba upgrade 1 rod. Return {"ok": bool, "msg": str}."""
    udata = get_user_fishing(uid)
    if rod_name not in (udata.get("owned_rods") or []):
        return {"ok": False, "msg": f"Lo belum punya rod **{rod_name}**!"}
    level = udata.get("rod_levels", {}).get(rod_name, 0)
    if level >= ROD_UPGRADE_MAX_LEVEL:
        return {"ok": False, "msg": f"**{rod_name}** udah level MAX ({ROD_UPGRADE_MAX_LEVEL})!"}
    cost = rod_upgrade_cost(level)
    if udata.get("materials", 0) < cost["materials"]:
        return {"ok": False, "msg": f"{MATERIAL_EMOJI} {MATERIAL_NAME} kurang! Butuh **{cost['materials']}**, lo punya **{udata.get('materials', 0)}**."}
    if udata["coins"] < cost["coins"]:
        return {"ok": False, "msg": f"{emoji('coin')} Koin kurang! Butuh **{cost['coins']}**, lo punya **{udata['coins']}**."}
    udata["materials"] -= cost["materials"]
    udata["coins"]     -= cost["coins"]
    udata.setdefault("rod_levels", {})[rod_name] = level + 1
    save_user_fishing(uid, udata)
    return {"ok": True, "msg": f"{emoji('success')} **{rod_name}** naik ke **Level {level + 1}**! (+{ROD_UPGRADE_LUCK_PER_LEVEL}% luck)"}

# ===================== LOOTBOX & CRATE SYSTEM =====================
# Didapetin SECARA ACAK pas mancing (drop rate kecil), disimpen sebagai
# item di inventori (belum dibuka), dibuka manual lewat panel Inventori.
LOOTBOX_DROP_CHANCE = 0.08   # 8% tiap mancing
CRATE_DROP_CHANCE   = 0.04   # 4% tiap mancing

LOOTBOX_REWARDS = [
    {"type": "coin",       "weight": 35, "min": 50, "max": 200},
    {"type": "material",   "weight": 30, "min": 3,  "max": 10},
    {"type": "bait",       "weight": 25, "qty_min": 2, "qty_max": 5},
    {"type": "luck_boost", "weight": 10, "pct_min": 10, "pct_max": 25, "catch_min": 3, "catch_max": 5},
]

def roll_fishing_drops(uid: str) -> list:
    """Roll drop lootbox/crate abis mancing (dipanggil tiap kali fish()).
    Return list pesan singkat kalau ada yang drop (buat ditampilin)."""
    udata = get_user_fishing(uid)
    msgs = []
    if random.random() < LOOTBOX_DROP_CHANCE:
        udata["lootbox"] = udata.get("lootbox", 0) + 1
        udata["lootbox_collected"] = udata.get("lootbox_collected", 0) + 1
        msgs.append("📦 Lo nemu **Lootbox**! Buka di `dinv`.")
    if random.random() < CRATE_DROP_CHANCE:
        udata["crate"] = udata.get("crate", 0) + 1
        udata["crate_collected"] = udata.get("crate_collected", 0) + 1
        msgs.append("🗃️ Lo nemu **Crate**! Buka di `dinv`.")
    if msgs:
        save_user_fishing(uid, udata)
    return msgs

def open_lootbox(uid: str) -> dict:
    """Buka 1 lootbox. Return {"ok", "msg"}."""
    udata = get_user_fishing(uid)
    if udata.get("lootbox", 0) <= 0:
        return {"ok": False, "msg": "Lo gak punya Lootbox buat dibuka!"}
    udata["lootbox"] -= 1
    prize = random.choices(LOOTBOX_REWARDS, weights=[r["weight"] for r in LOOTBOX_REWARDS], k=1)[0]
    if prize["type"] == "coin":
        amount = random.randint(prize["min"], prize["max"])
        udata["coins"] += amount
        msg = f"{emoji('coin')} Dapet **{amount} koin**!"
    elif prize["type"] == "material":
        amount = random.randint(prize["min"], prize["max"])
        udata["materials"] = udata.get("materials", 0) + amount
        msg = f"{MATERIAL_EMOJI} Dapet **{amount}x {MATERIAL_NAME}** (buat Tempa rod)!"
    elif prize["type"] == "bait":
        _, _, baits = get_fishing_config()
        if baits:
            bait = random.choice(baits)
            qty  = random.randint(prize["qty_min"], prize["qty_max"])
            udata.setdefault("bait", {})[bait["name"]] = udata["bait"].get(bait["name"], 0) + qty
            msg = f"{bait.get('emoji', '🪱')} Dapet **{bait['name']} x{qty}**!"
        else:
            udata["coins"] += 50
            msg = f"{emoji('coin')} Dapet **50 koin** (gak ada umpan terdaftar)!"
    else:  # luck_boost
        pct   = random.randint(prize["pct_min"], prize["pct_max"])
        catch = random.randint(prize["catch_min"], prize["catch_max"])
        udata["luck_boost_pct"]     = pct
        udata["luck_boost_catches"] = catch
        msg = f"🍀 Dapet **Jimat Luck +{pct}%** buat **{catch}x** mancing berikutnya!"
    save_user_fishing(uid, udata)
    return {"ok": True, "msg": msg}

def open_crate(uid: str) -> dict:
    """Buka 1 crate: rod acak (weighted, makin mahal makin langka) atau material."""
    udata = get_user_fishing(uid)
    if udata.get("crate", 0) <= 0:
        return {"ok": False, "msg": "Lo gak punya Crate buat dibuka!"}
    udata["crate"] -= 1
    _, rods, _ = get_fishing_config()
    if rods and random.random() < 0.35:
        weights = [1.0 / max(r.get("price", 1), 1) for r in rods]
        rod = random.choices(rods, weights=weights, k=1)[0]
        owned = udata.setdefault("owned_rods", [])
        if rod["name"] not in owned:
            owned.append(rod["name"])
            msg = f"{rod.get('emoji', emoji('fish'))} JACKPOT! Dapet rod baru: **{rod['name']}**! Cek Equipment buat pasang."
        else:
            bonus = random.randint(15, 30)
            udata["materials"] = udata.get("materials", 0) + bonus
            msg = f"{rod.get('emoji', emoji('fish'))} Dapet **{rod['name']}** tapi udah punya → ditukar jadi **{bonus}x {MATERIAL_EMOJI} {MATERIAL_NAME}**!"
    else:
        amount = random.randint(10, 25)
        udata["materials"] = udata.get("materials", 0) + amount
        msg = f"{MATERIAL_EMOJI} Dapet **{amount}x {MATERIAL_NAME}**!"
    save_user_fishing(uid, udata)
    return {"ok": True, "msg": msg}

# ===================== TEBAK-TEBAKAN =====================
TEBAKAN_LIST = [
    {"soal": "Apa yang selalu datang tapi gak pernah sampe?", "jawaban": "besok", "reward": 20},
    {"soal": "Makin diisi makin ringan, apa tuh?", "jawaban": "balon", "reward": 25},
    {"soal": "Punya kaki tapi ga bisa jalan, punya lidah tapi ga bisa ngomong. Apa coba?", "jawaban": "sepatu", "reward": 30},
    {"soal": "Apa yang bisa terbang tapi ga punya sayap?", "jawaban": "waktu", "reward": 25},
    {"soal": "Makin tua makin pendek, apa itu?", "jawaban": "lilin", "reward": 20},
    {"soal": "Ada di depan kita tapi ga bisa diliat. Apaan tuh?", "jawaban": "masa depan", "reward": 35},
    {"soal": "Sekali lahir langsung mati. Apa itu?", "jawaban": "korek api", "reward": 20},
    {"soal": "Semakin banyak diambil, semakin besar. Apaan?", "jawaban": "lubang", "reward": 30},
    {"soal": "Apa yang punya gigi tapi ga bisa gigit?", "jawaban": "sisir", "reward": 25},
    {"soal": "Terbalik tetap sama. Apa itu?", "jawaban": "angka 8", "reward": 30},
]

JAWABAN_BENAR_GAUL = [
    "GOKIL LO BRO! Tepat banget, lo emang jago sih! 🔥",
    "YAAMPUN BENERRRR!!! Otaknya encer banget sih wkwkwk 🧠💥",
    "MANTAP JIWA! Lo jawab beneran bro, gaskeun! 🚀",
    "GILAAAK BENER! Lo tuh emang sultan otak ya bestie ✨",
    "SABI BANGET! Jawaban lo pas banget, auto sultan nih! 💯",
    "WOOO BENERRR! Gila sih lo, padahal susah kan? Keren abis! 🎉",
    "ANJIRR BENER! Lo pinter banget sih, respect bro! 👏",
    "GAS POLLLL! Jawaban lo bener, lo emang the best! 🏆",
    "DAGING BANGET! Bener semua, lo emang ga ada lawan! 💪",
    "KEREN ABIS BRO! Gw kagum sama lo, jawaban lo tepat sasaran! 🎯",
]

def get_custom_tebakan():
    return load_json("custom_tebakan.json", [])

def save_custom_tebakan(data):
    save_json("custom_tebakan.json", data)

# ===================== HELPER FUNCTIONS =====================
def get_fishing_data():
    return load_json("fishing.json", {})

def save_fishing_data(data):
    save_json("fishing.json", data)

def get_user_fishing(user_id: str):
    data = get_fishing_data()
    uid  = str(user_id)
    if uid not in data:
        _, rods, baits = get_fishing_config()
        starter_rod = rods[0]["name"] if rods else "Pancing Bambu"
        data[uid] = {
            "coins": 100,
            "rod": starter_rod,
            "owned_rods": [starter_rod],
            "rod_levels": {},
            "bait": {baits[0]["name"]: 3} if baits else {},
            "equipped_bait": baits[0]["name"] if baits else None,
            "inventory": [],
            "fish_dex": [],
            "total_catch": 0,
            "last_fish": 0,
            "last_spin": 0,
            "claimed_quests": [],
            "materials": 0,
            "lootbox": 0,
            "crate": 0,
            "lootbox_collected": 0,
            "crate_collected": 0,
        }
        save_fishing_data(data)
    else:
        # Migrasi otomatis buat user lama yang datanya dibuat sebelum
        # fitur ini ada (Equipment/Koleksi/Tempa/Lootbox/Crate).
        defaults = {
            "owned_rods": lambda d: [d.get("rod", "Pancing Bambu")],
            "equipped_bait": lambda d: None,
            "rod_levels": lambda d: {},
            "fish_dex": lambda d: [],
            "materials": lambda d: 0,
            "lootbox": lambda d: 0,
            "crate": lambda d: 0,
            "lootbox_collected": lambda d: 0,
            "crate_collected": lambda d: 0,
            "last_spin": lambda d: 0,
        }
        changed = False
        for key, default_fn in defaults.items():
            if key not in data[uid]:
                data[uid][key] = default_fn(data[uid])
                changed = True
        if changed:
            save_fishing_data(data)
    return data[uid]

def save_user_fishing(user_id: str, udata: dict):
    data = get_fishing_data()
    data[str(user_id)] = udata
    save_fishing_data(data)

def get_warns():       return load_json("warns.json", {})
def save_warns(d):     save_json("warns.json", d)
def get_config():      return load_json("config.json", {})
def save_config(d):    save_json("config.json", d)
def get_autoresponse():    return load_json("autoresponse.json", {})
def save_autoresponse(d):  save_json("autoresponse.json", d)
def get_sticky():      return load_json("sticky.json", {})
def save_sticky(d):    save_json("sticky.json", d)
def get_giveaways():   return load_json("giveaways.json", {})
def save_giveaways(d): save_json("giveaways.json", d)
def get_premium_data():   return load_json("premium.json", {"users": {}, "settings": {}, "packages": {}, "locked_commands": []})
def save_premium_data(d): save_json("premium.json", d)
def get_premium_orders():   return load_json("premium_orders.json", {})
def save_premium_orders(d): save_json("premium_orders.json", d)

def dark_red_embed(title="", description="", **kwargs):
    return discord.Embed(title=title, description=description, color=DARK_RED, **kwargs)


# ===================== COMPONENTS V2 PANEL =====================
# Panel pengganti embed biasa, pake Discord Components V2 (Container/TextDisplay/
# Section/Separator) biar tampilannya lebih rapi & modern. Dipasang bertahap ke
# command-command paling sering dipakai (fishing, quest, daily, help, dll).

class StartDoomPanel(discord.ui.LayoutView):
    """
    Panel Components V2 yang niru tampilan dark_red_embed (judul + deskripsi +
    thumbnail opsional + footer opsional), plus bisa nampung ActionRow tombol
    kalau ada `buttons` yang dikasih.
    """
    def __init__(self, title: str = "", description: str = "", *,
                 footer: str | None = None, thumbnail_url: str | None = None,
                 image_url: str | None = None, color: int = DARK_RED,
                 buttons: list | None = None, fields: list | None = None,
                 timeout: float | None = 180):
        super().__init__(timeout=timeout)

        text = f"### {title}\n{description}" if title else description
        container = discord.ui.Container(accent_colour=color)

        if thumbnail_url:
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(text),
                    accessory=discord.ui.Thumbnail(thumbnail_url)
                )
            )
        elif text:
            container.add_item(discord.ui.TextDisplay(text))

        if image_url:
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(image_url)))

        # "fields" opsional: list of (name, value) buat niru embed.add_field
        if fields:
            container.add_item(discord.ui.Separator())
            for name, value in fields:
                container.add_item(discord.ui.TextDisplay(f"**{name}**\n{value}"))

        if buttons:
            container.add_item(discord.ui.Separator())
            row = discord.ui.ActionRow()
            for btn in buttons:
                row.add_item(btn)
            container.add_item(row)

        if footer:
            container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
            container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        self.add_item(container)


def panel(title: str = "", description: str = "", **kwargs) -> StartDoomPanel:
    """Shortcut bikin StartDoomPanel, pengganti dark_red_embed() buat pesan Components V2."""
    return StartDoomPanel(title=title, description=description, **kwargs)


# ===================== NO-PREFIX SYSTEM (Owner Only Grant) =====================
# Owner bot bisa kasih akses "no prefix" ke user tertentu, jadi mereka bisa
# ketik command langsung tanpa "d" di depannya (misal: "fish" alih-alih
# "dfish"). Owner bot sendiri OTOMATIS punya akses ini.

def get_noprefix_users() -> list:
    return load_json("noprefix.json", {"users": []}).get("users", [])

def save_noprefix_users(users: list):
    save_json("noprefix.json", {"users": list(dict.fromkeys(users))})

def is_noprefix_user(user_id) -> bool:
    uid = int(user_id)
    if OWNER_ID and uid == OWNER_ID:
        return True
    return str(uid) in get_noprefix_users()

def get_all_command_names() -> set:
    """Kumpulan semua nama command + alias prefix yang valid (lowercase)."""
    names = set()
    for cmd in bot.commands:
        names.add(cmd.name.lower())
        names.update(a.lower() for a in cmd.aliases)
    return names


# ===================== DAILY LOGIN SYSTEM =====================
DAILY_COIN_MIN   = 100
DAILY_COIN_MAX   = 250
DAILY_STREAK_BONUS_PER_DAY = 15   # bonus koin tiap hari streak, di-cap
DAILY_STREAK_BONUS_CAP     = 300  # bonus maksimal dari streak
DAILY_COOLDOWN_H = 24
DAILY_STREAK_GRACE_H = 48  # kalau claim lewat dari ini, streak reset ke 1

def get_daily_data() -> dict:
    return load_json("daily.json", {})

def save_daily_data(d: dict):
    save_json("daily.json", d)

def get_user_daily(user_id: str) -> dict:
    data = get_daily_data()
    return data.get(str(user_id), {"last_claim": 0, "streak": 0})

def set_user_daily(user_id: str, record: dict):
    data = get_daily_data()
    data[str(user_id)] = record
    save_daily_data(data)

def perform_daily_claim(uid: str) -> dict:
    """
    Coba klaim daily buat user. Return dict:
    - success=False, sisa_s=<detik sisa cooldown>  → kalau masih cooldown
    - success=True, base_reward, streak_bonus, total_reward, streak, total_coins → kalau berhasil
    """
    record  = get_user_daily(uid)
    now     = time.time()
    elapsed = now - record.get("last_claim", 0)
    cooldown_s = DAILY_COOLDOWN_H * 3600

    if elapsed < cooldown_s:
        return {"success": False, "sisa_s": int(cooldown_s - elapsed), "streak": record.get("streak", 0)}

    streak = record.get("streak", 0) + 1 if elapsed <= DAILY_STREAK_GRACE_H * 3600 else 1
    streak_bonus = min(streak * DAILY_STREAK_BONUS_PER_DAY, DAILY_STREAK_BONUS_CAP)
    base_reward  = random.randint(DAILY_COIN_MIN, DAILY_COIN_MAX)
    total_reward = base_reward + streak_bonus

    udata = get_user_fishing(uid)
    udata["coins"] += total_reward
    save_user_fishing(uid, udata)
    set_user_daily(uid, {"last_claim": now, "streak": streak})

    return {
        "success": True, "base_reward": base_reward, "streak_bonus": streak_bonus,
        "total_reward": total_reward, "streak": streak, "total_coins": udata["coins"],
    }


# ===================== QUEST SYSTEM (Mancing + Vote) =====================
# Quest dicek dari progress asli user (total tangkapan / status vote), BUKAN
# auto-reward. Begitu target kecapai, quest berstatus "siap diklaim" dan user
# harus pencet tombol Claim di panel "dquest" buat narik reward-nya —
# persis kaya sistem quest log Nocturne Assistant.
QUEST_LIST = [
    {"id": "quest_5",        "type": "fish",    "target": 5,   "label": "🎣 Pemula Mancing",     "reward_coins": 100,  "reward_rod": None},
    {"id": "quest_15",       "type": "fish",    "target": 15,  "label": "🐟 Mancing Rajin",      "reward_coins": 250,  "reward_rod": "Pancing Kayu"},
    {"id": "quest_30",       "type": "fish",    "target": 30,  "label": "🦈 Mancing Handal",     "reward_coins": 500,  "reward_rod": "Pancing Besi"},
    {"id": "quest_60",       "type": "fish",    "target": 60,  "label": "🔱 Master Pemancing",   "reward_coins": 1000, "reward_rod": "Pancing Karbon"},
    {"id": "quest_100",      "type": "fish",    "target": 100, "label": "🐉 Legenda Mancing",    "reward_coins": 2500, "reward_rod": "Pancing Titan"},
    {"id": "quest_vote",     "type": "vote",    "target": 1,   "label": "🗳️ Vote Bot di Top.gg",  "reward_coins": 150,  "reward_rod": None},
    {"id": "quest_lootbox3", "type": "lootbox", "target": 3,   "label": "📦 Kumpulin 3 Lootbox", "reward_coins": 300,  "reward_rod": None},
    {"id": "quest_crate3",   "type": "crate",   "target": 3,   "label": "🗃️ Kumpulin 3 Crate",   "reward_coins": 400,  "reward_rod": None},
]

def get_quest_progress(uid: str, quest: dict) -> int:
    """Ambil progress mentah user buat 1 quest, berdasarkan tipe quest-nya."""
    udata = get_user_fishing(uid)
    if quest["type"] == "fish":
        return udata.get("total_catch", 0)
    if quest["type"] == "vote":
        return 1 if get_vote_record(uid).get("last_claim") else 0
    if quest["type"] == "lootbox":
        return udata.get("lootbox_collected", 0)
    if quest["type"] == "crate":
        return udata.get("crate_collected", 0)
    return 0

def get_quest_status(uid: str) -> list:
    """
    Return list status tiap quest: {**quest, progress, done, ready}
    - done  = udah diklaim
    - ready = target kecapai tapi belum diklaim
    """
    udata   = get_user_fishing(uid)
    claimed = set(udata.get("claimed_quests", []))
    status  = []
    for q in QUEST_LIST:
        progress = get_quest_progress(uid, q)
        done     = q["id"] in claimed
        ready    = (not done) and progress >= q["target"]
        status.append({**q, "progress": progress, "done": done, "ready": ready})
    return status

def claim_ready_quests(uid: str) -> list:
    """Klaim semua quest yang statusnya 'ready'. Return list quest yang baru diklaim."""
    udata   = get_user_fishing(uid)
    claimed = set(udata.get("claimed_quests", []))
    newly   = []
    for q in QUEST_LIST:
        if q["id"] in claimed:
            continue
        if get_quest_progress(uid, q) >= q["target"]:
            udata["coins"] += q["reward_coins"]
            if q["reward_rod"]:
                udata["rod"] = q["reward_rod"]
                owned = udata.setdefault("owned_rods", [])
                if q["reward_rod"] not in owned:
                    owned.append(q["reward_rod"])
            claimed.add(q["id"])
            newly.append(q)
    if newly:
        udata["claimed_quests"] = list(claimed)
        save_user_fishing(uid, udata)
    return newly



# ===================== DAILY CHECKLIST + WEEKLY QUEST TRACKING =====================
# Counter-based progress buat panel checklist gaya gambar (lihat CHECKLIST IMAGE
# RENDERER di bawah). Kedua sistem ini pakai "rolling window" per user (reset N
# jam sejak window_start), bukan reset serentak jam 00:00, biar simpel & gak
# butuh scheduler terpisah.
CHECKLIST_WINDOW_H = 24
WEEKLY_WINDOW_H     = 24 * 7

DAILY_CHECKLIST_BONUS = 200   # bonus koin kalau semua task Daily checklist kelar
WEEKLY_QUEST_REWARD   = 1500  # reward koin kalau semua task Weekly kelar

def get_checklist_data() -> dict: return load_json("checklist.json", {})
def save_checklist_data(d):       save_json("checklist.json", d)
def get_weekly_data() -> dict:    return load_json("weekly.json", {})
def save_weekly_data(d):          save_json("weekly.json", d)

def _get_window_record(store_getter, uid: str, window_h: float, base_fields: dict) -> dict:
    data = store_getter()
    rec  = data.get(str(uid))
    now  = time.time()
    if not rec or now - rec.get("window_start", 0) > window_h * 3600:
        rec = {"window_start": now, **base_fields}
    return rec

def get_user_checklist(uid: str) -> dict:
    rec = _get_window_record(get_checklist_data, uid, CHECKLIST_WINDOW_H,
                              {"fish": 0, "sell": 0, "bonus_claimed": False})
    data = get_checklist_data()
    data[str(uid)] = rec
    save_checklist_data(data)
    return rec

def bump_checklist(uid: str, key: str, amt: int = 1):
    rec = get_user_checklist(uid)
    rec[key] = rec.get(key, 0) + amt
    data = get_checklist_data()
    data[str(uid)] = rec
    save_checklist_data(data)

def claim_checklist_bonus(uid: str) -> bool:
    rec = get_user_checklist(uid)
    if rec.get("bonus_claimed"):
        return False
    rec["bonus_claimed"] = True
    data = get_checklist_data()
    data[str(uid)] = rec
    save_checklist_data(data)
    udata = get_user_fishing(uid)
    udata["coins"] += DAILY_CHECKLIST_BONUS
    save_user_fishing(uid, udata)
    return True

def get_user_weekly(uid: str) -> dict:
    rec = _get_window_record(get_weekly_data, uid, WEEKLY_WINDOW_H,
                              {"fish": 0, "sell": 0, "vote": 0, "reward_claimed": False})
    data = get_weekly_data()
    data[str(uid)] = rec
    save_weekly_data(data)
    return rec

def bump_weekly(uid: str, key: str, amt: int = 1):
    rec = get_user_weekly(uid)
    rec[key] = rec.get(key, 0) + amt
    data = get_weekly_data()
    data[str(uid)] = rec
    save_weekly_data(data)

def claim_weekly_reward(uid: str) -> bool:
    rec = get_user_weekly(uid)
    if rec.get("reward_claimed"):
        return False
    rec["reward_claimed"] = True
    data = get_weekly_data()
    data[str(uid)] = rec
    save_weekly_data(data)
    udata = get_user_fishing(uid)
    udata["coins"] += WEEKLY_QUEST_REWARD
    save_user_fishing(uid, udata)
    return True

def build_daily_checklist_tasks(uid: str) -> list:
    daily_rec = get_user_daily(uid)
    vote_rec  = get_vote_record(uid)
    cl        = get_user_checklist(uid)
    now       = time.time()
    daily_done = (now - daily_rec.get("last_claim", 0)) < DAILY_COOLDOWN_H * 3600
    vote_done  = (now - vote_rec.get("last_claim", 0)) < VOTE_COOLDOWN_H * 3600
    return [
        {"label": "Claim your daily", "current": 1 if daily_done else 0, "target": 1, "done": daily_done, "icon": "sun"},
        {"label": "Claim a vote",     "current": 1 if vote_done else 0,  "target": 1, "done": vote_done,  "icon": "check"},
        {"label": "Go fishing 3 times", "current": min(cl.get("fish", 0), 3), "target": 3, "done": cl.get("fish", 0) >= 3, "icon": "fish"},
        {"label": "Sell 3 fish",        "current": min(cl.get("sell", 0), 3), "target": 3, "done": cl.get("sell", 0) >= 3, "icon": "coin"},
    ]

def build_weekly_checklist_tasks(uid: str) -> list:
    w = get_user_weekly(uid)
    targets = {"fish": 100, "sell": 50, "vote": 3}
    labels  = {"fish": "Hunt 100 fish", "sell": "Sell 50 fish", "vote": "Vote the bot 3 times"}
    icons   = {"fish": "fish", "sell": "coin", "vote": "check"}
    tasks = []
    for key in ("fish", "sell", "vote"):
        cur = w.get(key, 0)
        tgt = targets[key]
        tasks.append({"label": labels[key], "current": min(cur, tgt), "target": tgt, "done": cur >= tgt, "icon": icons[key]})
    return tasks

def build_quest_checklist_tasks(uid: str) -> list:
    status = get_quest_status(uid)
    return [{
        "label": q["label"].split(" ", 1)[-1] if q["label"][0] not in "0123456789" else q["label"],
        "current": min(q["progress"], q["target"]), "target": q["target"],
        "done": q["done"], "icon": "sword" if q["type"] == "fish" else "check",
    } for q in status]


# ===================== CHECKLIST IMAGE RENDERER (Pillow) =====================
# Panel Daily/Weekly/Quests digambar sebagai PNG card (mirip referensi bot lain
# yang dikasih owner), bukan Components V2 text. Card di-generate ulang tiap
# kali user pindah tab, terus dikirim sebagai attachment baru lewat
# interaction.response.edit_message(attachments=[...]).

_FONT_CACHE: dict = {}

def ck_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    key = (weight, size)
    if key not in _FONT_CACHE:
        path = FONT_DIR / f"Poppins-{weight}.ttf"
        try:
            _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]

CK_BG          = (13, 9, 9)
CK_CARD        = (24, 16, 16)
CK_CARD_BORDER = (64, 24, 24)
CK_ROW_BG      = (34, 20, 20)
CK_ROW_DONE_BG = (20, 28, 21)
CK_ACCENT      = (178, 34, 34)
CK_ACCENT_2    = (95, 200, 130)
CK_TEXT_MAIN   = (240, 232, 230)
CK_TEXT_DIM    = (175, 140, 138)
CK_TEXT_DONE   = (120, 150, 125)
CK_BAR_BG      = (58, 30, 30)
CK_GOLD        = (240, 190, 90)
CK_WIDTH       = 460

def _ck_rounded(draw, xy, radius, **kw):
    draw.rounded_rectangle(xy, radius=radius, **kw)

def _ck_badge(size: int, bg, icon_fn) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d  = ImageDraw.Draw(im)
    d.ellipse((0, 0, size, size), fill=bg)
    icon_fn(d, size)
    return im

def _ck_icon_fish(d, s):
    c = (255, 255, 255)
    cx, cy, r = s * 0.42, s * 0.5, s * 0.20
    d.ellipse((cx - r, cy - r * 0.7, cx + r, cy + r * 0.7), fill=c)
    d.polygon([(cx + r * 0.9, cy), (s * 0.82, cy - s * 0.18), (s * 0.82, cy + s * 0.18)], fill=c)
    d.ellipse((cx - r * 0.55, cy - r * 0.25, cx - r * 0.3, cy), fill=(30, 20, 50))

def _ck_icon_coin(d, s):
    c, m = (255, 255, 255), s * 0.18
    d.ellipse((m, m, s - m, s - m), outline=c, width=max(2, s // 14))
    fnt = ck_font("Bold", int(s * 0.42))
    bbox = d.textbbox((0, 0), "$", font=fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((s / 2 - tw / 2 - bbox[0], s / 2 - th / 2 - bbox[1]), "$", font=fnt, fill=c)

def _ck_icon_check(d, s):
    c, m = (255, 255, 255), s * 0.2
    _ck_rounded(d, (m, m, s - m, s - m), radius=s * 0.12, outline=c, width=max(2, s // 14))
    d.line([(s * 0.32, s * 0.52), (s * 0.44, s * 0.66), (s * 0.70, s * 0.34)], fill=c, width=max(3, s // 10), joint="curve")

def _ck_icon_sun(d, s):
    c = (255, 255, 255)
    cx, cy, r = s / 2, s / 2, s * 0.18
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c)
    for i in range(8):
        ang = i * math.pi / 4
        x1, y1 = cx + math.cos(ang) * r * 1.5, cy + math.sin(ang) * r * 1.5
        x2, y2 = cx + math.cos(ang) * r * 2.1, cy + math.sin(ang) * r * 2.1
        d.line([(x1, y1), (x2, y2)], fill=c, width=max(2, s // 16))

def _ck_icon_sword(d, s):
    c = (255, 255, 255)
    d.line([(s * 0.25, s * 0.75), (s * 0.75, s * 0.25)], fill=c, width=max(3, s // 10))
    d.line([(s * 0.25, s * 0.25), (s * 0.75, s * 0.75)], fill=c, width=max(3, s // 10))

def _ck_icon_trophy(d, s):
    c, m = CK_GOLD, s * 0.24
    d.rectangle((m, m, s - m, s * 0.55), fill=c)
    d.arc((0, m * 0.6, m * 1.4, s * 0.55), start=90, end=270, fill=c, width=max(2, s // 12))
    d.arc((s - m * 1.4, m * 0.6, s, s * 0.55), start=270, end=90, fill=c, width=max(2, s // 12))
    d.rectangle((s * 0.42, s * 0.55, s * 0.58, s * 0.72), fill=c)
    d.rectangle((s * 0.3, s * 0.72, s * 0.7, s * 0.8), fill=c)

CK_ICONS = {"fish": _ck_icon_fish, "coin": _ck_icon_coin, "check": _ck_icon_check,
            "sun": _ck_icon_sun, "sword": _ck_icon_sword}

def _ck_bar(d, x, y, w, h, frac, fill):
    _ck_rounded(d, (x, y, x + w, y + h), radius=h / 2, fill=CK_BAR_BG)
    frac = max(0.0, min(1.0, frac))
    if frac > 0:
        fw = max(h, w * frac)
        _ck_rounded(d, (x, y, x + fw, y + h), radius=h / 2, fill=fill)

def _ck_tabbar(d, x, y, w, active: str):
    tabs = [("daily", "Daily"), ("weekly", "Weekly"), ("quests", "Quests")]
    gap, h = 8, 40
    tw = (w - gap * 2) / 3
    for i, (key, label) in enumerate(tabs):
        tx = x + i * (tw + gap)
        is_active = key == active
        _ck_rounded(d, (tx, y, tx + tw, y + h), radius=12, fill=CK_ACCENT if is_active else CK_ROW_BG)
        fnt = ck_font("SemiBold", 15)
        bbox = d.textbbox((0, 0), label, font=fnt)
        d.text((tx + tw / 2 - (bbox[2] - bbox[0]) / 2, y + 10), label, font=fnt,
               fill=(255, 255, 255) if is_active else CK_TEXT_DIM)
    return y + h

def render_checklist_card(tab: str, username: str, balance: int, tasks: list, reset_text: str) -> io.BytesIO:
    pad, header_h, row_h, row_gap, footer_h = 20, 92, 62, 10, 66
    n = max(1, len(tasks))
    height = int(pad + 48 + 14 + header_h + n * (row_h + row_gap) + footer_h + pad)

    img = Image.new("RGB", (CK_WIDTH, height), CK_BG)
    d = ImageDraw.Draw(img)
    _ck_rounded(d, (pad // 2, pad // 2, CK_WIDTH - pad // 2, height - pad // 2), radius=22,
                fill=CK_CARD, outline=CK_CARD_BORDER, width=2)

    cx, cw = pad, CK_WIDTH - pad * 2
    cy = _ck_tabbar(d, cx, pad, cw, tab) + 14

    title_map = {"daily": "Daily Checklist", "weekly": "Weekly Checklist", "quests": "Quest Log"}
    badge = _ck_badge(46, CK_ACCENT, CK_ICONS["check"])
    img.paste(badge, (cx, cy), badge)
    d.text((cx + 58, cy - 2), f"@{username}'s {title_map.get(tab, 'Checklist')}", font=ck_font("Bold", 17), fill=CK_TEXT_MAIN)
    subtitle = "Complete quests to earn rewards!" if tab == "quests" else f"Complete {n} tasks to earn your reward!"
    d.text((cx + 58, cy + 22), subtitle, font=ck_font("Regular", 12), fill=CK_TEXT_DIM)
    bal_fnt = ck_font("Medium", 13)
    bal_txt = f"Balance: {balance} "
    d.text((cx + 58, cy + 42), bal_txt, font=bal_fnt, fill=CK_GOLD)
    bw = d.textbbox((0, 0), bal_txt, font=bal_fnt)[2]
    coin_icon = _ck_badge(16, CK_GOLD, _ck_icon_coin)
    img.paste(coin_icon, (int(cx + 58 + bw), cy + 42), coin_icon)
    d.text((cx + 58 + bw + 20, cy + 42), "koin", font=bal_fnt, fill=CK_GOLD)

    trophy = _ck_badge(44, (46, 42, 30), _ck_icon_trophy)
    img.paste(trophy, (cx + cw - 44, cy), trophy)

    cy += header_h
    for t in tasks:
        _ck_rounded(d, (cx, cy, cx + cw, cy + row_h), radius=14, fill=CK_ROW_DONE_BG if t["done"] else CK_ROW_BG)
        icon_im = _ck_badge(38, CK_ACCENT_2 if t["done"] else (60, 56, 82), CK_ICONS.get(t.get("icon", "check"), _ck_icon_check))
        img.paste(icon_im, (cx + 12, cy + 12), icon_im)

        label_fnt = ck_font("SemiBold", 14)
        label_color = CK_TEXT_DONE if t["done"] else CK_TEXT_MAIN
        label = t["label"][:34]
        d.text((cx + 62, cy + 10), label, font=label_fnt, fill=label_color)
        if t["done"]:
            bbox = d.textbbox((cx + 62, cy + 10), label, font=label_fnt)
            ymid = (bbox[1] + bbox[3]) / 2
            d.line([(bbox[0], ymid), (bbox[2], ymid)], fill=label_color, width=2)

        frac_fnt = ck_font("Medium", 12)
        frac_txt = f"{t['current']}/{t['target']}"
        fbbox = d.textbbox((0, 0), frac_txt, font=frac_fnt)
        d.text((cx + cw - (fbbox[2] - fbbox[0]) - 14, cy + 12), frac_txt, font=frac_fnt,
               fill=CK_ACCENT_2 if t["done"] else CK_TEXT_DIM)

        _ck_bar(d, cx + 62, cy + 40, cw - 62 - 14, 8, t["current"] / max(1, t["target"]),
                CK_ACCENT_2 if t["done"] else CK_ACCENT)
        cy += row_h + row_gap

    done_n = sum(1 for t in tasks if t["done"])
    d.text((cx, cy + 4), title_map.get(tab, "Progress").replace(" Checklist", " Progress").replace("Quest Log", "Quest Progress"),
           font=ck_font("SemiBold", 14), fill=CK_TEXT_MAIN)
    frac_txt = f"{done_n}/{n}"
    ffnt = ck_font("SemiBold", 14)
    fbbox = d.textbbox((0, 0), frac_txt, font=ffnt)
    d.text((cx + cw - (fbbox[2] - fbbox[0]), cy + 4), frac_txt, font=ffnt, fill=CK_TEXT_MAIN)
    cy += 26
    _ck_bar(d, cx, cy, cw, 10, done_n / n, CK_ACCENT_2)
    cy += 22
    d.text((cx, cy), reset_text, font=ck_font("Regular", 12), fill=CK_TEXT_DIM)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def render_catch_thumbnail(fish_name: str, rarity: str) -> io.BytesIO:
    """Card kecil (thumbnail) buat 1 hasil tangkapan, warna & label sesuai
    rarity biar user langsung ngeh dapet apa dari sekali liat, gak perlu
    baca teks dulu. Dipasang di Section accessory Thumbnail panel Mancing."""
    _, color = get_rarity_display(rarity)
    rgb = ((color >> 16) & 255, (color >> 8) & 255, color & 255)
    W = H = 240
    img = Image.new("RGB", (W, H), (18, 13, 13))
    d = ImageDraw.Draw(img)

    _ck_rounded(d, (0, 0, W, H), radius=28, fill=rgb)
    pad = 10
    _ck_rounded(d, (pad, pad, W - pad, H - pad), radius=22, fill=(20, 15, 15))

    label = RARITY_LABELS.get(rarity, "Common").upper()
    lfnt  = ck_font("Bold", 20)
    lbbox = d.textbbox((0, 0), label, font=lfnt)
    lw, lh = lbbox[2] - lbbox[0], lbbox[3] - lbbox[1]
    pill_pad_x, pill_pad_y = 16, 8
    pill_w, pill_h = lw + pill_pad_x * 2, lh + pill_pad_y * 2
    px, py = (W - pill_w) / 2, 26
    _ck_rounded(d, (px, py, px + pill_w, py + pill_h), radius=pill_h / 2, fill=rgb)
    d.text((px + pill_pad_x - lbbox[0], py + pill_pad_y - lbbox[1]), label, font=lfnt, fill=(255, 255, 255))

    nfnt  = ck_font("SemiBold", 22)
    words = fish_name.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textbbox((0, 0), test, font=nfnt)[2] > W - 40 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    line_h  = nfnt.size + 8
    total_h = len(lines) * line_h
    ny = H / 2 - total_h / 2 + 8
    for line in lines:
        bbox = d.textbbox((0, 0), line, font=nfnt)
        lw2  = bbox[2] - bbox[0]
        d.text((W / 2 - lw2 / 2 - bbox[0], ny), line, font=nfnt, fill=(240, 235, 232))
        ny += line_h

    strip_h = 14
    _ck_rounded(d, (pad, H - pad - strip_h, W - pad, H - pad), radius=8, fill=rgb)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


class ChecklistPanelView(discord.ui.View):
    """View interaktif Daily/Weekly/Quests. Tiap pindah tab, gambar card-nya
    di-generate ulang lewat render_checklist_card() dan dikirim sebagai
    attachment baru (edit_message dengan attachments=[file])."""
    def __init__(self, user: discord.abc.User, tab: str = "daily"):
        super().__init__(timeout=120)
        self.user = user
        self.tab  = tab
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for key, label, style in [
            ("daily", "📋 Daily", discord.ButtonStyle.primary),
            ("weekly", "📅 Weekly", discord.ButtonStyle.primary),
            ("quests", "📖 Quests", discord.ButtonStyle.primary),
        ]:
            btn = discord.ui.Button(label=label, style=style if key == self.tab else discord.ButtonStyle.secondary, row=0)
            btn.callback = self._make_tab_cb(key)
            self.add_item(btn)

        # Tombol Claim cuma ditampilin kalau MEMANG ada yang bisa diklaim,
        # dan jadi disabled (bukan ilang gitu aja) begitu udah diklaim —
        # biar user tau statusnya, tapi gak bisa diklik lagi/dobel klaim.
        state = self._claim_state()
        if state == "ready":
            claim_btn = discord.ui.Button(label="🎁 Claim", style=discord.ButtonStyle.success, row=1)
            claim_btn.callback = self.claim
            self.add_item(claim_btn)
        elif state == "claimed":
            claim_btn = discord.ui.Button(label="✅ Sudah Diklaim", style=discord.ButtonStyle.secondary, row=1, disabled=True)
            self.add_item(claim_btn)
        # state == "hidden" → belum ada yang beres, tombol gak usah ditampilin dulu

    def _claim_state(self) -> str:
        """Return 'ready' (ada yg bisa diklaim) | 'claimed' (udah abis diklaim
        semua) | 'hidden' (belum ada yg beres) — buat tab yang lagi aktif."""
        uid = str(self.user.id)
        if self.tab == "quests":
            statuses = get_quest_status(uid)
            if any(s["ready"] for s in statuses):
                return "ready"
            if statuses and all(s["done"] for s in statuses):
                return "claimed"
            return "hidden"
        elif self.tab == "weekly":
            tasks    = build_weekly_checklist_tasks(uid)
            all_done = bool(tasks) and all(t["done"] for t in tasks)
            claimed  = get_user_weekly(uid).get("reward_claimed", False)
            if all_done and not claimed:
                return "ready"
            if all_done and claimed:
                return "claimed"
            return "hidden"
        else:
            tasks    = build_daily_checklist_tasks(uid)
            all_done = bool(tasks) and all(t["done"] for t in tasks)
            claimed  = get_user_checklist(uid).get("bonus_claimed", False)
            if all_done and not claimed:
                return "ready"
            if all_done and claimed:
                return "claimed"
            return "hidden"

    def _make_tab_cb(self, key: str):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.user.id:
                await interaction.response.send_message("❌ Bukan panel lo bro!", ephemeral=True)
                return
            self.tab = key
            self._build_buttons()
            await interaction.response.edit_message(attachments=[self._render()], view=self)
        return cb

    def _tasks(self) -> list:
        uid = str(self.user.id)
        if self.tab == "weekly":
            return build_weekly_checklist_tasks(uid)
        if self.tab == "quests":
            return build_quest_checklist_tasks(uid)
        return build_daily_checklist_tasks(uid)

    def _reset_text(self) -> str:
        uid = str(self.user.id)
        now = time.time()
        if self.tab == "weekly":
            w = get_user_weekly(uid)
            left = WEEKLY_WINDOW_H * 3600 - (now - w.get("window_start", now))
        elif self.tab == "quests":
            return "Progress mancing lo, gak ada reset waktu"
        else:
            cl = get_user_checklist(uid)
            left = CHECKLIST_WINDOW_H * 3600 - (now - cl.get("window_start", now))
        left = max(0, int(left))
        h, m = left // 3600, (left % 3600) // 60
        return f"Checklist resets in {h}h {m}m"

    def _render(self) -> discord.File:
        buf = render_checklist_card(self.tab, self.user.display_name, get_user_fishing(str(self.user.id))["coins"],
                                     self._tasks(), self._reset_text())
        return discord.File(buf, filename="checklist.png")

    async def claim(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("❌ Bukan panel lo bro!", ephemeral=True)
            return
        uid = str(self.user.id)
        status_text = None
        if self.tab == "quests":
            newly = claim_ready_quests(uid)
            if newly:
                labels = ", ".join(q["label"] for q in newly)
                status_text = f"🎉 Quest diklaim: **{labels}**!"
        elif self.tab == "weekly":
            if claim_weekly_reward(uid):
                status_text = f"🎉 Weekly reward diklaim! +**{WEEKLY_QUEST_REWARD}** koin!"
        else:
            if claim_checklist_bonus(uid):
                status_text = f"🎉 Daily checklist bonus diklaim! +**{DAILY_CHECKLIST_BONUS}** koin!"
        # Semua refresh dalam SATU update (gambar checklist + tombol + status),
        # gak ada notif/pesan terpisah lagi.
        self._build_buttons()
        await interaction.response.edit_message(content=status_text, attachments=[self._render()], view=self)


async def send_checklist_panel(sender, user: discord.abc.User, tab: str = "daily"):
    """Kirim panel checklist pertama kali. `sender` = ctx.send / ctx.reply / interaction.response.send_message."""
    view = ChecklistPanelView(user, tab=tab)
    await sender(file=view._render(), view=view)


# ===================== EMOJI SERVER SYSTEM =====================
# Owner bot bisa ganti emoji unicode bawaan bot dengan emoji custom server
# lewat command "dsetemoji <key> <emoji>". Kalau belum diset, bot pakai
# emoji unicode default.
DEFAULT_EMOJIS = {
    "coin":      "🪙",
    "fish":      "🎣",
    "success":   "✅",
    "fail":      "❌",
    "mythic":    "🌈",
    "legendary": "⭐",
    "epic":      "🟣",
    "rare":      "💎",
    "uncommon":  "🔵",
    "common":    "⚪",
    "trash":     "💩",
    "quest":     "📜",
    "daily":     "🎁",
    "vote":      "🗳️",
    "streak":    "🔥",
}

def get_emoji_config() -> dict:
    return load_json("emoji_config.json", {})

def save_emoji_config(d: dict):
    save_json("emoji_config.json", d)

def emoji(key: str) -> str:
    """Ambil emoji (custom server kalau sudah diset, kalau belum pakai default unicode)."""
    cfg = get_emoji_config()
    return cfg.get(key, DEFAULT_EMOJIS.get(key, ""))

def parse_emoji_image_url(emoji_str: str | None) -> str | None:
    """Parse 1 string emoji APAPUN (custom Discord <:nama:id> / <a:nama:id>,
    bisa dari emoji_config ATAU dari field emoji ikan/rod/umpan hasil
    dsetfishing) jadi URL gambar CDN Discord. Return None kalau itu emoji
    unicode biasa (gak ada gambar buat di-URL-in)."""
    if not emoji_str:
        return None
    m = re.match(r"^<(a?):[a-zA-Z0-9_]+:(\d+)>$", emoji_str.strip())
    if not m:
        return None
    animated, eid = m.groups()
    ext = "gif" if animated else "png"
    return f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size=128"

def get_emoji_thumbnail_url(key: str) -> str | None:
    """Kalau owner udah set CUSTOM EMOJI DISCORD (format <:nama:id> / <a:nama:id>,
    bukan unicode default) buat key ini lewat `dsetemoji`, return URL gambar
    emoji itu dari CDN Discord — biar bisa dipasang langsung jadi Thumbnail
    Components V2 (misal buat rarity legendary/mythic/dll). Return None kalau
    key itu masih pakai emoji unicode default (gak ada gambar buat di-URL-in)."""
    return parse_emoji_image_url(emoji(key))


# ===================== SPIN WHEEL SYSTEM =====================
# Spin wheel pake koin. Hadiah rod sengaja dibikin SULIT BANGET (weight kecil),
# hadiah koin & umpan jauh lebih sering keluar. Owner bisa full custom daftar
# hadiah + peluangnya lewat panel "!Kingdoom spinwheel".
DEFAULT_SPIN_COST = 100

DEFAULT_SPIN_PRIZES = [
    {"type": "coin",  "label": "Koin Receh",      "weight": 35,   "min": 20,  "max": 80},
    {"type": "coin",  "label": "Koin Lumayan",     "weight": 20,   "min": 100, "max": 250},
    {"type": "bait",  "label": "Cacing Biasa",     "weight": 15,   "name": "Cacing Biasa", "qty": 3},
    {"type": "bait",  "label": "Jangkrik",         "weight": 10,   "name": "Jangkrik",     "qty": 2},
    {"type": "coin",  "label": "Jackpot Koin",     "weight": 5,    "min": 500, "max": 1000},
    {"type": "trash", "label": "Zonk",             "weight": 11.65},
    {"type": "rod",   "label": "Pancing Kayu",     "weight": 3,    "name": "Pancing Kayu"},
    {"type": "rod",   "label": "Pancing Besi",     "weight": 1.5,  "name": "Pancing Besi"},
    {"type": "rod",   "label": "Pancing Titan",    "weight": 0.3,  "name": "Pancing Titan"},
    {"type": "rod",   "label": "Pancing Legenda",  "weight": 0.05, "name": "Pancing Legenda"},
]

def get_spin_config():
    """Load config spin wheel (cost + prizes) dari JSON, fallback ke default
    kalau kosong (bukan cuma kalau key hilang, biar gak kena bug yang sama
    kayak fishing_config kemarin)."""
    cfg    = load_json("spin_config.json", {})
    cost   = cfg.get("cost")   or DEFAULT_SPIN_COST
    prizes = cfg.get("prizes") or DEFAULT_SPIN_PRIZES
    return cost, prizes

def save_spin_config(cost, prizes):
    save_json("spin_config.json", {"cost": cost, "prizes": prizes})

def spin_prize_label(p: dict) -> str:
    t_ = p.get("type")
    if t_ == "rod":
        return f"🎣 Rod **{p.get('name')}**"
    if t_ == "coin":
        return f"🪙 Koin **{p.get('min')}-{p.get('max')}**"
    if t_ == "bait":
        return f"🪱 Umpan **{p.get('name')} x{p.get('qty')}**"
    return f"{emoji('trash')} {p.get('label', 'Zonk')}"

def spin_chance_lines(prizes: list) -> str:
    total = sum(max(p.get("weight", 0), 0) for p in prizes) or 1
    lines = []
    for p in prizes:
        pct = max(p.get("weight", 0), 0) / total * 100
        lines.append(f"{spin_prize_label(p)} — **{pct:.2f}%**")
    return "\n".join(lines)

def do_spin_roll() -> dict:
    """Weighted random pick 1 hadiah dari config spin wheel."""
    _, prizes = get_spin_config()
    weights = [max(p.get("weight", 0), 0.0001) for p in prizes]
    return random.choices(prizes, weights=weights, k=1)[0]

def apply_spin_prize(uid: str, prize: dict) -> str:
    """Terapkan hadiah spin ke data user, return teks hasil buat ditampilin."""
    udata = get_user_fishing(uid)
    ptype = prize.get("type")
    if ptype == "rod":
        rod_name = prize.get("name")
        owned = udata.setdefault("owned_rods", [])
        if rod_name not in owned:
            owned.append(rod_name)
        udata["rod"] = rod_name
        save_user_fishing(uid, udata)
        return f"🎉 **JACKPOT LANGKA!** Lo dapet rod **{rod_name}**! Langsung otomatis kepasang, gaskeun mancing! 🔥"
    elif ptype == "coin":
        amount = random.randint(int(prize.get("min", 0)), int(prize.get("max", 0)))
        udata["coins"] += amount
        save_user_fishing(uid, udata)
        return f"🪙 Lo dapet **{amount} koin**! Total koin lo sekarang: **{udata['coins']}** 🪙"
    elif ptype == "bait":
        bait_name = prize.get("name")
        qty       = int(prize.get("qty", 1))
        udata.setdefault("bait", {})
        udata["bait"][bait_name] = udata["bait"].get(bait_name, 0) + qty
        save_user_fishing(uid, udata)
        return f"🪱 Lo dapet **{bait_name} x{qty}**! Langsung masuk inventori umpan lo."
    else:
        label = prize.get("label", "Zonk")
        return f"{emoji('trash')} Yah, **{label}**! Gak dapet apa-apa kali ini. Coba lagi bestie!"


# ===================== TEKS BOT (id_gaul, fixed) =====================
# Semua teks bot yang bisa diterjemahkan
# Key = kode string, Value = dict per bahasa
TRANSLATIONS: dict = {
    # ── GENERAL ──────────────────────────────────────────────
    "pong": {
        "id_gaul": "🏓 Pong! Latency: `{ms}ms` | Status: {status}",
        "id":       "🏓 Pong! Latency: `{ms}ms` | Status: {status}",
        "en":      "🏓 Pong! Latency: `{ms}ms` | Status: {status}",
        "de":      "🏓 Pong! Latenz: `{ms}ms` | Status: {status}",
        "ar":      "🏓 بونج! زمن الاستجابة: `{ms}ms` | الحالة: {status}",
        "th":      "🏓 ปอง! เวลาแฝง: `{ms}ms` | สถานะ: {status}",
        "ja":      "🏓 ポン！遅延: `{ms}ms` | 状態: {status}",
    },
    "status_good": {
        "id_gaul": "🟢 Lancar",
        "id":       "🟢 Lancar",
        "en":      "🟢 Good",
        "de":      "🟢 Gut",
        "ar":      "🟢 جيد",
        "th":      "🟢 ดี",
        "ja":      "🟢 良好",
    },
    "status_slow": {
        "id_gaul": "🟡 Agak lambat",
        "id":       "🟡 Agak lambat",
        "en":      "🟡 Slightly slow",
        "de":      "🟡 Etwas langsam",
        "ar":      "🟡 بطيء قليلاً",
        "th":      "🟡 ช้าเล็กน้อย",
        "ja":      "🟡 やや遅い",
    },
    "status_bad": {
        "id_gaul": "🔴 Lambat",
        "id":       "🔴 Lambat",
        "en":      "🔴 Slow",
        "de":      "🔴 Langsam",
        "ar":      "🔴 بطيء",
        "th":      "🔴 ช้า",
        "ja":      "🔴 遅い",
    },
    # ── MAINTENANCE ──────────────────────────────────────────
    "maintenance_title": {
        "id_gaul": "🔧 Bot Sedang Maintenance",
        "id":       "🔧 Bot Sedang Maintenance",
        "en":      "🔧 Bot Under Maintenance",
        "de":      "🔧 Bot in Wartung",
        "ar":      "🔧 البوت تحت الصيانة",
        "th":      "🔧 บอตอยู่ระหว่างการบำรุงรักษา",
        "ja":      "🔧 メンテナンス中",
    },
    "maintenance_desc": {
        "id_gaul": "Bot lagi maintenance bro, sabar ya!\n\n**Alasan:** {reason}",
        "id":       "Bot lagi maintenance bro, sabar ya!\n\n**Alasan:** {reason}",
        "en":      "The bot is under maintenance, please wait!\n\n**Reason:** {reason}",
        "de":      "Der Bot wird gewartet, bitte warte!\n\n**Grund:** {reason}",
        "ar":      "البوت تحت الصيانة، يرجى الانتظار!\n\n**السبب:** {reason}",
        "th":      "บอตอยู่ระหว่างการบำรุงรักษา โปรดรอ!\n\n**เหตุผล:** {reason}",
        "ja":      "ボットはメンテナンス中です、お待ちください！\n\n**理由:** {reason}",
    },
    # ── PREMIUM GATE ─────────────────────────────────────────
    "premium_locked_title": {
        "id_gaul": "👑 Command Ini Khusus Premium!",
        "id":       "👑 Command Ini Khusus Premium!",
        "en":      "👑 This Command is Premium Only!",
        "de":      "👑 Dieser Befehl ist nur für Premium!",
        "ar":      "👑 هذا الأمر للمميزين فقط!",
        "th":      "👑 คำสั่งนี้สำหรับพรีเมียมเท่านั้น!",
        "ja":      "👑 このコマンドはプレミアム限定です！",
    },
    "premium_locked_desc": {
        "id_gaul": "Command ini **terkunci** dan hanya bisa digunakan oleh member **Premium** bro!\n\n**📦 Paket Tersedia:**\n{packages}\n\n**💳 Info Pembayaran:**\n```{payment}```\n\nKetik `dpremium` untuk order sekarang!\n✨ Upgrade dan nikmatin semua fitur eksklusif!",
        "id":       "Command ini **terkunci** dan hanya bisa digunakan oleh member **Premium** bro!\n\n**📦 Paket Tersedia:**\n{packages}\n\n**💳 Info Pembayaran:**\n```{payment}```\n\nKetik `dpremium` untuk order sekarang!\n✨ Upgrade dan nikmatin semua fitur eksklusif!",
        "en":      "This command is **locked** and only available to **Premium** members!\n\n**📦 Available Packages:**\n{packages}\n\n**💳 Payment Info:**\n```{payment}```\n\nType `dpremium` to order now!\n✨ Upgrade and enjoy all exclusive features!",
        "de":      "Dieser Befehl ist **gesperrt** und nur für **Premium**-Mitglieder verfügbar!\n\n**📦 Verfügbare Pakete:**\n{packages}\n\n**💳 Zahlungsinfo:**\n```{payment}```\n\nTippe `dpremium` um jetzt zu bestellen!\n✨ Upgrade und genieße alle exklusiven Funktionen!",
        "ar":      "هذا الأمر **مقفل** ومتاح فقط للأعضاء **المميزين**!\n\n**📦 الباقات المتاحة:**\n{packages}\n\n**💳 معلومات الدفع:**\n```{payment}```\n\nاكتب `dpremium` للطلب الآن!\n✨ قم بالترقية واستمتع بجميع الميزات الحصرية!",
        "th":      "คำสั่งนี้**ถูกล็อค**และใช้ได้เฉพาะสมาชิก**พรีเมียม**เท่านั้น!\n\n**📦 แพ็คเกจที่มี:**\n{packages}\n\n**💳 ข้อมูลการชำระเงิน:**\n```{payment}```\n\nพิมพ์ `dpremium` เพื่อสั่งซื้อตอนนี้!\n✨ อัปเกรดและเพลิดเพลินกับฟีเจอร์พิเศษทั้งหมด!",
        "ja":      "このコマンドは**ロック**されており、**プレミアム**メンバーのみ利用可能です！\n\n**📦 利用可能なパッケージ:**\n{packages}\n\n**💳 支払い情報:**\n```{payment}```\n\n`dpremium` と入力して今すぐ注文！\n✨ アップグレードして限定機能をお楽しみください！",
    },
    # ── FISHING ──────────────────────────────────────────────
    "fish_title_rare": {
        "id_gaul": "{star} {rarity} CATCH!",
        "id":       "{star} {rarity} CATCH!",
        "en":      "{star} {rarity} CATCH!",
        "de":      "{star} {rarity} FANG!",
        "ar":      "{star} صيد {rarity}!",
        "th":      "{star} จับได้ {rarity}!",
        "ja":      "{star} {rarity} ゲット！",
    },
    "fish_desc_rare": {
        "id_gaul": "**{name}** dapet ikan **LANGKA** bro!\n\n{emoji} **{fish}**\n🍀 Luck: **{luck}%**\n💰 Harga jual: **+{coins} koin**{bonus_txt} (Total: {total})\n{E_FISH} Rod: **{rod}**\n{bait_txt}",
        "id":       "**{name}** dapet ikan **LANGKA** bro!\n\n{emoji} **{fish}**\n🍀 Luck: **{luck}%**\n💰 Harga jual: **+{coins} koin**{bonus_txt} (Total: {total})\n🎣 Rod: **{rod}**\n{bait_txt}",
        "en":      "**{name}** caught a **RARE** fish!\n\n{emoji} **{fish}**\n🍀 Luck: **{luck}%**\n💰 Sell price: **+{coins} coins**{bonus_txt} (Total: {total})\n🎣 Rod: **{rod}**\n{bait_txt}",
        "de":      "**{name}** hat einen **SELTENEN** Fisch gefangen!\n\n{emoji} **{fish}**\n🍀 Glück: **{luck}%**\n💰 Verkaufspreis: **+{coins} Münzen**{bonus_txt} (Gesamt: {total})\n🎣 Angel: **{rod}**\n{bait_txt}",
        "ar":      "**{name}** اصطاد سمكة **نادرة**!\n\n{emoji} **{fish}**\n🍀 الحظ: **{luck}%**\n💰 سعر البيع: **+{coins} عملة**{bonus_txt} (المجموع: {total})\n🎣 السنارة: **{rod}**\n{bait_txt}",
        "th":      "**{name}** จับปลา**หายาก**ได้!\n\n{emoji} **{fish}**\n🍀 โชค: **{luck}%**\n💰 ราคาขาย: **+{coins} เหรียญ**{bonus_txt} (รวม: {total})\n🎣 เบ็ด: **{rod}**\n{bait_txt}",
        "ja":      "**{name}** がレアな魚をゲット！\n\n{emoji} **{fish}**\n🍀 ラック: **{luck}%**\n💰 売値: **+{coins} コイン**{bonus_txt} (合計: {total})\n🎣 ロッド: **{rod}**\n{bait_txt}",
    },
    "fish_title_normal": {
        "id_gaul": "{emoji} Hasil Mancing",
        "id":       "{emoji} Hasil Mancing",
        "en":      "{emoji} Fishing Result",
        "de":      "{emoji} Fangergebnis",
        "ar":      "{emoji} نتيجة الصيد",
        "th":      "{emoji} ผลการตกปลา",
        "ja":      "{emoji} 釣り結果",
    },
    "fish_desc_normal": {
        "id_gaul": "**{name}** dapet **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} koin{bonus_txt} (Total: {total})\n{E_FISH} Rod: {rod}\n{bait_txt}",
        "id":       "**{name}** dapet **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} koin{bonus_txt} (Total: {total})\n🎣 Rod: {rod}\n{bait_txt}",
        "en":      "**{name}** caught **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} coins{bonus_txt} (Total: {total})\n🎣 Rod: {rod}\n{bait_txt}",
        "de":      "**{name}** hat **{fish}** gefangen [{rarity}]\n🍀 Glück: {luck}%\n💰 +{coins} Münzen{bonus_txt} (Gesamt: {total})\n🎣 Angel: {rod}\n{bait_txt}",
        "ar":      "**{name}** اصطاد **{fish}** [{rarity}]\n🍀 الحظ: {luck}%\n💰 +{coins} عملة{bonus_txt} (المجموع: {total})\n🎣 السنارة: {rod}\n{bait_txt}",
        "th":      "**{name}** จับ **{fish}** [{rarity}]\n🍀 โชค: {luck}%\n💰 +{coins} เหรียญ{bonus_txt} (รวม: {total})\n🎣 เบ็ด: {rod}\n{bait_txt}",
        "ja":      "**{name}** が **{fish}** を釣った [{rarity}]\n🍀 ラック: {luck}%\n💰 +{coins} コイン{bonus_txt} (合計: {total})\n🎣 ロッド: {rod}\n{bait_txt}",
    },
    "fish_vote_bonus": {
        "id_gaul": "\n{E_VOTE} **Vote Bonus aktif! +{pct}% koin** (sisa ~{mins} mnt)",
        "id":       "\n🗳️ **Vote Bonus aktif! +{pct}% koin** (sisa ~{mins} mnt)",
        "en":      "\n🗳️ **Vote Bonus active! +{pct}% coins** (~{mins} min left)",
        "de":      "\n🗳️ **Vote-Bonus aktiv! +{pct}% Münzen** (~{mins} Min übrig)",
        "ar":      "\n🗳️ **مكافأة التصويت نشطة! +{pct}% عملة** (~{mins} دقيقة متبقية)",
        "th":      "\n🗳️ **โบนัสโหวตใช้งานอยู่! +{pct}% เหรียญ** (~{mins} นาทีที่เหลือ)",
        "ja":      "\n🗳️ **投票ボーナス有効！ +{pct}% コイン** (残り約{mins}分)",
    },
    "fish_no_bait": {
        "id_gaul": "⚠️ Tanpa umpan",
        "id":       "⚠️ Tanpa umpan",
        "en":      "⚠️ No bait used",
        "de":      "⚠️ Kein Köder verwendet",
        "ar":      "⚠️ بدون طعم",
        "th":      "⚠️ ไม่ใช้เหยื่อ",
        "ja":      "⚠️ えさなし",
    },
    "fish_bait": {
        "id_gaul": "🪱 Umpan: {bait}",
        "id":       "🪱 Umpan: {bait}",
        "en":      "🪱 Bait: {bait}",
        "de":      "🪱 Köder: {bait}",
        "ar":      "🪱 الطعم: {bait}",
        "th":      "🪱 เหยื่อ: {bait}",
        "ja":      "🪱 えさ: {bait}",
    },
    "fish_cooldown": {
        "id_gaul": "⏳ Sabar bro! **{secs} detik** lagi.",
        "id":       "⏳ Sabar bro! **{secs} detik** lagi.",
        "en":      "⏳ Wait! **{secs} seconds** more.",
        "de":      "⏳ Warte! Noch **{secs} Sekunden**.",
        "ar":      "⏳ انتظر! **{secs} ثانية** أخرى.",
        "th":      "⏳ รอก่อน! อีก **{secs} วินาที**",
        "ja":      "⏳ 待って！あと **{secs} 秒** 。",
    },
    "fish_rare_footer": {
        "id_gaul": "🎊 LUAR BIASA! Tangkapan langka!",
        "id":       "🎊 LUAR BIASA! Tangkapan langka!",
        "en":      "🎊 AMAZING! Rare catch!",
        "de":      "🎊 FANTASTISCH! Seltener Fang!",
        "ar":      "🎊 رائع! صيدة نادرة!",
        "th":      "🎊 น่าทึ่งมาก! จับปลาหายากได้!",
        "ja":      "🎊 すごい！レアな魚！",
    },
    # ── TEBAK ────────────────────────────────────────────────
    "tebak_title": {
        "id_gaul": "🧠 TEBAK-TEBAKAN NIH!",
        "id":       "🧠 TEBAK-TEBAKAN NIH!",
        "en":      "🧠 RIDDLE TIME!",
        "de":      "🧠 RÄTSELRUNDE!",
        "ar":      "🧠 وقت الألغاز!",
        "th":      "🧠 ทายปัญหา!",
        "ja":      "🧠 なぞなぞタイム！",
    },
    "tebak_desc": {
        "id_gaul": "**Soal:**\n{question}\n\n💡 Jawab di chat dengan pesan biasa! Reward: **{reward} koin**\n⚠️ Si penanya ga bisa menang ya.",
        "id":       "**Soal:**\n{question}\n\n💡 Jawab di chat dengan pesan biasa! Reward: **{reward} koin**\n⚠️ Si penanya ga bisa menang ya.",
        "en":      "**Question:**\n{question}\n\n💡 Answer in chat! Reward: **{reward} coins**\n⚠️ The asker can't win.",
        "de":      "**Frage:**\n{question}\n\n💡 Antworte im Chat! Belohnung: **{reward} Münzen**\n⚠️ Der Fragesteller kann nicht gewinnen.",
        "ar":      "**السؤال:**\n{question}\n\n💡 أجب في الدردشة! المكافأة: **{reward} عملة**\n⚠️ السائل لا يمكنه الفوز.",
        "th":      "**คำถาม:**\n{question}\n\n💡 ตอบในแชท! รางวัล: **{reward} เหรียญ**\n⚠️ ผู้ถามไม่สามารถชนะได้",
        "ja":      "**問題:**\n{question}\n\n💡 チャットで答えて！ ご褒美: **{reward} コイン**\n⚠️ 出題者は勝てません。",
    },
    "tebak_correct_title": {
        "id_gaul": "🎉 BENERRR!!!",
        "id":       "🎉 BENERRR!!!",
        "en":      "🎉 CORRECT!!!",
        "de":      "🎉 RICHTIG!!!",
        "ar":      "🎉 صحيح!!!",
        "th":      "🎉 ถูกต้อง!!!",
        "ja":      "🎉 正解！！！",
    },
    "tebak_correct_desc": {
        "id_gaul": "{praise}\n\n**{user}** jawab bener!\n💰 Dapet **+{reward} koin** cuy!\n{E_SUCCESS} Jawaban: **{answer}**\n{E_COIN} Total koin lo: **{total}**",
        "id":       "{praise}\n\n**{user}** jawab bener!\n💰 Dapet **+{reward} koin** cuy!\n✅ Jawaban: **{answer}**\n🪙 Total koin lo: **{total}**",
        "en":      "**{user}** answered correctly!\n💰 Got **+{reward} coins**!\n✅ Answer: **{answer}**\n🪙 Total coins: **{total}**",
        "de":      "**{user}** hat richtig geantwortet!\n💰 **+{reward} Münzen** erhalten!\n✅ Antwort: **{answer}**\n🪙 Gesamt: **{total}**",
        "ar":      "**{user}** أجاب بشكل صحيح!\n💰 حصل على **+{reward} عملة**!\n✅ الإجابة: **{answer}**\n🪙 الإجمالي: **{total}**",
        "th":      "**{user}** ตอบถูกต้อง!\n💰 ได้รับ **+{reward} เหรียญ**!\n✅ คำตอบ: **{answer}**\n🪙 รวม: **{total}**",
        "ja":      "**{user}** が正解！\n💰 **+{reward} コイン** 獲得！\n✅ 答え: **{answer}**\n🪙 合計: **{total}**",
    },
    "tebak_still_active": {
        "id_gaul": "⚠️ Masih ada tebakan yang belum kejawab bro! Jawab dulu yang itu.",
        "id":       "⚠️ Masih ada tebakan yang belum kejawab bro! Jawab dulu yang itu.",
        "en":      "⚠️ There's still an unanswered riddle! Answer that one first.",
        "de":      "⚠️ Es gibt noch ein unbeantwortetes Rätsel! Beantworte das zuerst.",
        "ar":      "⚠️ لا يزال هناك لغز لم تتم الإجابة عليه! أجب على ذلك أولاً.",
        "th":      "⚠️ ยังมีปริศนาที่ยังไม่ได้ตอบ! ตอบอันนั้นก่อน",
        "ja":      "⚠️ まだ未回答のなぞなぞがあります！先にそちらを答えてください。",
    },
    # ── COINS ────────────────────────────────────────────────
    "coins_title": {
        "id_gaul": "{E_COIN} Koin Lo",
        "id":       "🪙 Koin Lo",
        "en":      "🪙 Your Coins",
        "de":      "🪙 Deine Münzen",
        "ar":      "🪙 عملاتك",
        "th":      "🪙 เหรียญของคุณ",
        "ja":      "🪙 あなたのコイン",
    },
    "coins_desc": {
        "id_gaul": "**{user}** punya **{amount} koin** {E_COIN}",
        "id":       "**{user}** punya **{amount} koin** 🪙",
        "en":      "**{user}** has **{amount} coins** 🪙",
        "de":      "**{user}** hat **{amount} Münzen** 🪙",
        "ar":      "**{user}** لديه **{amount} عملة** 🪙",
        "th":      "**{user}** มี **{amount} เหรียญ** 🪙",
        "ja":      "**{user}** は **{amount} コイン** を持っています 🪙",
    },
    # ── VOTE ─────────────────────────────────────────────────
    "vote_title": {
        "id_gaul": "{E_VOTE} Vote Bot di Top.gg!",
        "id":       "🗳️ Vote Bot di Top.gg!",
        "en":      "🗳️ Vote for the Bot on Top.gg!",
        "de":      "🗳️ Stimme für den Bot auf Top.gg ab!",
        "ar":      "🗳️ صوّت للبوت على Top.gg!",
        "th":      "🗳️ โหวตบอทบน Top.gg!",
        "ja":      "🗳️ Top.gg でボットに投票！",
    },
    "vote_desc": {
        "id_gaul": "**Support bot ini dengan vote di Top.gg!** {E_STREAK}\n\n🔗 **[Klik di sini untuk Vote]({url})**\n\n**🎁 Reward Vote:**\n• **{min} - {max} koin** langsung ke saldo lo!\n• **+{pct}% bonus coin mancing** selama **{mins} menit**!\n\n**⏰ Cooldown Claim:** {cd} jam\n\nSetelah vote, ketik `dclaimvote` untuk ambil reward! 🚀",
        "id":       "**Support bot ini dengan vote di Top.gg!** 🔥\n\n🔗 **[Klik di sini untuk Vote]({url})**\n\n**🎁 Reward Vote:**\n• **{min} - {max} koin** langsung ke saldo lo!\n• **+{pct}% bonus coin mancing** selama **{mins} menit**!\n\n**⏰ Cooldown Claim:** {cd} jam\n\nSetelah vote, ketik `dclaimvote` untuk ambil reward! 🚀",
        "en":      "**Support this bot by voting on Top.gg!** 🔥\n\n🔗 **[Click here to Vote]({url})**\n\n**🎁 Vote Rewards:**\n• **{min} - {max} coins** directly to your balance!\n• **+{pct}% fishing coin bonus** for **{mins} minutes**!\n\n**⏰ Claim Cooldown:** {cd} hours\n\nAfter voting, type `dclaimvote` to claim your reward! 🚀",
        "de":      "**Unterstütze diesen Bot durch Abstimmen auf Top.gg!** 🔥\n\n🔗 **[Hier klicken zum Abstimmen]({url})**\n\n**🎁 Abstimmungsbelohnungen:**\n• **{min} - {max} Münzen** direkt auf dein Konto!\n• **+{pct}% Angel-Münzen-Bonus** für **{mins} Minuten**!\n\n**⏰ Claim-Abklingzeit:** {cd} Stunden\n\nNach dem Abstimmen tippe `dclaimvote` um deine Belohnung zu erhalten! 🚀",
        "ar":      "**ادعم هذا البوت بالتصويت على Top.gg!** 🔥\n\n🔗 **[انقر هنا للتصويت]({url})**\n\n**🎁 مكافآت التصويت:**\n• **{min} - {max} عملة** مباشرة إلى رصيدك!\n• **+{pct}% مكافأة عملة الصيد** لمدة **{mins} دقيقة**!\n\n**⏰ مهلة المطالبة:** {cd} ساعات\n\nبعد التصويت، اكتب `dclaimvote` للمطالبة بمكافأتك! 🚀",
        "th":      "**สนับสนุนบอทนี้ด้วยการโหวตบน Top.gg!** 🔥\n\n🔗 **[คลิกที่นี่เพื่อโหวต]({url})**\n\n**🎁 รางวัลโหวต:**\n• **{min} - {max} เหรียญ** ตรงไปยังยอดเงินของคุณ!\n• **+{pct}% โบนัสเหรียญตกปลา** เป็นเวลา **{mins} นาที**!\n\n**⏰ คูลดาวน์การเคลม:** {cd} ชั่วโมง\n\nหลังจากโหวต พิมพ์ `dclaimvote` เพื่อรับรางวัล! 🚀",
        "ja":      "**Top.gg でボットに投票してサポートしよう！** 🔥\n\n🔗 **[こちらをクリックして投票]({url})**\n\n**🎁 投票報酬:**\n• **{min} - {max} コイン** が即座に残高へ！\n• **+{pct}% 釣りコインボーナス** が **{mins} 分間** 有効！\n\n**⏰ クレームクールダウン:** {cd} 時間\n\n投票後、`dclaimvote` と入力して報酬を受け取ろう！ 🚀",
    },
    "vote_not_voted_title": {
        "id_gaul": "{E_FAIL} Belum Vote Bro!",
        "id":       "❌ Belum Vote Bro!",
        "en":      "❌ You Haven't Voted Yet!",
        "de":      "❌ Du hast noch nicht abgestimmt!",
        "ar":      "❌ لم تصوت بعد!",
        "th":      "❌ คุณยังไม่ได้โหวต!",
        "ja":      "❌ まだ投票していません！",
    },
    "vote_not_voted_desc": {
        "id_gaul": "Lo belum vote bot ini di Top.gg!\n\n🔗 **[Vote Sekarang di sini]({url})**\n\nSetelah vote, tunggu beberapa detik terus ketik `dclaimvote` lagi ya!",
        "id":       "Lo belum vote bot ini di Top.gg!\n\n🔗 **[Vote Sekarang di sini]({url})**\n\nSetelah vote, tunggu beberapa detik terus ketik `dclaimvote` lagi ya!",
        "en":      "You haven't voted for this bot on Top.gg yet!\n\n🔗 **[Vote Now here]({url})**\n\nAfter voting, wait a few seconds then type `dclaimvote` again!",
        "de":      "Du hast noch nicht für diesen Bot auf Top.gg abgestimmt!\n\n🔗 **[Jetzt hier abstimmen]({url})**\n\nNach dem Abstimmen warte ein paar Sekunden und tippe dann `dclaimvote` erneut!",
        "ar":      "لم تصوت لهذا البوت على Top.gg بعد!\n\n🔗 **[صوّت الآن هنا]({url})**\n\nبعد التصويت، انتظر بضع ثوانٍ ثم اكتب `dclaimvote` مرة أخرى!",
        "th":      "คุณยังไม่ได้โหวตบอทนี้บน Top.gg!\n\n🔗 **[โหวตตอนนี้ที่นี่]({url})**\n\nหลังจากโหวตแล้ว รอสักครู่แล้วพิมพ์ `dclaimvote` อีกครั้ง!",
        "ja":      "まだTop.ggでこのボットに投票していません！\n\n🔗 **[今すぐここで投票]({url})**\n\n投票後、数秒待ってから`dclaimvote`と入力してください！",
    },
    "vote_cooldown_title": {
        "id_gaul": "⏰ Cooldown Claim Vote",
        "id":       "⏰ Cooldown Claim Vote",
        "en":      "⏰ Vote Claim Cooldown",
        "de":      "⏰ Vote-Claim-Abklingzeit",
        "ar":      "⏰ مهلة المطالبة بالتصويت",
        "th":      "⏰ คูลดาวน์การเคลมโหวต",
        "ja":      "⏰ 投票クレームクールダウン",
    },
    "vote_cooldown_desc": {
        "id_gaul": "Lo udah claim vote sebelumnya bro!\n\n**Bisa claim lagi:** {next_time} WIB\n**Sisa waktu:** {hours} jam {mins} menit\n\nSabar dulu ya, reward lo udah aman! 🙏",
        "id":       "Lo udah claim vote sebelumnya bro!\n\n**Bisa claim lagi:** {next_time} WIB\n**Sisa waktu:** {hours} jam {mins} menit\n\nSabar dulu ya, reward lo udah aman! 🙏",
        "en":      "You've already claimed your vote reward!\n\n**Can claim again:** {next_time}\n**Time remaining:** {hours}h {mins}m\n\nPlease wait, your reward is safe! 🙏",
        "de":      "Du hast deine Abstimmungsbelohnung bereits beansprucht!\n\n**Kann wieder beansprucht werden:** {next_time}\n**Verbleibende Zeit:** {hours}h {mins}m\n\nBitte warte, deine Belohnung ist sicher! 🙏",
        "ar":      "لقد طالبت بمكافأة تصويتك بالفعل!\n\n**يمكن المطالبة مرة أخرى:** {next_time}\n**الوقت المتبقي:** {hours} ساعة {mins} دقيقة\n\nيرجى الانتظار، مكافأتك آمنة! 🙏",
        "th":      "คุณได้รับรางวัลโหวตแล้ว!\n\n**เคลมได้อีกครั้ง:** {next_time}\n**เวลาที่เหลือ:** {hours} ชม {mins} นาที\n\nโปรดรอ รางวัลของคุณปลอดภัย! 🙏",
        "ja":      "すでに投票報酬を受け取りました！\n\n**次回クレーム可能:** {next_time}\n**残り時間:** {hours}時間{mins}分\n\nお待ちください、報酬は安全です！ 🙏",
    },
    "vote_claimed_title": {
        "id_gaul": "🎉 REWARD VOTE DIKLAIM!",
        "id":       "🎉 REWARD VOTE DIKLAIM!",
        "en":      "🎉 VOTE REWARD CLAIMED!",
        "de":      "🎉 ABSTIMMUNGSBELOHNUNG ERHALTEN!",
        "ar":      "🎉 تم الحصول على مكافأة التصويت!",
        "th":      "🎉 ได้รับรางวัลโหวตแล้ว!",
        "ja":      "🎉 投票報酬を受け取りました！",
    },
    "vote_claimed_desc": {
        "id_gaul": "Makasih udah vote bot ini **{user}**! {E_STREAK}\n\n**💰 Koin Didapat:** +**{reward} koin**!\n**{E_COIN} Total Koin:** {total} koin\n\n**{E_FISH} Vote Bonus Fishing Aktif!**\n+**{pct}% coin** dari mancing selama **{mins} menit**\n(Aktif sampai jam **{until}**) 🚀\n\n**Total Vote Lo:** {count} kali 🏆\n\nBisa claim lagi dalam **{cd} jam**!",
        "id":       "Makasih udah vote bot ini **{user}**! 🔥\n\n**💰 Koin Didapat:** +**{reward} koin**!\n**🪙 Total Koin:** {total} koin\n\n**🎣 Vote Bonus Fishing Aktif!**\n+**{pct}% coin** dari mancing selama **{mins} menit**\n(Aktif sampai jam **{until}**) 🚀\n\n**Total Vote Lo:** {count} kali 🏆\n\nBisa claim lagi dalam **{cd} jam**!",
        "en":      "Thanks for voting **{user}**! 🔥\n\n**💰 Coins Received:** +**{reward} coins**!\n**🪙 Total Coins:** {total} coins\n\n**🎣 Vote Fishing Bonus Active!**\n+**{pct}% coins** from fishing for **{mins} minutes**\n(Active until **{until}**) 🚀\n\n**Your Total Votes:** {count} times 🏆\n\nCan claim again in **{cd} hours**!",
        "de":      "Danke für deine Stimme **{user}**! 🔥\n\n**💰 Münzen erhalten:** +**{reward} Münzen**!\n**🪙 Gesamt-Münzen:** {total} Münzen\n\n**🎣 Vote-Angel-Bonus aktiv!**\n+**{pct}% Münzen** beim Angeln für **{mins} Minuten**\n(Aktiv bis **{until}**) 🚀\n\n**Deine Gesamtabstimmungen:** {count} Mal 🏆\n\nKann wieder beansprucht werden in **{cd} Stunden**!",
        "ar":      "شكراً لتصويتك **{user}**! 🔥\n\n**💰 العملات المستلمة:** +**{reward} عملة**!\n**🪙 إجمالي العملات:** {total} عملة\n\n**🎣 مكافأة الصيد بالتصويت نشطة!**\n+**{pct}% عملات** من الصيد لمدة **{mins} دقيقة**\n(نشط حتى **{until}**) 🚀\n\n**إجمالي تصويتاتك:** {count} مرة 🏆\n\nيمكن المطالبة مرة أخرى في **{cd} ساعات**!",
        "th":      "ขอบคุณที่โหวต **{user}**! 🔥\n\n**💰 เหรียญที่ได้รับ:** +**{reward} เหรียญ**!\n**🪙 เหรียญทั้งหมด:** {total} เหรียญ\n\n**🎣 โบนัสตกปลาจากการโหวตใช้งานอยู่!**\n+**{pct}% เหรียญ** จากการตกปลาเป็นเวลา **{mins} นาที**\n(ใช้งานถึง **{until}**) 🚀\n\n**โหวตทั้งหมดของคุณ:** {count} ครั้ง 🏆\n\nเคลมได้อีกครั้งใน **{cd} ชั่วโมง**!",
        "ja":      "投票してくれてありがとう **{user}**！ 🔥\n\n**💰 獲得コイン:** +**{reward} コイン**！\n**🪙 合計コイン:** {total} コイン\n\n**🎣 投票釣りボーナス有効！**\n+**{pct}% コイン** が釣りで **{mins} 分間** 有効\n(**{until}** まで) 🚀\n\n**総投票数:** {count} 回 🏆\n\n**{cd} 時間後** に再クレーム可能！",
    },
}

# ─── Language helper (fixed bahasa, fitur setlang sudah dihapus) ─────────────
# Bot sekarang selalu pake Bahasa Indonesia gaul untuk semua user, gak ada lagi
# per-user language switching. Parameter user_id tetap diterima biar semua
# pemanggilan t() di seluruh kode lama gak perlu diubah satu-satu.

def t(key: str, user_id=None, **kwargs) -> str:
    """Ambil teks berdasarkan key. Bahasa selalu id_gaul (fixed).
    Semua teks otomatis dapet token emoji (E_COIN, E_FISH, dst) dari
    emoji_config, jadi setemoji ke-reflect di semua teks bot, bukan cuma
    yang secara eksplisit manggil emoji()."""
    entry = TRANSLATIONS.get(key, {})
    text  = entry.get("id_gaul") or entry.get("id") or entry.get("en") or key
    emoji_tokens = {
        "E_COIN": emoji('coin'), "E_FISH": emoji('fish'),
        "E_SUCCESS": emoji('success'), "E_FAIL": emoji('fail'),
        "E_QUEST": emoji('quest'), "E_DAILY": emoji('daily'),
        "E_VOTE": emoji('vote'), "E_STREAK": emoji('streak'),
        "E_LEGENDARY": emoji('legendary'), "E_RARE": emoji('rare'),
        "E_UNCOMMON": emoji('uncommon'), "E_COMMON": emoji('common'),
        "E_TRASH": emoji('trash'),
    }
    merged = {**emoji_tokens, **kwargs}
    try:
        text = text.format(**merged)
    except (KeyError, ValueError):
        pass
    return text

fishing_cooldowns   = {}
spin_cooldowns      = {}   # {uid: last_spin_timestamp} — cooldown buat dspin
SPIN_COOLDOWN_SECONDS = 5
active_tebakan      = {}   # {gid: {jawaban, reward, asker}} — sesi tebak prefix lama
arena_tebak         = {}   # {gid: ArenaSession} — sesi arena tebak baru
# vote_bonus_cache: {str(user_id): float(expire_timestamp)}
vote_bonus_cache: dict = {}

# ===================== VOTE HELPERS =====================
def get_vote_data() -> dict:
    return load_json("vote.json", {})

def save_vote_data(d: dict):
    save_json("vote.json", d)

def get_vote_record(user_id: str) -> dict:
    """Return record vote user. Keys: last_claim, last_vote_webhook."""
    data = get_vote_data()
    return data.get(str(user_id), {})

def set_vote_record(user_id: str, record: dict):
    data = get_vote_data()
    data[str(user_id)] = record
    save_vote_data(data)

def is_vote_bonus_active(user_id: str) -> bool:
    """Cek apakah user sedang dalam periode bonus vote."""
    uid = str(user_id)
    exp = vote_bonus_cache.get(uid, 0)
    return time.time() < exp

def activate_vote_bonus(user_id: str):
    """Aktifkan bonus mancing +20% selama VOTE_BONUS_MINS menit."""
    uid = str(user_id)
    vote_bonus_cache[uid] = time.time() + VOTE_BONUS_MINS * 60

def get_vote_bonus_remaining(user_id: str) -> int:
    """Return sisa detik bonus. 0 jika tidak aktif."""
    uid = str(user_id)
    exp = vote_bonus_cache.get(uid, 0)
    remaining = exp - time.time()
    return max(0, int(remaining))

async def notify_vote_dm(user_id: str):
    """DM user abis bot nerima webhook vote dari Top.gg. Ini yang tadinya
    BELUM ADA — webhook cuma nyimpen record doang, gak pernah ngirim DM."""
    try:
        user = await bot.fetch_user(int(user_id))
        await user.send(
            f"{emoji('success')} Makasih udah vote **{bot.user.name if bot.user else 'bot ini'}** di Top.gg! 🎉\n"
            f"Ketik `dclaimvote` di server buat klaim reward koin + bonus luck mancing kamu!"
        )
    except Exception as e:
        print(f"⚠️  Gagal DM user {user_id} soal vote: {e}")

async def check_user_voted_topgg(user_id: int) -> bool:
    """
    Cek via Top.gg API apakah user sudah vote.
    Return True jika sudah vote, False jika belum atau error.
    Fallback ke record webhook (persisten di vote.json, BUKAN cuma in-memory
    cache yang ilang tiap restart) kalau API gagal/gak dikonfig.
    """
    uid = str(user_id)

    if TOPGG_TOKEN and BOT_ID:
        url = f"https://top.gg/api/bots/{BOT_ID}/check?userId={user_id}"
        headers = {"Authorization": TOPGG_TOKEN}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if bool(data.get("voted", 0)):
                            return True
                    else:
                        body = await resp.text()
                        print(f"⚠️  Top.gg API respon {resp.status}: {body[:200]}")
        except Exception as e:
            print(f"⚠️  Top.gg API error: {e}")

    # Fallback: record webhook (in-memory cache ATAU vote.json persisten).
    # Top.gg vote berlaku 12 jam, jadi record webhook dianggap valid kalau
    # umurnya belum lewat itu — biar tetep kedeteksi walau bot abis restart.
    if uid in _vote_cache:
        return True
    last_webhook = get_vote_record(uid).get("last_vote_webhook", 0)
    return (time.time() - last_webhook) < 12 * 3600

# ===================== MAINTENANCE =====================
def get_maintenance() -> dict:
    return load_json("maintenance.json", {"active": False, "reason": "", "started_at": 0})

def save_maintenance(d):
    save_json("maintenance.json", d)

# ===================== PREMIUM HELPERS =====================
def is_premium(user_id: str) -> bool:
    """Cek apakah user punya premium aktif & belum expired."""
    pdata = get_premium_data()
    uid   = str(user_id)
    users = pdata.get("users", {})
    if uid not in users:
        return False
    u = users[uid]
    if not u.get("active", False):
        return False
    exp = u.get("expires_at", 0)
    if exp and time.time() > exp:
        return False
    return True

def get_premium_settings():
    return get_premium_data().get("settings", {})

def get_premium_packages() -> dict:
    """Return dict paket premium. Key = nama paket."""
    pdata = get_premium_data()
    pkgs  = pdata.get("packages", {})
    if not pkgs:
        # Default packages
        pkgs = {
            "Basic": {"price": "Rp 15.000", "duration_days": 7,  "description": "Akses 7 hari"},
            "Standard": {"price": "Rp 25.000", "duration_days": 30, "description": "Akses 30 hari"},
            "Premium": {"price": "Rp 50.000", "duration_days": 90, "description": "Akses 90 hari"},
        }
    return pkgs

def premium_required(ctx_or_interaction):
    """Cek premium, return (ok, panel_notif). Jika ok=False, kirim panel_notif ke user."""
    if isinstance(ctx_or_interaction, commands.Context):
        uid = str(ctx_or_interaction.author.id)
    else:
        uid = str(ctx_or_interaction.user.id)
    if is_premium(uid):
        return True, None
    pnl = panel(
        "👑 Fitur Premium",
        (
            "Command ini **khusus untuk member Premium** bro!\n\n"
            "Dapetin akses premium dengan ketik:\n"
            "**`dpremium`** untuk lihat paket & cara order.\n\n"
            "✨ Upgrade sekarang dan nikmatin semua fitur eksklusif!"
        ),
        color=0xFFD700,
        footer="Nikoliesamphink · Premium System"
    )
    return False, pnl

# ===================== PREMIUM COMMAND GATE =====================

def get_locked_commands() -> list:
    """Return list nama command yang dikunci premium."""
    return get_premium_data().get("locked_commands", [])

def set_locked_commands(cmds: list):
    pdata = get_premium_data()
    pdata["locked_commands"] = cmds
    save_premium_data(pdata)
    # Schedule re-sync slash commands agar deskripsi premium terupdate
    asyncio.get_event_loop().create_task(_resync_slash_descriptions())

async def _resync_slash_descriptions():
    """
    Update deskripsi slash command yang bisa dikunci premium,
    lalu re-sync tree ke Discord agar label 👑 Premium muncul/hilang secara otomatis.
    Kalau command tidak dikunci, deskripsi dikembalikan ke aslinya (tanpa label apapun).
    """
    # Mapping: nama command → deskripsi asli (tanpa suffix apapun)
    _PREMIUM_COMMANDS_DESC = {
        "fish":         "Mulai mancing!",
        "tebak":        "Buka Arena Tebak-Tebakan!",
        "coins":        "Cek koin lo",
        "giveaway":     "Mulai giveaway!",
        "reactionrole": "Setup reaction role dengan button",
        "leaderboard":  "Lihat leaderboard koin terbanyak",
        "tambahsoal":   "Tambah soal untuk Arena Tebak yang sedang aktif (host/admin only)",
        "daily":        "Klaim koin harian",
        "quest":        "Lihat progress quest mancing lo",
    }
    locked = get_locked_commands()
    for cmd in tree.get_commands():
        if cmd.name in _PREMIUM_COMMANDS_DESC:
            base = _PREMIUM_COMMANDS_DESC[cmd.name]
            if cmd.name in locked:
                cmd.description = base + " | 👑 Premium"
            else:
                cmd.description = base  # kembalikan ke deskripsi asli
    try:
        await tree.sync()
        print(f"✅ Slash commands re-synced (premium label updated)")
    except Exception as e:
        print(f"⚠️ Re-sync slash error: {e}")



def premium_block_panel(user_id=None, command_name: str = "") -> "StartDoomPanel":
    """Panel Components V2 notifikasi command terkunci premium — tampilan profesional."""
    uid      = user_id or 0
    pdata    = get_premium_data()
    pkgs     = get_premium_packages()
    qris_url = pdata.get("settings", {}).get("qris_url", "")

    # Build paket lines singkat
    pkg_lines = []
    badges    = ["🥉", "🥈", "🥇"]
    for i, (k, v) in enumerate(pkgs.items()):
        badge = badges[i] if i < len(badges) else "👑"
        pkg_lines.append(f"{badge} **{k}** — {v['price']} · {v['duration_days']} days")
    pkg_text = "\n".join(pkg_lines) if pkg_lines else "No packages available."

    desc = (
        "This command is **locked** and only available to **Premium** members.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "**📦 Available Packages**\n"
        f"{pkg_text}\n\n"
        "Type `dpremium` to see full details & order now!\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ Unlock all exclusive features by upgrading to Premium."
    )
    footer = f"Nikoliesamphink · Premium · Command `{command_name}` is locked" if command_name else "Nikoliesamphink · Premium System"
    return panel("🔒 Premium Feature", desc, color=0xFFD700,
                 thumbnail_url=qris_url or None, footer=footer)


async def check_premium_gate(ctx, command_name: str) -> bool:
    """
    Cek apakah command ini dikunci premium.
    Return True = BLOCKED (user tidak premium & command terkunci).
    Return False = BOLEH LANJUT.
    Hanya OWNER BOT yang bypass — admin server biasa tetap kena gate.
    """
    # Hanya OWNER BOT yang bypass, BUKAN admin server
    if ctx.author.id == OWNER_ID:
        return False

    locked = get_locked_commands()
    if command_name not in locked:
        return False  # command ini bebas, lanjut

    if is_premium(str(ctx.author.id)):
        return False  # user premium, lanjut

    # Blocked — user belum premium
    # Tampilkan panel premium dengan nama command yang dikunci
    await ctx.reply(view=premium_block_panel(ctx.author.id, command_name))
    return True

async def check_premium_gate_slash(interaction: discord.Interaction, command_name: str) -> bool:
    """
    Versi slash command untuk check_premium_gate.
    Return True = BLOCKED.
    Hanya OWNER BOT yang bypass.
    """
    if interaction.user.id == OWNER_ID:
        return False

    locked = get_locked_commands()
    if command_name not in locked:
        return False

    if is_premium(str(interaction.user.id)):
        return False

    await interaction.response.send_message(view=premium_block_panel(interaction.user.id, f"/{command_name}"), ephemeral=True)
    return True

# ===================== MAINTENANCE CHECK =====================
async def check_maintenance(ctx) -> bool:
    """Return True jika maintenance aktif (dan bot tidak boleh respon)."""
    maint = get_maintenance()
    if not maint.get("active", False):
        return False
    if ctx.author.id == OWNER_ID:
        return False  # owner tetap bisa pakai bot
    uid_m = ctx.author.id
    await ctx.reply(view=panel(
        t("maintenance_title", uid_m),
        t("maintenance_desc", uid_m, reason=maint.get("reason", "-")),
        color=0xFF6600
    ))
    return True

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} udah nyala bro!")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="StartDoom | dhelp")
    )
    try:
        synced = await tree.sync()
        print(f"✅ {len(synced)} slash commands synced!")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    check_giveaways.start()
    check_sticky.start()
    # Jalankan webhook server Top.gg vote
    asyncio.create_task(run_flask_webhook())
    # Jalankan webhook server Top.gg vote

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # ===== HANDLER MANUAL: !Kingdoom commands =====
    cs = message.content.strip()
    cl = cs.lower()
    if cl.startswith("!kingdoom "):
        if message.guild:
            is_owner = message.author.id == OWNER_ID
            if is_owner:
                sub = cl[len("!kingdoom "):].strip()
                ctx = await bot.get_context(message)
                if sub == "premium":
                    await premium_setup_panel(ctx)
                elif sub == "setfishing":
                    await fishing_setup_panel(ctx)
                elif sub == "spinwheel":
                    await spinwheel_setup_panel(ctx)
                elif sub == "maintenance":
                    await maintenance_panel(ctx)
                else:
                    await ctx.send(view=panel(
                        "⚙️ Kingdoom Control Panel",
                        "**Subcommand tersedia:**\n"
                        "• `!Kingdoom premium` — Setup sistem premium\n"
                        "• `!Kingdoom setfishing` — Setup fishing\n"
                        "• `!Kingdoom spinwheel` — Setup spin wheel (hadiah rod/koin/umpan + harga)\n"
                        "• `!Kingdoom maintenance` — Toggle maintenance\n\n"
                        "*Panel ini hanya bisa diakses owner/admin.*"
                    ))
                try:
                    await message.delete()
                except:
                    pass
        return
    # ==============================================

    guild_id    = str(message.guild.id) if message.guild else None
    content_lower = message.content.lower()

    # ===== NO-PREFIX SYSTEM =====
    # User yang di-grant akses "no prefix" oleh owner (atau owner sendiri) bisa
    # ketik nama command langsung tanpa "d" di depannya.
    if message.guild and message.content and not message.content.startswith("!"):
        if is_noprefix_user(message.author.id):
            first_word = message.content.strip().split(" ")[0].lower()
            if first_word in get_all_command_names():
                fake_message = copy.copy(message)
                fake_message.content = f"d{message.content.strip()}"
                await bot.process_commands(fake_message)
                return

    # Auto response
    if guild_id:
        ar = get_autoresponse()
        if guild_id in ar:
            for trigger, response in ar[guild_id].items():
                if trigger.lower() in content_lower:
                    await message.channel.send(response)
                    break

    # ── ARENA TEBAK: cek jawaban ronde aktif ──────────────────────────────────
    if guild_id and guild_id in arena_tebak:
        sess = arena_tebak[guild_id]
        if sess.phase == "soal" and sess.current_soal and message.author.id in sess.peserta:
            if message.author.id not in sess.answered_this_ronde:
                jawaban_target = sess.current_soal["jawaban"].lower().strip()
                pesan_clean    = re.sub(r'[^\w\s]', '', message.content.lower()).strip()
                if jawaban_target in pesan_clean or pesan_clean == jawaban_target:
                    reward = sess.current_soal.get("reward", 25)
                    sess.answered_this_ronde.add(message.author.id)
                    sess.skor[message.author.id] = sess.skor.get(message.author.id, 0) + reward
                    # Tambah ke koin fishing juga
                    udata_a = get_user_fishing(str(message.author.id))
                    udata_a["coins"] += reward
                    save_user_fishing(str(message.author.id), udata_a)
                    em_ok = discord.Embed(
                        title="✅ Jawaban Benar!",
                        description=(
                            f"**{message.author.display_name}** menjawab dengan benar!\n"
                            f"💰 +**{reward} koin** | Total Arena: **{sess.skor[message.author.id]} koin**"
                        ),
                        color=0x00FF88
                    )
                    await message.channel.send(embed=em_ok)

    # Tebak-tebakan answer check — deteksi teks biasa mengandung jawaban
    if guild_id and guild_id in active_tebakan:
        tb = active_tebakan[guild_id]
        if message.author.id != tb["asker"]:
            jawaban_target = tb["jawaban"].lower().strip()
            pesan_clean    = re.sub(r'[^\w\s]', '', message.content.lower()).strip()
            # Cek apakah jawaban ada sebagai kata/frase dalam pesan
            if jawaban_target in pesan_clean or pesan_clean == jawaban_target:
                udata  = get_user_fishing(str(message.author.id))
                reward = tb["reward"]
                udata["coins"] += reward
                save_user_fishing(str(message.author.id), udata)
                uid_w = message.author.id
                praise = random.choice(JAWABAN_BENAR_GAUL)
                desc   = t("tebak_correct_desc", uid_w,
                            praise=praise, user=message.author.display_name,
                            reward=reward, answer=tb["jawaban"].title(), total=udata["coins"])
                await message.channel.send(view=panel(
                    t("tebak_correct_title", uid_w), desc,
                    thumbnail_url=str(message.author.display_avatar.url)
                ))
                del active_tebakan[guild_id]

    # Sticky message
    if guild_id:
        sticky_data = get_sticky()
        ch_id = str(message.channel.id)
        if guild_id in sticky_data and ch_id in sticky_data[guild_id]:
            s = sticky_data[guild_id][ch_id]
            s["count"] = s.get("count", 0) + 1
            if s["count"] >= s.get("min_messages", 3):
                s["count"] = 0
                try:
                    old_id = s.get("last_message_id")
                    if old_id:
                        try:
                            old_msg = await message.channel.fetch_message(old_id)
                            await old_msg.delete()
                        except:
                            pass
                    sent = await message.channel.send(view=panel("📌 Sticky Message", s["content"]))
                    s["last_message_id"] = sent.id
                except:
                    pass
            sticky_data[guild_id][ch_id] = s
            save_sticky(sticky_data)

    await bot.process_commands(message)

# ===================== TASKS =====================
@tasks.loop(seconds=30)
async def check_giveaways():
    gw_data = get_giveaways()
    now     = time.time()
    for gid in list(gw_data.keys()):
        for msg_id in list(gw_data[gid].keys()):
            gw = gw_data[gid][msg_id]
            if gw.get("ended"):
                continue
            if now >= gw["end_time"]:
                guild = bot.get_guild(int(gid))
                if not guild:
                    continue
                ch = guild.get_channel(int(gw["channel_id"]))
                if not ch:
                    continue
                try:
                    msg      = await ch.fetch_message(int(msg_id))
                    reaction = discord.utils.get(msg.reactions, emoji="🎉")
                    users    = []
                    if reaction:
                        async for u in reaction.users():
                            if not u.bot:
                                users.append(u)
                    if users:
                        winner = random.choice(users)
                        em = dark_red_embed(
                            "🎉 GIVEAWAY SELESAI!",
                            f"**Hadiah:** {gw['prize']}\n**Pemenang:** {winner.mention}\nSelamat ya bestie! 🥳"
                        )
                        await ch.send(embed=em)
                    else:
                        await ch.send("😢 Gak ada yang ikut giveaway, hadiahnya disimpen aja deh...")
                    gw_data[gid][msg_id]["ended"] = True
                except:
                    pass
    save_giveaways(gw_data)

@tasks.loop(seconds=60)
async def check_sticky():
    pass

# ===================== VIEWS =====================

# ===================== ARENA TEBAK-TEBAKAN =====================

class ArenaSession:
    """Menyimpan state satu sesi Arena Tebak per guild."""
    def __init__(self, host_id: int, max_ronde: int, taunt_text: str, loser_role_id: int | None):
        self.host_id      = host_id
        self.max_ronde    = max_ronde        # 1-30
        self.taunt_text   = taunt_text       # kalimat menyindir
        self.loser_role_id= loser_role_id    # role yang dikasih ke yang kalah/ga jawab
        self.ronde        = 0
        self.soal_list    : list  = []       # list soal yg sudah diset host
        self.peserta      : set   = set()    # user_id yang join
        self.skor         : dict  = {}       # {user_id: int}
        self.phase        = "lobby"          # lobby | soal | selesai
        self.current_soal : dict | None = None  # {soal, jawaban, reward}
        self.answered_this_ronde: set = set()
        self.lobby_message_id : int | None = None
        self.soal_message_id  : int | None = None
        self.channel_id       : int | None = None

class ArenaLobbyView(discord.ui.View):
    """View lobby sebelum arena dimulai."""
    def __init__(self, gid: str, host_id: int):
        super().__init__(timeout=300)
        self.gid     = gid
        self.host_id = host_id

    @discord.ui.button(label="🙋 Join Arena", style=discord.ButtonStyle.success, custom_id="arena_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = arena_tebak.get(self.gid)
        if not sess or sess.phase != "lobby":
            await interaction.response.send_message("❌ Arena sudah tidak aktif!", ephemeral=True)
            return
        sess.peserta.add(interaction.user.id)
        sess.skor.setdefault(interaction.user.id, 0)
        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** berhasil join arena! Total peserta: **{len(sess.peserta)}**",
            ephemeral=True
        )

    @discord.ui.button(label="▶️ Mulai Arena", style=discord.ButtonStyle.danger, custom_id="arena_start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = arena_tebak.get(self.gid)
        if not sess or sess.phase != "lobby":
            await interaction.response.send_message("❌ Arena tidak aktif!", ephemeral=True)
            return
        if interaction.user.id != self.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Hanya host atau admin yang bisa mulai arena!", ephemeral=True)
            return
        if len(sess.peserta) < 1:
            await interaction.response.send_message("❌ Minimal 1 peserta dulu bro!", ephemeral=True)
            return
        if not sess.soal_list:
            await interaction.response.send_message("❌ Belum ada soal! Host harus tambah soal dulu via `/tambahsoal`.", ephemeral=True)
            return
        sess.phase = "soal"
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🏟️ Arena Dimulai!",
                description=f"**{len(sess.peserta)} peserta** siap bertanding!\nRonde pertama dimulai sekarang...",
                color=0xFF4500
            ),
            view=self
        )
        await asyncio.sleep(2)
        await _arena_next_ronde(interaction.channel, self.gid)

    @discord.ui.button(label="❌ Batalkan", style=discord.ButtonStyle.secondary, custom_id="arena_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = arena_tebak.get(self.gid)
        if not sess:
            await interaction.response.send_message("❌ Tidak ada arena aktif!", ephemeral=True)
            return
        if interaction.user.id != self.host_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Hanya host atau admin yang bisa batalkan!", ephemeral=True)
            return
        arena_tebak.pop(self.gid, None)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ Arena Dibatalkan", description="Arena tebak-tebakan dibatalkan.", color=0x888888),
            view=self
        )

async def _arena_next_ronde(channel: discord.TextChannel, gid: str):
    """Lanjut ke ronde berikutnya atau akhiri arena."""
    sess = arena_tebak.get(gid)
    if not sess:
        return

    if sess.ronde >= sess.max_ronde or not sess.soal_list:
        await _arena_selesai(channel, gid)
        return

    sess.ronde += 1
    sess.current_soal     = sess.soal_list.pop(0)
    sess.answered_this_ronde = set()

    soal_text  = sess.current_soal["soal"]
    reward     = sess.current_soal.get("reward", 25)
    total_soal = sess.ronde + len(sess.soal_list)

    em = discord.Embed(
        title=f"🧠 Ronde {sess.ronde}/{sess.max_ronde} — Tebak-Tebakan Arena!",
        description=(
            f"**Soal:**\n{soal_text}\n\n"
            f"💰 Reward jawaban benar: **{reward} koin**\n"
            f"💡 Ketik jawaban langsung di chat!\n"
            f"⏰ Waktu: **30 detik**"
        ),
        color=0xFF4500
    )
    em.set_footer(text=f"Peserta: {len(sess.peserta)} | Soal sisa: {len(sess.soal_list)}")
    em.timestamp = datetime.datetime.now(tz=WIB)
    msg = await channel.send(embed=em)
    sess.soal_message_id = msg.id

    # Tunggu 30 detik jawaban masuk (ditangani on_message)
    await asyncio.sleep(30)

    # Setelah 30 detik — cek siapa yang tidak jawab dan kasih taunt + role
    sess_now = arena_tebak.get(gid)
    if not sess_now or sess_now.phase != "soal":
        return

    belum_jawab = sess_now.peserta - sess_now.answered_this_ronde
    taunt_lines = ""
    if belum_jawab and sess_now.taunt_text:
        names = []
        for uid in belum_jawab:
            member = channel.guild.get_member(uid)
            if member:
                names.append(member.mention)
                # Kasih loser role kalau diset
                if sess_now.loser_role_id:
                    role = channel.guild.get_role(sess_now.loser_role_id)
                    if role:
                        try:
                            await member.add_roles(role)
                        except:
                            pass
        if names:
            taunt_lines = f"\n\n😂 **{sess_now.taunt_text}**\n{' '.join(names)}"

    jawaban = sess_now.current_soal["jawaban"]
    em_result = discord.Embed(
        title=f"⏰ Waktu Habis! — Ronde {sess_now.ronde}",
        description=(
            f"✅ **Jawaban:** `{jawaban}`{taunt_lines}"
        ),
        color=0xFF6600
    )
    await channel.send(embed=em_result)
    await asyncio.sleep(3)
    await _arena_next_ronde(channel, gid)

async def _arena_selesai(channel: discord.TextChannel, gid: str):
    """Tampilkan hasil akhir arena dan bersihkan sesi."""
    sess = arena_tebak.pop(gid, None)
    if not sess:
        return

    # Sort skor
    sorted_skor = sorted(sess.skor.items(), key=lambda x: x[1], reverse=True)
    podium_emoji = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, skor) in enumerate(sorted_skor[:10]):
        member = channel.guild.get_member(uid)
        name   = member.display_name if member else f"User {uid}"
        medal  = podium_emoji[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} **{name}** — {skor} koin")

    winner_mention = ""
    if sorted_skor:
        w = channel.guild.get_member(sorted_skor[0][0])
        if w:
            winner_mention = f"\n\n🎉 **Pemenang: {w.mention}!** 🎉"

    em = discord.Embed(
        title="🏆 Arena Selesai! — Hasil Akhir",
        description="\n".join(lines) + winner_mention if lines else "Tidak ada skor tercatat.",
        color=0xFFD700
    )
    em.set_footer(text=f"Total Ronde: {sess.ronde} | Total Peserta: {len(sess.peserta)}")
    em.timestamp = datetime.datetime.now(tz=WIB)
    await channel.send(embed=em)


class ReactionRoleView(discord.ui.LayoutView):
    def __init__(self, roles_config, title: str = "🎭 Reaction Role", description: str = "Klik tombol buat ambil/lepas role!"):
        super().__init__(timeout=None)
        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(f"### {title}\n{description}"))
        container.add_item(discord.ui.Separator())
        row = discord.ui.ActionRow()
        for cfg in roles_config:
            btn = discord.ui.Button(
                label=cfg["label"], emoji=cfg.get("emoji"),
                style=discord.ButtonStyle.danger,
                custom_id=f"rr_{cfg['role_id']}"
            )
            btn.callback = self.toggle_role
            row.add_item(btn)
        container.add_item(row)
        self.add_item(container)

    async def toggle_role(self, interaction: discord.Interaction):
        role_id = int(interaction.data["custom_id"].split("_")[1])
        role    = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("❌ Role gak ketemu bro!", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Role **{role.name}** dicopot dari lo!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Role **{role.name}** berhasil dapet!", ephemeral=True)

# ===================== FISHING VIEWS =====================

# ===================== MANUAL SELL FISH =====================
# Sekarang ikan hasil mancing GAK auto-sell — numpuk dulu di inventori,
# baru dikonversi jadi koin lewat tombol "Jual" di panel Inventori.

def _fish_sell_price(fish_name: str) -> int:
    fishes, _, _ = get_fishing_config()
    for f in fishes:
        if f["name"] == fish_name:
            return f.get("sell_price", 0)
    return 0

def sell_all_fish(uid: str) -> dict:
    """Jual SEMUA ikan di inventori user. Return {count, total}."""
    udata = get_user_fishing(uid)
    inv   = udata.get("inventory", [])
    if not inv:
        return {"count": 0, "total": 0}
    vote_active = is_vote_bonus_active(uid)
    total = 0
    for name in inv:
        base  = _fish_sell_price(name)
        bonus = int(base * VOTE_BONUS_PCTS / 100) if vote_active else 0
        total += base + bonus
    count = len(inv)
    udata["coins"] += total
    udata["inventory"] = []
    save_user_fishing(uid, udata)
    bump_checklist(uid, "sell", count)
    bump_weekly(uid, "sell", count)
    return {"count": count, "total": total}

def sell_fish_type(uid: str, fish_name: str) -> dict:
    """Jual semua ikan dari SATU jenis tertentu di inventori. Return {count, total}."""
    udata = get_user_fishing(uid)
    inv   = udata.get("inventory", [])
    count = inv.count(fish_name)
    if count == 0:
        return {"count": 0, "total": 0}
    vote_active = is_vote_bonus_active(uid)
    base  = _fish_sell_price(fish_name)
    bonus = int(base * VOTE_BONUS_PCTS / 100) if vote_active else 0
    total = (base + bonus) * count
    udata["inventory"] = [x for x in inv if x != fish_name]
    udata["coins"] += total
    save_user_fishing(uid, udata)
    bump_checklist(uid, "sell", count)
    bump_weekly(uid, "sell", count)
    return {"count": count, "total": total}


class SellFishSelect(discord.ui.Select):
    """Dropdown buat jual 1 jenis ikan tertentu dari inventori."""
    def __init__(self, user_id: int, inv_count: dict):
        options = [
            discord.SelectOption(label=f"{name} (x{qty})", value=name,
                                  description=f"Jual semua {name} — {_fish_sell_price(name)} 🪙/ekor")
            for name, qty in list(inv_count.items())[:25]
        ]
        super().__init__(placeholder="Pilih ikan buat dijual...", options=options, row=1)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        result = sell_fish_type(str(self.user_id), self.values[0])
        await interaction.response.edit_message(
            view=InventoryView(self.user_id,
                note=f"✅ Terjual **{result['count']}x {self.values[0]}** → +**{result['total']}** 🪙!")
        )


class InventoryView(discord.ui.LayoutView):
    """Panel inventori + tombol/dropdown buat jual ikan (sistem manual sell)
    + tombol Equipment, Tempa, Koleksi, dan buka Lootbox/Crate."""
    def __init__(self, user_id: int, note: str | None = None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.note    = note
        self._build()

    def _build(self):
        self.clear_items()
        udata     = get_user_fishing(str(self.user_id))
        inv       = udata.get("inventory", [])
        inv_count = {}
        for item in inv:
            inv_count[item] = inv_count.get(item, 0) + 1
        est_total  = sum(_fish_sell_price(n) * q for n, q in inv_count.items())
        coin_e     = emoji('coin')
        inv_text   = "\n".join([f"• {k} `x{v}` — ~{_fish_sell_price(k) * v} {coin_e}" for k, v in inv_count.items()]) if inv_count else "_Inventori kosong, ayo mancing dulu!_"
        bait_text  = "\n".join([f"• {k} `x{v}`" for k, v in udata.get('bait', {}).items()]) or "_Habis!_"
        n_rods     = len(udata.get("owned_rods") or [udata.get("rod", "-")])
        _, cur_rods, cur_baits = get_fishing_config()
        rod_info   = next((r for r in cur_rods if r["name"] == udata["rod"]), {})
        rod_emoji  = rod_info.get("emoji") or emoji('fish')
        eq_bait    = udata.get("equipped_bait")
        bait_info  = next((b for b in cur_baits if b["name"] == eq_bait), {}) if eq_bait else {}
        bait_emoji = bait_info.get("emoji") or "🪱"
        n_lootbox  = udata.get("lootbox", 0)
        n_crate    = udata.get("crate", 0)
        n_material = udata.get("materials", 0)
        n_dex      = len(udata.get("fish_dex", []))

        desc = (
            f"### 🎒 Inventori\n"
            f"**{coin_e} Koin:** {udata['coins']} | **Total Tangkapan:** {udata['total_catch']} | **Koleksi:** {n_dex} jenis\n"
            f"**{rod_emoji} Rod dipakai:** {udata['rod']} _(punya {n_rods} rod)_ | "
            f"**{bait_emoji} Umpan dipakai:** {eq_bait or '-'}\n"
            f"**{MATERIAL_EMOJI} {MATERIAL_NAME}:** {n_material} | **📦 Lootbox:** {n_lootbox} | **🗃️ Crate:** {n_crate}"
        )
        if self.note:
            desc = f"{self.note}\n\n{desc}"

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(desc))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**🐟 Ikan** _(belum dijual, estimasi total: {est_total} {coin_e})_\n{inv_text}"
        ))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.TextDisplay(f"**🪱 Umpan dimiliki**\n{bait_text}"))
        container.add_item(discord.ui.Separator())

        row1 = discord.ui.ActionRow()
        equip_btn = discord.ui.Button(label="Equipment", emoji="⚔️", style=discord.ButtonStyle.primary)
        tempa_btn = discord.ui.Button(label="Tempa Rod", emoji="🔨", style=discord.ButtonStyle.primary)
        dex_btn   = discord.ui.Button(label="Koleksi", emoji="📖", style=discord.ButtonStyle.secondary)
        equip_btn.callback = self.open_equipment
        tempa_btn.callback = self.open_tempa
        dex_btn.callback    = self.open_collection
        row1.add_item(equip_btn)
        row1.add_item(tempa_btn)
        row1.add_item(dex_btn)
        container.add_item(row1)

        row2 = discord.ui.ActionRow()
        has_row2 = False
        if inv_count:
            sell_all_btn = discord.ui.Button(label="Jual Semua Ikan", emoji=coin_e, style=discord.ButtonStyle.success)
            sell_all_btn.callback = self.sell_all
            row2.add_item(sell_all_btn)
            has_row2 = True
        if n_lootbox > 0:
            lb_btn = discord.ui.Button(label=f"Buka Lootbox ({n_lootbox})", emoji="📦", style=discord.ButtonStyle.success)
            lb_btn.callback = self.open_lootbox_btn
            row2.add_item(lb_btn)
            has_row2 = True
        if n_crate > 0:
            cr_btn = discord.ui.Button(label=f"Buka Crate ({n_crate})", emoji="🗃️", style=discord.ButtonStyle.success)
            cr_btn.callback = self.open_crate_btn
            row2.add_item(cr_btn)
            has_row2 = True
        if has_row2:
            container.add_item(row2)

        if inv_count:
            # Select HARUS dibungkus ActionRow, gak boleh nempel langsung ke
            # Container/View Components V2 (Discord nolak dengan error 400
            # "components.X: type must be one of (1,9,10,12,13,14,17)").
            container.add_item(discord.ui.ActionRow(SellFishSelect(self.user_id, inv_count)))
        self.add_item(container)

    async def open_equipment(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        await interaction.response.send_message(view=EquipmentView(self.user_id), ephemeral=True)

    async def open_tempa(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        await interaction.response.send_message(view=TempaView(self.user_id), ephemeral=True)

    async def open_collection(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        await interaction.response.send_message(view=CollectionView(self.user_id, interaction.user), ephemeral=True)

    async def open_lootbox_btn(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        result = open_lootbox(str(self.user_id))
        self.note = f"📦 {result['msg']}"
        self._build()
        await interaction.response.edit_message(view=self)

    async def open_crate_btn(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        result = open_crate(str(self.user_id))
        self.note = f"🗃️ {result['msg']}"
        self._build()
        await interaction.response.edit_message(view=self)

    async def sell_all(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        result = sell_all_fish(str(self.user_id))
        if result["count"] == 0:
            await interaction.response.send_message("⚠️ Inventori ikan lo udah kosong!", ephemeral=True)
            return
        self.note = f"{emoji('success')} Terjual **{result['count']}x ikan** → +**{result['total']}** {emoji('coin')}!"
        self._build()
        await interaction.response.edit_message(view=self)


class FishingMainView(discord.ui.LayoutView):
    """Panel utama fishing, full Components V2 (Container + TextDisplay + ActionRow)."""
    def __init__(self, user_id, body_text: str | None = None):
        super().__init__(timeout=120)
        self.user_id  = user_id
        self.body_text = body_text or f"Hey <@{user_id}>! Choose your action:"
        self.last_catch = None  # (fish_dict, rarity) — dipakai buat render thumbnail
        self._build()

    def _thumb_url(self):
        """URL gambar buat thumbnail tangkapan terakhir, prioritas:
        1. Emoji custom IKAN itu sendiri (di-set lewat dsetfishing → Edit Ikan)
        2. Emoji custom RARITY (di-set lewat dsetemoji)
        3. None (berarti pakai card generate fallback)"""
        if not self.last_catch:
            return None
        caught, rarity = self.last_catch
        return parse_emoji_image_url(caught.get("emoji")) or get_emoji_thumbnail_url(rarity)

    def _render_catch_file(self):
        """Generate thumbnail PNG FALLBACK doang — cuma dipake kalau ikannya
        DAN rarity-nya masih pakai emoji unicode default (belum ada yang
        di-custom). Kalau salah satunya udah custom, itu yang dipakai
        langsung (lihat _thumb_url), bukan gambar buatan sendiri."""
        if not self.last_catch or self._thumb_url():
            return None
        caught, rarity = self.last_catch
        buf = render_catch_thumbnail(caught["name"], rarity)
        return discord.File(buf, filename="catch.png")

    def _build(self):
        self.clear_items()
        container = discord.ui.Container(accent_colour=DARK_RED)
        header_text = f"### {emoji('fish')} StartDoom Fishing\n{self.body_text}"
        if self.last_catch:
            # Ada tangkapan terakhir → tampilin thumbnail-nya (lihat prioritas
            # di _thumb_url: emoji ikan itu sendiri > emoji rarity > card generate).
            thumb_src = self._thumb_url() or "attachment://catch.png"
            container.add_item(discord.ui.Section(
                discord.ui.TextDisplay(header_text),
                accessory=discord.ui.Thumbnail(thumb_src)
            ))
        else:
            container.add_item(discord.ui.TextDisplay(header_text))
        container.add_item(discord.ui.Separator())

        fish_btn = discord.ui.Button(label="Mancing", emoji=emoji('fish'), style=discord.ButtonStyle.danger)
        inv_btn  = discord.ui.Button(label="Inventori", emoji="🎒", style=discord.ButtonStyle.secondary)
        shop_btn = discord.ui.Button(label="Shop", emoji="🏪", style=discord.ButtonStyle.primary)
        fish_btn.callback = self.fish
        inv_btn.callback  = self.inventory
        shop_btn.callback = self.shop

        row = discord.ui.ActionRow()
        row.add_item(fish_btn)
        row.add_item(inv_btn)
        row.add_item(shop_btn)
        container.add_item(row)

        self.add_item(container)

    async def fish(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ini bukan mancing lo bro!", ephemeral=True)
            return
        now = time.time()
        uid = str(interaction.user.id)
        if uid in fishing_cooldowns and now - fishing_cooldowns[uid] < 10:
            sisa = round(10 - (now - fishing_cooldowns[uid]))
            await interaction.response.send_message(
                t("fish_cooldown", interaction.user.id, secs=sisa), ephemeral=True)
            # Notif otomatis ilang sendiri sesuai sisa detik cooldown-nya
            async def _auto_dismiss(delay: float):
                await asyncio.sleep(delay)
                try:
                    await interaction.delete_original_response()
                except Exception:
                    pass
            asyncio.create_task(_auto_dismiss(max(sisa, 1)))
            return
        fishing_cooldowns[uid] = now
        udata = get_user_fishing(uid)

        # Pakai umpan yang di-equip dulu (dari panel Equipment), fallback ke
        # umpan pertama yang tersedia kalau belum equip / stoknya udah habis.
        bait_list = udata.get("bait", {})
        used_bait = None
        equipped  = udata.get("equipped_bait")
        if equipped and bait_list.get(equipped, 0) > 0:
            bait_list[equipped] -= 1
            if bait_list[equipped] <= 0:
                del bait_list[equipped]
                udata["equipped_bait"] = None  # stok habis, auto-unequip
            used_bait = equipped
        else:
            for bname, qty in list(bait_list.items()):
                if qty > 0:
                    bait_list[bname] -= 1
                    if bait_list[bname] <= 0:
                        del bait_list[bname]
                    used_bait = bname
                    break
        udata["bait"] = bait_list

        # Total bonus luck EXTRA di luar base rod/bait (yang udah dihandle
        # sendiri di do_fish_roll): level Tempa rod + luck boost lootbox aktif.
        tempa_bonus = get_rod_tempa_bonus(udata, udata.get("rod", "Pancing Bambu"))
        boost_pct = 0.0
        if udata.get("luck_boost_catches", 0) > 0:
            boost_pct = udata.get("luck_boost_pct", 0)
            udata["luck_boost_catches"] -= 1
            if udata["luck_boost_catches"] <= 0:
                udata.pop("luck_boost_catches", None)
                udata.pop("luck_boost_pct", None)

        caught, rarity = do_fish_roll(udata.get("rod", "Pancing Bambu"), used_bait,
                                       extra_luck_pct=tempa_bonus + boost_pct)
        # Ikan GAK auto-sell lagi — numpuk di inventori, dijual manual lewat
        # tombol "Jual" di panel Inventori (lihat InventoryView / sell_all_fish).
        udata["total_catch"] += 1
        udata["inventory"].append(caught["name"])
        is_new_dex = caught["name"] not in udata.get("fish_dex", [])
        if is_new_dex:
            udata.setdefault("fish_dex", []).append(caught["name"])
        save_user_fishing(uid, udata)
        drop_msgs = roll_fishing_drops(uid)
        bump_checklist(uid, "fish", 1)
        bump_weekly(uid, "fish", 1)

        rarity_label, _ = get_rarity_display(rarity)
        luck_pct  = caught.get("luck", 0)
        uid_fish  = interaction.user.id
        est_price = _fish_sell_price(caught["name"])

        # Ambil emoji ROD YANG BENERAN DIPAKAI (bukan emoji('fish') generic),
        # biar tiap rod nampilin emoji custom-nya masing-masing.
        _, cur_rods, _ = get_fishing_config()
        rod_info  = next((r for r in cur_rods if r["name"] == udata["rod"]), {})
        rod_emoji = rod_info.get("emoji") or emoji('fish')

        bait_txt  = (t("fish_bait", uid_fish, bait=used_bait)
                     if used_bait else t("fish_no_bait", uid_fish))
        star      = {"mythic": "🌈", "legendary": "🌟", "epic": "💎"}.get(rarity, "✨")
        sell_hint = f"{emoji('coin')} Nilai jual: ~**{est_price} koin** (belum kejual, cek `Inventori` buat jual!)"
        extra_lines = ""
        if is_new_dex:
            extra_lines += "\n🆕 Ikan baru di Koleksi lo! Cek `dkoleksi`."

        self.last_catch = (caught, rarity)  # buat generate thumbnail gambar

        if rarity in ("mythic", "legendary", "epic", "rare"):
            title = t("fish_title_rare", uid_fish, star=star, rarity=rarity_label)
            desc  = (
                f"**{interaction.user.display_name}** dapet ikan **LANGKA** bro!\n\n"
                f"{caught['emoji']} **{caught['name']}**\n🍀 Luck: **{luck_pct}%**\n{sell_hint}\n"
                f"{rod_emoji} Rod: **{udata['rod']}**\n{bait_txt}{extra_lines}"
                f"\n\n-# {t('fish_rare_footer', uid_fish)}"
            )
        else:
            title = t("fish_title_normal", uid_fish, emoji=caught["emoji"])
            desc  = (
                f"**{interaction.user.display_name}** dapet **{caught['name']}** [{rarity_label}]\n"
                f"🍀 Luck: **{luck_pct}%**\n{sell_hint}\n{rod_emoji} Rod: **{udata['rod']}**\n{bait_txt}{extra_lines}"
            )

        self.body_text = f"**{title}**\n{desc}"
        self._build()
        catch_file = self._render_catch_file()
        await interaction.response.edit_message(view=self, attachments=[catch_file] if catch_file else [])

        # Notif Lootbox/Crate dipisah dari embed hasil mancing (message ephemeral
        # sendiri), biar gak numpuk jadi 1 embed campur aduk sama hasil tangkapan.
        if drop_msgs:
            await interaction.followup.send("\n".join(drop_msgs), ephemeral=True)

        # Cek kalau ada quest mancing yang baru "siap diklaim" (belum auto-reward,
        # user harus klaim manual lewat dquest)
        newly_ready = [
            q for q in get_quest_status(uid)
            if q["type"] == "fish" and q["ready"] and q["progress"] == q["target"]
        ]
        if newly_ready:
            labels = ", ".join(q["label"] for q in newly_ready)
            try:
                await interaction.followup.send(
                    f"{emoji('quest')} **Quest siap diklaim:** {labels}\nKetik `dquest` buat klaim reward-nya!",
                    ephemeral=True
                )
            except Exception:
                pass

    async def inventory(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        await interaction.response.send_message(view=InventoryView(interaction.user.id), ephemeral=True)

    async def shop(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Buka shop sendiri bro!", ephemeral=True)
            return
        await interaction.response.send_message(view=ShopBuyView(interaction.user.id), ephemeral=True)

# ===================== SPIN WHEEL VIEW =====================

class SpinWheelView(discord.ui.LayoutView):
    """Panel spin wheel pake koin. Hadiah rod SENGAJA dibikin langka banget,
    hadiah lain koin/umpan jauh lebih sering keluar. Config full bisa diatur
    owner lewat '!Kingdoom spinwheel'."""
    def __init__(self, user_id, body_text: str | None = None):
        super().__init__(timeout=120)
        self.user_id  = user_id
        self.body_text = body_text or f"Hey <@{user_id}>! Pencet tombol di bawah buat coba keberuntungan lo!"
        self._build()

    def _build(self):
        self.clear_items()
        cost, _ = get_spin_config()
        udata   = get_user_fishing(str(self.user_id))
        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(
            f"### 🎰 StartDoom Spin Wheel\n{self.body_text}\n\n"
            f"**Biaya sekali putar:** {cost} {emoji('coin')} | **Koin lo:** {udata['coins']} {emoji('coin')}"
        ))
        container.add_item(discord.ui.Separator())

        spin_btn = discord.ui.Button(label=f"Putar! ({cost} 🪙)", emoji="🎰", style=discord.ButtonStyle.danger)
        info_btn = discord.ui.Button(label="Peluang Hadiah", emoji="📊", style=discord.ButtonStyle.secondary)
        spin_btn.callback = self.spin
        info_btn.callback = self.show_chances

        row = discord.ui.ActionRow()
        row.add_item(spin_btn)
        row.add_item(info_btn)
        container.add_item(row)

        self.add_item(container)

    async def spin(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ini bukan giliran lo bro, putar punya lo sendiri!", ephemeral=True)
            return
        uid = str(interaction.user.id)
        now = time.time()
        if uid in spin_cooldowns and now - spin_cooldowns[uid] < SPIN_COOLDOWN_SECONDS:
            sisa = round(SPIN_COOLDOWN_SECONDS - (now - spin_cooldowns[uid]))
            await interaction.response.send_message(
                f"⏳ Sabar bro, tunggu **{sisa} detik** lagi sebelum putar lagi!", ephemeral=True
            )
            # Notif otomatis ilang sendiri sesuai sisa detik cooldown-nya
            async def _auto_dismiss(delay: float):
                await asyncio.sleep(delay)
                try:
                    await interaction.delete_original_response()
                except Exception:
                    pass
            asyncio.create_task(_auto_dismiss(max(sisa, 1)))
            return
        cost, _ = get_spin_config()
        udata = get_user_fishing(uid)
        if udata["coins"] < cost:
            await interaction.response.send_message(
                f"{emoji('fail')} Koin lo kurang! Butuh **{cost}** {emoji('coin')}, koin lo cuma **{udata['coins']}** {emoji('coin')}. Mancing/jual ikan dulu ya!",
                ephemeral=True
            )
            return

        spin_cooldowns[uid] = now
        udata["coins"] -= cost
        save_user_fishing(uid, udata)

        prize       = do_spin_roll()
        result_text = apply_spin_prize(uid, prize)

        self.body_text = f"🎉 **Hasil Putaran {interaction.user.display_name}:**\n{result_text}"
        self._build()
        await interaction.response.edit_message(view=self)

    async def show_chances(self, interaction: discord.Interaction):
        _, prizes = get_spin_config()
        await interaction.response.send_message(
            view=panel("📊 Peluang Hadiah Spin Wheel", spin_chance_lines(prizes),
                       footer="Nikoliesamphink · Spin Wheel · Peluang bisa berubah kapan aja diatur owner"),
            ephemeral=True
        )

def buy_rod_for_user(uid: str, rod_name: str) -> dict:
    """Proses pembelian 1 rod. Return {"ok": bool, "msg": str}."""
    _, rods, _ = get_fishing_config()
    rod = next((r for r in rods if r["name"] == rod_name), None)
    if not rod:
        return {"ok": False, "msg": "❌ Rod tidak ditemukan!"}
    udata = get_user_fishing(uid)
    if udata["coins"] < rod["price"]:
        return {"ok": False, "msg": f"❌ Koin kurang! Butuh {rod['price']} {emoji('coin')}"}
    udata["coins"] -= rod["price"]
    # Rod ditambahin ke owned_rods (gak ilang rod lama), terus auto-equip
    # rod yang baru dibeli. User bisa ganti-ganti lagi lewat Equipment.
    owned = udata.setdefault("owned_rods", [])
    if rod["name"] not in owned:
        owned.append(rod["name"])
    udata["rod"] = rod["name"]
    save_user_fishing(uid, udata)
    return {"ok": True, "msg": (
        f"{emoji('success')} Beli & pasang **{rod['name']}**! Sisa koin: {udata['coins']} {emoji('coin')}\n"
        f"-# Cek `dinv` → Equipment buat ganti-ganti rod yang lo punya."
    )}

def buy_bait_for_user(uid: str, bait_name: str) -> dict:
    """Proses pembelian 1 umpan (x5). Return {"ok": bool, "msg": str}."""
    _, _, baits = get_fishing_config()
    bait = next((b for b in baits if b["name"] == bait_name), None)
    if not bait:
        return {"ok": False, "msg": "❌ Umpan tidak ditemukan!"}
    udata = get_user_fishing(uid)
    if udata["coins"] < bait["price"]:
        return {"ok": False, "msg": f"❌ Koin kurang! Butuh {bait['price']} {emoji('coin')}"}
    udata["coins"] -= bait["price"]
    udata.setdefault("bait", {})[bait["name"]] = udata["bait"].get(bait["name"], 0) + 5
    if not udata.get("equipped_bait"):
        udata["equipped_bait"] = bait["name"]
    save_user_fishing(uid, udata)
    return {"ok": True, "msg": (
        f"{emoji('success')} Beli **{bait['name']}** x5! Sisa koin: {udata['coins']} {emoji('coin')}\n"
        f"-# Cek `dinv` → Equipment buat ganti-ganti umpan yang lo punya."
    )}


class PurchaseConfirmView(discord.ui.View):
    """Konfirmasi Ya/Tidak sebelum beli item di Shop — biar gak kebeli gak
    sengaja gara-gara salah pencet di dropdown."""
    def __init__(self, user_id: int, kind: str, item_name: str):
        super().__init__(timeout=30)
        self.user_id   = user_id
        self.kind      = kind  # "rod" atau "bait"
        self.item_name = item_name

    async def _finish(self, interaction: discord.Interaction, content: str):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=content, view=self)

    @discord.ui.button(label="Ya, Beli!", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Bukan pembelian lo!", ephemeral=True)
            return
        if self.kind == "rod":
            result = buy_rod_for_user(str(self.user_id), self.item_name)
        else:
            result = buy_bait_for_user(str(self.user_id), self.item_name)
        await self._finish(interaction, result["msg"])

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Bukan pembelian lo!", ephemeral=True)
            return
        await self._finish(interaction, "❌ Pembelian dibatalin.")


class ShopBuyView(discord.ui.LayoutView):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        fishes, rods, baits = get_fishing_config()
        # Rod "limited" (didaftarin lewat Spin Wheel prize custom) gak boleh
        # muncul/dibeli di Shop — cuma bisa didapet dari Spin Wheel.
        rods  = [r for r in rods if not r.get("limited")]
        udata = get_user_fishing(str(user_id))

        rod_text  = "\n".join([f"{r['emoji']} **{r['name']}** - {r['price']} {emoji('coin')} (Tier {r['tier']}, +{r['luck_bonus']}% luck)" for r in rods])
        bait_text = "\n".join([f"{b['emoji']} **{b['name']}** - {b['price']} {emoji('coin')} (+{b['luck_bonus']}% luck)" for b in baits])

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(
            f"### 🏪 Fishing Shop\n**Koin lo:** {udata['coins']} {emoji('coin')}\n\n"
            f"**🎣 Rod:**\n{rod_text}\n\n**🪱 Umpan:**\n{bait_text}"
        ))
        container.add_item(discord.ui.Separator())

        # Safety guard: Discord menolak Select tanpa option sama sekali (error 400
        # "Must be between 1 and 25 in length"). Kalau rods/baits somehow kosong,
        # skip dropdown-nya daripada bikin panel gagal total.
        if rods:
            rod_options = [discord.SelectOption(label=r["name"], description=f"Tier {r['tier']} - {r['price']} koin | +{r['luck_bonus']}% luck", emoji=r["emoji"]) for r in rods[:25]]
            rod_select  = discord.ui.Select(placeholder="Beli Rod...", custom_id="buy_rod", options=rod_options)
            rod_select.callback = self.buy_rod
            container.add_item(discord.ui.ActionRow(rod_select))
        else:
            container.add_item(discord.ui.TextDisplay("⚠️ Belum ada rod yang terdaftar."))

        if baits:
            bait_options = [discord.SelectOption(label=b["name"], description=f"{b['price']} koin | +{b['luck_bonus']}% luck", emoji=b["emoji"]) for b in baits[:25]]
            bait_select  = discord.ui.Select(placeholder="Beli Umpan...", custom_id="buy_bait", options=bait_options)
            bait_select.callback = self.buy_bait
            container.add_item(discord.ui.ActionRow(bait_select))
        else:
            container.add_item(discord.ui.TextDisplay("⚠️ Belum ada umpan yang terdaftar."))

        self.add_item(container)

    async def buy_rod(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Belanja sendiri bro!", ephemeral=True)
            return
        item_name = interaction.data["values"][0]
        _, rods, _ = get_fishing_config()
        rod = next((r for r in rods if r["name"] == item_name), None)
        if not rod:
            await interaction.response.send_message("❌ Rod tidak ditemukan!", ephemeral=True)
            return
        udata = get_user_fishing(str(interaction.user.id))
        await interaction.response.send_message(
            f"{rod.get('emoji', emoji('fish'))} Beli **{rod['name']}** seharga **{rod['price']}** {emoji('coin')}?\n"
            f"Koin lo: {udata['coins']} {emoji('coin')}",
            view=PurchaseConfirmView(interaction.user.id, "rod", rod["name"]),
            ephemeral=True
        )

    async def buy_bait(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Belanja sendiri bro!", ephemeral=True)
            return
        item_name   = interaction.data["values"][0]
        _, _, baits = get_fishing_config()
        bait = next((b for b in baits if b["name"] == item_name), None)
        if not bait:
            await interaction.response.send_message("❌ Umpan tidak ditemukan!", ephemeral=True)
            return
        udata = get_user_fishing(str(interaction.user.id))
        await interaction.response.send_message(
            f"{bait.get('emoji', '🪱')} Beli **{bait['name']} x5** seharga **{bait['price']}** {emoji('coin')}?\n"
            f"Koin lo: {udata['coins']} {emoji('coin')}",
            view=PurchaseConfirmView(interaction.user.id, "bait", bait["name"]),
            ephemeral=True
        )

# ===================== EQUIPMENT SYSTEM =====================

class EquipRodSelect(discord.ui.Select):
    """Dropdown buat milih rod mana dari yang dimiliki user yang mau dipakai."""
    def __init__(self, user_id: int, owned_rods: list, current_rod: str | None):
        _, rods, _ = get_fishing_config()
        rod_map = {r["name"]: r for r in rods}
        options = []
        for name in owned_rods[:25]:
            r = rod_map.get(name, {})
            desc = f"+{r.get('luck_bonus', 0)}% luck"
            if name == current_rod:
                desc += " • sedang dipakai"
            options.append(discord.SelectOption(
                label=name, value=name, description=desc,
                emoji=r.get("emoji", emoji('fish')), default=(name == current_rod)
            ))
        super().__init__(placeholder="⚙️ Pilih Rod buat dipakai...", options=options, row=0)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        udata = get_user_fishing(str(self.user_id))
        udata["rod"] = self.values[0]
        save_user_fishing(str(self.user_id), udata)
        await interaction.response.edit_message(
            view=EquipmentView(self.user_id, note=f"{emoji('success')} Rod **{self.values[0]}** sekarang dipakai!")
        )


class EquipBaitSelect(discord.ui.Select):
    """Dropdown buat milih umpan mana dari inventori yang mau dipakai."""
    def __init__(self, user_id: int, bait_inv: dict, current_bait: str | None):
        _, _, baits = get_fishing_config()
        bait_map = {b["name"]: b for b in baits}
        options = []
        for name, qty in list(bait_inv.items())[:25]:
            if qty <= 0:
                continue
            b = bait_map.get(name, {})
            desc = f"x{qty} • +{b.get('luck_bonus', 0)}% luck"
            if name == current_bait:
                desc += " • dipakai"
            options.append(discord.SelectOption(
                label=name, value=name, description=desc,
                emoji=b.get("emoji", "🪱"), default=(name == current_bait)
            ))
        if not options:
            options = [discord.SelectOption(label="Belum punya umpan", value="__none__", description="Beli umpan dulu di Shop")]
        super().__init__(placeholder="⚙️ Pilih Umpan buat dipakai...", options=options, row=1)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message("⚠️ Beli umpan dulu di Shop!", ephemeral=True)
            return
        udata = get_user_fishing(str(self.user_id))
        udata["equipped_bait"] = self.values[0]
        save_user_fishing(str(self.user_id), udata)
        await interaction.response.edit_message(
            view=EquipmentView(self.user_id, note=f"{emoji('success')} Umpan **{self.values[0]}** sekarang dipakai!")
        )


class EquipmentView(discord.ui.LayoutView):
    """Panel Equipment: user pilih rod & umpan yang mau dipakai buat mancing,
    dari semua rod/umpan yang udah pernah dia beli."""
    def __init__(self, user_id: int, note: str | None = None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.note    = note
        self._build()

    def _build(self):
        self.clear_items()
        udata = get_user_fishing(str(self.user_id))
        owned_rods   = udata.get("owned_rods") or [udata.get("rod", "Pancing Bambu")]
        current_rod  = udata.get("rod")
        current_bait = udata.get("equipped_bait")
        bait_inv     = udata.get("bait", {})

        _, rods, baits = get_fishing_config()
        bait_info    = next((b for b in baits if b["name"] == current_bait), {})
        rod_level    = udata.get("rod_levels", {}).get(current_rod, 0)
        eff_luck     = get_rod_effective_luck(udata, current_rod)

        desc = (
            f"**Rod dipakai:** {current_rod} — Lv.{rod_level} (+{eff_luck:.1f}% luck total)\n"
            f"**Umpan dipakai:** {current_bait or '-'}"
            + (f" (+{bait_info.get('luck_bonus', 0)}% luck)" if current_bait else "")
            + f"\n\n*Lo punya {len(owned_rods)} rod. Pilih di dropdown buat ganti yang dipakai.*"
            + f"\n-# Mau naikin level rod? Buka **Tempa Rod** di `dinv`."
        )
        if self.note:
            desc = f"{self.note}\n\n{desc}"

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(f"### ⚔️ Equipment\n{desc}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(EquipRodSelect(self.user_id, owned_rods, current_rod)))
        container.add_item(discord.ui.ActionRow(EquipBaitSelect(self.user_id, bait_inv, current_bait)))
        self.add_item(container)

# ===================== TEMPA VIEW (Rod Upgrade UI) =====================

class TempaRodSelect(discord.ui.Select):
    """Dropdown buat milih rod mana yang mau di-Tempa (naikin level)."""
    def __init__(self, user_id: int, owned_rods: list, rod_levels: dict):
        options = []
        for name in owned_rods[:25]:
            level = rod_levels.get(name, 0)
            maxed = level >= ROD_UPGRADE_MAX_LEVEL
            desc  = f"Lv.{level}" + (" (MAX)" if maxed else f" → Lv.{level+1}")
            options.append(discord.SelectOption(label=name, value=name, description=desc, emoji="🔨"))
        super().__init__(placeholder="🔨 Pilih Rod buat di-Tempa...", options=options, row=0)
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        result = upgrade_rod(str(self.user_id), self.values[0])
        await interaction.response.edit_message(view=TempaView(self.user_id, note=result["msg"]))


class TempaView(discord.ui.LayoutView):
    """Panel Tempa: upgrade rod pake Serpihan Tempa + koin, naikin luck bonus
    rod itu secara permanen (per-level, max ROD_UPGRADE_MAX_LEVEL)."""
    def __init__(self, user_id: int, note: str | None = None):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.note    = note
        self._build()

    def _build(self):
        self.clear_items()
        udata      = get_user_fishing(str(self.user_id))
        owned_rods = udata.get("owned_rods") or [udata.get("rod", "Pancing Bambu")]
        rod_levels = udata.get("rod_levels", {})

        lines = []
        for name in owned_rods:
            level = rod_levels.get(name, 0)
            if level >= ROD_UPGRADE_MAX_LEVEL:
                lines.append(f"• **{name}** — Lv.{level} `MAX`")
            else:
                cost = rod_upgrade_cost(level)
                lines.append(f"• **{name}** — Lv.{level} → biaya naik: {cost['materials']}{MATERIAL_EMOJI} + {cost['coins']}{emoji('coin')}")

        desc = (
            f"### 🔨 Tempa Rod\n"
            f"Naikin level rod pake **{MATERIAL_NAME}** ({MATERIAL_EMOJI}, didapet dari Lootbox/Crate) + koin.\n"
            f"Tiap level: **+{ROD_UPGRADE_LUCK_PER_LEVEL}% luck** (max Lv.{ROD_UPGRADE_MAX_LEVEL}).\n\n"
            f"**Punya:** {udata.get('materials', 0)} {MATERIAL_EMOJI} | {udata['coins']} {emoji('coin')}\n\n"
            + "\n".join(lines)
        )
        if self.note:
            desc = f"{self.note}\n\n{desc}"

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(desc))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(TempaRodSelect(self.user_id, owned_rods, rod_levels)))
        self.add_item(container)

# ===================== COLLECTION VIEW (Koleksi — buat pamer) =====================

class CollectionView(discord.ui.LayoutView):
    """Panel Koleksi: nunjukin ikan yang udah pernah ditangkap (per rarity)
    + rod yang udah dimiliki. Bisa dibuka buat diri sendiri ATAU buat
    ngeliat koleksi user lain (pamer!)."""
    RARITY_ORDER = ["mythic", "legendary", "epic", "rare", "uncommon", "common"]

    def __init__(self, user_id: int, target_user: discord.abc.User, note: str | None = None):
        super().__init__(timeout=120)
        self.user_id     = user_id       # yang buka panel (buat cek privasi tombol, kalau ada)
        self.target_user = target_user   # yang koleksinya ditampilin
        self.note        = note
        self._build()

    def _build(self):
        self.clear_items()
        udata      = get_user_fishing(str(self.target_user.id))
        dex        = set(udata.get("fish_dex", []))
        owned_rods = set(udata.get("owned_rods") or [])
        fishes, rods, _ = get_fishing_config()

        by_rarity = {}
        for f in fishes:
            if f.get("luck", 0) <= 0:
                continue
            r = get_rarity_from_luck(f["luck"])
            by_rarity.setdefault(r, []).append(f)

        total_fish  = sum(len(v) for v in by_rarity.values())
        total_owned = len(dex)
        pct = round(total_owned / total_fish * 100) if total_fish else 0

        lines = []
        for r in self.RARITY_ORDER:
            fs = by_rarity.get(r, [])
            if not fs:
                continue
            label, _ = get_rarity_display(r)
            got = sum(1 for f in fs if f["name"] in dex)
            lines.append(f"**{label}** ({got}/{len(fs)})")
            for f in fs:
                mark = "✅" if f["name"] in dex else "❔"
                shown_name = f["name"] if f["name"] in dex else "???"
                lines.append(f"{mark} {f.get('emoji', '🐟')} {shown_name}")

        rod_lines = []
        for r in rods:
            mark = "✅" if r["name"] in owned_rods else "❔"
            rod_lines.append(f"{mark} {r.get('emoji', emoji('fish'))} {r['name']}")

        desc = (
            f"### 📖 Koleksi {self.target_user.display_name}\n"
            f"**Ikan:** {total_owned}/{total_fish} ({pct}%) | **Rod dimiliki:** {len(owned_rods)}/{len(rods)}\n"
        )
        if self.note:
            desc = f"{self.note}\n\n{desc}"

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(desc))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("**🐟 Ikan Dex**\n" + "\n".join(lines)))
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.TextDisplay("**🎣 Rod Dimiliki**\n" + "\n".join(rod_lines)))
        self.add_item(container)

# ===================== FISHING SETUP PANEL (Owner Only) =====================

class FishingSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🐟 Edit Ikan", style=discord.ButtonStyle.primary, row=0)
    async def edit_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
        fishes, rods, baits = get_fishing_config()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
        lines = "\n".join([f"{i+1}. {f['emoji']} {f['name']} | sell:{f['sell_price']} | luck:{f['luck']}%" for i, f in enumerate(fishes)])
        await interaction.response.send_message(
            f"🐟 **Daftar Ikan Saat Ini:**\n```{lines}```\n\n"
            "Ketik data ikan baru format:\n"
            "`nama|emoji|sell_price|luck_persen`\n"
            "Satu baris per ikan. Contoh:\n"
            "```Ikan Lele|🐟|15|35\nIkan Naga|🐉|1000|0.5```\n"
            "⚠️ Ini akan **REPLACE** semua ikan. Kirim dalam 120 detik.",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            new_fishes = []
            for line in msg.content.strip().split("\n"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                try:
                    new_fishes.append({"name": parts[0], "emoji": parts[1], "sell_price": int(parts[2]), "luck": float(parts[3])})
                except:
                    pass
            if not new_fishes:
                await interaction.followup.send("❌ Format salah atau tidak ada ikan valid!", ephemeral=True)
                return
            save_fishing_config(new_fishes, rods, baits)
            names = ", ".join([f["name"] for f in new_fishes])
            await interaction.followup.send(f"✅ **{len(new_fishes)} ikan** berhasil disimpan!\n`{names}`", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="🎣 Edit Rod", style=discord.ButtonStyle.secondary, row=0)
    async def edit_rod(self, interaction: discord.Interaction, button: discord.ui.Button):
        fishes, rods, baits = get_fishing_config()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
        lines = "\n".join([f"{i+1}. {r['emoji']} {r['name']} | tier:{r['tier']} | price:{r['price']} | luck_bonus:+{r['luck_bonus']}%" for i, r in enumerate(rods)])
        await interaction.response.send_message(
            f"🎣 **Daftar Rod Saat Ini:**\n```{lines}```\n\n"
            "Format baru: `nama|emoji|tier|price|luck_bonus`\n"
            "Contoh:\n```Pancing Bambu|🎋|1|50|0\nPancing Legenda|⚡|6|5000|40```",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            new_rods = []
            for line in msg.content.strip().split("\n"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 5:
                    continue
                try:
                    new_rods.append({"name": parts[0], "emoji": parts[1], "tier": int(parts[2]), "price": int(parts[3]), "luck_bonus": float(parts[4])})
                except:
                    pass
            if not new_rods:
                await interaction.followup.send("❌ Format salah!", ephemeral=True)
                return
            save_fishing_config(fishes, new_rods, baits)
            await interaction.followup.send(f"✅ **{len(new_rods)} rod** berhasil disimpan!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="🪱 Edit Bait", style=discord.ButtonStyle.secondary, row=0)
    async def edit_bait(self, interaction: discord.Interaction, button: discord.ui.Button):
        fishes, rods, baits = get_fishing_config()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
        lines = "\n".join([f"{i+1}. {b['emoji']} {b['name']} | price:{b['price']} | luck_bonus:+{b['luck_bonus']}%" for i, b in enumerate(baits)])
        await interaction.response.send_message(
            f"🪱 **Daftar Bait Saat Ini:**\n```{lines}```\n\n"
            "Format baru: `nama|emoji|price|luck_bonus`\n"
            "Contoh:\n```Cacing Biasa|🪱|10|0\nIkan Kecil|🐟|100|20```",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            new_baits = []
            for line in msg.content.strip().split("\n"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 4:
                    continue
                try:
                    new_baits.append({"name": parts[0], "emoji": parts[1], "price": int(parts[2]), "luck_bonus": float(parts[3])})
                except:
                    pass
            if not new_baits:
                await interaction.followup.send("❌ Format salah!", ephemeral=True)
                return
            save_fishing_config(fishes, rods, new_baits)
            await interaction.followup.send(f"✅ **{len(new_baits)} bait** berhasil disimpan!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="📋 Lihat Semua Config", style=discord.ButtonStyle.success, row=1)
    async def view_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        fishes, rods, baits = get_fishing_config()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
        fish_lines = "\n".join([f"{f['emoji']} **{f['name']}** — Jual: {f['sell_price']} 🪙 | Luck: {f['luck']}% [{get_rarity_from_luck(f['luck']).upper()}]" for f in fishes])
        rod_lines  = "\n".join([f"{r['emoji']} **{r['name']}** — Harga: {r['price']} 🪙 | +{r['luck_bonus']}% luck" for r in rods])
        bait_lines = "\n".join([f"{b['emoji']} **{b['name']}** — Harga: {b['price']} 🪙 | +{b['luck_bonus']}% luck" for b in baits])
        em = dark_red_embed("🎣 Fishing Config", f"**🐟 Ikan ({len(fishes)}):**\n{fish_lines}\n\n**🎣 Rod ({len(rods)}):**\n{rod_lines}\n\n**🪱 Bait ({len(baits)}):**\n{bait_lines}")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🔄 Reset ke Default", style=discord.ButtonStyle.danger, row=1)
    async def reset_default(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
        save_fishing_config(DEFAULT_FISHES, DEFAULT_RODS, DEFAULT_BAITS)
        await interaction.response.send_message("✅ Fishing config direset ke default!", ephemeral=True)

async def fishing_setup_panel(ctx):
    fishes, rods, baits = get_fishing_config()
    em = dark_red_embed(
        "🎣 Setup Fishing System",
        f"**🐟 Ikan terdaftar:** {len(fishes)}\n"
        f"**🎣 Rod terdaftar:** {len(rods)}\n"
        f"**🪱 Bait terdaftar:** {len(baits)}\n\n"
        "Gunakan tombol di bawah untuk mengatur fishing system.\n"
        "**Luck** = persentase kemungkinan ikan muncul.\n"
        "Semakin kecil luck, semakin langka ikan tersebut."
    )
    em.set_footer(text="⚠️ Panel ini hanya untuk Owner/Admin")
    await ctx.send(embed=em, view=FishingSetupView())

# ===================== SPIN WHEEL SETUP PANEL (Owner Only) =====================

class SpinSetupView(discord.ui.View):
    """Panel owner buat atur hadiah spin wheel (rod/koin/umpan custom + peluang)
    dan harga sekali putar."""
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🎁 Edit Daftar Hadiah", style=discord.ButtonStyle.primary, row=0)
    async def edit_prizes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur spin wheel!", ephemeral=True)
            return
        cost, prizes = get_spin_config()
        _, rods, baits = get_fishing_config()
        rod_names  = ", ".join(r["name"] for r in rods) or "-"
        bait_names = ", ".join(b["name"] for b in baits) or "-"
        lines = "\n".join([f"{i+1}. [{p['type']}] {spin_prize_label(p)} | weight:{p.get('weight')}" for i, p in enumerate(prizes)])
        await interaction.response.send_message(
            f"🎁 **Daftar Hadiah Saat Ini:**\n```{lines}```\n\n"
            "Kirim daftar hadiah baru, **1 baris per hadiah**, format sesuai tipe:\n"
            "• Rod (pakai rod yang UDAH ADA di Shop) → `rod|nama_rod|weight`\n"
            "• Rod **LIMITED** (baru, HANYA bisa didapet dari spin, gak muncul di Shop) →\n"
            "  `rod|nama_rod_baru|weight|emoji|luck_bonus`\n"
            "• Koin → `coin|label|weight|min|max`\n"
            "• Umpan → `bait|nama_umpan|weight|jumlah`\n"
            "• Zonk → `trash|label|weight`\n\n"
            f"Rod yang UDAH ada di Shop: `{rod_names}`\n"
            f"Umpan yang UDAH ada di Shop: `{bait_names}`\n"
            "*(Weight makin kecil = makin langka. Bikin weight rod KECIL BANGET biar susah dapetnya.)*\n\n"
            "Contoh:\n"
            "```coin|Koin Receh|35|20|80\nbait|Cacing Biasa|15|3\n"
            "rod|Pancing Titan|0.3\n"
            "rod|Pancing Meteor|0.05|<:meteorpole:123456789012345678>|60\n"
            "trash|Zonk|11.65```\n"
            "⚠️ Ini akan **REPLACE** semua hadiah. Kirim dalam 120 detik.",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            cur_fishes, cur_rods, cur_baits = get_fishing_config()
            valid_rod_names  = {r["name"] for r in cur_rods}
            valid_bait_names = {b["name"] for b in cur_baits}
            new_prizes    = []
            skipped       = []
            rods_changed  = False
            for line in msg.content.strip().split("\n"):
                parts = [p.strip() for p in line.split("|")]
                if not parts or not parts[0]:
                    continue
                ptype = parts[0].lower()
                try:
                    if ptype == "rod" and len(parts) >= 3:
                        name, weight = parts[1], float(parts[2])
                        if name not in valid_rod_names:
                            if len(parts) < 5:
                                skipped.append(line); continue
                            # Rod BARU, self-contained (emoji + luck_bonus sendiri).
                            # Didaftarin sebagai rod "limited" — masuk ke fishing_config
                            # biar dikenali sistem (Equipment/Inventori/mancing), TAPI
                            # ditandain limited=True biar gak ikut muncul di Shop.
                            rod_emoji = parts[3]
                            luck_bonus = float(parts[4])
                            cur_rods.append({
                                "name": name, "emoji": rod_emoji, "tier": 99,
                                "price": 0, "luck_bonus": luck_bonus, "limited": True
                            })
                            valid_rod_names.add(name)
                            rods_changed = True
                        new_prizes.append({"type": "rod", "label": name, "name": name, "weight": weight})
                    elif ptype == "coin" and len(parts) >= 5:
                        label, weight, mn, mx = parts[1], float(parts[2]), int(parts[3]), int(parts[4])
                        new_prizes.append({"type": "coin", "label": label, "weight": weight, "min": mn, "max": mx})
                    elif ptype == "bait" and len(parts) >= 4:
                        name, weight, qty = parts[1], float(parts[2]), int(parts[3])
                        if name not in valid_bait_names:
                            skipped.append(line); continue
                        new_prizes.append({"type": "bait", "label": name, "name": name, "weight": weight, "qty": qty})
                    elif ptype == "trash" and len(parts) >= 3:
                        label, weight = parts[1], float(parts[2])
                        new_prizes.append({"type": "trash", "label": label, "weight": weight})
                    else:
                        skipped.append(line)
                except Exception:
                    skipped.append(line)

            if not new_prizes:
                await interaction.followup.send("❌ Gak ada hadiah valid yang bisa disimpan! Cek lagi format & nama rod/umpannya.", ephemeral=True)
                return
            if rods_changed:
                save_fishing_config(cur_fishes, cur_rods, cur_baits)
            save_spin_config(cost, new_prizes)
            msg_txt = f"✅ **{len(new_prizes)} hadiah** berhasil disimpan!"
            if rods_changed:
                msg_txt += "\n🔒 Ada rod LIMITED baru yang didaftarin — cuma bisa didapet dari Spin Wheel, gak muncul di Shop."
            if skipped:
                msg_txt += f"\n⚠️ **{len(skipped)} baris dilewati** (format salah / nama rod-umpan gak ketemu):\n```{chr(10).join(skipped[:10])}```"
            await interaction.followup.send(msg_txt, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="💰 Edit Harga Putar", style=discord.ButtonStyle.secondary, row=0)
    async def edit_cost(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur spin wheel!", ephemeral=True)
            return
        cost, prizes = get_spin_config()
        await interaction.response.send_message(
            f"💰 **Harga sekali putar saat ini:** {cost} 🪙\n\nKetik angka harga baru (koin). Kirim dalam 60 detik.",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
            new_cost = int(msg.content.strip())
            if new_cost < 1:
                await interaction.followup.send("❌ Harga harus lebih dari 0!", ephemeral=True)
                return
            save_spin_config(new_cost, prizes)
            await interaction.followup.send(f"✅ Harga sekali putar diubah jadi **{new_cost}** 🪙!", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ Itu bukan angka valid!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="📋 Lihat Config", style=discord.ButtonStyle.success, row=1)
    async def view_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        cost, prizes = get_spin_config()
        em = dark_red_embed("🎰 Spin Wheel Config", f"**Harga sekali putar:** {cost} 🪙\n\n**Peluang Hadiah:**\n{spin_chance_lines(prizes)}")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🔄 Reset ke Default", style=discord.ButtonStyle.danger, row=1)
    async def reset_default(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur spin wheel!", ephemeral=True)
            return
        save_spin_config(DEFAULT_SPIN_COST, DEFAULT_SPIN_PRIZES)
        await interaction.response.send_message("✅ Spin wheel config direset ke default!", ephemeral=True)

async def spinwheel_setup_panel(ctx):
    cost, prizes = get_spin_config()
    em = dark_red_embed(
        "🎰 Setup Spin Wheel",
        f"**Harga sekali putar:** {cost} 🪙\n"
        f"**Jumlah hadiah terdaftar:** {len(prizes)}\n\n"
        "Gunakan tombol di bawah buat atur hadiah (termasuk rod custom) & harganya.\n"
        "**Weight** = bobot peluang. Semakin kecil weight-nya dibanding total, semakin langka hadiah itu keluar.\n"
        "Rod sengaja dibuat weight kecil biar susah didapat."
    )
    em.set_footer(text="⚠️ Panel ini hanya untuk Owner/Admin")
    await ctx.send(embed=em, view=SpinSetupView())

# ===================== PREMIUM ORDER VIEWS =====================

class PremiumOrderView(discord.ui.View):
    def __init__(self, order_id: str, user_id: int, guild_id: str):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.user_id  = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="prem_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Akses ditolak! Hanya Owner Bot yang bisa approve.", ephemeral=True)
            return
        orders = get_premium_orders()
        if self.order_id not in orders:
            await interaction.response.send_message("❌ Order tidak ditemukan!", ephemeral=True)
            return
        order = orders[self.order_id]
        if order.get("status") != "pending":
            await interaction.response.send_message(f"⚠️ Order sudah **{order['status']}**!", ephemeral=True)
            return

        pdata = get_premium_data()
        pdata.setdefault("users", {})
        duration_days = order.get("duration_days", 30)
        pdata["users"][str(self.user_id)] = {
            "active": True,
            "activated_at": time.time(),
            "expires_at": time.time() + (duration_days * 86400),
            "approved_by": str(interaction.user.id),
            "package": order.get("package", "Premium")
        }
        save_premium_data(pdata)
        orders[self.order_id].update({"status": "approved", "approved_by": str(interaction.user.id), "approved_at": time.time()})
        save_premium_orders(orders)

        try:
            user    = await bot.fetch_user(self.user_id)
            expires = datetime.datetime.fromtimestamp(pdata["users"][str(self.user_id)]["expires_at"], tz=WIB)
            dm_em = discord.Embed(
                title="👑 Premium Access Activated!",
                description=(
                    "Your premium order has been **approved**!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=0xFFD700
            )
            dm_em.set_thumbnail(url=user.display_avatar.url)
            dm_em.add_field(
                name="🎉 Welcome to Premium!",
                value=(
                    f"**Hey {user.display_name}**, your access is now active.\n"
                    "Enjoy all the exclusive features!"
                ),
                inline=False
            )
            dm_em.add_field(
                name="📋 Subscription Details",
                value=(
                    f"**Package** · {order.get('package', 'Premium')}\n"
                    f"**Duration** · {duration_days} days\n"
                    f"**Expires** · {expires.strftime('%d %B %Y, %H:%M')} WIB"
                ),
                inline=False
            )
            dm_em.add_field(
                name="💡 Get Started",
                value=(
                    "Use `dpremium` to check your status anytime.\n"
                    "Thank you for supporting **StartDoom**! 🙏"
                ),
                inline=False
            )
            dm_em.set_footer(text="Nikoliesamphink · Premium System")
            await user.send(embed=dm_em)
        except Exception as e:
            print(f"Gagal DM user premium: {e}")

        em = interaction.message.embeds[0] if interaction.message.embeds else dark_red_embed("Order")
        em.color = 0x00FF00
        em.set_footer(text=f"✅ APPROVED oleh {interaction.user.display_name} | {datetime.datetime.now(tz=WIB).strftime('%d/%m/%Y %H:%M')}")
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=em, view=self)
        await interaction.followup.send(f"✅ Order **{self.order_id}** di-approve! User sudah di-DM.", ephemeral=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id="prem_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Akses ditolak! Hanya Owner Bot yang bisa reject.", ephemeral=True)
            return
        orders = get_premium_orders()
        if self.order_id not in orders or orders[self.order_id].get("status") != "pending":
            await interaction.response.send_message("❌ Order tidak valid/sudah diproses!", ephemeral=True)
            return
        orders[self.order_id].update({"status": "rejected", "rejected_by": str(interaction.user.id), "rejected_at": time.time()})
        save_premium_orders(orders)
        try:
            user  = await bot.fetch_user(self.user_id)
            dm_em = discord.Embed(
                title="❌ Order Not Approved",
                description=(
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Hey **{user.display_name}**, unfortunately your premium order was **not approved**.\n\n"
                    "This may be due to:\n"
                    "• Invalid or unclear payment proof\n"
                    "• Payment amount mismatch\n"
                    "• Other verification issues\n\n"
                    "Please contact the admin for more information or try ordering again."
                ),
                color=0xFF4444
            )
            dm_em.set_footer(text="Nikoliesamphink · Premium System")
            await user.send(embed=dm_em)
        except:
            pass
        em = interaction.message.embeds[0] if interaction.message.embeds else dark_red_embed("Order")
        em.color = 0xFF0000
        em.set_footer(text=f"❌ REJECTED oleh {interaction.user.display_name} | {datetime.datetime.now(tz=WIB).strftime('%d/%m/%Y %H:%M')}")
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(embed=em, view=self)
        await interaction.followup.send(f"✅ Order **{self.order_id}** di-reject.", ephemeral=True)

    @discord.ui.button(label="💬 Pesan Singkat", style=discord.ButtonStyle.secondary, custom_id="prem_msg")
    async def send_message(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Akses ditolak! Hanya Owner Bot yang bisa kirim pesan.", ephemeral=True)
            return
        await interaction.response.send_message("📝 Ketik pesan untuk dikirim ke user (60 detik):", ephemeral=True)
        try:
            msg  = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
            user = await bot.fetch_user(self.user_id)
            dm_em = dark_red_embed(
                "📩 Message from StartDoom Admin",
                f"**Halo {user.display_name}!**\n\n```{msg.content}```\n*Ref Order: `{self.order_id}`*"
            )
            dm_em.set_footer(text=f"Dikirim oleh {interaction.user.display_name}")
            await user.send(embed=dm_em)
            await interaction.followup.send(f"✅ Pesan terkirim ke **{user.display_name}**!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Gagal: {str(e)[:100]}", ephemeral=True)

# ===================== PREMIUM SETUP VIEW =====================

class PremiumSetupView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔗 Set Webhook URL", style=discord.ButtonStyle.primary, row=0)
    async def set_webhook(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur ini!", ephemeral=True)
            return
        await interaction.response.send_message("🔗 Paste Discord Webhook URL:", ephemeral=True)
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
            url = msg.content.strip()
            if not url.startswith("https://discord.com/api/webhooks/"):
                await interaction.followup.send("❌ URL tidak valid!", ephemeral=True)
                return
            pdata = get_premium_data()
            pdata.setdefault("settings", {})["webhook_url"] = url
            save_premium_data(pdata)
            try:
                await msg.delete()
            except:
                pass
            await interaction.followup.send("✅ Webhook URL disimpan!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="📦 Kelola Paket", style=discord.ButtonStyle.secondary, row=0)
    async def manage_packages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur ini!", ephemeral=True)
            return
        pkgs  = get_premium_packages()
        lines = "\n".join([f"• **{k}** — {v['price']} | {v['duration_days']} hari | {v.get('description','')}" for k, v in pkgs.items()])
        await interaction.response.send_message(
            f"📦 **Paket Premium Saat Ini:**\n{lines}\n\n"
            "Ketik paket baru format (satu baris per paket):\n"
            "`NamaPaket|Harga|DurasiHari|Deskripsi`\n"
            "Contoh:\n```Basic|Rp 15.000|7|Akses 7 hari\nStandard|Rp 25.000|30|Akses 30 hari```\n"
            "⚠️ Ini akan replace semua paket!",
            ephemeral=True
        )
        try:
            msg      = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            new_pkgs = {}
            for line in msg.content.strip().split("\n"):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                try:
                    new_pkgs[parts[0]] = {"price": parts[1], "duration_days": int(parts[2]), "description": parts[3] if len(parts) > 3 else ""}
                except:
                    pass
            if not new_pkgs:
                await interaction.followup.send("❌ Format salah!", ephemeral=True)
                return
            pdata = get_premium_data()
            pdata["packages"] = new_pkgs
            save_premium_data(pdata)
            await interaction.followup.send(f"✅ **{len(new_pkgs)} paket** berhasil disimpan!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="📋 Lihat Pengaturan", style=discord.ButtonStyle.success, row=1)
    async def view_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa melihat ini!", ephemeral=True)
            return
        pdata    = get_premium_data()
        settings = pdata.get("settings", {})
        pkgs     = get_premium_packages()
        wh       = settings.get("webhook_url", "")
        wh_disp  = f"✅ Sudah diset (`...{wh[-20:]}`)" if wh else "❌ Belum diset"
        pkg_text = "\n".join([f"• **{k}** — {v['price']} ({v['duration_days']} hari)" for k, v in pkgs.items()])
        em = dark_red_embed(
            "👑 Pengaturan Premium System",
            f"**🔗 Webhook:** {wh_disp}\n\n**📦 Paket Premium:**\n{pkg_text}"
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="📊 Daftar User Premium", style=discord.ButtonStyle.success, row=1)
    async def list_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa melihat ini!", ephemeral=True)
            return
        pdata = get_premium_data()
        users = pdata.get("users", {})
        if not users:
            await interaction.response.send_message("📊 Belum ada user premium.", ephemeral=True)
            return
        lines = []
        now   = time.time()
        for uid, udata in users.items():
            try:
                u    = await bot.fetch_user(int(uid))
                name = u.display_name
            except:
                name = f"User {uid}"
            exp    = udata.get("expires_at", 0)
            active = udata.get("active", False)
            if exp and now > exp:
                status = "⏰ Expired"
            elif active:
                exp_dt = datetime.datetime.fromtimestamp(exp, tz=WIB).strftime('%d/%m/%Y') if exp else "Permanen"
                status = f"✅ Aktif s.d. {exp_dt}"
            else:
                status = "❌ Nonaktif"
            lines.append(f"**{name}** (`{uid}`) — {status}")
        em = dark_red_embed("📊 User Premium", "\n".join(lines[:20]))
        em.set_footer(text=f"Total: {len(users)} user")
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🗑️ Cabut Premium", style=discord.ButtonStyle.danger, row=1)
    async def revoke_premium(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa melakukan ini!", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ Ketik User ID yang dicabut premium-nya:", ephemeral=True)
        try:
            msg   = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=30)
            uid   = msg.content.strip()
            pdata = get_premium_data()
            if uid in pdata.get("users", {}):
                pdata["users"][uid]["active"] = False
                save_premium_data(pdata)
                await interaction.followup.send(f"✅ Premium user `{uid}` dicabut!", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ User ID `{uid}` tidak ditemukan.", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="🔒 Set Command Premium", style=discord.ButtonStyle.danger, row=2)
    async def set_locked_cmds(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Set command mana saja yang dikunci premium."""
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur ini!", ephemeral=True)
            return
        locked = get_locked_commands()
        current = ", ".join(locked) if locked else "Belum ada"

        # Semua command yang bisa dikunci
        available = [
            "fish", "tebak", "coins", "giveaway", "event",
            "warn", "sticky", "autoresponse",
            "reactionrole", "leaderboard", "daily", "quest"
        ]
        avail_text = ", ".join([f"`{c}`" for c in available])

        await interaction.response.send_message(
            f"🔒 **Command yang Saat Ini Dikunci Premium:**\n"
            f"`{current}`\n\n"
            f"**Command yang Tersedia untuk Dikunci:**\n{avail_text}\n\n"
            f"**Cara pakai:**\n"
            f"Ketik nama command yang mau dikunci, pisah dengan koma.\n"
            f"Contoh: `fish, tebak, giveaway, daily`\n\n"
            f"Ketik `none` untuk hapus semua lock.\n"
            f"*(120 detik)*",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=120)
            raw = msg.content.strip().lower()
            if raw == "none":
                set_locked_commands([])
                await interaction.followup.send("✅ Semua command lock dihapus! Semua command bebas diakses.", ephemeral=True)
            else:
                new_locked = [c.strip() for c in raw.split(",") if c.strip() in available]
                invalid    = [c.strip() for c in raw.split(",") if c.strip() and c.strip() not in available]
                set_locked_commands(new_locked)
                msg_text = f"✅ **{len(new_locked)} command** berhasil dikunci premium!\n🔒 Locked: `{', '.join(new_locked) if new_locked else 'Tidak ada'}`"
                if invalid:
                    msg_text += f"\n⚠️ Tidak dikenali (diabaikan): `{', '.join(invalid)}`"
                await interaction.followup.send(msg_text, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="🔓 Lihat Command Terkunci", style=discord.ButtonStyle.secondary, row=2)
    async def view_locked_cmds(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa melihat ini!", ephemeral=True)
            return
        locked = get_locked_commands()
        pdata  = get_premium_data()
        pkgs   = get_premium_packages()
        payment_info = pdata.get("settings", {}).get("payment_info", "Belum diset. Set via panel 💳 Set Info Pembayaran.")

        em = discord.Embed(
            title="🔒 Command Terkunci Premium",
            description=(
                "**Command yang memerlukan premium:**\n"
                + (", ".join([f"`{c}`" for c in locked]) if locked else "*(Tidak ada command yang dikunci)*")
                + f"\n\n**💳 Info Pembayaran:**\n{payment_info}"
            ),
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="💳 Set Info Pembayaran", style=discord.ButtonStyle.primary, row=2)
    async def set_payment_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur ini!", ephemeral=True)
            return
        pdata = get_premium_data()
        current = pdata.get("settings", {}).get("payment_info", "Belum diset.")
        await interaction.response.send_message(
            f"💳 **Info Pembayaran Saat Ini:**\n```{current}```\n\n"
            "Ketik info pembayaran baru (rekening, GoPay, dll):\n"
            "Contoh:\n"
            "```BCA: 1234567890 a/n John Doe\nGoPay/OVO: 081234567890```\n"
            "*(60 detik)*",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
            pdata.setdefault("settings", {})["payment_info"] = msg.content.strip()
            save_premium_data(pdata)
            await interaction.followup.send("✅ Info pembayaran berhasil disimpan!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="🖼️ Set QRIS Image", style=discord.ButtonStyle.primary, row=2)
    async def set_qris(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur ini!", ephemeral=True)
            return
        pdata   = get_premium_data()
        current = pdata.get("settings", {}).get("qris_url", "")
        await interaction.response.send_message(
            f"🖼️ **QRIS URL Saat Ini:** `{current if current else 'Belum diset'}`\n\n"
            "Ketik URL gambar QRIS lo (harus link langsung ke gambar `.png/.jpg`):\n"
            "Karena file `qris.png` ada di GitHub, format URL-nya:\n"
            "`https://raw.githubusercontent.com/USERNAME/REPO/main/qris.png`\n\n"
            "*(60 detik)*",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
            qris_url = msg.content.strip()
            if not (qris_url.startswith("http") and any(qris_url.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"])):
                await interaction.followup.send("❌ URL tidak valid! Harus link langsung ke file gambar (.png/.jpg/.jpeg/.gif/.webp)", ephemeral=True)
                return
            pdata.setdefault("settings", {})["qris_url"] = qris_url
            save_premium_data(pdata)
            # Preview
            preview_em = discord.Embed(title="✅ QRIS Berhasil Disimpan!", description=f"URL: `{qris_url}`\n\n*Preview QRIS di bawah:*", color=0x00FF00)
            preview_em.set_image(url=qris_url)
            await interaction.followup.send(embed=preview_em, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

async def premium_setup_panel(ctx):
    pdata    = get_premium_data()
    settings = pdata.get("settings", {})
    pkgs     = get_premium_packages()
    wh       = settings.get("webhook_url", "")
    locked   = get_locked_commands()
    payment  = settings.get("payment_info", "")
    locked_txt = (", ".join([f"`{c}`" for c in locked])) if locked else "*(belum ada)*"
    qris_url_p = settings.get("qris_url", "")
    em = discord.Embed(
        title="⚙️ Setup Premium System",
        description=(
            f"**🔗 Webhook:** {'✅ Sudah diset' if wh else '❌ Belum diset'}\n"
            f"**📦 Paket tersedia:** {len(pkgs)} paket\n"
            f"**👥 User premium:** {len(pdata.get('users', {}))} user\n"
            f"**🔒 Command dikunci:** {len(locked)} ({locked_txt})\n"
            f"**💳 Info Pembayaran:** {'✅ Sudah diset' if payment else '❌ Belum diset'}\n"
            f"**🖼️ QRIS Image:** {'✅ Sudah diset' if qris_url_p else '❌ Belum diset'}\n\n"
            "Gunakan tombol di bawah untuk mengatur sistem premium."
        ),
        color=0xFFD700
    )
    if qris_url_p:
        em.set_thumbnail(url=qris_url_p)
    em.set_footer(text="⚠️ Panel ini hanya untuk Owner/Admin")
    await ctx.send(embed=em, view=PremiumSetupView())

# ===================== MAINTENANCE PANEL =====================

class MaintenanceView(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=120)
        maint  = get_maintenance()
        active = maint.get("active", False)

        container = discord.ui.Container(accent_colour=DARK_RED)
        container.add_item(discord.ui.TextDisplay(
            "### 🔧 Maintenance Control Panel\n"
            f"**Status saat ini:** {'🔴 MAINTENANCE AKTIF' if active else '🟢 Bot Normal'}\n"
            f"**Alasan:** {maint.get('reason', '-')}\n"
            f"**Server:** {len(bot.guilds)} server\n\n"
            "Toggle maintenance untuk aktifkan/nonaktifkan dan broadcast ke semua server."
        ))
        container.add_item(discord.ui.Separator())

        toggle_btn = discord.ui.Button(label="Toggle Maintenance", emoji="🔧", style=discord.ButtonStyle.danger)
        announce_btn = discord.ui.Button(label="Set Announce Channel", emoji="📢", style=discord.ButtonStyle.secondary)
        status_btn = discord.ui.Button(label="Status Maintenance", emoji="📊", style=discord.ButtonStyle.success)
        toggle_btn.callback = self.toggle_maintenance
        announce_btn.callback = self.set_announce
        status_btn.callback = self.view_status
        row = discord.ui.ActionRow()
        row.add_item(toggle_btn)
        row.add_item(announce_btn)
        row.add_item(status_btn)
        container.add_item(row)

        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.TextDisplay("-# ⚠️ Panel ini hanya untuk Owner/Admin"))
        self.add_item(container)

    async def toggle_maintenance(self, interaction: discord.Interaction):
        maint = get_maintenance()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur maintenance!", ephemeral=True)
            return
        if maint.get("active"):
            # Matikan maintenance
            maint["active"]    = False
            maint["reason"]    = ""
            maint["started_at"] = 0
            save_maintenance(maint)
            await interaction.response.send_message("✅ **Maintenance DIMATIKAN!** Bot kembali normal.", ephemeral=True)
            # Kirim notif ke semua server
            asyncio.create_task(broadcast_maintenance(False, ""))
        else:
            # Aktifkan maintenance - minta alasan
            await interaction.response.send_message("🔧 Ketik **alasan maintenance** (60 detik):", ephemeral=True)
            try:
                msg    = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
                reason = msg.content.strip()
                maint["active"]     = True
                maint["reason"]     = reason
                maint["started_at"] = time.time()
                save_maintenance(maint)
                await interaction.followup.send(f"✅ **Maintenance AKTIF!**\nAlasan: {reason}\n\nBroadcast ke semua server sedang dikirim...", ephemeral=True)
                asyncio.create_task(broadcast_maintenance(True, reason))
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout! Maintenance tidak diaktifkan.", ephemeral=True)

    async def set_announce(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur maintenance!", ephemeral=True)
            return
        await interaction.response.send_message(
            "📢 Ketik **channel ID** untuk announce maintenance di server ini:\n"
            "*(Bot otomatis cari channel `announce`/`pengumuman`/`general` jika tidak diset)*",
            ephemeral=True
        )
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=30)
            ch_id = msg.content.strip()
            config = get_config()
            config.setdefault("maintenance_announce", {})["channel_id"] = ch_id
            save_config(config)
            await interaction.followup.send(f"✅ Announce channel diset ke ID `{ch_id}`!", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    async def view_status(self, interaction: discord.Interaction):
        maint  = get_maintenance()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur maintenance!", ephemeral=True)
            return
        active = maint.get("active", False)
        reason = maint.get("reason", "-")
        ts     = maint.get("started_at", 0)
        since  = datetime.datetime.fromtimestamp(ts, tz=WIB).strftime("%d/%m/%Y %H:%M") if ts else "-"
        await interaction.response.send_message(view=panel(
            "🔧 Status Maintenance",
            f"**Status:** {'🔴 AKTIF' if active else '🟢 NONAKTIF'}\n"
            f"**Alasan:** {reason}\n"
            f"**Aktif sejak:** {since if active else '-'}\n"
            f"**Server terdaftar:** {len(bot.guilds)}"
        ), ephemeral=True)

async def broadcast_maintenance(active: bool, reason: str):
    """
    Kirim notif maintenance ke channel yang sudah dipilih tiap server via /setmaintenancechannel.
    Kalau belum diset, auto-detect channel announce/general, fallback ke channel pertama.
    """
    config = get_config()

    for guild in bot.guilds:
        gid       = str(guild.id)
        target_ch = None

        # Prioritas 1: channel yang dipilih admin server via /setmaintenancechannel
        per_guild_ch_id = config.get(gid, {}).get("maintenance_channel_id")
        if per_guild_ch_id:
            target_ch = guild.get_channel(int(per_guild_ch_id))

        # Prioritas 2: auto-detect nama channel umum
        if not target_ch:
            for name in ["announce", "pengumuman", "announcement", "general", "umum", "bot-notif", "notifikasi"]:
                ch = discord.utils.get(guild.text_channels, name=name)
                if ch and ch.permissions_for(guild.me).send_messages:
                    target_ch = ch
                    break

        # Prioritas 3: fallback channel pertama yang bisa ditulis
        if not target_ch:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    target_ch = ch
                    break

        if not target_ch:
            continue

        try:
            if active:
                em = discord.Embed(
                    title="🔧 Bot Sedang Maintenance",
                    description=(
                        f"Hei **{guild.name}**! 👋\n\n"
                        f"Bot **{bot.user.display_name}** saat ini sedang dalam mode **MAINTENANCE**.\n\n"
                        f"**Alasan:** {reason}\n\n"
                        "Mohon bersabar ya, bot akan kembali normal secepatnya! 🙏\n\n"
                        f"*Ingin ganti channel notifikasi? Gunakan `/setmaintenancechannel`*"
                    ),
                    color=0xFF6600
                )
                em.set_footer(text="Nikoliesamphink · Bot System")
                em.timestamp = datetime.datetime.now(tz=WIB)
            else:
                em = discord.Embed(
                    title="✅ Maintenance Selesai!",
                    description=(
                        f"Hei **{guild.name}**! 🎉\n\n"
                        f"Bot **{bot.user.display_name}** sudah kembali **ONLINE** dan siap digunakan!\n\n"
                        "Gas pakai bot lagi! 🚀"
                    ),
                    color=0x00FF00
                )
                em.set_footer(text="Nikoliesamphink · Bot System")
                em.timestamp = datetime.datetime.now(tz=WIB)
            await target_ch.send(embed=em)
        except Exception as e:
            print(f"Broadcast maintenance error di {guild.name}: {e}")
        await asyncio.sleep(0.5)  # Rate limit protection

# ===================== ON GUILD JOIN =====================

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Kirim embed sambutan + info fitur bot saat join server baru."""
    target_ch = None
    for name in ["general", "umum", "chat", "lounge", "welcome", "bot", "bot-commands"]:
        ch = discord.utils.get(guild.text_channels, name=name)
        if ch and ch.permissions_for(guild.me).send_messages:
            target_ch = ch
            break
    if not target_ch and guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        target_ch = guild.system_channel
    if not target_ch:
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                target_ch = ch
                break
    if not target_ch:
        return

    # Notif ke owner bot
    if OWNER_ID:
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(view=panel(
                "🆕 Bot Masuk Server Baru!",
                (
                    f"**🏠 Server:** {guild.name}\n"
                    f"**🆔 Server ID:** `{guild.id}`\n"
                    f"**👥 Member:** {guild.member_count} orang\n"
                    f"**👑 Owner Server:** {guild.owner} (`{guild.owner_id}`)\n"
                    f"**📅 Dibuat:** {guild.created_at.strftime('%d/%m/%Y')}\n"
                    f"**🤖 Total Server Bot:** {len(bot.guilds)}"
                ),
                color=0x00FF88,
                thumbnail_url=str(guild.icon.url) if guild.icon else None,
                footer="Nikoliesamphink · Bot System"
            ))
        except Exception as e:
            print(f"Gagal DM owner saat join guild: {e}")

    maint        = get_maintenance()
    maint_status = "🔴 Under Maintenance" if maint.get("active") else "🟢 Online & Running"
    maint_reason = f"\n**Reason:** {maint.get('reason', '-')}" if maint.get("active") else ""

    fields = [
        ("🎣 Fishing & Mini Games", (
            "`dfish` / `/fish` — Go fishing & sell your catch\n"
            "`dtebak` / `/tebak` — Riddle arena with coin rewards\n"
            "`dcoins` / `/coins` — Check your coin balance\n"
            "`dleaderboard` / `/leaderboard` — Level ranking"
        )),
        ("⚠️ Moderation", (
            "`dwarn` — Warn a member\n"
            "`dkick` / `ban` / `timeout` — Moderate members\n"
            "`dclear` — Bulk delete messages\n"
            "`daddrole` / `removerole` — Manage roles"
        )),
        ("🎉 Events & Giveaways", (
            "`dgiveaway` / `/giveaway` — Start a giveaway\n"
            "`devent` / `/event` — Announce events with auto-timer\n"
            "`dsticky` — Sticky message in a channel"
        )),
        ("🎭 Roles", (
            "`/reactionrole` — Button role picker\n"
            "`daddrole` / `removerole` — Manage roles"
        )),
        ("🪙 Coins & Quest", (
            "`ddaily` / `/daily` — Klaim koin harian\n"
            "`dquest` / `/quest` — Cek progress quest mancing"
        )),
        ("🛠️ Utilities", (
            "`dautoresponse` — Auto-reply on trigger words\n"
            "`dembed` — Send custom embed messages\n"
            "`dvote` — Vote the bot & get coin rewards"
        )),
        ("👑 Premium", (
            "Some features can be locked for premium members only.\n"
            "`dpremium` — View info & order premium"
        )),
        ("📡 Bot Status & Maintenance Notifications", (
            f"**Current Status:** {maint_status}{maint_reason}\n\n"
            "Use `/setmaintenancechannel` to choose which channel receives maintenance notifications."
        )),
    ]

    try:
        await target_ch.send(view=panel(
            f"👋 Hey {guild.name}! Thanks for inviting me!",
            (
                f"I'm **{bot.user.display_name}**, a multipurpose bot made by **StartDoom**!\n\n"
                "Ready to make your server more fun and organized. "
                "Here are the features you can use:"
            ),
            thumbnail_url=str(bot.user.display_avatar.url) if bot.user.display_avatar else None,
            fields=fields,
            footer=f"Prefix: d | Slash Commands supported! | {len(bot.guilds)} servers"
        ))
    except Exception as e:
        print(f"Failed to send welcome message in {guild.name}: {e}")

async def maintenance_panel(ctx):
    await ctx.send(view=MaintenanceView())

# ===================== PREFIX COMMANDS =====================

@bot.command(name="ping", aliases=["p", "latency"])
async def ping_cmd(ctx):
    if await check_maintenance(ctx):
        return
    uid     = ctx.author.id
    latency = round(bot.latency * 1000)
    status  = (t("status_good", uid) if latency < 100
               else t("status_slow", uid) if latency < 200
               else t("status_bad", uid))
    await ctx.reply(view=panel("🏓 Pong!", t("pong", uid, ms=latency, status=status)))

@bot.command(name="fish", aliases=["mancing", "fishing"])
async def fishing_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "fish"): return
    await ctx.reply(view=FishingMainView(ctx.author.id, body_text=f"Hey **{ctx.author.display_name}**! Choose your action:"))

@bot.command(name="spin", aliases=["roda", "putar", "spinwheel"])
async def spin_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "spin"): return
    await ctx.reply(view=SpinWheelView(ctx.author.id, body_text=f"Hey **{ctx.author.display_name}**! Pencet tombol di bawah buat coba keberuntungan lo!"))

# Command teks langsung buat Inventori & Shop (BUKAN slash) — soalnya tombol/
# slash sama-sama interaction yang bisa gagal "didn't respond in time" kalau
# ack telat >3 detik. Command teks prefix gak punya batasan itu sama sekali,
# jadi ini fallback yang jauh lebih stabil dibanding harus klik tombol di panel
# "dfish" buat buka Inventori/Shop. Tombolnya tetap ada juga, dua-duanya jalan.
@bot.command(name="inventory", aliases=["inv", "inventori"])
async def inventory_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "inventory"): return
    await ctx.reply(view=InventoryView(ctx.author.id))

@bot.command(name="shop", aliases=["toko"])
async def shop_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "shop"): return
    await ctx.reply(view=ShopBuyView(ctx.author.id))

@bot.command(name="collection", aliases=["koleksi", "dex", "fishdex"])
async def collection_cmd(ctx, member: discord.Member = None):
    """Liat koleksi ikan & rod. Bisa liat punya orang lain buat pamer:
    `dkoleksi @user`"""
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "collection"): return
    target = member or ctx.author
    await ctx.reply(view=CollectionView(ctx.author.id, target))

@bot.command(name="tempa", aliases=["forge", "upgraderod"])
async def tempa_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "tempa"): return
    await ctx.reply(view=TempaView(ctx.author.id))

@bot.command(name="tebak", aliases=["riddle", "tebakan"])
async def tebak_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "tebak"): return
    uid = ctx.author.id
    gid = str(ctx.guild.id)
    if gid in active_tebakan:
        await ctx.reply(t("tebak_still_active", uid))
        return
    semua_soal = TEBAKAN_LIST + get_custom_tebakan()
    soal = random.choice(semua_soal)
    active_tebakan[gid] = {"jawaban": soal["jawaban"].lower(), "reward": soal["reward"], "asker": uid}
    await ctx.send(view=panel(
        t("tebak_title", uid),
        t("tebak_desc", uid, question=soal["soal"], reward=soal["reward"])
    ))

@bot.command(name="addtebak", aliases=["addriddle", "tambahtebak"])
@commands.has_permissions(administrator=True)
async def addtebak_cmd(ctx, *, content: str = None):
    if not content:
        await ctx.reply("❓ Format: `daddtebak Pertanyaan|jawaban|reward_koin`")
        return
    parts = content.split("|")
    if len(parts) < 2:
        await ctx.reply("❌ Format salah! Pisah soal dan jawaban dengan `|`")
        return
    soal   = parts[0].strip()
    jawaban = parts[1].strip().lower()
    reward  = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 25
    custom  = get_custom_tebakan()
    custom.append({"soal": soal, "jawaban": jawaban, "reward": reward})
    save_custom_tebakan(custom)
    await ctx.reply(view=panel("✅ Soal Tebakan Ditambah!", f"**Soal:** {soal}\n**Jawaban:** {jawaban}\n**Reward:** {reward} koin\n\nTotal soal custom: **{len(custom)}**"))

@bot.command(name="listtebak", aliases=["listriddle", "tebaklist"])
async def listtebak_cmd(ctx):
    custom = get_custom_tebakan()
    if not custom:
        await ctx.reply("📋 Belum ada soal custom. Tambah pake `daddtebak`!")
        return
    lines = [f"{i+1}. {s['soal']} → **{s['jawaban']}** ({s['reward']} koin)" for i, s in enumerate(custom)]
    await ctx.reply(view=panel(
        "📋 Soal Tebakan Custom", "\n".join(lines[:20]),
        footer=f"Total: {len(custom)} custom | Default: {len(TEBAKAN_LIST)}"
    ))

@bot.command(name="removetebak", aliases=["deltebak", "hapustebak"])
@commands.has_permissions(administrator=True)
async def removetebak_cmd(ctx, nomor: int = None):
    if not nomor:
        await ctx.reply("❓ Format: `dremovetebak [nomor]`")
        return
    custom = get_custom_tebakan()
    if nomor < 1 or nomor > len(custom):
        await ctx.reply(f"❌ Nomor tidak valid! Total soal custom: {len(custom)}")
        return
    removed = custom.pop(nomor - 1)
    save_custom_tebakan(custom)
    await ctx.reply(view=panel("🗑️ Soal Dihapus!", f"**\"{removed['soal']}\"** dihapus!"))

@bot.command(name="coins", aliases=["koin", "saldo"])
async def check_coins(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "coins"): return
    uid   = ctx.author.id
    udata = get_user_fishing(str(uid))
    await ctx.reply(view=panel(
        f"{emoji('coin')} Koin Lo",
        f"**{ctx.author.display_name}** punya **{udata['coins']} koin** {emoji('coin')}"
    ))

# --- Gift Coin (Owner Only) ---
@bot.command(name="givecoin", aliases=["giftcoin", "addcoin", "kasihkoin"])
async def givecoin_cmd(ctx, member: discord.Member = None, amount: int = None):
    """Owner bot kasih koin gratis ke user lain."""
    if ctx.author.id != OWNER_ID:
        await ctx.reply(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa kasih koin gratis!"))
        return
    if member is None or amount is None or amount <= 0:
        await ctx.reply(view=panel(
            "⚙️ Cara Pakai",
            "`dgivecoin @user <jumlah>` — Kasih koin gratis ke user (jumlah harus > 0)."
        ))
        return
    uid   = str(member.id)
    udata = get_user_fishing(uid)
    udata["coins"] += amount
    save_user_fishing(uid, udata)
    await ctx.reply(view=panel(
        f"{emoji('success')} Koin Dikirim!",
        f"**{amount}** {emoji('coin')} berhasil dikasih ke {member.mention}!\n"
        f"Total koin dia sekarang: **{udata['coins']}** {emoji('coin')}"
    ))
    try:
        await member.send(view=panel(
            f"{emoji('coin')} Lo Dapet Koin Gratis!",
            f"Owner bot ngasih lo **{amount}** {emoji('coin')} koin gratis!\n"
            f"Total koin lo sekarang: **{udata['coins']}** {emoji('coin')}"
        ))
    except Exception:
        pass

# --- Warn ---
@bot.command(name="warn", aliases=["peringatan"])
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member = None, *, reason: str = "Gak ada alasan"):
    if await check_premium_gate(ctx, "warn"): return
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    warns = get_warns()
    gid   = str(ctx.guild.id)
    uid   = str(member.id)
    warns.setdefault(gid, {}).setdefault(uid, []).append({"reason": reason, "by": str(ctx.author.id), "time": time.time()})
    save_warns(warns)
    count  = len(warns[gid][uid])
    dm_status = ""
    try:
        await member.send(view=panel(
            "⚠️ Lo Kena Warn!",
            f"Lo di-warn di **{ctx.guild.name}**\n**Alasan:** {reason}\n**Total Warn:** {count}",
            footer=f"Warn oleh: {ctx.author.display_name}"
        ))
        dm_status = "\n✅ DM terkirim."
    except:
        dm_status = "\n⚠️ Gagal kirim DM."
    await ctx.send(view=panel("⚠️ Member Di-Warn!", f"**{member.display_name}** dapet warn!\n**Alasan:** {reason}\n**Total:** {count}{dm_status}"))

@bot.command(name="warns", aliases=["warnlist", "cekwarn"])
async def check_warns(ctx, member: discord.Member = None):
    member    = member or ctx.author
    warns     = get_warns()
    user_warns = warns.get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not user_warns:
        await ctx.reply(f"✅ **{member.display_name}** bersih, gak ada warn!")
        return
    warn_text = "\n".join([f"{i+1}. {w['reason']}" for i, w in enumerate(user_warns)])
    await ctx.reply(view=panel(f"⚠️ Warn {member.display_name}", f"Total: **{len(user_warns)} warn**\n\n{warn_text}"))

# --- Moderation ---
@bot.command(name="kick", aliases=["tendang"])
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member = None, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    await member.kick(reason=reason)
    await ctx.send(view=panel("👢 Di-Kick!", f"**{member.display_name}** di-kick!\n**Alasan:** {reason}"))

@bot.command(name="ban", aliases=["banned"])
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member = None, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    await member.ban(reason=reason)
    await ctx.send(view=panel("🔨 Di-Ban!", f"**{member.display_name}** di-ban!\n**Alasan:** {reason}"))

@bot.command(name="timeout", aliases=["mute"])
@commands.has_permissions(moderate_members=True)
async def timeout_cmd(ctx, member: discord.Member = None, minutes: int = 10, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await ctx.send(view=panel("⏱️ Timeout!", f"**{member.display_name}** di-timeout {minutes} menit!\n**Alasan:** {reason}"))

@bot.command(name="move", aliases=["pindah", "vcmove"])
@commands.has_permissions(move_members=True)
async def move(ctx, member: discord.Member = None, *, channel: discord.VoiceChannel = None):
    if not member or not channel:
        await ctx.reply("❓ Format: `dmove @member #channel`")
        return
    await member.move_to(channel)
    await ctx.send(view=panel("🔀 Di-Move!", f"**{member.display_name}** dipindah ke **{channel.name}**!"))

@bot.command(name="addrole", aliases=["arole", "giverole"])
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member = None, role: discord.Role = None):
    if not member or not role:
        await ctx.reply("❓ Format: `daddrole @member @role`")
        return
    await member.add_roles(role)
    await ctx.send(view=panel("✅ Role Ditambah!", f"**{role.name}** dikasih ke **{member.display_name}**!"))

@bot.command(name="removerole", aliases=["rrole", "delrole"])
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member = None, role: discord.Role = None):
    if not member or not role:
        await ctx.reply("❓ Format: `dremoverole @member @role`")
        return
    await member.remove_roles(role)
    await ctx.send(view=panel("❌ Role Dicopot!", f"**{role.name}** dicopot dari **{member.display_name}**!"))

@bot.command(name="avatar", aliases=["av"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    await ctx.reply(view=panel(f"🖼️ Avatar {member.display_name}", "", image_url=str(member.display_avatar.url)))

@bot.command(name="userinfo", aliases=["ui", "whois"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    fields = [
        ("Username", str(member)),
        ("ID", str(member.id)),
        ("Bergabung Server", member.joined_at.strftime("%d/%m/%Y")),
        ("Akun Dibuat", member.created_at.strftime("%d/%m/%Y")),
        ("Roles", ", ".join([r.name for r in member.roles[1:]]) or "Gak ada"),
    ]
    await ctx.reply(view=panel(f"👤 Info: {member.display_name}", "", thumbnail_url=str(member.display_avatar.url), fields=fields))

@bot.command(name="clear", aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(view=panel("🗑️ Dihapus!", f"**{amount}** pesan berhasil dihapus!"))
    await asyncio.sleep(3)
    await msg.delete()

@bot.command(name="embed", aliases=["em"])
@commands.has_permissions(manage_messages=True)
async def embed_cmd(ctx, *, content: str = None):
    if not content:
        await ctx.reply("❓ Format: `dembed Judul|Deskripsi` atau `dembed Judul|Deskripsi|main`")
        return
    parts        = content.split("|")
    title        = parts[0].strip()
    desc         = parts[1].strip() if len(parts) > 1 else ""
    send_to_main = len(parts) > 2 and parts[2].strip().lower() == "main"
    target_channel = ctx.channel
    if send_to_main:
        config     = get_config()
        gid        = str(ctx.guild.id)
        main_ch_id = config.get(gid, {}).get("embed_main_channel")
        if main_ch_id:
            ch = ctx.guild.get_channel(int(main_ch_id))
            if ch:
                target_channel = ch
        else:
            await ctx.reply("⚠️ Main channel belum diset! Gunakan `dsetmainchannel #channel` dulu.")
            return
    await target_channel.send(view=panel(title, desc))
    if target_channel != ctx.channel:
        await ctx.reply(f"✅ Embed dikirim ke {target_channel.mention}!")
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="setmainchannel", aliases=["mainchannel", "setmc"])
@commands.has_permissions(administrator=True)
async def set_main_channel(ctx, channel: discord.TextChannel = None):
    if not channel:
        await ctx.reply("❓ Format: `dsetmainchannel #channel`")
        return
    config = get_config()
    gid    = str(ctx.guild.id)
    config.setdefault(gid, {})["embed_main_channel"] = str(channel.id)
    save_config(config)
    await ctx.reply(view=panel("✅ Main Channel Diset!", f"Embed notifikasi → {channel.mention}"))

@bot.command(name="autoresponse", aliases=["ar"])
@commands.has_permissions(administrator=True)
async def autoresponse_cmd(ctx, action: str = None, trigger: str = None, *, response: str = None):
    if await check_premium_gate(ctx, "autoresponse"): return
    gid = str(ctx.guild.id)
    ar  = get_autoresponse()
    ar.setdefault(gid, {})
    if action == "add" and trigger and response:
        ar[gid][trigger] = response
        save_autoresponse(ar)
        await ctx.reply(f"✅ Auto-respon **'{trigger}'** ditambah!")
    elif action == "remove" and trigger:
        ar[gid].pop(trigger, None)
        save_autoresponse(ar)
        await ctx.reply(f"✅ Auto-respon **'{trigger}'** dihapus!")
    elif action == "list":
        text = "\n".join([f"• **{k}** → {v}" for k, v in ar[gid].items()]) or "Belum ada"
        await ctx.reply(view=panel("📋 Auto-Respon", text))
    else:
        await ctx.reply("❓ Format:\n`dar add [trigger] [response]`\n`dar remove [trigger]`\n`dar list`")

@bot.command(name="sticky", aliases=["stickymsg"])
@commands.has_permissions(manage_messages=True)
async def sticky_cmd(ctx, action: str = None, *, content: str = None):
    if await check_premium_gate(ctx, "sticky"): return
    gid    = str(ctx.guild.id)
    cid    = str(ctx.channel.id)
    sticky = get_sticky()
    sticky.setdefault(gid, {})
    if action == "set" and content:
        parts   = content.split("|")
        msg_c   = parts[0].strip()
        min_msg = int(parts[1].strip()) if len(parts) > 1 else 3
        sticky[gid][cid] = {"content": msg_c, "min_messages": min_msg, "count": 0}
        save_sticky(sticky)
        await ctx.reply(f"✅ Sticky diset! Trigger tiap **{min_msg} pesan**.")
    elif action == "remove":
        sticky[gid].pop(cid, None)
        save_sticky(sticky)
        await ctx.reply("✅ Sticky dihapus!")
    else:
        await ctx.reply("❓ Format:\n`dsticky set [pesan]|[min_pesan]`\n`dsticky remove`")

@bot.command(name="giveaway", aliases=["ga"])
@commands.has_permissions(administrator=True)
async def giveaway_cmd(ctx, duration: str = None, *, prize: str = None):
    if await check_premium_gate(ctx, "giveaway"): return
    if not duration or not prize:
        await ctx.reply("❓ Format: `dgiveaway [durasi][s/m/h] [hadiah]`")
        return
    multipliers = {"s": 1, "m": 60, "h": 3600}
    unit        = duration[-1].lower()
    if unit not in multipliers:
        await ctx.reply("❌ Unit waktu salah! Pake s, m, atau h.")
        return
    seconds  = int(duration[:-1]) * multipliers[unit]
    end_time = time.time() + seconds
    end_dt   = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    msg = await ctx.send(view=panel(
        "🎉 GIVEAWAY NIH!",
        f"**Hadiah:** {prize}\n**Berakhir:** {end_dt.strftime('%d/%m/%Y %H:%M')}\n\n🎉 React buat ikutan!",
        footer="Klik 🎉 buat ikut giveaway!"
    ))
    await msg.add_reaction("🎉")
    gw_data = get_giveaways()
    gid     = str(ctx.guild.id)
    gw_data.setdefault(gid, {})[str(msg.id)] = {"prize": prize, "end_time": end_time, "channel_id": str(ctx.channel.id), "ended": False}
    save_giveaways(gw_data)

@bot.command(name="event", aliases=["announce", "pengumuman"])
@commands.has_permissions(administrator=True)
async def event_cmd(ctx, *, content: str = None):
    if await check_premium_gate(ctx, "event"): return
    if not content:
        await ctx.reply(
            "❓ Format: `devent Nama|Deskripsi|HH:MM|#channel|durasi_jam`\n"
            "• `durasi_jam` = durasi event dalam jam (opsional, default: 1)\n"
            "Contoh: `devent Turnamen ML|Yuk gaskeun!|20:00|#announce|2`"
        )
        return
    parts          = content.split("|")
    name           = parts[0].strip()
    desc           = parts[1].strip() if len(parts) > 1 else "Event seru!"
    start_time_str = parts[2].strip() if len(parts) > 2 else "Belum ditentukan"
    target_channel = ctx.channel

    # Parse channel (part 3)
    if len(parts) > 3:
        if ctx.message.channel_mentions:
            target_channel = ctx.message.channel_mentions[0]
        else:
            raw_ch = parts[3].strip().replace("#", "")
            # Bisa berupa channel ID atau nama
            if raw_ch.isdigit():
                found = ctx.guild.get_channel(int(raw_ch))
            else:
                found = discord.utils.get(ctx.guild.channels, name=raw_ch)
            if found:
                target_channel = found

    # Parse durasi jam (part 4)
    durasi_jam = 1.0
    if len(parts) > 4:
        try:
            durasi_jam = float(parts[4].strip())
            if durasi_jam <= 0:
                durasi_jam = 1.0
        except ValueError:
            durasi_jam = 1.0

    durasi_str = f"{int(durasi_jam)} jam" if durasi_jam == int(durasi_jam) else f"{durasi_jam} jam"

    event_msg = await target_channel.send(view=panel(
        f"📅 EVENT: {name}",
        (
            f"@everyone\n\n{desc}\n\n"
            f"⏰ **Jam Mulai:** {start_time_str} WIB\n"
            f"⏱️ **Durasi:** {durasi_str}\n\n"
            "📢 Jangan sampe ketinggalan! Gas ikutan! 🔥"
        ),
        footer=f"Event oleh {ctx.author.display_name}"
    ))
    if target_channel != ctx.channel:
        await ctx.reply(f"✅ Event **{name}** dikirim ke {target_channel.mention}!")
    try:
        now_wib    = datetime.datetime.now(tz=WIB)
        naive      = datetime.datetime.strptime(start_time_str, "%H:%M")
        event_time = now_wib.replace(hour=naive.hour, minute=naive.minute, second=0, microsecond=0)
        if event_time <= now_wib:
            event_time += datetime.timedelta(days=1)
        end_time   = event_time + datetime.timedelta(hours=durasi_jam)
        delay      = (event_time - now_wib).total_seconds()

        async def send_event_lifecycle(tc, ev_msg, ev_name, ev_desc, ev_ts, start_ts, end_ts, dur_str):
            # === MULAI EVENT ===
            wait_start = max(0, (start_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_start)
            start_view = panel(
                f"🚨 EVENT MULAI: {ev_name}!",
                (
                    f"**{ev_desc}**\n\n"
                    f"🔥 **EVENT DIMULAI SEKARANG!**\n"
                    f"⏰ Jam Mulai: **{ev_ts} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n"
                    f"🏁 Berakhir: **{end_ts.strftime('%H:%M')} WIB**"
                ),
                color=0xFF4500,
                footer="Gas ikutan sebelum telat! 🔥"
            )
            try:
                await ev_msg.edit(view=start_view)
            except:
                pass
            try:
                await tc.send(content="@everyone 🚨 **EVENT DIMULAI SEKARANG!** 🚨")
            except:
                pass

            # === SELESAI EVENT ===
            wait_end = max(0, (end_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_end)
            end_view = panel(
                f"🏁 EVENT SELESAI: {ev_name}",
                (
                    f"**{ev_desc}**\n\n"
                    f"✅ Event telah **BERAKHIR**!\n"
                    f"⏰ Mulai: **{ev_ts} WIB** | Selesai: **{end_ts.strftime('%H:%M')} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n\n"
                    "Makasih udah ikutan! 🎉"
                ),
                color=0x95A5A6,
                footer="Event telah berakhir."
            )
            try:
                await ev_msg.edit(view=end_view)
            except:
                pass
            try:
                await tc.send(content=f"🏁 **Event {ev_name} telah selesai!** Makasih semua yang ikutan!")
            except:
                pass

        asyncio.create_task(send_event_lifecycle(
            target_channel, event_msg, name, desc, start_time_str,
            event_time, end_time, durasi_str
        ))
        if target_channel == ctx.channel:
            await ctx.reply(
                f"✅ Event **{name}** dikirim!\n"
                f"⏰ Mulai: **{start_time_str} WIB** ({int(delay//60)} menit lagi)\n"
                f"⏱️ Durasi: **{durasi_str}** | Selesai: **{end_time.strftime('%H:%M')} WIB**"
            )
    except ValueError:
        if target_channel == ctx.channel:
            await ctx.reply(f"✅ Event **{name}** dikirim! ⚠️ Format jam tidak valid, auto-announce dinonaktifkan.")

@bot.command(name="addemoji", aliases=["ae", "addemote"])
@commands.has_permissions(manage_emojis=True)
async def addemoji_cmd(ctx):
    """
    Usage: daddemoji <emoji1> <emoji2> ...
    Langsung parse emoji dari pesan yang sama — tidak perlu kirim ulang.
    """
    # Ambil semua custom emoji dari pesan command itu sendiri
    emojis_found = ctx.message.emojis
    if not emojis_found:
        await ctx.reply(
            view=panel(
                "❌ Tidak Ada Emoji",
                "Sertakan emoji custom yang mau ditambah langsung di pesan command!\n\n"
                "**Contoh:** `daddemoji :NamaEmoji: :EmojiLain:`"
            )
        )
        return
    added   = []
    failed  = []
    for emoji in emojis_found:
        try:
            url = f"https://cdn.discordapp.com/emojis/{emoji.id}.{'gif' if emoji.animated else 'png'}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    img_bytes = await resp.read()
            new_emoji = await ctx.guild.create_custom_emoji(name=emoji.name, image=img_bytes)
            added.append(str(new_emoji))
        except Exception as e:
            failed.append(f"`{emoji.name}` ({str(e)[:60]})")
    desc = ""
    if added:
        desc += f"**✅ Berhasil ditambah ({len(added)}):**\n{' '.join(added)}\n\n"
    if failed:
        desc += f"**❌ Gagal ({len(failed)}):**\n" + "\n".join(failed)
    if not desc:
        desc = "Tidak ada emoji yang berhasil diproses."
    await ctx.reply(view=panel("🖼️ Hasil Add Emoji", desc))

# ===================== PREMIUM COMMAND (User) =====================

@bot.command(name="premium", aliases=["prem", "vip"])
async def premium_user_cmd(ctx):
    if await check_maintenance(ctx):
        return
    pdata    = get_premium_data()
    uid      = str(ctx.author.id)
    u_prem   = pdata.get("users", {}).get(uid, {})
    pkgs     = get_premium_packages()
    settings = pdata.get("settings", {})
    webhook_url = settings.get("webhook_url", "")

    # ── Sudah Premium: tampilkan status card ────────────────────────────────
    if u_prem.get("active") and (not u_prem.get("expires_at") or time.time() < u_prem.get("expires_at", 0)):
        exp_at      = u_prem.get("expires_at")
        activated   = u_prem.get("activated_at", 0)
        exp_dt      = datetime.datetime.fromtimestamp(exp_at, tz=WIB) if exp_at else None
        act_dt      = datetime.datetime.fromtimestamp(activated, tz=WIB) if activated else None
        exp_txt     = exp_dt.strftime("%d %B %Y, %H:%M") + " WIB" if exp_dt else "Lifetime"
        act_txt     = act_dt.strftime("%d %B %Y") if act_dt else "-"
        # Hitung sisa hari
        if exp_at:
            sisa_detik = max(0, int(exp_at - time.time()))
            sisa_hari  = sisa_detik // 86400
            sisa_jam   = (sisa_detik % 86400) // 3600
            sisa_txt   = f"{sisa_hari}d {sisa_jam}h remaining"
            # Progress bar (10 kotak)
            total_dur  = u_prem.get("duration_days", 30) * 86400 or 1
            pct        = max(0.0, min(1.0, (exp_at - time.time()) / total_dur))
            filled     = int(pct * 10)
            bar        = "█" * filled + "░" * (10 - filled)
            bar_txt    = f"`[{bar}]` {int(pct*100)}%"
        else:
            sisa_txt = "Lifetime Access"
            bar_txt  = "`[██████████]` ∞"
        locked  = get_locked_commands()
        cmd_txt = " · ".join([f"`{cmd}`" for cmd in locked]) if locked else "*All commands unlocked*"
        em = discord.Embed(
            title="👑 Your Premium Status",
            color=0xFFD700
        )
        em.set_thumbnail(url=ctx.author.display_avatar.url)
        em.add_field(
            name="━━━━━━━━━━━━━━━━━━━━━━",
            value=(
                f"**Package** · {u_prem.get('package', 'Premium')}\n"
                f"**Activated** · {act_txt}\n"
                f"**Expires** · {exp_txt}\n"
                f"**Time Left** · {sisa_txt}"
            ),
            inline=False
        )
        em.add_field(name="⏳ Subscription Progress", value=bar_txt, inline=False)
        em.add_field(name="🔓 Premium Commands", value=cmd_txt, inline=False)
        em.set_footer(text="Nikoliesamphink · Premium System · Thank you for your support! 🙏")
        await ctx.reply(embed=em)
        return

    # ── Belum Premium: tampilkan halaman utama premium ───────────────────────
    payment_info  = settings.get("payment_info", "Contact admin for payment info.")
    locked        = get_locked_commands()
    locked_txt    = " · ".join([f"`{cmd}`" for cmd in locked]) if locked else "*None*"
    qris_url_main = settings.get("qris_url", "")

    # Build paket cards
    badges     = ["🥉 Starter", "🥈 Popular", "🥇 Best Value"]
    pkg_lines  = []
    for i, (k, v) in enumerate(pkgs.items()):
        badge = badges[i] if i < len(badges) else "👑 Elite"
        desc  = v.get("description", "")
        pkg_lines.append(
            f"{badge}\n"
            f"**{k}** — **{v['price']}**\n"
            f"⏳ {v['duration_days']} days access"
            + (f"\n_{desc}_" if desc else "")
        )
    pkg_text = "\n\n".join(pkg_lines) if pkg_lines else "No packages available."

    em = discord.Embed(
        title="👑 StartDoom — Premium",
        description=(
            "Unlock exclusive features and support the bot!\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0xFFD700
    )
    em.add_field(name="🔒 Locked Commands", value=locked_txt, inline=False)
    em.add_field(name="━━━━━━━━━━━━━━━━━━━━━━", value="**📦 Available Packages**", inline=False)
    em.add_field(name="​", value=pkg_text, inline=False)
    em.add_field(
        name="💳 Payment Info",
        value=f"```{payment_info}```",
        inline=False
    )
    em.add_field(
        name="📌 How to Order",
        value=(
            "1️⃣ Select a package below\n"
            "2️⃣ Complete the payment\n"
            "3️⃣ Send your payment proof\n"
            "4️⃣ Wait for admin approval\n"
            "5️⃣ Get your premium access! 🎉"
        ),
        inline=False
    )
    if qris_url_main:
        em.set_image(url=qris_url_main)
    em.set_footer(text="Nikoliesamphink · Premium System · Select a package below to order")

    pkg_options = [discord.SelectOption(
        label=k,
        description=f"{v['price']} · {v['duration_days']} days",
        emoji="👑"
    ) for k, v in pkgs.items()]

    class OrderPremiumView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            if pkg_options:
                select = discord.ui.Select(placeholder="🛒 Select a package to order...", options=pkg_options)
                select.callback = self.select_package
                self.add_item(select)
            self.selected_pkg = None

        async def select_package(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Ini bukan order lo!", ephemeral=True)
                return
            self.selected_pkg = interaction.data["values"][0]
            pkg = pkgs.get(self.selected_pkg, {})
            # Tampilkan QRIS + instruksi kirim bukti
            pdata_inner  = get_premium_data()
            payment_info = pdata_inner.get("settings", {}).get("payment_info", "Hubungi admin untuk info pembayaran.")
            qris_url     = pdata_inner.get("settings", {}).get("qris_url", "")

            info_em = discord.Embed(
                title=f"💳 Order Summary — {self.selected_pkg}",
                description=(
                    "Please complete your payment and send the proof below.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=0xFFD700
            )
            info_em.add_field(
                name="📦 Package Details",
                value=(
                    f"**Package** · {self.selected_pkg}\n"
                    f"**Price** · {pkg.get('price', '?')}\n"
                    f"**Duration** · {pkg.get('duration_days', 30)} days\n"
                    f"**Description** · {pkg.get('description', '-')}"
                ),
                inline=False
            )
            info_em.add_field(
                name="💳 Payment Method",
                value=f"```{payment_info}```",
                inline=False
            )
            info_em.add_field(
                name="📋 Steps",
                value=(
                    "1️⃣ Transfer to the account above\n"
                    "2️⃣ Take a screenshot of your payment\n"
                    "3️⃣ **Send the screenshot here** (as image attachment)\n"
                    "4️⃣ Wait for admin approval — usually within 24 hours\n\n"
                    "⏰ *Timeout: 120 seconds*"
                ),
                inline=False
            )
            if qris_url:
                info_em.set_image(url=qris_url)
            info_em.set_footer(text="Nikoliesamphink · Send your payment proof after transfer")
            await interaction.response.send_message(embed=info_em, ephemeral=True)

            try:
                # Tunggu bukti: bisa pesan teks, gambar attachment, atau keduanya
                confirm_msg = await bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == interaction.user.id,
                    timeout=120
                )
                order_note   = confirm_msg.content[:500] if confirm_msg.content else "(Tidak ada teks)"
                order_id     = hashlib.md5(f"{interaction.user.id}{time.time()}".encode()).hexdigest()[:8].upper()
                duration     = pkg.get("duration_days", 30)
                price_str    = pkg.get("price", "?")

                # Cek apakah ada gambar attachment
                proof_image_url = None
                if confirm_msg.attachments:
                    att = confirm_msg.attachments[0]
                    if any(att.filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]):
                        proof_image_url = att.url

                orders = get_premium_orders()
                orders[order_id] = {
                    "user_id": str(interaction.user.id), "username": str(interaction.user),
                    "guild_id": str(ctx.guild.id), "guild_name": ctx.guild.name,
                    "note": order_note, "package": self.selected_pkg,
                    "duration_days": duration, "price": price_str,
                    "proof_image_url": proof_image_url,
                    "status": "pending", "ordered_at": time.time()
                }
                save_premium_orders(orders)

                # Build order embed untuk owner — clean receipt style
                has_image = proof_image_url is not None
                order_em  = discord.Embed(
                    title="🛒 New Premium Order",
                    description=(
                        "A new premium order has been submitted and is awaiting your review.\n"
                        "━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    color=0xFFD700
                )
                order_em.set_thumbnail(url=interaction.user.display_avatar.url)
                order_em.add_field(
                    name="👤 Customer",
                    value=(
                        f"{interaction.user.mention}\n"
                        f"`{interaction.user}` · ID: `{interaction.user.id}`\n"
                        f"Server: **{ctx.guild.name}**"
                    ),
                    inline=False
                )
                order_em.add_field(
                    name="📦 Order Details",
                    value=(
                        f"**Package** · {self.selected_pkg}\n"
                        f"**Price** · {price_str}\n"
                        f"**Duration** · {duration} days\n"
                        f"**Order ID** · `{order_id}`\n"
                        f"**Submitted** · {datetime.datetime.now(tz=WIB).strftime('%d %B %Y, %H:%M')} WIB"
                    ),
                    inline=False
                )
                order_em.add_field(
                    name="📝 Payment Note",
                    value=f"```{order_note[:400]}```",
                    inline=False
                )
                order_em.add_field(
                    name="🖼️ Payment Proof",
                    value="✅ Image attached below" if has_image else "❌ No image provided",
                    inline=False
                )
                if proof_image_url:
                    order_em.set_image(url=proof_image_url)
                order_em.set_footer(text=f"Nikoliesamphink · Order ID: {order_id}")

                sent_ok = False
                if webhook_url:
                    try:
                        async with aiohttp.ClientSession() as session:
                            wh = discord.Webhook.from_url(webhook_url, session=session)
                            await wh.send(embed=order_em, view=PremiumOrderView(order_id, interaction.user.id, str(ctx.guild.id)))
                            sent_ok = True
                    except Exception as e:
                        print(f"Webhook error: {e}")
                if not sent_ok and OWNER_ID:
                    try:
                        owner = await bot.fetch_user(OWNER_ID)
                        await owner.send(embed=order_em, view=PremiumOrderView(order_id, interaction.user.id, str(ctx.guild.id)))
                    except Exception as e:
                        print(f"DM owner error: {e}")

                conf_em = discord.Embed(
                    title="✅ Order Submitted Successfully!",
                    description=(
                        "Your order has been sent to the admin for review.\n"
                        "━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    color=0x00FF88
                )
                conf_em.add_field(
                    name="🧾 Order Receipt",
                    value=(
                        f"**Order ID** · `{order_id}`\n"
                        f"**Package** · {self.selected_pkg}\n"
                        f"**Price** · {price_str}\n"
                        f"**Duration** · {duration} days\n"
                        f"**Submitted** · {datetime.datetime.now(tz=WIB).strftime('%d %B %Y, %H:%M')} WIB"
                    ),
                    inline=False
                )
                conf_em.add_field(
                    name="⏳ What's Next?",
                    value=(
                        "• Admin will review your payment proof\n"
                        "• You will receive a **DM notification** once approved\n"
                        "• Approval is usually within **24 hours**\n\n"
                        "Save your **Order ID** for reference: `" + order_id + "`"
                    ),
                    inline=False
                )
                conf_em.set_footer(text="Nikoliesamphink · Premium System · Thank you for your order!")
                await interaction.followup.send(embed=conf_em, ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout! Order dibatalkan.", ephemeral=True)

    await ctx.reply(embed=em, view=OrderPremiumView())

# ===================== DAILY LOGIN COMMAND =====================

@bot.command(name="daily", aliases=["login", "harian", "claim"])
async def daily_cmd(ctx):
    """Klaim koin harian, streak makin panjang makin gede bonusnya."""
    if await check_maintenance(ctx):
        return
    if await check_premium_gate(ctx, "daily"):
        return
    uid    = str(ctx.author.id)
    result = perform_daily_claim(uid)

    if not result["success"]:
        sisa_h, sisa_m = result["sisa_s"] // 3600, (result["sisa_s"] % 3600) // 60
        await ctx.reply(view=panel(
            "⏰ Udah Klaim Daily Hari Ini!",
            f"Sabar bro, klaim lagi dalam **{sisa_h} jam {sisa_m} menit**."
        ))
        return

    await ctx.reply(view=panel(
        f"{emoji('daily')} Daily Login Diklaim!",
        (
            f"Makasih udah mampir **{ctx.author.display_name}**! 🔥\n\n"
            f"**{emoji('coin')} Koin Didapat:** +{result['base_reward']} (base) + {result['streak_bonus']} (streak bonus) = **{result['total_reward']} koin**\n"
            f"**{emoji('streak')} Streak Lo:** {result['streak']} hari berturut-turut\n"
            f"**{emoji('coin')} Total Koin:** {result['total_coins']}\n\n"
            f"Balik lagi besok biar streak-nya jalan terus!"
        ),
        thumbnail_url=str(ctx.author.display_avatar.url),
        color=0x00FF88,
        footer="Nikoliesamphink | Daily Login"
    ))


# ===================== QUEST MANCING COMMAND =====================

@bot.command(name="quest", aliases=["quests", "misi"])
async def quest_cmd(ctx):
    """Buka panel checklist Daily/Weekly/Quests (gambar, tombol Claim)."""
    if await check_maintenance(ctx):
        return
    if await check_premium_gate(ctx, "quest"):
        return
    await send_checklist_panel(ctx.reply, ctx.author, tab="daily")


# ===================== NO-PREFIX COMMAND (Owner Only) =====================

@bot.command(name="noprefix", aliases=["np"])
async def noprefix_cmd(ctx, action: str = None, member: discord.Member = None):
    """Owner bot kasih/cabut akses no-prefix ke user lain."""
    if ctx.author.id != OWNER_ID:
        await ctx.reply(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa atur no-prefix access!"))
        return

    users = get_noprefix_users()

    if action is None or action.lower() == "list":
        if not users:
            desc = "Belum ada user yang dikasih akses no-prefix."
        else:
            desc = "\n".join([f"• <@{u}>" for u in users])
        await ctx.reply(view=panel("📋 Daftar User No-Prefix", desc))
        return

    action = action.lower()
    if action not in ("add", "remove") or member is None:
        await ctx.reply(view=panel(
            "⚙️ Cara Pakai",
            "`dnoprefix add @user` — Kasih akses no-prefix\n"
            "`dnoprefix remove @user` — Cabut akses no-prefix\n"
            "`dnoprefix list` — Lihat semua user dengan akses no-prefix"
        ))
        return

    uid = str(member.id)
    if action == "add":
        if uid in users:
            await ctx.reply(view=panel(f"{emoji('fail')} Udah Punya Akses", f"{member.mention} udah punya akses no-prefix bro!"))
            return
        users.append(uid)
        save_noprefix_users(users)
        await ctx.reply(view=panel(f"{emoji('success')} No-Prefix Diaktifkan", f"{member.mention} sekarang bisa pakai command tanpa prefix `d`!"))
    else:
        if uid not in users:
            await ctx.reply(view=panel(f"{emoji('fail')} Gak Ketemu", f"{member.mention} emang belum punya akses no-prefix."))
            return
        users.remove(uid)
        save_noprefix_users(users)
        await ctx.reply(view=panel(f"{emoji('success')} No-Prefix Dicabut", f"Akses no-prefix {member.mention} udah dicabut."))


# ===================== EMOJI SERVER COMMAND (Owner Only) =====================

@bot.command(name="setemoji", aliases=["emojiset", "seteemoji"])
async def setemoji_cmd(ctx, key: str = None, custom_emoji: str = None):
    """Owner bot bisa ganti emoji unicode default bot dengan emoji custom server."""
    if ctx.author.id != OWNER_ID:
        await ctx.reply(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa atur emoji bot!"))
        return

    cfg = get_emoji_config()

    if key is None or key.lower() == "list":
        lines = [f"`{k}` → {cfg.get(k, DEFAULT_EMOJIS[k])} {'*(custom)*' if k in cfg else '*(default)*'}" for k in DEFAULT_EMOJIS]
        await ctx.reply(view=panel("🖼️ Emoji Bot Saat Ini", "\n".join(lines)))
        return

    key = key.lower()
    if key not in DEFAULT_EMOJIS:
        opts = ", ".join([f"`{k}`" for k in DEFAULT_EMOJIS])
        await ctx.reply(view=panel("❌ Key Tidak Valid", f"Key yang tersedia: {opts}"))
        return

    if custom_emoji is None:
        await ctx.reply(view=panel(
            "⚙️ Cara Pakai",
            f"`dsetemoji {key} <emoji_server>` — Set emoji custom untuk `{key}`\n"
            f"`dsetemoji {key} reset` — Balikin ke emoji default\n"
            f"`dsetemoji list` — Lihat semua emoji yang bisa diatur"
        ))
        return

    if custom_emoji.lower() == "reset":
        cfg.pop(key, None)
        save_emoji_config(cfg)
        await ctx.reply(view=panel(f"{emoji('success')} Emoji Direset", f"`{key}` balik ke default: {DEFAULT_EMOJIS[key]}"))
        return

    # Validasi: harus emoji custom server (format <:name:id> / <a:name:id>) atau unicode emoji biasa
    is_custom_guild_emoji = bool(re.match(r"^<a?:\w+:\d+>$", custom_emoji.strip()))
    if not is_custom_guild_emoji and len(custom_emoji.strip()) > 4:
        await ctx.reply(view=panel(
            f"{emoji('fail')} Emoji Gak Valid",
            "Kirim emoji custom server (misal: `<:namaemoji:123456789>`) atau emoji unicode biasa."
        ))
        return

    cfg[key] = custom_emoji.strip()
    save_emoji_config(cfg)
    await ctx.reply(view=panel(f"{emoji('success')} Emoji Diset!", f"`{key}` sekarang jadi {custom_emoji.strip()}"))


# ===================== HELP COMMAND =====================


@bot.command(name="help", aliases=["h"])
async def help_cmd(ctx):
    if await check_maintenance(ctx):
        return
    fields = [
        ("🎣 Fishing", f"`fish` — Mancing (ikan masuk inventori)\n`coins` `daily` — Cek koin & klaim harian {emoji('coin')}\n`quest` — Panel checklist Daily/Weekly/Quests (gambar)"),
        ("💰 Jual Ikan", "Buka `Inventori` di panel `fish` → tombol **Jual Semua** atau dropdown buat jual 1 jenis ikan"),
        ("🎰 Spin Wheel", "`spin` / `/spin` — Putar pake koin, siapa tau dapet rod langka!"),
        ("🧠 Tebak-Tebakan", "`tebak` `addtebak` `listtebak` `removetebak` | `/tebak` (Arena) `/tambahsoal`"),
        ("⚠️ Mod", "`warn` `warns` `kick` `ban` `timeout` `move` `clear`"),
        ("👤 Info", "`avatar` `userinfo` `ping`"),
        ("🎭 Role", "`addrole` `removerole` | `/reactionrole`"),
        ("📢 Utility", "`embed` `setmainchannel` `sticky` `autoresponse` `giveaway` `event` `addemoji`"),
        ("👑 Premium", "`premium` — Lihat info & order premium"),
        ("🗳️ Vote", "`vote` — Link vote Top.gg | `claimvote` — Claim reward vote"),
    ]
    if ctx.author.id == OWNER_ID:
        fields.append((
            "👑 Owner Only",
            "`noprefix add/remove/list @user` — Kasih/cabut akses command tanpa prefix\n"
            "`setemoji <key> <emoji>` — Ganti emoji bot pakai emoji custom server\n"
            "`setmaintenancechannel #channel` — Pilih channel notif maintenance\n"
            "`givecoin @user <jumlah>` — Kasih koin gratis ke user"
        ))
    await ctx.reply(view=panel(
        "📖 StartDoom — Help", "Your complete multipurpose server bot!",
        fields=fields,
        footer="Prefix: d | Semua command bisa pake slash juga! | Ketik dquest buat cek progress mancing lo"
    ))

# ===================== SLASH COMMANDS =====================

@tree.command(name="ping", description="Cek latency bot")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(view=panel("🏓 Pong!", f"**Latency:** `{latency}ms`\n**Status:** {'🟢 Lancar' if latency < 100 else '🟡 Agak lambat' if latency < 200 else '🔴 Lambat'}"))

@tree.command(name="fish", description="Mulai mancing!")
async def slash_fish(interaction: discord.Interaction):
    maint = get_maintenance()
    if maint.get("active") and interaction.user.id != OWNER_ID:
        await interaction.response.send_message(view=panel("🔧 Maintenance", f"Bot sedang maintenance.\n**Alasan:** {maint.get('reason','')}", color=0xFF6600), ephemeral=True)
        return
    if await check_premium_gate_slash(interaction, "fish"): return
    await interaction.response.send_message(view=FishingMainView(interaction.user.id, body_text=f"Hey **{interaction.user.display_name}**! Choose your action:"))

@tree.command(name="spin", description="Putar spin wheel pake koin, siapa tau dapet rod langka!")
async def slash_spin(interaction: discord.Interaction):
    maint = get_maintenance()
    if maint.get("active") and interaction.user.id != OWNER_ID:
        await interaction.response.send_message(view=panel("🔧 Maintenance", f"Bot sedang maintenance.\n**Alasan:** {maint.get('reason','')}", color=0xFF6600), ephemeral=True)
        return
    if await check_premium_gate_slash(interaction, "spin"): return
    await interaction.response.send_message(view=SpinWheelView(interaction.user.id, body_text=f"Hey **{interaction.user.display_name}**! Pencet tombol di bawah buat coba keberuntungan lo!"))


@tree.command(name="reactionrole", description="Setup reaction role dengan button")
@app_commands.describe(judul="Judul embed", deskripsi="Deskripsi", role1="Role pertama", emoji1="Emoji 1", label1="Label 1", role2="Role kedua", emoji2="Emoji 2", label2="Label 2")
@app_commands.default_permissions(administrator=True)
async def slash_reactionrole(interaction: discord.Interaction, judul: str, deskripsi: str, role1: discord.Role, emoji1: str = "🎭", label1: str = "Ambil Role", role2: discord.Role = None, emoji2: str = "🎭", label2: str = "Ambil Role 2"):
    if await check_premium_gate_slash(interaction, "reactionrole"): return
    roles_config = [{"role_id": role1.id, "label": label1, "emoji": emoji1}]
    if role2:
        roles_config.append({"role_id": role2.id, "label": label2, "emoji": emoji2})
    view = ReactionRoleView(roles_config, title=judul, description=deskripsi)
    await interaction.response.send_message(view=view)

@tree.command(name="giveaway", description="Mulai giveaway!")
@app_commands.describe(durasi_menit="Durasi dalam menit", hadiah="Hadiah giveaway")
@app_commands.default_permissions(administrator=True)
async def slash_giveaway(interaction: discord.Interaction, durasi_menit: int, hadiah: str):
    if await check_premium_gate_slash(interaction, "giveaway"): return
    end_time = time.time() + durasi_menit * 60
    end_dt   = datetime.datetime.now() + datetime.timedelta(minutes=durasi_menit)
    em = panel("🎉 GIVEAWAY NIH!", f"**Hadiah:** {hadiah}\n**Berakhir:** {end_dt.strftime('%d/%m/%Y %H:%M')}\n\n🎉 React buat ikutan!")
    await interaction.response.send_message(view=em)
    msg = await interaction.original_response()
    await msg.add_reaction("🎉")
    gw_data = get_giveaways()
    gw_data.setdefault(str(interaction.guild.id), {})[str(msg.id)] = {"prize": hadiah, "end_time": end_time, "channel_id": str(interaction.channel.id), "ended": False}
    save_giveaways(gw_data)

@tree.command(name="warn", description="Warn member")
@app_commands.describe(member="Member yang di-warn", alasan="Alasan warn")
@app_commands.default_permissions(manage_messages=True)
async def slash_warn(interaction: discord.Interaction, member: discord.Member, alasan: str = "Gak ada alasan"):
    warns = get_warns()
    gid   = str(interaction.guild.id)
    uid   = str(member.id)
    warns.setdefault(gid, {}).setdefault(uid, []).append({"reason": alasan, "by": str(interaction.user.id), "time": time.time()})
    save_warns(warns)
    count = len(warns[gid][uid])
    dm_status = ""
    try:
        await member.send(view=panel(
            "⚠️ Lo Kena Warn!",
            f"Server: **{interaction.guild.name}**\n**Alasan:** {alasan}\n**Total:** {count}",
            footer=f"Warn oleh: {interaction.user.display_name}"
        ))
        dm_status = "\n✅ DM terkirim."
    except:
        dm_status = "\n⚠️ Gagal kirim DM."
    await interaction.response.send_message(view=panel("⚠️ Di-Warn!", f"**{member.display_name}** dapet warn!\n**Alasan:** {alasan}\n**Total:** {count}{dm_status}"))

@tree.command(name="kick", description="Kick member")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member, alasan: str = "Gak ada alasan"):
    await member.kick(reason=alasan)
    await interaction.response.send_message(view=panel("👢 Di-Kick!", f"**{member.display_name}** dikick.\n**Alasan:** {alasan}"))

@tree.command(name="ban", description="Ban member")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member, alasan: str = "Gak ada alasan"):
    await member.ban(reason=alasan)
    await interaction.response.send_message(view=panel("🔨 Di-Ban!", f"**{member.display_name}** dibanned.\n**Alasan:** {alasan}"))

@tree.command(name="timeout", description="Timeout member")
@app_commands.default_permissions(moderate_members=True)
async def slash_timeout(interaction: discord.Interaction, member: discord.Member, menit: int = 10, alasan: str = "Gak ada alasan"):
    until = discord.utils.utcnow() + datetime.timedelta(minutes=menit)
    await member.timeout(until, reason=alasan)
    await interaction.response.send_message(view=panel("⏱️ Timeout!", f"**{member.display_name}** di-timeout {menit} menit!"))

@tree.command(name="clear", description="Hapus pesan")
@app_commands.describe(jumlah="Jumlah pesan yang dihapus")
@app_commands.default_permissions(manage_messages=True)
async def slash_clear(interaction: discord.Interaction, jumlah: int = 5):
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=jumlah)
    await interaction.followup.send(f"✅ {jumlah} pesan dihapus!", ephemeral=True)

@tree.command(name="avatar", description="Lihat avatar member")
async def slash_avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    await interaction.response.send_message(view=panel(f"🖼️ Avatar {member.display_name}", "", image_url=str(member.display_avatar.url)))

@tree.command(name="userinfo", description="Info lengkap user")
async def slash_userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    fields = [
        ("Username",  str(member)),
        ("ID",        str(member.id)),
        ("Join Date", member.joined_at.strftime("%d/%m/%Y")),
        ("Roles",     ", ".join([r.name for r in member.roles[1:]]) or "Gak ada"),
    ]
    await interaction.response.send_message(view=panel(f"👤 Info {member.display_name}", "", thumbnail_url=str(member.display_avatar.url), fields=fields))

@tree.command(name="addrole", description="Tambah role ke member")
@app_commands.default_permissions(manage_roles=True)
async def slash_addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await interaction.response.send_message(view=panel("✅ Role Ditambah!", f"**{role.name}** → **{member.display_name}**!"))

@tree.command(name="removerole", description="Copot role dari member")
@app_commands.default_permissions(manage_roles=True)
async def slash_removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(view=panel("❌ Role Dicopot!", f"**{role.name}** dicopot dari **{member.display_name}**!"))

@tree.command(name="embed", description="Kirim embed message")
@app_commands.describe(judul="Judul embed", deskripsi="Isi embed", ke_main_channel="Kirim ke main channel?")
@app_commands.default_permissions(manage_messages=True)
async def slash_embed(interaction: discord.Interaction, judul: str, deskripsi: str, ke_main_channel: bool = False):
    target_channel = interaction.channel
    if ke_main_channel:
        config     = get_config()
        main_ch_id = config.get(str(interaction.guild.id), {}).get("embed_main_channel")
        if main_ch_id:
            ch = interaction.guild.get_channel(int(main_ch_id))
            if ch:
                target_channel = ch
        else:
            await interaction.response.send_message("⚠️ Main channel belum diset!", ephemeral=True)
            return
    await target_channel.send(view=panel(judul, deskripsi))
    msg = f"✅ Embed dikirim ke {target_channel.mention}!" if target_channel != interaction.channel else "✅ Embed terkirim!"
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="sticky", description="Setup sticky message")
@app_commands.describe(aksi="set atau remove", pesan="Isi sticky", min_pesan="Min pesan trigger")
@app_commands.default_permissions(manage_messages=True)
async def slash_sticky(interaction: discord.Interaction, aksi: str, pesan: str = None, min_pesan: int = 3):
    gid    = str(interaction.guild.id)
    cid    = str(interaction.channel.id)
    sticky = get_sticky()
    sticky.setdefault(gid, {})
    if aksi == "set" and pesan:
        sticky[gid][cid] = {"content": pesan, "min_messages": min_pesan, "count": 0}
        save_sticky(sticky)
        await interaction.response.send_message(f"✅ Sticky diset! Trigger tiap **{min_pesan} pesan**.", ephemeral=True)
    elif aksi == "remove":
        sticky[gid].pop(cid, None)
        save_sticky(sticky)
        await interaction.response.send_message("✅ Sticky dihapus!", ephemeral=True)
    else:
        await interaction.response.send_message("❓ Aksi: `set` atau `remove`", ephemeral=True)

@tree.command(name="autoresponse", description="Setup auto response")
@app_commands.describe(aksi="add/remove/list", trigger="Kata trigger", balasan="Balasan bot")
@app_commands.default_permissions(administrator=True)
async def slash_autoresponse(interaction: discord.Interaction, aksi: str, trigger: str = None, balasan: str = None):
    gid = str(interaction.guild.id)
    ar  = get_autoresponse()
    ar.setdefault(gid, {})
    if aksi == "add" and trigger and balasan:
        ar[gid][trigger] = balasan
        save_autoresponse(ar)
        await interaction.response.send_message(f"✅ Auto-respon **'{trigger}'** ditambah!", ephemeral=True)
    elif aksi == "remove" and trigger:
        ar[gid].pop(trigger, None)
        save_autoresponse(ar)
        await interaction.response.send_message(f"✅ Auto-respon **'{trigger}'** dihapus!", ephemeral=True)
    elif aksi == "list":
        text = "\n".join([f"• **{k}** → {v}" for k, v in ar.get(gid, {}).items()]) or "Belum ada"
        await interaction.response.send_message(view=panel("📋 Auto-Respon", text), ephemeral=True)
    else:
        await interaction.response.send_message("❓ Aksi: `add`, `remove`, `list`", ephemeral=True)

@tree.command(name="event", description="Kirim event ke channel dengan durasi otomatis")
@app_commands.describe(
    nama="Nama event",
    deskripsi="Deskripsi event",
    jam_mulai="Jam mulai WIB format HH:MM (contoh: 20:00)",
    durasi_jam="Durasi event dalam jam (contoh: 2 = 2 jam, 0.5 = 30 menit)",
    channel="Channel tujuan announce (opsional)"
)
@app_commands.default_permissions(administrator=True)
async def slash_event(
    interaction: discord.Interaction,
    nama: str,
    deskripsi: str,
    jam_mulai: str,
    durasi_jam: float = 1.0,
    channel: discord.TextChannel = None
):
    if durasi_jam <= 0:
        durasi_jam = 1.0
    target_channel = channel or interaction.channel
    durasi_str = f"{int(durasi_jam)} jam" if durasi_jam == int(durasi_jam) else f"{durasi_jam} jam"

    event_msg = await target_channel.send(view=panel(
        f"📅 EVENT: {nama}",
        (
            f"@everyone\n\n{deskripsi}\n\n"
            f"⏰ **Jam Mulai:** {jam_mulai} WIB\n"
            f"⏱️ **Durasi:** {durasi_str}\n\n"
            "📢 Gas ikutan! 🔥"
        ),
        footer=f"Event oleh {interaction.user.display_name}"
    ))
    reply_text   = f"✅ Event **{nama}** dikirim ke {target_channel.mention}!"
    try:
        now_wib    = datetime.datetime.now(tz=WIB)
        naive      = datetime.datetime.strptime(jam_mulai, "%H:%M")
        event_time = now_wib.replace(hour=naive.hour, minute=naive.minute, second=0, microsecond=0)
        if event_time <= now_wib:
            event_time += datetime.timedelta(days=1)
        end_time   = event_time + datetime.timedelta(hours=durasi_jam)
        delay      = (event_time - now_wib).total_seconds()

        async def send_event_lifecycle_slash(tc, ev_msg, ev_name, ev_desc, ev_ts, start_ts, end_ts, dur_str):
            # === MULAI EVENT ===
            wait_start = max(0, (start_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_start)
            start_view = panel(
                f"🚨 EVENT MULAI: {ev_name}!",
                (
                    f"**{ev_desc}**\n\n"
                    f"🔥 **EVENT DIMULAI SEKARANG!**\n"
                    f"⏰ Jam Mulai: **{ev_ts} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n"
                    f"🏁 Berakhir: **{end_ts.strftime('%H:%M')} WIB**"
                ),
                color=0xFF4500,
                footer="Gas ikutan sebelum telat! 🔥"
            )
            try:
                await ev_msg.edit(view=start_view)
            except:
                pass
            try:
                await tc.send(content="@everyone 🚨 **EVENT DIMULAI SEKARANG!** 🚨")
            except:
                pass

            # === SELESAI EVENT ===
            wait_end = max(0, (end_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_end)
            end_view = panel(
                f"🏁 EVENT SELESAI: {ev_name}",
                (
                    f"**{ev_desc}**\n\n"
                    f"✅ Event telah **BERAKHIR**!\n"
                    f"⏰ Mulai: **{ev_ts} WIB** | Selesai: **{end_ts.strftime('%H:%M')} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n\n"
                    "Makasih udah ikutan! 🎉"
                ),
                color=0x95A5A6,
                footer="Event telah berakhir."
            )
            try:
                await ev_msg.edit(view=end_view)
            except:
                pass
            try:
                await tc.send(content=f"🏁 **Event {ev_name} telah selesai!** Makasih semua yang ikutan!")
            except:
                pass

        asyncio.create_task(send_event_lifecycle_slash(
            target_channel, event_msg, nama, deskripsi, jam_mulai,
            event_time, end_time, durasi_str
        ))
        reply_text += (
            f"\n⏰ Mulai: **{jam_mulai} WIB** ({int(delay//60)} menit lagi)"
            f"\n⏱️ Durasi: **{durasi_str}** | Selesai: **{end_time.strftime('%H:%M')} WIB**"
        )
    except ValueError:
        reply_text += "\n⚠️ Format jam tidak valid (gunakan HH:MM), auto-announce dinonaktifkan."
    await interaction.response.send_message(reply_text, ephemeral=True)

@tree.command(name="tebak", description="Buka Arena Tebak-Tebakan!")
@app_commands.describe(
    max_ronde="Jumlah ronde (1-30, default 5)",
    taunt="Kalimat menyindir untuk yang tidak bisa jawab",
    loser_role="Role yang dikasih ke yang kalah/tidak jawab (opsional)"
)
@app_commands.default_permissions(administrator=True)
async def slash_tebak(
    interaction: discord.Interaction,
    max_ronde: int = 5,
    taunt: str = "Belajar dulu sono bro, masa gitu aja ga bisa! 😂",
    loser_role: discord.Role = None
):
    if await check_premium_gate_slash(interaction, "tebak"): return
    gid = str(interaction.guild.id)

    # Cek arena sudah aktif
    if gid in arena_tebak:
        await interaction.response.send_message(
            "⚠️ Masih ada **Arena Tebak** yang aktif di server ini! Tunggu sampai selesai dulu.",
            ephemeral=True
        )
        return

    # Validasi max_ronde
    max_ronde = max(1, min(30, max_ronde))

    loser_role_id = loser_role.id if loser_role else None

    # Buat sesi baru
    sess = ArenaSession(
        host_id      = interaction.user.id,
        max_ronde    = max_ronde,
        taunt_text   = taunt,
        loser_role_id= loser_role_id
    )
    sess.channel_id = interaction.channel_id
    arena_tebak[gid] = sess

    em = discord.Embed(
        title="🏟️ ARENA TEBAK-TEBAKAN DIBUKA!",
        description=(
            f"**Host:** {interaction.user.mention}\n"
            f"**Max Ronde:** {max_ronde}\n"
            f"**Taunt Kalah:** {taunt}\n"
            f"**Loser Role:** {loser_role.mention if loser_role else '➖ Tidak diset'}\n\n"
            "**📋 Langkah selanjutnya:**\n"
            f"1. Host tambah soal via `/tambahsoal` (min 1 soal, max {max_ronde} soal)\n"
            "2. Member klik **🙋 Join Arena** untuk ikut\n"
            "3. Host klik **▶️ Mulai Arena** saat semua siap\n\n"
            "⚠️ Jawab soal langsung di **chat channel ini**!"
        ),
        color=0xFF4500
    )
    em.set_footer(text=f"Arena oleh {interaction.user.display_name} | Peserta: 0")
    em.timestamp = datetime.datetime.now(tz=WIB)

    view = ArenaLobbyView(gid, interaction.user.id)
    await interaction.response.send_message(embed=em, view=view)
    msg  = await interaction.original_response()
    sess.lobby_message_id = msg.id

@tree.command(name="tambahsoal", description="Tambah soal untuk Arena Tebak yang sedang aktif (host/admin only)")
@app_commands.describe(
    soal="Pertanyaan yang akan ditampilkan ke peserta",
    jawaban="Jawaban benar (hanya terlihat oleh kamu via DM)",
    reward="Reward koin untuk yang menjawab benar (default 25)"
)
@app_commands.default_permissions(administrator=True)
async def slash_tambahsoal(
    interaction: discord.Interaction,
    soal: str,
    jawaban: str,
    reward: int = 25
):
    gid  = str(interaction.guild.id)
    sess = arena_tebak.get(gid)

    if not sess:
        await interaction.response.send_message(
            "❌ Tidak ada Arena Tebak aktif! Buat dulu via `/tebak`.",
            ephemeral=True
        )
        return

    if interaction.user.id != sess.host_id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Hanya **host** atau **admin** yang bisa tambah soal!",
            ephemeral=True
        )
        return

    if len(sess.soal_list) >= sess.max_ronde:
        await interaction.response.send_message(
            f"❌ Soal sudah penuh! Maksimal **{sess.max_ronde} soal** sesuai jumlah ronde.",
            ephemeral=True
        )
        return

    if sess.phase != "lobby":
        await interaction.response.send_message(
            "❌ Arena sudah berjalan, tidak bisa tambah soal lagi!",
            ephemeral=True
        )
        return

    sess.soal_list.append({"soal": soal, "jawaban": jawaban.lower().strip(), "reward": reward})

    # Konfirmasi ke channel (tanpa jawaban)
    await interaction.response.send_message(
        embed=discord.Embed(
            title="✅ Soal Ditambahkan!",
            description=(
                f"**Soal #{len(sess.soal_list)}:** {soal}\n"
                f"**Reward:** {reward} koin\n\n"
                f"📊 Total soal: **{len(sess.soal_list)}/{sess.max_ronde}**"
            ),
            color=0x00FF88
        ),
        ephemeral=True
    )

    # Kirim jawaban ke host via DM (ephemeral + DM supaya aman)
    try:
        dm_em = discord.Embed(
            title="🔐 Jawaban Soal Arena",
            description=(
                f"**Soal:** {soal}\n"
                f"**✅ Jawaban:** `{jawaban}`\n"
                f"**Reward:** {reward} koin\n\n"
                "⚠️ **DI INGET BRO JAWABAN SOAL LO YANG GABUT INI, "
                "KALO ILANG/LUPA GW GA BAKAL MAU BANTU LO LAGI** 💀"
            ),
            color=0xFF4500
        )
        dm_em.set_footer(text=f"Arena Server: {interaction.guild.name}")
        await interaction.user.send(embed=dm_em)
    except discord.Forbidden:
        # Kalau DM tertutup, fallback kirim ephemeral lagi
        await interaction.followup.send(
            embed=discord.Embed(
                title="⚠️ DM Tertutup!",
                description=(
                    f"Gw ga bisa DM lo! Aktifkan DM dulu.\n\n"
                    f"**Jawaban soal #{len(sess.soal_list)}:** ||`{jawaban}`||\n"
                    "*(Spoiler — klik untuk lihat)*"
                ),
                color=0xFF6600
            ),
            ephemeral=True
        )

@tree.command(name="addtebak", description="Tambah soal tebakan custom")
@app_commands.describe(soal="Pertanyaan", jawaban="Jawaban benar", reward="Reward koin")
@app_commands.default_permissions(administrator=True)
async def slash_addtebak(interaction: discord.Interaction, soal: str, jawaban: str, reward: int = 25):
    custom = get_custom_tebakan()
    custom.append({"soal": soal, "jawaban": jawaban.lower(), "reward": reward})
    save_custom_tebakan(custom)
    await interaction.response.send_message(view=panel("✅ Soal Ditambah!", f"**{soal}** → {jawaban} ({reward} koin)\nTotal: **{len(custom)}**"), ephemeral=True)

@tree.command(name="coins", description="Cek koin lo")
async def slash_coins(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "coins"): return
    udata = get_user_fishing(str(interaction.user.id))
    await interaction.response.send_message(
        view=panel(f"{emoji('coin')} Koin Lo", f"**{interaction.user.display_name}** punya **{udata['coins']} koin** {emoji('coin')}"),
        ephemeral=True
    )

@tree.command(name="givecoin", description="Owner: kasih koin gratis ke user lain")
@app_commands.describe(member="User yang mau dikasih koin", amount="Jumlah koin (> 0)")
async def slash_givecoin(interaction: discord.Interaction, member: discord.Member, amount: int):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa kasih koin gratis!"), ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message(view=panel("❌ Jumlah Gak Valid", "Jumlah koin harus lebih dari 0!"), ephemeral=True)
        return
    uid   = str(member.id)
    udata = get_user_fishing(uid)
    udata["coins"] += amount
    save_user_fishing(uid, udata)
    await interaction.response.send_message(view=panel(
        f"{emoji('success')} Koin Dikirim!",
        f"**{amount}** {emoji('coin')} berhasil dikasih ke {member.mention}!\n"
        f"Total koin dia sekarang: **{udata['coins']}** {emoji('coin')}"
    ))
    try:
        await member.send(view=panel(
            f"{emoji('coin')} Lo Dapet Koin Gratis!",
            f"Owner bot ngasih lo **{amount}** {emoji('coin')} koin gratis!\n"
            f"Total koin lo sekarang: **{udata['coins']}** {emoji('coin')}"
        ))
    except Exception:
        pass

@tree.command(name="leaderboard", description="Lihat leaderboard koin terbanyak")
async def slash_leaderboard(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "leaderboard"): return
    fdata = get_fishing_data()
    sorted_users = sorted(fdata.items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:10]
    if not sorted_users:
        await interaction.response.send_message("📊 Belum ada data koin!", ephemeral=True)
        return
    text = ""
    for i, (uid, data) in enumerate(sorted_users):
        member = interaction.guild.get_member(int(uid))
        name   = member.display_name if member else f"User {uid[:6]}"
        medal  = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        text  += f"{medal} **{name}** — {data.get('coins', 0)} {emoji('coin')}\n"
    await interaction.response.send_message(view=panel(f"{emoji('coin')} Leaderboard Koin", text))

@tree.command(name="daily", description="Klaim koin harian")
async def slash_daily(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "daily"): return
    uid    = str(interaction.user.id)
    result = perform_daily_claim(uid)

    if not result["success"]:
        sisa_h, sisa_m = result["sisa_s"] // 3600, (result["sisa_s"] % 3600) // 60
        await interaction.response.send_message(
            view=panel("⏰ Udah Klaim Daily Hari Ini!", f"Sabar bro, klaim lagi dalam **{sisa_h} jam {sisa_m} menit**."),
            ephemeral=True
        )
        return

    await interaction.response.send_message(view=panel(
        f"{emoji('daily')} Daily Login Diklaim!",
        (
            f"Makasih udah mampir **{interaction.user.display_name}**! 🔥\n\n"
            f"**{emoji('coin')} Koin Didapat:** +{result['base_reward']} (base) + {result['streak_bonus']} (streak bonus) = **{result['total_reward']} koin**\n"
            f"**{emoji('streak')} Streak Lo:** {result['streak']} hari berturut-turut\n"
            f"**{emoji('coin')} Total Koin:** {result['total_coins']}"
        ),
        thumbnail_url=str(interaction.user.display_avatar.url),
        color=0x00FF88
    ))

@tree.command(name="quest", description="Buka panel checklist Daily/Weekly/Quests (gambar) + klaim reward")
async def slash_quest(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "quest"): return
    await send_checklist_panel(interaction.response.send_message, interaction.user, tab="daily")

@tree.command(name="noprefix", description="Owner: atur akses no-prefix user lain")
@app_commands.describe(action="add / remove / list", member="User yang mau diatur")
async def slash_noprefix(interaction: discord.Interaction, action: str = "list", member: discord.Member = None):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa atur no-prefix access!"), ephemeral=True)
        return
    users = get_noprefix_users()
    action = action.lower()

    if action == "list":
        desc = "\n".join([f"• <@{u}>" for u in users]) if users else "Belum ada user yang dikasih akses no-prefix."
        await interaction.response.send_message(view=panel("📋 Daftar User No-Prefix", desc), ephemeral=True)
        return

    if action not in ("add", "remove") or member is None:
        await interaction.response.send_message(view=panel("⚙️ Cara Pakai", "`/noprefix add @user` · `/noprefix remove @user` · `/noprefix list`"), ephemeral=True)
        return

    uid = str(member.id)
    if action == "add":
        if uid in users:
            await interaction.response.send_message(view=panel(f"{emoji('fail')} Udah Punya Akses", f"{member.mention} udah punya akses no-prefix bro!"), ephemeral=True)
            return
        users.append(uid)
        save_noprefix_users(users)
        await interaction.response.send_message(view=panel(f"{emoji('success')} No-Prefix Diaktifkan", f"{member.mention} sekarang bisa pakai command tanpa prefix `d`!"))
    else:
        if uid not in users:
            await interaction.response.send_message(view=panel(f"{emoji('fail')} Gak Ketemu", f"{member.mention} emang belum punya akses no-prefix."), ephemeral=True)
            return
        users.remove(uid)
        save_noprefix_users(users)
        await interaction.response.send_message(view=panel(f"{emoji('success')} No-Prefix Dicabut", f"Akses no-prefix {member.mention} udah dicabut."))

@tree.command(name="setemoji", description="Owner: atur emoji custom server buat bot")
@app_commands.describe(key="Nama key emoji (contoh: coin, fish, quest)", custom_emoji="Emoji custom server, atau 'reset'")
async def slash_setemoji(interaction: discord.Interaction, key: str = "list", custom_emoji: str = None):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(view=panel("❌ No Permission!", "Cuma Owner Bot yang bisa atur emoji bot!"), ephemeral=True)
        return
    cfg = get_emoji_config()
    key = key.lower()

    if key == "list":
        lines = [f"`{k}` → {cfg.get(k, DEFAULT_EMOJIS[k])} {'*(custom)*' if k in cfg else '*(default)*'}" for k in DEFAULT_EMOJIS]
        await interaction.response.send_message(view=panel("🖼️ Emoji Bot Saat Ini", "\n".join(lines)), ephemeral=True)
        return

    if key not in DEFAULT_EMOJIS:
        opts = ", ".join([f"`{k}`" for k in DEFAULT_EMOJIS])
        await interaction.response.send_message(view=panel("❌ Key Tidak Valid", f"Key yang tersedia: {opts}"), ephemeral=True)
        return

    if custom_emoji is None:
        await interaction.response.send_message(view=panel("⚙️ Cara Pakai", f"`/setemoji {key} <emoji_server>` atau `/setemoji {key} reset`"), ephemeral=True)
        return

    if custom_emoji.lower() == "reset":
        cfg.pop(key, None)
        save_emoji_config(cfg)
        await interaction.response.send_message(view=panel(f"{emoji('success')} Emoji Direset", f"`{key}` balik ke default: {DEFAULT_EMOJIS[key]}"), ephemeral=True)
        return

    is_custom_guild_emoji = bool(re.match(r"^<a?:\w+:\d+>$", custom_emoji.strip()))
    if not is_custom_guild_emoji and len(custom_emoji.strip()) > 4:
        await interaction.response.send_message(view=panel(f"{emoji('fail')} Emoji Gak Valid", "Kirim emoji custom server (misal: `<:namaemoji:123456789>`) atau emoji unicode biasa."), ephemeral=True)
        return

    cfg[key] = custom_emoji.strip()
    save_emoji_config(cfg)
    await interaction.response.send_message(view=panel(f"{emoji('success')} Emoji Diset!", f"`{key}` sekarang jadi {custom_emoji.strip()}"), ephemeral=True)

# ===================== SET MAINTENANCE CHANNEL =====================

@tree.command(name="setmaintenancechannel", description="Pilih channel untuk nerima notifikasi maintenance bot")
@app_commands.describe(channel="Channel tujuan notifikasi maintenance")
@app_commands.default_permissions(administrator=True)
async def slash_setmaintenancechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Admin server bisa pilih channel notif maintenance untuk server mereka sendiri."""
    if not channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.response.send_message(
            view=panel("❌ Bot Tidak Punya Akses", f"Bot tidak punya izin kirim pesan di {channel.mention}!"),
            ephemeral=True
        )
        return
    config = get_config()
    gid    = str(interaction.guild.id)
    config.setdefault(gid, {})["maintenance_channel_id"] = str(channel.id)
    save_config(config)
    await interaction.response.send_message(view=panel(
        "📡 Channel Notifikasi Maintenance Diset!",
        (
            f"✅ Channel **{channel.mention}** akan menerima notifikasi saat bot:\n\n"
            "• 🔧 **Masuk maintenance** (beserta alasannya)\n"
            "• ✅ **Selesai maintenance** (bot kembali online)\n\n"
            "Lo bisa ubah channel ini kapan saja dengan jalankan command ini lagi."
        ),
        color=0x00FF88,
        footer=f"Nikoliesamphink · Bot System · {interaction.guild.name}"
    ), ephemeral=True)
    # Kirim konfirmasi ke channel yang dipilih
    try:
        await channel.send(view=panel(
            "📡 Channel Ini Dipilih untuk Notifikasi Maintenance",
            (
                f"Channel ini akan menerima notifikasi dari bot **{bot.user.display_name}** saat:\n\n"
                "• 🔧 Bot masuk mode **Maintenance**\n"
                "• ✅ Bot kembali **Online** setelah maintenance\n\n"
                "*Pengaturan ini dilakukan oleh owner bot.*"
            ),
            footer="Nikoliesamphink · Bot System"
        ))
    except:
        pass

@bot.command(name="setmaintenancechannel", aliases=["setmaintchannel", "maintchannel"])
@commands.has_permissions(administrator=True)
async def prefix_setmaintenancechannel(ctx, channel: discord.TextChannel = None):
    """Admin server bisa pilih channel notif maintenance untuk server mereka sendiri."""
    if not channel:
        await ctx.reply("❓ Format: `dsetmaintenancechannel #channel`")
        return
    if not channel.permissions_for(ctx.guild.me).send_messages:
        await ctx.reply(view=panel("❌ Bot Tidak Punya Akses", f"Bot tidak punya izin kirim pesan di {channel.mention}!"))
        return
    config = get_config()
    gid    = str(ctx.guild.id)
    config.setdefault(gid, {})["maintenance_channel_id"] = str(channel.id)
    save_config(config)
    await ctx.reply(view=panel(
        "📡 Channel Notifikasi Maintenance Diset!",
        (
            f"✅ Channel **{channel.mention}** akan menerima notifikasi saat bot:\n\n"
            "• 🔧 **Masuk maintenance** (beserta alasannya)\n"
            "• ✅ **Selesai maintenance** (bot kembali online)\n\n"
            "Lo bisa ubah channel ini kapan saja dengan jalankan command ini lagi."
        ),
        color=0x00FF88,
        footer=f"Nikoliesamphink · Bot System · {ctx.guild.name}"
    ))
    try:
        await channel.send(view=panel(
            "📡 Channel Ini Dipilih untuk Notifikasi Maintenance",
            (
                f"Channel ini akan menerima notifikasi dari bot **{bot.user.display_name}** saat:\n\n"
                "• 🔧 Bot masuk mode **Maintenance**\n"
                "• ✅ Bot kembali **Online** setelah maintenance\n\n"
                "*Pengaturan ini dilakukan oleh owner bot.*"
            ),
            footer="Nikoliesamphink · Bot System"
        ))
    except:
        pass

# ===================== VOTE TOP.GG COMMANDS =====================

@bot.command(name="vote", aliases=["upvote"])
async def vote_cmd(ctx):
    """Kirim link vote bot di Top.gg."""
    if await check_maintenance(ctx):
        return
    uid        = ctx.author.id
    bot_id_str = BOT_ID or str(bot.user.id)
    vote_url   = f"https://top.gg/bot/{bot_id_str}/vote"
    vote_btn   = discord.ui.Button(label="Vote di Top.gg", emoji=emoji('vote'), style=discord.ButtonStyle.link, url=vote_url)
    await ctx.reply(view=panel(
        t("vote_title", uid),
        t("vote_desc", uid,
            url=vote_url, min=VOTE_REWARD_MIN, max=VOTE_REWARD_MAX,
            pct=VOTE_BONUS_PCTS, mins=VOTE_BONUS_MINS, cd=VOTE_COOLDOWN_H
        ),
        thumbnail_url=str(bot.user.display_avatar.url),
        buttons=[vote_btn],
        footer="Nikoliesamphink | Vote every 12 hours!"
    ))

@bot.command(name="claimvote", aliases=["voteclaim"])
async def claimvote_cmd(ctx):
    """Claim reward setelah vote di Top.gg."""
    if await check_maintenance(ctx):
        return
    uid = str(ctx.author.id)

    # Cek cooldown claim
    record      = get_vote_record(uid)
    last_claim  = record.get("last_claim", 0)
    cooldown_s  = VOTE_COOLDOWN_H * 3600
    elapsed     = time.time() - last_claim
    if elapsed < cooldown_s:
        sisa_s   = int(cooldown_s - elapsed)
        sisa_h   = sisa_s // 3600
        sisa_m   = (sisa_s % 3600) // 60
        next_dt  = datetime.datetime.fromtimestamp(last_claim + cooldown_s, tz=WIB)
        uid_cv = ctx.author.id
        await ctx.reply(view=panel(
            t("vote_cooldown_title", uid_cv),
            t("vote_cooldown_desc", uid_cv,
                next_time=next_dt.strftime("%d/%m/%Y %H:%M"),
                hours=sisa_h, mins=sisa_m
            )
        ))
        return

    # Cek apakah user sudah vote via Top.gg API atau cache webhook
    async with ctx.typing():
        voted = await check_user_voted_topgg(ctx.author.id)

    if not voted:
        bot_id_str = BOT_ID or str(bot.user.id)
        vote_url   = f"https://top.gg/bot/{bot_id_str}/vote"
        uid_nv = ctx.author.id
        await ctx.reply(view=panel(
            t("vote_not_voted_title", uid_nv),
            t("vote_not_voted_desc", uid_nv, url=vote_url),
            color=0xFF4444,
            footer="Vote dulu bro baru bisa claim reward!"
        ))
        return

    # Berikan reward
    reward = random.randint(VOTE_REWARD_MIN, VOTE_REWARD_MAX)
    udata  = get_user_fishing(uid)
    udata["coins"] += reward
    save_user_fishing(uid, udata)
    bump_weekly(uid, "vote", 1)

    # Aktifkan vote bonus fishing
    activate_vote_bonus(uid)
    bonus_until = datetime.datetime.fromtimestamp(
        vote_bonus_cache.get(uid, time.time()), tz=WIB
    ).strftime("%H:%M")

    # Update record
    record["last_claim"] = time.time()
    record["total_claimed"] = record.get("total_claimed", 0) + 1
    set_vote_record(uid, record)

    # Hapus dari cache webhook supaya tidak double claim
    _vote_cache.discard(uid)

    uid_cl = ctx.author.id
    await ctx.reply(view=panel(
        t("vote_claimed_title", uid_cl),
        t("vote_claimed_desc", uid_cl,
            user=ctx.author.display_name, reward=reward,
            total=udata["coins"], pct=VOTE_BONUS_PCTS,
            mins=VOTE_BONUS_MINS, until=bonus_until,
            count=record["total_claimed"], cd=VOTE_COOLDOWN_H
        ),
        color=0x00FF88,
        thumbnail_url=str(ctx.author.display_avatar.url),
        footer="Nikoliesamphink | Thanks for voting! 🗳️"
    ))

# ===================== TOP.GG WEBHOOK SERVER (Flask) =====================

def create_vote_webhook_app():
    """Buat Flask app untuk menerima webhook vote dari Top.gg."""
    if not FLASK_AVAILABLE:
        return None

    app = Flask(__name__)

    @app.route("/dblwebhook", methods=["POST"])
    @app.route("/webhook", methods=["POST"])  # alias — Top.gg lo kepasang ke path ini
    def dbl_webhook():
        print(f"📨 Webhook masuk dari {flask_request.remote_addr} → {flask_request.path}")

        # Validasi password webhook
        auth = flask_request.headers.get("Authorization", "")
        if WEBHOOK_PASSWORD and auth != WEBHOOK_PASSWORD:
            print(f"❌ Webhook DITOLAK: Authorization header gak cocok sama WEBHOOK_PASSWORD.")
            abort(401)

        data = flask_request.get_json(silent=True)
        if not data:
            raw = flask_request.get_data(as_text=True)
            print(f"❌ Webhook DITOLAK: body bukan JSON valid. Raw: {raw[:200]}")
            abort(400)

        user_id = str(data.get("user", ""))
        bot_id  = str(data.get("bot", ""))
        vote_type = data.get("type", "upvote")  # "upvote" atau "test"
        print(f"✅ Webhook payload valid: user={user_id or '-'} bot={bot_id or '-'} type={vote_type}")

        if user_id:
            # Simpan ke cache dan JSON
            _vote_cache.add(user_id)
            vote_data = get_vote_data()
            if user_id not in vote_data:
                vote_data[user_id] = {}
            vote_data[user_id]["last_vote_webhook"] = time.time()
            vote_data[user_id]["vote_type"] = vote_type
            save_vote_data(vote_data)
            print(f"✅ Vote webhook diterima: user {user_id} | type: {vote_type}")

            # DM user biar dia tau votenya udah masuk & bisa langsung dclaimvote.
            # Flask jalan di thread terpisah dari asyncio, jadi dijadwalin pake
            # run_coroutine_threadsafe ke event loop bot.
            try:
                asyncio.run_coroutine_threadsafe(notify_vote_dm(user_id), bot.loop)
            except Exception as e:
                print(f"⚠️  Gagal schedule DM vote: {e}")

        return "OK", 200

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok", "bot": str(bot.user) if bot.user else "starting"}, 200

    return app

async def run_flask_webhook():
    """Jalankan Flask webhook server di thread terpisah."""
    if not FLASK_AVAILABLE:
        print("⚠️  Flask tidak tersedia, webhook server tidak dijalankan.")
        return
    if not WEBHOOK_PASSWORD:
        print("⚠️  WEBHOOK_PASSWORD belum diset, webhook server tidak dijalankan.")
        return

    app = create_vote_webhook_app()
    if not app:
        return

    import threading

    def run_app():
        # Gunakan threaded=False agar tidak konflik dengan asyncio
        app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)

    thread = threading.Thread(target=run_app, daemon=True)
    thread.start()
    print(f"✅ Vote webhook server berjalan di port {PORT} → /dblwebhook & /webhook")

# ===================== ERROR HANDLERS =====================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(view=panel("❌ No Permission!", "Lo gak punya izin buat command ini!"))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply(view=panel("❌ Member Gak Ketemu!", "Member yang lo mention gak ada!"))
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Error: {error}")

# ===================== RUN =====================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
