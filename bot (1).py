import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
import random
import re
import time
import datetime
import zoneinfo
import hashlib
import aiohttp
from pathlib import Path

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
PREFIX = "!Doom"
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
    return ["!Doom ", "!Kingdoom ", "!doom ", "!kingdoom "]

bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None, case_insensitive=True)
tree = bot.tree

# ===================== FISHING DATA (Default - bisa di-override dari JSON) =====================
DEFAULT_FISHES = [
    {"name": "Ikan Lele",     "sell_price": 15,   "luck": 35.0, "emoji": "🐟"},
    {"name": "Ikan Mas",      "sell_price": 25,   "luck": 30.0, "emoji": "🐠"},
    {"name": "Ikan Gurame",   "sell_price": 40,   "luck": 15.0, "emoji": "🐡"},
    {"name": "Ikan Salmon",   "sell_price": 60,   "luck": 10.0, "emoji": "🐟"},
    {"name": "Ikan Tuna",     "sell_price": 100,  "luck": 5.0,  "emoji": "🐟"},
    {"name": "Ikan Hiu",      "sell_price": 200,  "luck": 2.5,  "emoji": "🦈"},
    {"name": "Ikan Duyung",   "sell_price": 500,  "luck": 1.5,  "emoji": "🧜"},
    {"name": "Ikan Naga",     "sell_price": 1000, "luck": 0.5,  "emoji": "🐉"},
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
# luck >= 20%  → common
# 10-20%       → uncommon
# 3-10%        → rare
# < 3%         → legendary
def get_rarity_from_luck(luck: float) -> str:
    if luck <= 0:
        return "trash"
    elif luck < 3.0:
        return "legendary"
    elif luck < 10.0:
        return "rare"
    elif luck < 20.0:
        return "uncommon"
    else:
        return "common"

RARITY_DISPLAY = {
    "legendary": ("⭐ LEGENDARY", 0xFFD700),
    "rare":      ("💎 Rare",      0x9B59B6),
    "uncommon":  ("🔵 Uncommon",  0x3498DB),
    "common":    ("⚪ Common",    DARK_RED),
    "trash":     ("💩 Trash",     0x95A5A6),
}

def get_fishing_config():
    """Load fishing config (ikan, rod, bait) dari JSON, fallback ke default."""
    cfg = load_json("fishing_config.json", {})
    fishes = cfg.get("fishes", DEFAULT_FISHES)
    rods   = cfg.get("rods",   DEFAULT_RODS)
    baits  = cfg.get("baits",  DEFAULT_BAITS)
    return fishes, rods, baits

def save_fishing_config(fishes, rods, baits):
    save_json("fishing_config.json", {"fishes": fishes, "rods": rods, "baits": baits})

def do_fish_roll(rod_name: str, bait_name: str | None):
    """Lakukan roll mancing. Return (fish_dict, rarity_str)."""
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

    # Pisah ikan normal & sampah
    normal_fishes = [f for f in fishes if f.get("luck", 0) > 0]
    trash_fishes  = [f for f in fishes if f.get("luck", 0) <= 0]

    # Hitung weight per ikan dengan luck bonus dari rod+bait
    # luck_bonus menambah luck semua ikan secara proporsional
    weights = []
    for f in normal_fishes:
        base_luck = f.get("luck", 1.0)
        adjusted  = base_luck + (base_luck * (rod_bonus + bait_bonus) / 100.0)
        weights.append(max(adjusted, 0.01))

    # Tambah slot "sampah" dengan weight tetap = max(0, 100 - sum_normal)
    total_normal = sum(weights)
    trash_weight = max(5.0, 100.0 - total_normal)

    pool    = normal_fishes + [random.choice(trash_fishes) if trash_fishes else {"name": "Sampah", "sell_price": 0, "luck": 0, "emoji": "🗑️"}]
    weights = weights + [trash_weight]

    caught = random.choices(pool, weights=weights, k=1)[0]
    rarity = get_rarity_from_luck(caught.get("luck", 0))
    return caught, rarity

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
        data[uid] = {
            "coins": 100,
            "rod": rods[0]["name"] if rods else "Pancing Bambu",
            "bait": {baits[0]["name"]: 3} if baits else {},
            "inventory": [],
            "total_catch": 0,
            "last_fish": 0,
        }
        save_fishing_data(data)
    return data[uid]

def save_user_fishing(user_id: str, udata: dict):
    data = get_fishing_data()
    data[str(user_id)] = udata
    save_fishing_data(data)

def get_warns():       return load_json("warns.json", {})
def save_warns(d):     save_json("warns.json", d)
def get_levels():      return load_json("levels.json", {})
def save_levels(d):    save_json("levels.json", d)
def get_config():      return load_json("config.json", {})
def save_config(d):    save_json("config.json", d)
def get_autoresponse():    return load_json("autoresponse.json", {})
def save_autoresponse(d):  save_json("autoresponse.json", d)
def get_sticky():      return load_json("sticky.json", {})
def save_sticky(d):    save_json("sticky.json", d)
def get_giveaways():   return load_json("giveaways.json", {})
def save_giveaways(d): save_json("giveaways.json", d)
def get_tickets():     return load_json("tickets.json", {"panels": {}, "tickets": {}})
def save_tickets(d):   save_json("tickets.json", d)
def get_premium_data():   return load_json("premium.json", {"users": {}, "settings": {}, "packages": {}, "locked_commands": []})
def save_premium_data(d): save_json("premium.json", d)
def get_premium_orders():   return load_json("premium_orders.json", {})
def save_premium_orders(d): save_json("premium_orders.json", d)

def dark_red_embed(title="", description="", **kwargs):
    return discord.Embed(title=title, description=description, color=DARK_RED, **kwargs)


# ===================== LANGUAGE SYSTEM =====================
# Bahasa: id_gaul (khusus owner bot), id (Indonesia Gaul untuk user/admin), en (default), de, ar, th, ja

SUPPORTED_LANGS = {
    "id_gaul": "🇮🇩 Indonesia Gaul (Owner Only)",
    "id":      "🇮🇩 Indonesia Gaul",
    "en":      "🇬🇧 English",
    "de":      "🇩🇪 Deutsch",
    "ar":      "🇸🇦 العربية",
    "th":      "🇹🇭 ภาษาไทย",
    "ja":      "🇯🇵 日本語",
}

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
        "id_gaul": "Command ini **terkunci** dan hanya bisa digunakan oleh member **Premium** bro!\n\n**📦 Paket Tersedia:**\n{packages}\n\n**💳 Info Pembayaran:**\n```{payment}```\n\nKetik `!Doom premium` untuk order sekarang!\n✨ Upgrade dan nikmatin semua fitur eksklusif!",
        "id":       "Command ini **terkunci** dan hanya bisa digunakan oleh member **Premium** bro!\n\n**📦 Paket Tersedia:**\n{packages}\n\n**💳 Info Pembayaran:**\n```{payment}```\n\nKetik `!Doom premium` untuk order sekarang!\n✨ Upgrade dan nikmatin semua fitur eksklusif!",
        "en":      "This command is **locked** and only available to **Premium** members!\n\n**📦 Available Packages:**\n{packages}\n\n**💳 Payment Info:**\n```{payment}```\n\nType `!Doom premium` to order now!\n✨ Upgrade and enjoy all exclusive features!",
        "de":      "Dieser Befehl ist **gesperrt** und nur für **Premium**-Mitglieder verfügbar!\n\n**📦 Verfügbare Pakete:**\n{packages}\n\n**💳 Zahlungsinfo:**\n```{payment}```\n\nTippe `!Doom premium` um jetzt zu bestellen!\n✨ Upgrade und genieße alle exklusiven Funktionen!",
        "ar":      "هذا الأمر **مقفل** ومتاح فقط للأعضاء **المميزين**!\n\n**📦 الباقات المتاحة:**\n{packages}\n\n**💳 معلومات الدفع:**\n```{payment}```\n\nاكتب `!Doom premium` للطلب الآن!\n✨ قم بالترقية واستمتع بجميع الميزات الحصرية!",
        "th":      "คำสั่งนี้**ถูกล็อค**และใช้ได้เฉพาะสมาชิก**พรีเมียม**เท่านั้น!\n\n**📦 แพ็คเกจที่มี:**\n{packages}\n\n**💳 ข้อมูลการชำระเงิน:**\n```{payment}```\n\nพิมพ์ `!Doom premium` เพื่อสั่งซื้อตอนนี้!\n✨ อัปเกรดและเพลิดเพลินกับฟีเจอร์พิเศษทั้งหมด!",
        "ja":      "このコマンドは**ロック**されており、**プレミアム**メンバーのみ利用可能です！\n\n**📦 利用可能なパッケージ:**\n{packages}\n\n**💳 支払い情報:**\n```{payment}```\n\n`!Doom premium` と入力して今すぐ注文！\n✨ アップグレードして限定機能をお楽しみください！",
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
        "id_gaul": "**{name}** dapet ikan **LANGKA** bro!\n\n{emoji} **{fish}**\n🍀 Luck: **{luck}%**\n💰 Harga jual: **+{coins} koin**{bonus_txt} (Total: {total})\n🎣 Rod: **{rod}**\n{bait_txt}",
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
        "id_gaul": "**{name}** dapet **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} koin{bonus_txt} (Total: {total})\n🎣 Rod: {rod}\n{bait_txt}",
        "id":       "**{name}** dapet **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} koin{bonus_txt} (Total: {total})\n🎣 Rod: {rod}\n{bait_txt}",
        "en":      "**{name}** caught **{fish}** [{rarity}]\n🍀 Luck: {luck}%\n💰 +{coins} coins{bonus_txt} (Total: {total})\n🎣 Rod: {rod}\n{bait_txt}",
        "de":      "**{name}** hat **{fish}** gefangen [{rarity}]\n🍀 Glück: {luck}%\n💰 +{coins} Münzen{bonus_txt} (Gesamt: {total})\n🎣 Angel: {rod}\n{bait_txt}",
        "ar":      "**{name}** اصطاد **{fish}** [{rarity}]\n🍀 الحظ: {luck}%\n💰 +{coins} عملة{bonus_txt} (المجموع: {total})\n🎣 السنارة: {rod}\n{bait_txt}",
        "th":      "**{name}** จับ **{fish}** [{rarity}]\n🍀 โชค: {luck}%\n💰 +{coins} เหรียญ{bonus_txt} (รวม: {total})\n🎣 เบ็ด: {rod}\n{bait_txt}",
        "ja":      "**{name}** が **{fish}** を釣った [{rarity}]\n🍀 ラック: {luck}%\n💰 +{coins} コイン{bonus_txt} (合計: {total})\n🎣 ロッド: {rod}\n{bait_txt}",
    },
    "fish_vote_bonus": {
        "id_gaul": "\n🗳️ **Vote Bonus aktif! +{pct}% koin** (sisa ~{mins} mnt)",
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
        "id_gaul": "{praise}\n\n**{user}** jawab bener!\n💰 Dapet **+{reward} koin** cuy!\n✅ Jawaban: **{answer}**\n🪙 Total koin lo: **{total}**",
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
        "id_gaul": "🪙 Koin Lo",
        "id":       "🪙 Koin Lo",
        "en":      "🪙 Your Coins",
        "de":      "🪙 Deine Münzen",
        "ar":      "🪙 عملاتك",
        "th":      "🪙 เหรียญของคุณ",
        "ja":      "🪙 あなたのコイン",
    },
    "coins_desc": {
        "id_gaul": "**{user}** punya **{amount} koin** 🪙",
        "id":       "**{user}** punya **{amount} koin** 🪙",
        "en":      "**{user}** has **{amount} coins** 🪙",
        "de":      "**{user}** hat **{amount} Münzen** 🪙",
        "ar":      "**{user}** لديه **{amount} عملة** 🪙",
        "th":      "**{user}** มี **{amount} เหรียญ** 🪙",
        "ja":      "**{user}** は **{amount} コイン** を持っています 🪙",
    },
    # ── VOTE ─────────────────────────────────────────────────
    "vote_title": {
        "id_gaul": "🗳️ Vote Bot di Top.gg!",
        "id":       "🗳️ Vote Bot di Top.gg!",
        "en":      "🗳️ Vote for the Bot on Top.gg!",
        "de":      "🗳️ Stimme für den Bot auf Top.gg ab!",
        "ar":      "🗳️ صوّت للبوت على Top.gg!",
        "th":      "🗳️ โหวตบอทบน Top.gg!",
        "ja":      "🗳️ Top.gg でボットに投票！",
    },
    "vote_desc": {
        "id_gaul": "**Support bot ini dengan vote di Top.gg!** 🔥\n\n🔗 **[Klik di sini untuk Vote]({url})**\n\n**🎁 Reward Vote:**\n• **{min} - {max} koin** langsung ke saldo lo!\n• **+{pct}% bonus coin mancing** selama **{mins} menit**!\n\n**⏰ Cooldown Claim:** {cd} jam\n\nSetelah vote, ketik `!Doom claimvote` untuk ambil reward! 🚀",
        "id":       "**Support bot ini dengan vote di Top.gg!** 🔥\n\n🔗 **[Klik di sini untuk Vote]({url})**\n\n**🎁 Reward Vote:**\n• **{min} - {max} koin** langsung ke saldo lo!\n• **+{pct}% bonus coin mancing** selama **{mins} menit**!\n\n**⏰ Cooldown Claim:** {cd} jam\n\nSetelah vote, ketik `!Doom claimvote` untuk ambil reward! 🚀",
        "en":      "**Support this bot by voting on Top.gg!** 🔥\n\n🔗 **[Click here to Vote]({url})**\n\n**🎁 Vote Rewards:**\n• **{min} - {max} coins** directly to your balance!\n• **+{pct}% fishing coin bonus** for **{mins} minutes**!\n\n**⏰ Claim Cooldown:** {cd} hours\n\nAfter voting, type `!Doom claimvote` to claim your reward! 🚀",
        "de":      "**Unterstütze diesen Bot durch Abstimmen auf Top.gg!** 🔥\n\n🔗 **[Hier klicken zum Abstimmen]({url})**\n\n**🎁 Abstimmungsbelohnungen:**\n• **{min} - {max} Münzen** direkt auf dein Konto!\n• **+{pct}% Angel-Münzen-Bonus** für **{mins} Minuten**!\n\n**⏰ Claim-Abklingzeit:** {cd} Stunden\n\nNach dem Abstimmen tippe `!Doom claimvote` um deine Belohnung zu erhalten! 🚀",
        "ar":      "**ادعم هذا البوت بالتصويت على Top.gg!** 🔥\n\n🔗 **[انقر هنا للتصويت]({url})**\n\n**🎁 مكافآت التصويت:**\n• **{min} - {max} عملة** مباشرة إلى رصيدك!\n• **+{pct}% مكافأة عملة الصيد** لمدة **{mins} دقيقة**!\n\n**⏰ مهلة المطالبة:** {cd} ساعات\n\nبعد التصويت، اكتب `!Doom claimvote` للمطالبة بمكافأتك! 🚀",
        "th":      "**สนับสนุนบอทนี้ด้วยการโหวตบน Top.gg!** 🔥\n\n🔗 **[คลิกที่นี่เพื่อโหวต]({url})**\n\n**🎁 รางวัลโหวต:**\n• **{min} - {max} เหรียญ** ตรงไปยังยอดเงินของคุณ!\n• **+{pct}% โบนัสเหรียญตกปลา** เป็นเวลา **{mins} นาที**!\n\n**⏰ คูลดาวน์การเคลม:** {cd} ชั่วโมง\n\nหลังจากโหวต พิมพ์ `!Doom claimvote` เพื่อรับรางวัล! 🚀",
        "ja":      "**Top.gg でボットに投票してサポートしよう！** 🔥\n\n🔗 **[こちらをクリックして投票]({url})**\n\n**🎁 投票報酬:**\n• **{min} - {max} コイン** が即座に残高へ！\n• **+{pct}% 釣りコインボーナス** が **{mins} 分間** 有効！\n\n**⏰ クレームクールダウン:** {cd} 時間\n\n投票後、`!Doom claimvote` と入力して報酬を受け取ろう！ 🚀",
    },
    "vote_not_voted_title": {
        "id_gaul": "❌ Belum Vote Bro!",
        "id":       "❌ Belum Vote Bro!",
        "en":      "❌ You Haven't Voted Yet!",
        "de":      "❌ Du hast noch nicht abgestimmt!",
        "ar":      "❌ لم تصوت بعد!",
        "th":      "❌ คุณยังไม่ได้โหวต!",
        "ja":      "❌ まだ投票していません！",
    },
    "vote_not_voted_desc": {
        "id_gaul": "Lo belum vote bot ini di Top.gg!\n\n🔗 **[Vote Sekarang di sini]({url})**\n\nSetelah vote, tunggu beberapa detik terus ketik `!Doom claimvote` lagi ya!",
        "id":       "Lo belum vote bot ini di Top.gg!\n\n🔗 **[Vote Sekarang di sini]({url})**\n\nSetelah vote, tunggu beberapa detik terus ketik `!Doom claimvote` lagi ya!",
        "en":      "You haven't voted for this bot on Top.gg yet!\n\n🔗 **[Vote Now here]({url})**\n\nAfter voting, wait a few seconds then type `!Doom claimvote` again!",
        "de":      "Du hast noch nicht für diesen Bot auf Top.gg abgestimmt!\n\n🔗 **[Jetzt hier abstimmen]({url})**\n\nNach dem Abstimmen warte ein paar Sekunden und tippe dann `!Doom claimvote` erneut!",
        "ar":      "لم تصوت لهذا البوت على Top.gg بعد!\n\n🔗 **[صوّت الآن هنا]({url})**\n\nبعد التصويت، انتظر بضع ثوانٍ ثم اكتب `!Doom claimvote` مرة أخرى!",
        "th":      "คุณยังไม่ได้โหวตบอทนี้บน Top.gg!\n\n🔗 **[โหวตตอนนี้ที่นี่]({url})**\n\nหลังจากโหวตแล้ว รอสักครู่แล้วพิมพ์ `!Doom claimvote` อีกครั้ง!",
        "ja":      "まだTop.ggでこのボットに投票していません！\n\n🔗 **[今すぐここで投票]({url})**\n\n投票後、数秒待ってから`!Doom claimvote`と入力してください！",
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
        "id_gaul": "Makasih udah vote bot ini **{user}**! 🔥\n\n**💰 Koin Didapat:** +**{reward} koin**!\n**🪙 Total Koin:** {total} koin\n\n**🎣 Vote Bonus Fishing Aktif!**\n+**{pct}% coin** dari mancing selama **{mins} menit**\n(Aktif sampai jam **{until}**) 🚀\n\n**Total Vote Lo:** {count} kali 🏆\n\nBisa claim lagi dalam **{cd} jam**!",
        "id":       "Makasih udah vote bot ini **{user}**! 🔥\n\n**💰 Koin Didapat:** +**{reward} koin**!\n**🪙 Total Koin:** {total} koin\n\n**🎣 Vote Bonus Fishing Aktif!**\n+**{pct}% coin** dari mancing selama **{mins} menit**\n(Aktif sampai jam **{until}**) 🚀\n\n**Total Vote Lo:** {count} kali 🏆\n\nBisa claim lagi dalam **{cd} jam**!",
        "en":      "Thanks for voting **{user}**! 🔥\n\n**💰 Coins Received:** +**{reward} coins**!\n**🪙 Total Coins:** {total} coins\n\n**🎣 Vote Fishing Bonus Active!**\n+**{pct}% coins** from fishing for **{mins} minutes**\n(Active until **{until}**) 🚀\n\n**Your Total Votes:** {count} times 🏆\n\nCan claim again in **{cd} hours**!",
        "de":      "Danke für deine Stimme **{user}**! 🔥\n\n**💰 Münzen erhalten:** +**{reward} Münzen**!\n**🪙 Gesamt-Münzen:** {total} Münzen\n\n**🎣 Vote-Angel-Bonus aktiv!**\n+**{pct}% Münzen** beim Angeln für **{mins} Minuten**\n(Aktiv bis **{until}**) 🚀\n\n**Deine Gesamtabstimmungen:** {count} Mal 🏆\n\nKann wieder beansprucht werden in **{cd} Stunden**!",
        "ar":      "شكراً لتصويتك **{user}**! 🔥\n\n**💰 العملات المستلمة:** +**{reward} عملة**!\n**🪙 إجمالي العملات:** {total} عملة\n\n**🎣 مكافأة الصيد بالتصويت نشطة!**\n+**{pct}% عملات** من الصيد لمدة **{mins} دقيقة**\n(نشط حتى **{until}**) 🚀\n\n**إجمالي تصويتاتك:** {count} مرة 🏆\n\nيمكن المطالبة مرة أخرى في **{cd} ساعات**!",
        "th":      "ขอบคุณที่โหวต **{user}**! 🔥\n\n**💰 เหรียญที่ได้รับ:** +**{reward} เหรียญ**!\n**🪙 เหรียญทั้งหมด:** {total} เหรียญ\n\n**🎣 โบนัสตกปลาจากการโหวตใช้งานอยู่!**\n+**{pct}% เหรียญ** จากการตกปลาเป็นเวลา **{mins} นาที**\n(ใช้งานถึง **{until}**) 🚀\n\n**โหวตทั้งหมดของคุณ:** {count} ครั้ง 🏆\n\nเคลมได้อีกครั้งใน **{cd} ชั่วโมง**!",
        "ja":      "投票してくれてありがとう **{user}**！ 🔥\n\n**💰 獲得コイン:** +**{reward} コイン**！\n**🪙 合計コイン:** {total} コイン\n\n**🎣 投票釣りボーナス有効！**\n+**{pct}% コイン** が釣りで **{mins} 分間** 有効\n(**{until}** まで) 🚀\n\n**総投票数:** {count} 回 🏆\n\n**{cd} 時間後** に再クレーム可能！",
    },
    # ── SETLANG ──────────────────────────────────────────────
    "setlang_title": {
        "id_gaul": "🌐 Pengaturan Bahasa",
        "id":       "🌐 Pengaturan Bahasa",
        "en":      "🌐 Language Settings",
        "de":      "🌐 Spracheinstellungen",
        "ar":      "🌐 إعدادات اللغة",
        "th":      "🌐 การตั้งค่าภาษา",
        "ja":      "🌐 言語設定",
    },
    "setlang_changed": {
        "id_gaul": "✅ Bahasa berhasil diubah ke **{lang}**!",
        "id":       "✅ Bahasa berhasil diubah ke **{lang}**!",
        "en":      "✅ Language successfully changed to **{lang}**!",
        "de":      "✅ Sprache erfolgreich auf **{lang}** geändert!",
        "ar":      "✅ تم تغيير اللغة بنجاح إلى **{lang}**!",
        "th":      "✅ เปลี่ยนภาษาเป็น **{lang}** สำเร็จ!",
        "ja":      "✅ 言語を **{lang}** に変更しました！",
    },
    "setlang_invalid": {
        "id_gaul": "❌ Bahasa tidak valid! Pilih: {options}",
        "id":       "❌ Bahasa tidak valid! Pilih: {options}",
        "en":      "❌ Invalid language! Choose: {options}",
        "de":      "❌ Ungültige Sprache! Wähle: {options}",
        "ar":      "❌ لغة غير صالحة! اختر: {options}",
        "th":      "❌ ภาษาไม่ถูกต้อง! เลือก: {options}",
        "ja":      "❌ 無効な言語！選択: {options}",
    },
    "setlang_current": {
        "id_gaul": "**Bahasa lo saat ini:** {lang}\n\n**Pilihan bahasa tersedia:**\n{options}\n\nGunakan: `!Doom setlang [kode]`\nContoh: `!Doom setlang id`",
        "id":       "**Bahasa lo saat ini:** {lang}\n\n**Pilihan bahasa tersedia:**\n{options}\n\nGunakan: `!Doom setlang [kode]`\nContoh: `!Doom setlang id`",
        "en":      "**Your current language:** {lang}\n\n**Available languages:**\n{options}\n\nUse: `!Doom setlang [code]`\nExample: `!Doom setlang ja`",
        "de":      "**Deine aktuelle Sprache:** {lang}\n\n**Verfügbare Sprachen:**\n{options}\n\nVerwende: `!Doom setlang [code]`\nBeispiel: `!Doom setlang de`",
        "ar":      "**لغتك الحالية:** {lang}\n\n**اللغات المتاحة:**\n{options}\n\nاستخدم: `!Doom setlang [code]`\nمثال: `!Doom setlang ar`",
        "th":      "**ภาษาปัจจุบันของคุณ:** {lang}\n\n**ภาษาที่ใช้ได้:**\n{options}\n\nใช้: `!Doom setlang [code]`\nตัวอย่าง: `!Doom setlang th`",
        "ja":      "**現在の言語:** {lang}\n\n**利用可能な言語:**\n{options}\n\n使用法: `!Doom setlang [コード]`\n例: `!Doom setlang ja`",
    },
}

# ─── Language data helpers ───────────────────────────────────────────────────

def get_lang_data() -> dict:
    return load_json("lang.json", {})

def save_lang_data(d: dict):
    save_json("lang.json", d)

def get_user_lang(user_id) -> str:
    """
    Return kode bahasa user.
    Owner bot → selalu id_gaul (tidak bisa diubah).
    User lain → dari lang.json, default 'en'.
    Jika user non-owner tersimpan sebagai 'id_gaul' (data lama), otomatis di-reset ke 'en'.
    """
    uid = str(user_id)
    if OWNER_ID and int(uid) == OWNER_ID:
        return "id_gaul"
    data = get_lang_data()
    lang = data.get(uid, "en")
    # Kalau user non-owner punya data lama "id_gaul", reset ke "en" dan simpan
    if lang == "id_gaul":
        data[uid] = "en"
        save_lang_data(data)
        return "en"
    return lang

def set_user_lang(user_id, lang_code: str):
    data = get_lang_data()
    data[str(user_id)] = lang_code
    save_lang_data(data)

def t(key: str, user_id, **kwargs) -> str:
    """
    Ambil teks terjemahan berdasarkan key dan user_id.
    Fallback: en → id_gaul → key itu sendiri.
    """
    lang = get_user_lang(user_id)
    entry = TRANSLATIONS.get(key, {})
    text  = entry.get(lang) or entry.get("en") or entry.get("id_gaul") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text

fishing_cooldowns   = {}
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

async def check_user_voted_topgg(user_id: int) -> bool:
    """
    Cek via Top.gg API apakah user sudah vote.
    Return True jika sudah vote, False jika belum atau error.
    """
    if not TOPGG_TOKEN or not BOT_ID:
        return False
    url = f"https://top.gg/api/bots/{BOT_ID}/check?userId={user_id}"
    headers = {"Authorization": TOPGG_TOKEN}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return bool(data.get("voted", 0))
    except Exception as e:
        print(f"Top.gg API error: {e}")
    # Fallback: cek cache webhook
    return str(user_id) in _vote_cache

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
    """Cek premium, return (ok, embed_notif). Jika ok=False, kirim embed_notif ke user."""
    if isinstance(ctx_or_interaction, commands.Context):
        uid = str(ctx_or_interaction.author.id)
    else:
        uid = str(ctx_or_interaction.user.id)
    if is_premium(uid):
        return True, None
    em = discord.Embed(
        title="👑 Fitur Premium",
        description=(
            "Command ini **khusus untuk member Premium** bro!\n\n"
            "Dapetin akses premium dengan ketik:\n"
            "**`!Doom premium`** untuk lihat paket & cara order.\n\n"
            "✨ Upgrade sekarang dan nikmatin semua fitur eksklusif!"
        ),
        color=0xFFD700
    )
    em.set_footer(text="DOOMINIKS PARADISE · Premium System")
    return False, em

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
        "ticket":       "Setup panel ticket",
        "leveling":     "Setup fitur leveling",
        "reactionrole": "Setup reaction role dengan button",
        "leaderboard":  "Lihat leaderboard level",
        "setlang":      "Change bot language / Ganti bahasa bot",
        "tambahsoal":   "Tambah soal untuk Arena Tebak yang sedang aktif (host/admin only)",
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



def premium_block_embed(user_id=None) -> discord.Embed:
    """Embed notifikasi command terkunci premium — tampilan profesional."""
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

    em = discord.Embed(
        title="🔒 Premium Feature",
        description=(
            "This command is **locked** and only available to **Premium** members.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "**📦 Available Packages**\n"
            f"{pkg_text}\n\n"
            "Type `!Doom premium` to see full details & order now!\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✨ Unlock all exclusive features by upgrading to Premium."
        ),
        color=0xFFD700
    )
    if qris_url:
        em.set_thumbnail(url=qris_url)
    em.set_footer(text="DOOMINIKS PARADISE · Premium System")
    return em


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
    # Tampilkan embed premium dengan nama command yang dikunci
    em = premium_block_embed(ctx.author.id)
    em.set_footer(text=f"DOOMINIKS PARADISE · Premium · Command `{command_name}` is locked")
    await ctx.reply(embed=em)
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

    em = premium_block_embed(interaction.user.id)
    em.set_footer(text=f"DOOMINIKS PARADISE · Premium · Command `/{command_name}` is locked")
    await interaction.response.send_message(embed=em, ephemeral=True)
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
    em = discord.Embed(
        title=t("maintenance_title", uid_m),
        description=t("maintenance_desc", uid_m, reason=maint.get("reason", "-")),
        color=0xFF6600
    )
    await ctx.reply(embed=em)
    return True

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} udah nyala bro!")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="DOOMINIKS PARADISE | !Doom help")
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
                elif sub == "maintenance":
                    await maintenance_panel(ctx)
                else:
                    await ctx.send(embed=dark_red_embed(
                        "⚙️ Kingdoom Control Panel",
                        "**Subcommand tersedia:**\n"
                        "• `!Kingdoom premium` — Setup sistem premium\n"
                        "• `!Kingdoom setfishing` — Setup fishing\n"
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
                # id_gaul pake praise gaul, bahasa lain tidak
                if get_user_lang(uid_w) == "id_gaul":
                    praise = random.choice(JAWABAN_BENAR_GAUL)
                    desc   = t("tebak_correct_desc", uid_w,
                                praise=praise, user=message.author.display_name,
                                reward=reward, answer=tb["jawaban"].title(), total=udata["coins"])
                else:
                    desc   = t("tebak_correct_desc", uid_w,
                                praise="", user=message.author.display_name,
                                reward=reward, answer=tb["jawaban"].title(), total=udata["coins"])
                em = dark_red_embed(t("tebak_correct_title", uid_w), desc)
                em.set_thumbnail(url=message.author.display_avatar.url)
                await message.channel.send(embed=em)
                del active_tebakan[guild_id]

    # Leveling
    if guild_id and message.content and not message.content.startswith("!"):
        await handle_leveling(message)

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
                    em  = dark_red_embed("📌 Sticky Message", s["content"])
                    sent = await message.channel.send(embed=em)
                    s["last_message_id"] = sent.id
                except:
                    pass
            sticky_data[guild_id][ch_id] = s
            save_sticky(sticky_data)

    await bot.process_commands(message)

async def handle_leveling(message):
    config = get_config()
    gid    = str(message.guild.id)
    if gid not in config or not config[gid].get("leveling_enabled", True):
        return
    levels = get_levels()
    uid    = str(message.author.id)
    if gid not in levels:
        levels[gid] = {}
    if uid not in levels[gid]:
        levels[gid][uid] = {"xp": 0, "level": 0}
    xp_gain = random.randint(10, 25)
    levels[gid][uid]["xp"] += xp_gain
    needed  = (levels[gid][uid]["level"] + 1) * 100
    if levels[gid][uid]["xp"] >= needed:
        levels[gid][uid]["level"] += 1
        levels[gid][uid]["xp"]    = 0
        new_level  = levels[gid][uid]["level"]
        channel_id = config[gid].get("level_channel")
        ch         = message.guild.get_channel(int(channel_id)) if channel_id else message.channel
        em = dark_red_embed(
            "🆙 LEVEL UP GAES!",
            f"Selamat **{message.author.mention}** naik ke level **{new_level}**! 🎉\nTerus aktif ya bro!"
        )
        em.set_thumbnail(url=message.author.display_avatar.url)
        await ch.send(embed=em)
        level_roles = config[gid].get("level_roles", {})
        if str(new_level) in level_roles:
            role = message.guild.get_role(int(level_roles[str(new_level)]))
            if role:
                try:
                    await message.author.add_roles(role)
                    await ch.send(f"🏆 {message.author.mention} dapet role **{role.name}** karena udah level {new_level}!")
                except:
                    pass
    save_levels(levels)

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

class TicketView(discord.ui.View):
    def __init__(self, panel_config):
        super().__init__(timeout=None)
        self.panel_config = panel_config
        btn = discord.ui.Button(
            label=panel_config.get("button_label", "Buka Ticket"),
            emoji=panel_config.get("button_emoji", "🎫"),
            style=discord.ButtonStyle.danger,
            custom_id=f"ticket_open_{panel_config['panel_id']}"
        )
        btn.callback = self.open_ticket
        self.add_item(btn)

    async def open_ticket(self, interaction: discord.Interaction):
        guild  = interaction.guild
        config = self.panel_config
        existing = discord.utils.get(guild.channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing:
            await interaction.response.send_message(f"Lo udah punya ticket aktif: {existing.mention} bro!", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me:           discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        # Whitelist role — otomatis bisa baca & kirim pesan di channel ticket
        for role_id in config.get("whitelist_roles", []):
            role = guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        cat = guild.get_channel(int(config["category_id"])) if config.get("category_id") else None
        ch  = await guild.create_text_channel(
            f"ticket-{interaction.user.name}",
            overwrites=overwrites, category=cat,
            topic=f"Ticket milik {interaction.user}"
        )

        em = dark_red_embed(
            f"🎫 Ticket - {interaction.user.display_name}",
            config.get("description", "Hai! Cerita masalah lo di sini, tim kami bakal bantu ASAP!")
        )
        # Thumbnail & image dari attachment yang di-upload saat setup
        if config.get("thumbnail_url"):
            em.set_thumbnail(url=config["thumbnail_url"])
        if config.get("image_url"):
            em.set_image(url=config["image_url"])
        # Tampilkan role staff di embed
        role_mentions = [guild.get_role(int(rid)).mention for rid in config.get("whitelist_roles", []) if guild.get_role(int(rid))]
        if role_mentions:
            em.add_field(name="👥 Staff yang bisa bantu", value=" ".join(role_mentions), inline=False)

        close_view = TicketCloseView(config)
        await ch.send(content=interaction.user.mention, embed=em, view=close_view)
        await interaction.response.send_message(f"Ticket lo udah kebuka bro! {ch.mention}", ephemeral=True)

class TicketCloseView(discord.ui.View):
    def __init__(self, panel_config=None):
        super().__init__(timeout=None)
        self.panel_config = panel_config or {}

    @discord.ui.button(label="Tutup Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Hanya pembuka ticket, whitelist role, atau admin yang bisa tutup
        whitelist_ids   = self.panel_config.get("whitelist_roles", [])
        user_role_ids   = [str(r.id) for r in interaction.user.roles]
        is_ticket_owner = interaction.channel.name == f"ticket-{interaction.user.name.lower()}"
        is_whitelisted  = any(rid in user_role_ids for rid in whitelist_ids)
        is_admin        = interaction.user.guild_permissions.administrator
        if not (is_ticket_owner or is_whitelisted or is_admin):
            await interaction.response.send_message("❌ Lo tidak punya izin untuk menutup ticket ini!", ephemeral=True)
            return
        em = dark_red_embed("🔒 Ticket Ditutup", f"Ticket ditutup oleh {interaction.user.mention}.\nChannel akan dihapus dalam 5 detik.")
        await interaction.response.send_message(embed=em)
        await asyncio.sleep(5)
        await interaction.channel.delete()

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


class ReactionRoleView(discord.ui.View):
    def __init__(self, roles_config):
        super().__init__(timeout=None)
        for cfg in roles_config:
            btn = discord.ui.Button(
                label=cfg["label"], emoji=cfg.get("emoji"),
                style=discord.ButtonStyle.danger,
                custom_id=f"rr_{cfg['role_id']}"
            )
            btn.callback = self.toggle_role
            self.add_item(btn)

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

class LevelingSetupView(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=300)
        self.guild_id = str(guild_id)

    @discord.ui.button(label="Toggle Leveling ON/OFF", style=discord.ButtonStyle.danger, row=0)
    async def toggle_leveling(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = get_config()
        gid    = self.guild_id
        if gid not in config:
            config[gid] = {}
        config[gid]["leveling_enabled"] = not config[gid].get("leveling_enabled", True)
        save_config(config)
        status = "✅ AKTIF" if config[gid]["leveling_enabled"] else "❌ NONAKTIF"
        await interaction.response.send_message(f"Leveling sekarang: **{status}**", ephemeral=True)

    @discord.ui.button(label="Set Channel Level", style=discord.ButtonStyle.secondary, row=0)
    async def set_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Mention channel buat notif level up:", ephemeral=True)
        try:
            msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id and m.channel_mentions, timeout=30)
            ch  = msg.channel_mentions[0]
            config = get_config()
            gid    = self.guild_id
            if gid not in config:
                config[gid] = {}
            config[gid]["level_channel"] = str(ch.id)
            save_config(config)
            await msg.reply(f"✅ Channel level up diset ke {ch.mention}!")
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @discord.ui.button(label="Set Role per Level", style=discord.ButtonStyle.secondary, row=0)
    async def set_role_level(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Ketik: `level:role_id` contoh `5:123456789`", ephemeral=True)
        try:
            msg   = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id and ":" in m.content, timeout=30)
            parts = msg.content.split(":")
            lvl, rid = parts[0].strip(), parts[1].strip()
            config = get_config()
            gid    = self.guild_id
            if gid not in config:
                config[gid] = {}
            if "level_roles" not in config[gid]:
                config[gid]["level_roles"] = {}
            config[gid]["level_roles"][lvl] = rid
            save_config(config)
            await msg.reply(f"✅ Level {lvl} akan dapet role ID {rid}!")
        except asyncio.TimeoutError:
            await interaction.followup.send("⏰ Timeout!", ephemeral=True)

# ===================== FISHING VIEWS =====================

class FishingMainView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label="🎣 Mancing", style=discord.ButtonStyle.danger, row=0)
    async def fish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ini bukan mancing lo bro!", ephemeral=True)
            return
        now = time.time()
        uid = str(interaction.user.id)
        if uid in fishing_cooldowns and now - fishing_cooldowns[uid] < 10:
            sisa = round(10 - (now - fishing_cooldowns[uid]))
            await interaction.response.send_message(
                t("fish_cooldown", interaction.user.id, secs=sisa), ephemeral=True)
            return
        fishing_cooldowns[uid] = now
        udata = get_user_fishing(uid)

        # Ambil bait pertama yang ada
        bait_list  = udata.get("bait", {})
        used_bait  = None
        for bname, qty in list(bait_list.items()):
            if qty > 0:
                bait_list[bname] -= 1
                if bait_list[bname] <= 0:
                    del bait_list[bname]
                used_bait = bname
                break
        udata["bait"] = bait_list

        caught, rarity = do_fish_roll(udata.get("rod", "Pancing Bambu"), used_bait)
        base_price  = caught.get("sell_price", 0)
        # Vote bonus: +20% coin selama VOTE_BONUS_MINS menit setelah claim vote
        vote_active  = is_vote_bonus_active(uid)
        bonus_coins  = int(base_price * VOTE_BONUS_PCTS / 100) if vote_active else 0
        sell_price   = base_price + bonus_coins
        udata["coins"]       += sell_price
        udata["total_catch"] += 1
        udata["inventory"].append(caught["name"])
        save_user_fishing(uid, udata)

        rarity_label, embed_color = RARITY_DISPLAY.get(rarity, ("⚪ Common", DARK_RED))
        luck_pct = caught.get("luck", 0)
        uid_fish = interaction.user.id

        # Info bonus vote
        bonus_txt = ""
        if vote_active:
            sisa_mnt = get_vote_bonus_remaining(uid) // 60
            bonus_txt = t("fish_vote_bonus", uid_fish,
                          pct=VOTE_BONUS_PCTS, mins=sisa_mnt)

        bonus_str = f" (+{bonus_coins} bonus vote)" if bonus_coins else ""
        bait_txt  = (t("fish_bait", uid_fish, bait=used_bait)
                     if used_bait else t("fish_no_bait", uid_fish))
        star      = "🌟" if rarity == "legendary" else "💎"

        if rarity in ("legendary", "rare"):
            em = discord.Embed(
                title=t("fish_title_rare", uid_fish,
                        star=star, rarity=rarity_label),
                description=t("fish_desc_rare", uid_fish,
                    name=interaction.user.display_name, emoji=caught["emoji"],
                    fish=caught["name"], luck=luck_pct,
                    coins=sell_price, bonus_txt=bonus_str,
                    total=udata["coins"], rod=udata["rod"], bait_txt=bait_txt
                ) + bonus_txt,
                color=embed_color
            )
            em.set_thumbnail(url=interaction.user.display_avatar.url)
            em.set_footer(text=t("fish_rare_footer", uid_fish))
        else:
            em = discord.Embed(
                title=t("fish_title_normal", uid_fish, emoji=caught["emoji"]),
                description=t("fish_desc_normal", uid_fish,
                    name=interaction.user.display_name, fish=caught["name"],
                    rarity=rarity_label, luck=luck_pct,
                    coins=sell_price, bonus_txt=bonus_str,
                    total=udata["coins"], rod=udata["rod"], bait_txt=bait_txt
                ) + bonus_txt,
                color=embed_color
            )
        await interaction.response.edit_message(embed=em, view=self)

    @discord.ui.button(label="🎒 Inventori", style=discord.ButtonStyle.secondary, row=0)
    async def inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Privasi dong!", ephemeral=True)
            return
        udata     = get_user_fishing(str(interaction.user.id))
        inv       = udata.get("inventory", [])
        inv_count = {}
        for item in inv:
            inv_count[item] = inv_count.get(item, 0) + 1
        inv_text = "\n".join([f"• {k}: x{v}" for k, v in inv_count.items()]) if inv_count else "Inventori kosong, ayo mancing dulu!"
        em = dark_red_embed(
            f"🎒 Inventori {interaction.user.display_name}",
            f"**Koin:** {udata['coins']} 🪙\n**Rod:** {udata['rod']}\n**Total Tangkapan:** {udata['total_catch']}\n\n**Ikan:**\n{inv_text}"
        )
        em.add_field(name="🪱 Umpan", value="\n".join([f"{k}: x{v}" for k, v in udata.get('bait', {}).items()]) or "Habis!", inline=True)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="🏪 Shop", style=discord.ButtonStyle.primary, row=0)
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Buka shop sendiri bro!", ephemeral=True)
            return
        fishes, rods, baits = get_fishing_config()
        udata    = get_user_fishing(str(interaction.user.id))
        rod_text  = "\n".join([f"{r['emoji']} **{r['name']}** - {r['price']} 🪙 (Tier {r['tier']}, +{r['luck_bonus']}% luck)" for r in rods])
        bait_text = "\n".join([f"{b['emoji']} **{b['name']}** - {b['price']} 🪙 (+{b['luck_bonus']}% luck)" for b in baits])
        em = dark_red_embed(
            "🏪 Fishing Shop",
            f"**Koin lo:** {udata['coins']} 🪙\n\n**🎣 Rod:**\n{rod_text}\n\n**🪱 Umpan:**\n{bait_text}"
        )
        await interaction.response.send_message(embed=em, view=ShopBuyView(interaction.user.id), ephemeral=True)

class ShopBuyView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        fishes, rods, baits = get_fishing_config()
        rod_options  = [discord.SelectOption(label=r["name"], description=f"Tier {r['tier']} - {r['price']} koin | +{r['luck_bonus']}% luck", emoji=r["emoji"]) for r in rods]
        bait_options = [discord.SelectOption(label=b["name"], description=f"{b['price']} koin | +{b['luck_bonus']}% luck", emoji=b["emoji"]) for b in baits]
        rod_select  = discord.ui.Select(placeholder="Beli Rod...",   custom_id="buy_rod",  options=rod_options)
        bait_select = discord.ui.Select(placeholder="Beli Umpan...", custom_id="buy_bait", options=bait_options)
        rod_select.callback  = self.buy_rod
        bait_select.callback = self.buy_bait
        self.add_item(rod_select)
        self.add_item(bait_select)

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
        if udata["coins"] < rod["price"]:
            await interaction.response.send_message(f"❌ Koin kurang! Butuh {rod['price']} 🪙", ephemeral=True)
            return
        udata["coins"] -= rod["price"]
        udata["rod"]    = rod["name"]
        save_user_fishing(str(interaction.user.id), udata)
        await interaction.response.send_message(f"✅ Beli **{rod['name']}**! Sisa koin: {udata['coins']} 🪙", ephemeral=True)

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
        if udata["coins"] < bait["price"]:
            await interaction.response.send_message(f"❌ Koin kurang! Butuh {bait['price']} 🪙", ephemeral=True)
            return
        udata["coins"] -= bait["price"]
        udata.setdefault("bait", {})[bait["name"]] = udata["bait"].get(bait["name"], 0) + 5
        save_user_fishing(str(interaction.user.id), udata)
        await interaction.response.send_message(f"✅ Beli **{bait['name']}** x5! Sisa koin: {udata['coins']} 🪙", ephemeral=True)

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
        save_fishing_config(DEFAULT_FISHES, DEFAULT_RODS, DEFAULT_BAITS)
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur fishing!", ephemeral=True)
            return
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
                    "Use `!Doom premium` to check your status anytime.\n"
                    "Thank you for supporting **DOOMINIKS PARADISE**! 🙏"
                ),
                inline=False
            )
            dm_em.set_footer(text="DOOMINIKS PARADISE · Premium System")
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
            dm_em.set_footer(text="DOOMINIKS PARADISE · Premium System")
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
                "📩 Message from DOOMINIKS PARADISE Admin",
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
            "ticket", "leveling", "reactionrole", "leaderboard",
            "setlang"
        ]
        avail_text = ", ".join([f"`{c}`" for c in available])

        await interaction.response.send_message(
            f"🔒 **Command yang Saat Ini Dikunci Premium:**\n"
            f"`{current}`\n\n"
            f"**Command yang Tersedia untuk Dikunci:**\n{avail_text}\n\n"
            f"**Cara pakai:**\n"
            f"Ketik nama command yang mau dikunci, pisah dengan koma.\n"
            f"Contoh: `fish, tebak, giveaway, ticket`\n\n"
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

class MaintenanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="🔧 Toggle Maintenance", style=discord.ButtonStyle.danger, row=0)
    async def toggle_maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(label="📢 Set Announce Channel", style=discord.ButtonStyle.secondary, row=0)
    async def set_announce(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    @discord.ui.button(label="📊 Status Maintenance", style=discord.ButtonStyle.success, row=0)
    async def view_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        maint  = get_maintenance()
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Hanya Owner Bot yang bisa mengatur maintenance!", ephemeral=True)
            return
        active = maint.get("active", False)
        reason = maint.get("reason", "-")
        ts     = maint.get("started_at", 0)
        since  = datetime.datetime.fromtimestamp(ts, tz=WIB).strftime("%d/%m/%Y %H:%M") if ts else "-"
        em = dark_red_embed(
            "🔧 Status Maintenance",
            f"**Status:** {'🔴 AKTIF' if active else '🟢 NONAKTIF'}\n"
            f"**Alasan:** {reason}\n"
            f"**Aktif sejak:** {since if active else '-'}\n"
            f"**Server terdaftar:** {len(bot.guilds)}"
        )
        await interaction.response.send_message(embed=em, ephemeral=True)

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
                em.set_footer(text="DOOMINIKS PARADISE · Bot System")
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
                em.set_footer(text="DOOMINIKS PARADISE · Bot System")
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
            owner_em = discord.Embed(
                title="🆕 Bot Masuk Server Baru!",
                description=(
                    f"**🏠 Server:** {guild.name}\n"
                    f"**🆔 Server ID:** `{guild.id}`\n"
                    f"**👥 Member:** {guild.member_count} orang\n"
                    f"**👑 Owner Server:** {guild.owner} (`{guild.owner_id}`)\n"
                    f"**📅 Dibuat:** {guild.created_at.strftime('%d/%m/%Y')}\n"
                    f"**🤖 Total Server Bot:** {len(bot.guilds)}"
                ),
                color=0x00FF88
            )
            if guild.icon:
                owner_em.set_thumbnail(url=guild.icon.url)
            owner_em.set_footer(text="DOOMINIKS PARADISE · Bot System")
            owner_em.timestamp = datetime.datetime.now(tz=WIB)
            await owner.send(embed=owner_em)
        except Exception as e:
            print(f"Gagal DM owner saat join guild: {e}")

    maint        = get_maintenance()
    maint_status = "🔴 Under Maintenance" if maint.get("active") else "🟢 Online & Running"
    maint_reason = f"\n**Reason:** {maint.get('reason', '-')}" if maint.get("active") else ""

    em = discord.Embed(
        title=f"👋 Hey {guild.name}! Thanks for inviting me!",
        description=(
            f"I'm **{bot.user.display_name}**, a multipurpose bot made by **DOOMINIKS PARADISE**!\n\n"
            "Ready to make your server more fun and organized. "
            "Here are the features you can use:"
        ),
        color=DARK_RED
    )
    if bot.user.display_avatar:
        em.set_thumbnail(url=bot.user.display_avatar.url)
    em.add_field(
        name="🎣 Fishing & Mini Games",
        value=(
            "`!Doom fish` / `/fish` — Go fishing & sell your catch\n"
            "`!Doom tebak` / `/tebak` — Riddle arena with coin rewards\n"
            "`!Doom coins` / `/coins` — Check your coin balance\n"
            "`!Doom leaderboard` / `/leaderboard` — Level ranking"
        ),
        inline=False
    )
    em.add_field(
        name="⚠️ Moderation",
        value=(
            "`!Doom warn` — Warn a member\n"
            "`!Doom kick` / `ban` / `timeout` — Moderate members\n"
            "`!Doom clear` — Bulk delete messages\n"
            "`!Doom addrole` / `removerole` — Manage roles"
        ),
        inline=False
    )
    em.add_field(
        name="🎉 Events & Giveaways",
        value=(
            "`!Doom giveaway` / `/giveaway` — Start a giveaway\n"
            "`!Doom event` / `/event` — Announce events with auto-timer\n"
            "`!Doom sticky` — Sticky message in a channel"
        ),
        inline=False
    )
    em.add_field(
        name="🎫 Tickets & Roles",
        value=(
            "`/ticket` — Setup support ticket panel\n"
            "`/reactionrole` — Button role picker\n"
            "`/leveling` — Setup leveling & XP system"
        ),
        inline=False
    )
    em.add_field(
        name="🛠️ Utilities",
        value=(
            "`!Doom autoresponse` — Auto-reply on trigger words\n"
            "`!Doom embed` — Send custom embed messages\n"
            "`!Doom vote` — Vote the bot & get coin rewards\n"
            "`!Doom setlang` / `/setlang` — Change bot language (id/en/de/ar/th/ja)"
        ),
        inline=False
    )
    em.add_field(
        name="👑 Premium",
        value=(
            "Some features can be locked for premium members only.\n"
            "`!Doom premium` — View info & order premium"
        ),
        inline=False
    )
    em.add_field(
        name="📡 Bot Status & Maintenance Notifications",
        value=(
            f"**Current Status:** {maint_status}{maint_reason}\n\n"
            "Use `/setmaintenancechannel` to choose which channel receives maintenance notifications."
        ),
        inline=False
    )
    em.set_footer(text=f"Prefix: !Doom | Slash Commands supported! | {len(bot.guilds)} servers")
    em.timestamp = datetime.datetime.now(tz=WIB)

    try:
        await target_ch.send(embed=em)
    except Exception as e:
        print(f"Failed to send welcome embed in {guild.name}: {e}")

async def maintenance_panel(ctx):
    maint  = get_maintenance()
    active = maint.get("active", False)
    em = dark_red_embed(
        "🔧 Maintenance Control Panel",
        f"**Status saat ini:** {'🔴 MAINTENANCE AKTIF' if active else '🟢 Bot Normal'}\n"
        f"**Alasan:** {maint.get('reason', '-')}\n"
        f"**Server:** {len(bot.guilds)} server\n\n"
        "Toggle maintenance untuk aktifkan/nonaktifkan dan broadcast ke semua server."
    )
    em.set_footer(text="⚠️ Panel ini hanya untuk Owner/Admin")
    await ctx.send(embed=em, view=MaintenanceView())

# ===================== PREFIX COMMANDS =====================

@bot.command(name="ping")
async def ping_cmd(ctx):
    if await check_maintenance(ctx):
        return
    uid     = ctx.author.id
    latency = round(bot.latency * 1000)
    status  = (t("status_good", uid) if latency < 100
               else t("status_slow", uid) if latency < 200
               else t("status_bad", uid))
    em = dark_red_embed("🏓 Pong!", t("pong", uid, ms=latency, status=status))
    await ctx.reply(embed=em)

@bot.command(name="fish", aliases=["mancing", "fishing"])
async def fishing_cmd(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "fish"): return
    em = dark_red_embed("🎣 DOOMINIKS PARADISE Fishing", f"Hey **{ctx.author.display_name}**! Choose your action:")
    await ctx.reply(embed=em, view=FishingMainView(ctx.author.id))

@bot.command(name="tebak")
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
    em = dark_red_embed(
        t("tebak_title", uid),
        t("tebak_desc", uid, question=soal["soal"], reward=soal["reward"])
    )
    await ctx.send(embed=em)

@bot.command(name="addtebak")
@commands.has_permissions(administrator=True)
async def addtebak_cmd(ctx, *, content: str = None):
    if not content:
        await ctx.reply("❓ Format: `!Doom addtebak Pertanyaan|jawaban|reward_koin`")
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
    em = dark_red_embed("✅ Soal Tebakan Ditambah!", f"**Soal:** {soal}\n**Jawaban:** {jawaban}\n**Reward:** {reward} koin\n\nTotal soal custom: **{len(custom)}**")
    await ctx.reply(embed=em)

@bot.command(name="listtebak")
async def listtebak_cmd(ctx):
    custom = get_custom_tebakan()
    if not custom:
        await ctx.reply("📋 Belum ada soal custom. Tambah pake `!Doom addtebak`!")
        return
    lines = [f"{i+1}. {s['soal']} → **{s['jawaban']}** ({s['reward']} koin)" for i, s in enumerate(custom)]
    em = dark_red_embed("📋 Soal Tebakan Custom", "\n".join(lines[:20]))
    em.set_footer(text=f"Total: {len(custom)} custom | Default: {len(TEBAKAN_LIST)}")
    await ctx.reply(embed=em)

@bot.command(name="removetebak")
@commands.has_permissions(administrator=True)
async def removetebak_cmd(ctx, nomor: int = None):
    if not nomor:
        await ctx.reply("❓ Format: `!Doom removetebak [nomor]`")
        return
    custom = get_custom_tebakan()
    if nomor < 1 or nomor > len(custom):
        await ctx.reply(f"❌ Nomor tidak valid! Total soal custom: {len(custom)}")
        return
    removed = custom.pop(nomor - 1)
    save_custom_tebakan(custom)
    await ctx.reply(embed=dark_red_embed("🗑️ Soal Dihapus!", f"**\"{removed['soal']}\"** dihapus!"))

@bot.command(name="coins", aliases=["koin", "saldo"])
async def check_coins(ctx):
    if await check_maintenance(ctx): return
    if await check_premium_gate(ctx, "coins"): return
    uid   = ctx.author.id
    udata = get_user_fishing(str(uid))
    em = dark_red_embed(
        t("coins_title", uid),
        t("coins_desc", uid, user=ctx.author.display_name, amount=udata["coins"])
    )
    await ctx.reply(embed=em)

# --- Warn ---
@bot.command(name="warn")
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
        dm_em = dark_red_embed("⚠️ Lo Kena Warn!", f"Lo di-warn di **{ctx.guild.name}**\n**Alasan:** {reason}\n**Total Warn:** {count}")
        dm_em.set_footer(text=f"Warn oleh: {ctx.author.display_name}")
        await member.send(embed=dm_em)
        dm_status = "\n✅ DM terkirim."
    except:
        dm_status = "\n⚠️ Gagal kirim DM."
    await ctx.send(embed=dark_red_embed("⚠️ Member Di-Warn!", f"**{member.display_name}** dapet warn!\n**Alasan:** {reason}\n**Total:** {count}{dm_status}"))

@bot.command(name="warns")
async def check_warns(ctx, member: discord.Member = None):
    member    = member or ctx.author
    warns     = get_warns()
    user_warns = warns.get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not user_warns:
        await ctx.reply(f"✅ **{member.display_name}** bersih, gak ada warn!")
        return
    warn_text = "\n".join([f"{i+1}. {w['reason']}" for i, w in enumerate(user_warns)])
    await ctx.reply(embed=dark_red_embed(f"⚠️ Warn {member.display_name}", f"Total: **{len(user_warns)} warn**\n\n{warn_text}"))

# --- Moderation ---
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member = None, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    await member.kick(reason=reason)
    await ctx.send(embed=dark_red_embed("👢 Di-Kick!", f"**{member.display_name}** di-kick!\n**Alasan:** {reason}"))

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member = None, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    await member.ban(reason=reason)
    await ctx.send(embed=dark_red_embed("🔨 Di-Ban!", f"**{member.display_name}** di-ban!\n**Alasan:** {reason}"))

@bot.command(name="timeout", aliases=["mute"])
@commands.has_permissions(moderate_members=True)
async def timeout_cmd(ctx, member: discord.Member = None, minutes: int = 10, *, reason="Gak ada alasan"):
    if not member:
        await ctx.reply("❓ Mention member dulu!")
        return
    until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await ctx.send(embed=dark_red_embed("⏱️ Timeout!", f"**{member.display_name}** di-timeout {minutes} menit!\n**Alasan:** {reason}"))

@bot.command(name="move")
@commands.has_permissions(move_members=True)
async def move(ctx, member: discord.Member = None, *, channel: discord.VoiceChannel = None):
    if not member or not channel:
        await ctx.reply("❓ Format: `!Doom move @member #channel`")
        return
    await member.move_to(channel)
    await ctx.send(embed=dark_red_embed("🔀 Di-Move!", f"**{member.display_name}** dipindah ke **{channel.name}**!"))

@bot.command(name="addrole")
@commands.has_permissions(manage_roles=True)
async def addrole(ctx, member: discord.Member = None, role: discord.Role = None):
    if not member or not role:
        await ctx.reply("❓ Format: `!Doom addrole @member @role`")
        return
    await member.add_roles(role)
    await ctx.send(embed=dark_red_embed("✅ Role Ditambah!", f"**{role.name}** dikasih ke **{member.display_name}**!"))

@bot.command(name="removerole")
@commands.has_permissions(manage_roles=True)
async def removerole(ctx, member: discord.Member = None, role: discord.Role = None):
    if not member or not role:
        await ctx.reply("❓ Format: `!Doom removerole @member @role`")
        return
    await member.remove_roles(role)
    await ctx.send(embed=dark_red_embed("❌ Role Dicopot!", f"**{role.name}** dicopot dari **{member.display_name}**!"))

@bot.command(name="avatar", aliases=["av"])
async def avatar(ctx, member: discord.Member = None):
    member = member or ctx.author
    em = dark_red_embed(f"🖼️ Avatar {member.display_name}")
    em.set_image(url=member.display_avatar.url)
    await ctx.reply(embed=em)

@bot.command(name="userinfo", aliases=["ui", "whois"])
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    em = dark_red_embed(f"👤 Info: {member.display_name}")
    em.set_thumbnail(url=member.display_avatar.url)
    em.add_field(name="Username",        value=str(member),                                                  inline=True)
    em.add_field(name="ID",              value=member.id,                                                    inline=True)
    em.add_field(name="Bergabung Server", value=member.joined_at.strftime("%d/%m/%Y"),                        inline=True)
    em.add_field(name="Akun Dibuat",     value=member.created_at.strftime("%d/%m/%Y"),                       inline=True)
    em.add_field(name="Roles",           value=", ".join([r.name for r in member.roles[1:]]) or "Gak ada",  inline=False)
    await ctx.reply(embed=em)

@bot.command(name="clear", aliases=["purge"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(embed=dark_red_embed("🗑️ Dihapus!", f"**{amount}** pesan berhasil dihapus!"))
    await asyncio.sleep(3)
    await msg.delete()

@bot.command(name="embed")
@commands.has_permissions(manage_messages=True)
async def embed_cmd(ctx, *, content: str = None):
    if not content:
        await ctx.reply("❓ Format: `!Doom embed Judul|Deskripsi` atau `!Doom embed Judul|Deskripsi|main`")
        return
    parts        = content.split("|")
    title        = parts[0].strip()
    desc         = parts[1].strip() if len(parts) > 1 else ""
    send_to_main = len(parts) > 2 and parts[2].strip().lower() == "main"
    em = dark_red_embed(title, desc)
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
            await ctx.reply("⚠️ Main channel belum diset! Gunakan `!Doom setmainchannel #channel` dulu.")
            return
    await target_channel.send(embed=em)
    if target_channel != ctx.channel:
        await ctx.reply(f"✅ Embed dikirim ke {target_channel.mention}!")
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="setmainchannel")
@commands.has_permissions(administrator=True)
async def set_main_channel(ctx, channel: discord.TextChannel = None):
    if not channel:
        await ctx.reply("❓ Format: `!Doom setmainchannel #channel`")
        return
    config = get_config()
    gid    = str(ctx.guild.id)
    config.setdefault(gid, {})["embed_main_channel"] = str(channel.id)
    save_config(config)
    await ctx.reply(embed=dark_red_embed("✅ Main Channel Diset!", f"Embed notifikasi → {channel.mention}"))

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
        await ctx.reply(embed=dark_red_embed("📋 Auto-Respon", text))
    else:
        await ctx.reply("❓ Format:\n`!Doom ar add [trigger] [response]`\n`!Doom ar remove [trigger]`\n`!Doom ar list`")

@bot.command(name="sticky")
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
        await ctx.reply("❓ Format:\n`!Doom sticky set [pesan]|[min_pesan]`\n`!Doom sticky remove`")

@bot.command(name="giveaway", aliases=["ga"])
@commands.has_permissions(administrator=True)
async def giveaway_cmd(ctx, duration: str = None, *, prize: str = None):
    if await check_premium_gate(ctx, "giveaway"): return
    if not duration or not prize:
        await ctx.reply("❓ Format: `!Doom giveaway [durasi][s/m/h] [hadiah]`")
        return
    multipliers = {"s": 1, "m": 60, "h": 3600}
    unit        = duration[-1].lower()
    if unit not in multipliers:
        await ctx.reply("❌ Unit waktu salah! Pake s, m, atau h.")
        return
    seconds  = int(duration[:-1]) * multipliers[unit]
    end_time = time.time() + seconds
    end_dt   = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    em = dark_red_embed("🎉 GIVEAWAY NIH!", f"**Hadiah:** {prize}\n**Berakhir:** {end_dt.strftime('%d/%m/%Y %H:%M')}\n\n🎉 React buat ikutan!")
    em.set_footer(text="Klik 🎉 buat ikut giveaway!")
    msg = await ctx.send(embed=em)
    await msg.add_reaction("🎉")
    gw_data = get_giveaways()
    gid     = str(ctx.guild.id)
    gw_data.setdefault(gid, {})[str(msg.id)] = {"prize": prize, "end_time": end_time, "channel_id": str(ctx.channel.id), "ended": False}
    save_giveaways(gw_data)

@bot.command(name="event")
@commands.has_permissions(administrator=True)
async def event_cmd(ctx, *, content: str = None):
    if await check_premium_gate(ctx, "event"): return
    if not content:
        await ctx.reply(
            "❓ Format: `!Doom event Nama|Deskripsi|HH:MM|#channel|durasi_jam`\n"
            "• `durasi_jam` = durasi event dalam jam (opsional, default: 1)\n"
            "Contoh: `!Doom event Turnamen ML|Yuk gaskeun!|20:00|#announce|2`"
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

    em = dark_red_embed(
        f"📅 EVENT: {name}",
        f"{desc}\n\n"
        f"⏰ **Jam Mulai:** {start_time_str} WIB\n"
        f"⏱️ **Durasi:** {durasi_str}\n\n"
        "📢 Jangan sampe ketinggalan! Gas ikutan! 🔥"
    )
    em.set_footer(text=f"Event oleh {ctx.author.display_name}")
    em.timestamp   = datetime.datetime.now(tz=WIB)
    event_msg      = await target_channel.send(content="@everyone", embed=em)
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
            start_em = discord.Embed(
                title=f"🚨 EVENT MULAI: {ev_name}!",
                description=(
                    f"**{ev_desc}**\n\n"
                    f"🔥 **EVENT DIMULAI SEKARANG!**\n"
                    f"⏰ Jam Mulai: **{ev_ts} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n"
                    f"🏁 Berakhir: **{end_ts.strftime('%H:%M')} WIB**"
                ),
                color=0xFF4500
            )
            start_em.set_footer(text="Gas ikutan sebelum telat! 🔥")
            start_em.timestamp = datetime.datetime.now(tz=WIB)
            try:
                await ev_msg.edit(embed=start_em)
            except:
                pass
            try:
                await tc.send(content="@everyone 🚨 **EVENT DIMULAI SEKARANG!** 🚨")
            except:
                pass

            # === SELESAI EVENT ===
            wait_end = max(0, (end_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_end)
            end_em = discord.Embed(
                title=f"🏁 EVENT SELESAI: {ev_name}",
                description=(
                    f"**{ev_desc}**\n\n"
                    f"✅ Event telah **BERAKHIR**!\n"
                    f"⏰ Mulai: **{ev_ts} WIB** | Selesai: **{end_ts.strftime('%H:%M')} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n\n"
                    "Makasih udah ikutan! 🎉"
                ),
                color=0x95A5A6
            )
            end_em.set_footer(text="Event telah berakhir.")
            end_em.timestamp = datetime.datetime.now(tz=WIB)
            try:
                await ev_msg.edit(embed=end_em)
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

@bot.command(name="addemoji", aliases=["emoji"])
@commands.has_permissions(manage_emojis=True)
async def addemoji_cmd(ctx):
    """
    Usage: !Doom addemoji <emoji1> <emoji2> ...
    Langsung parse emoji dari pesan yang sama — tidak perlu kirim ulang.
    """
    # Ambil semua custom emoji dari pesan command itu sendiri
    emojis_found = ctx.message.emojis
    if not emojis_found:
        await ctx.reply(
            embed=dark_red_embed(
                "❌ Tidak Ada Emoji",
                "Sertakan emoji custom yang mau ditambah langsung di pesan command!\n\n"
                "**Contoh:** `!Doom addemoji :NamaEmoji: :EmojiLain:`"
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
    await ctx.reply(embed=dark_red_embed("🖼️ Hasil Add Emoji", desc))

# ===================== PREMIUM COMMAND (User) =====================

@bot.command(name="premium")
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
        em.set_footer(text="DOOMINIKS PARADISE · Premium System · Thank you for your support! 🙏")
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
        title="👑 DOOMINIKS PARADISE — Premium",
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
    em.set_footer(text="DOOMINIKS PARADISE · Premium System · Select a package below to order")

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
            info_em.set_footer(text="DOOMINIKS PARADISE · Send your payment proof after transfer")
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
                order_em.set_footer(text=f"DOOMINIKS PARADISE · Order ID: {order_id}")

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
                conf_em.set_footer(text="DOOMINIKS PARADISE · Premium System · Thank you for your order!")
                await interaction.followup.send(embed=conf_em, ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout! Order dibatalkan.", ephemeral=True)

    await ctx.reply(embed=em, view=OrderPremiumView())

# ===================== HELP COMMAND =====================


# ===================== SETLANG COMMAND =====================

@bot.command(name="setlang", aliases=["language", "lang"])
async def setlang_cmd(ctx, lang_code: str = None):
    """Ganti bahasa bot untuk user ini."""
    if await check_maintenance(ctx):
        return
    uid = str(ctx.author.id)

    # Owner tidak bisa ganti bahasa (selalu id_gaul)
    if ctx.author.id == OWNER_ID:
        em = discord.Embed(
            title="👑 Language / Bahasa",
            description="Sebagai **Owner Bot**, bahasa lo dikunci ke **🇮🇩 Indonesia Gaul** permanen dan tidak bisa diubah.",
            color=DARK_RED
        )
        await ctx.reply(embed=em)
        return

    options_text = "\n".join([f"• `{code}` — {name}" for code, name in SUPPORTED_LANGS.items() if code != "id_gaul"])

    if not lang_code:
        current_lang = get_user_lang(uid)
        current_name = SUPPORTED_LANGS.get(current_lang, current_lang)
        em = discord.Embed(
            title=t("setlang_title", uid),
            description=t("setlang_current", uid,
                lang=current_name,
                options=options_text
            ),
            color=DARK_RED
        )
        await ctx.reply(embed=em)
        return

    code = lang_code.lower().strip()
    # id_gaul khusus owner bot, user biasa tidak bisa pilih ini (pilih "id" untuk Indonesia Gaul)
    valid_codes = [lc for lc in SUPPORTED_LANGS if lc != "id_gaul"]
    if code not in valid_codes:
        opts = ", ".join([f"`{lc}`" for lc in valid_codes])
        em = discord.Embed(
            title="❌ Invalid Language",
            description=t("setlang_invalid", uid, options=opts),
            color=0xFF4444
        )
        await ctx.reply(embed=em)
        return

    set_user_lang(uid, code)
    lang_name = SUPPORTED_LANGS[code]
    em = discord.Embed(
        title=t("setlang_title", uid),
        description=t("setlang_changed", uid, lang=lang_name),
        color=0x00FF88
    )
    await ctx.reply(embed=em)

@bot.command(name="help", aliases=["h"])
async def help_cmd(ctx):
    if await check_maintenance(ctx):
        return
    em = dark_red_embed("📖 DOOMINIKS PARADISE — Help", "Your complete multipurpose server bot!")
    em.add_field(name="🎣 Fishing",   value="`fish` `coins`",                                         inline=True)
    em.add_field(name="🧠 Tebak-Tebakan", value="`tebak` `addtebak` `listtebak` `removetebak` | `/tebak` (Arena) `/tambahsoal`", inline=True)
    em.add_field(name="⚠️ Mod",       value="`warn` `warns` `kick` `ban` `timeout` `move` `clear`",  inline=False)
    em.add_field(name="👤 Info",      value="`avatar` `userinfo` `ping`",                              inline=True)
    em.add_field(name="🎭 Role",      value="`addrole` `removerole`",                                  inline=True)
    em.add_field(name="📢 Utility",   value="`embed` `setmainchannel` `sticky` `autoresponse` `giveaway` `event` `addemoji`", inline=False)
    em.add_field(name="👑 Premium",   value="`premium` — Lihat info & order premium",                  inline=False)
    em.add_field(name="🗳️ Vote",      value="`vote` — Link vote Top.gg | `claimvote` — Claim reward vote", inline=False)
    em.add_field(name="🌐 Bahasa",    value="`setlang [kode]` — Ganti bahasa bot (en/de/ar/th/ja)", inline=False)
    em.add_field(name="📡 Notifikasi", value="`setmaintenancechannel #channel` — Pilih channel notif maintenance *(owner bot only)*", inline=False)
    em.set_footer(text="Prefix: !Doom | Semua command bisa pake slash juga!")
    await ctx.reply(embed=em)

# ===================== SLASH COMMANDS =====================

@tree.command(name="ping", description="Cek latency bot")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    em = dark_red_embed("🏓 Pong!", f"**Latency:** `{latency}ms`\n**Status:** {'🟢 Lancar' if latency < 100 else '🟡 Agak lambat' if latency < 200 else '🔴 Lambat'}")
    await interaction.response.send_message(embed=em)

@tree.command(name="fish", description="Mulai mancing!")
async def slash_fish(interaction: discord.Interaction):
    maint = get_maintenance()
    if maint.get("active") and interaction.user.id != OWNER_ID:
        await interaction.response.send_message(embed=discord.Embed(title="🔧 Maintenance", description=f"Bot sedang maintenance.\n**Alasan:** {maint.get('reason','')}", color=0xFF6600), ephemeral=True)
        return
    if await check_premium_gate_slash(interaction, "fish"): return
    em = dark_red_embed("🎣 DOOMINIKS PARADISE Fishing", f"Hey **{interaction.user.display_name}**! Choose your action:")
    await interaction.response.send_message(embed=em, view=FishingMainView(interaction.user.id))

@tree.command(name="ticket", description="Setup panel ticket")
@app_commands.describe(
    judul="Judul embed panel ticket",
    deskripsi="Deskripsi panel ticket",
    button_label="Label button buka ticket",
    button_emoji="Emoji button",
    kategori="ID kategori channel ticket"
)
@app_commands.default_permissions(administrator=True)
async def slash_ticket(interaction: discord.Interaction, judul: str = "🎫 Support Ticket", deskripsi: str = "Klik button untuk buka ticket!", button_label: str = "Buka Ticket", button_emoji: str = "🎫", kategori: str = None):
    if await check_premium_gate_slash(interaction, "ticket"): return

    panel_id     = str(int(time.time()))
    panel_config = {
        "panel_id":       panel_id,
        "button_label":   button_label,
        "button_emoji":   button_emoji,
        "description":    deskripsi,
        "category_id":    kategori,
        "whitelist_roles": [],
        "thumbnail_url":  None,
        "image_url":      None,
    }

    def check_author(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel_id

    # ── LANGKAH 1: Tanya whitelist role ──────────────────────────────────────
    await interaction.response.send_message(
        embed=discord.Embed(
            title="🎫 Setup Ticket — Langkah 1/2: Whitelist Role",
            description=(
                "Mention **role-role** yang bisa lihat & urus ticket di server ini.\n\n"
                "**Contoh:** `@Staff @Moderator @Support`\n\n"
                "Ketik `skip` kalau tidak mau set whitelist role.\n"
                "*(Timeout 60 detik)*"
            ),
            color=DARK_RED
        ),
        ephemeral=True
    )
    try:
        msg_role = await bot.wait_for("message", check=check_author, timeout=60)
        if msg_role.content.strip().lower() != "skip":
            panel_config["whitelist_roles"] = [str(r.id) for r in msg_role.role_mentions]
        try:
            await msg_role.delete()
        except:
            pass
    except asyncio.TimeoutError:
        pass  # lanjut tanpa whitelist role

    # ── LANGKAH 2: Tanya gambar (thumbnail & image via attachment) ────────────
    await interaction.followup.send(
        embed=discord.Embed(
            title="🎫 Setup Ticket — Langkah 2/2: Gambar (Opsional)",
            description=(
                "Upload gambar sebagai **attachment Discord** untuk embed ticket.\n\n"
                "• **1 gambar** → jadi **thumbnail** (pojok kanan atas embed)\n"
                "• **2 gambar** → gambar pertama jadi **thumbnail**, kedua jadi **gambar besar**\n\n"
                "Ketik `skip` kalau tidak mau tambah gambar.\n"
                "*(Timeout 60 detik)*"
            ),
            color=DARK_RED
        ),
        ephemeral=True
    )
    try:
        msg_img = await bot.wait_for("message", check=check_author, timeout=60)
        if msg_img.content.strip().lower() != "skip":
            valid_exts = [".png", ".jpg", ".jpeg", ".gif", ".webp"]
            attachments = [a for a in msg_img.attachments if any(a.filename.lower().endswith(e) for e in valid_exts)]
            if len(attachments) >= 1:
                panel_config["thumbnail_url"] = attachments[0].url
            if len(attachments) >= 2:
                panel_config["image_url"] = attachments[1].url
        try:
            await msg_img.delete()
        except:
            pass
    except asyncio.TimeoutError:
        pass  # lanjut tanpa gambar

    # ── Build & kirim panel ───────────────────────────────────────────────────
    em = dark_red_embed(judul, deskripsi)
    if panel_config.get("thumbnail_url"):
        em.set_thumbnail(url=panel_config["thumbnail_url"])
    if panel_config.get("image_url"):
        em.set_image(url=panel_config["image_url"])

    view = TicketView(panel_config)
    await interaction.channel.send(embed=em, view=view)

    td = get_tickets()
    td.setdefault("panels", {})[panel_id] = panel_config
    save_tickets(td)

    # Ringkasan setup
    roles_set  = len(panel_config["whitelist_roles"])
    thumb_set  = "✅" if panel_config.get("thumbnail_url") else "➖"
    image_set  = "✅" if panel_config.get("image_url") else "➖"
    await interaction.followup.send(
        embed=discord.Embed(
            title="✅ Panel Ticket Berhasil Dibuat!",
            description=(
                f"**👥 Whitelist Role:** {roles_set} role diset\n"
                f"**🖼️ Thumbnail:** {thumb_set}\n"
                f"**🖼️ Gambar Besar:** {image_set}\n\n"
                "Panel ticket sudah aktif di channel ini!"
            ),
            color=0x00FF88
        ),
        ephemeral=True
    )

@tree.command(name="leveling", description="Setup fitur leveling")
@app_commands.default_permissions(administrator=True)
async def slash_leveling(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "leveling"): return
    config = get_config()
    gid    = str(interaction.guild.id)
    config.setdefault(gid, {})
    status = "✅ AKTIF" if config[gid].get("leveling_enabled", True) else "❌ NONAKTIF"
    em = dark_red_embed("⚙️ Setup Leveling", f"**Status:** {status}\n\nPake button untuk setup!")
    await interaction.response.send_message(embed=em, view=LevelingSetupView(interaction.guild.id))

@tree.command(name="reactionrole", description="Setup reaction role dengan button")
@app_commands.describe(judul="Judul embed", deskripsi="Deskripsi", role1="Role pertama", emoji1="Emoji 1", label1="Label 1", role2="Role kedua", emoji2="Emoji 2", label2="Label 2")
@app_commands.default_permissions(administrator=True)
async def slash_reactionrole(interaction: discord.Interaction, judul: str, deskripsi: str, role1: discord.Role, emoji1: str = "🎭", label1: str = "Ambil Role", role2: discord.Role = None, emoji2: str = "🎭", label2: str = "Ambil Role 2"):
    if await check_premium_gate_slash(interaction, "reactionrole"): return
    roles_config = [{"role_id": role1.id, "label": label1, "emoji": emoji1}]
    if role2:
        roles_config.append({"role_id": role2.id, "label": label2, "emoji": emoji2})
    em   = dark_red_embed(judul, deskripsi)
    view = ReactionRoleView(roles_config)
    await interaction.response.send_message(embed=em, view=view)

@tree.command(name="giveaway", description="Mulai giveaway!")
@app_commands.describe(durasi_menit="Durasi dalam menit", hadiah="Hadiah giveaway")
@app_commands.default_permissions(administrator=True)
async def slash_giveaway(interaction: discord.Interaction, durasi_menit: int, hadiah: str):
    if await check_premium_gate_slash(interaction, "giveaway"): return
    end_time = time.time() + durasi_menit * 60
    end_dt   = datetime.datetime.now() + datetime.timedelta(minutes=durasi_menit)
    em = dark_red_embed("🎉 GIVEAWAY NIH!", f"**Hadiah:** {hadiah}\n**Berakhir:** {end_dt.strftime('%d/%m/%Y %H:%M')}\n\n🎉 React buat ikutan!")
    await interaction.response.send_message(embed=em)
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
        dm_em = dark_red_embed("⚠️ Lo Kena Warn!", f"Server: **{interaction.guild.name}**\n**Alasan:** {alasan}\n**Total:** {count}")
        dm_em.set_footer(text=f"Warn oleh: {interaction.user.display_name}")
        await member.send(embed=dm_em)
        dm_status = "\n✅ DM terkirim."
    except:
        dm_status = "\n⚠️ Gagal kirim DM."
    await interaction.response.send_message(embed=dark_red_embed("⚠️ Di-Warn!", f"**{member.display_name}** dapet warn!\n**Alasan:** {alasan}\n**Total:** {count}{dm_status}"))

@tree.command(name="kick", description="Kick member")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member, alasan: str = "Gak ada alasan"):
    await member.kick(reason=alasan)
    await interaction.response.send_message(embed=dark_red_embed("👢 Di-Kick!", f"**{member.display_name}** dikick.\n**Alasan:** {alasan}"))

@tree.command(name="ban", description="Ban member")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member, alasan: str = "Gak ada alasan"):
    await member.ban(reason=alasan)
    await interaction.response.send_message(embed=dark_red_embed("🔨 Di-Ban!", f"**{member.display_name}** dibanned.\n**Alasan:** {alasan}"))

@tree.command(name="timeout", description="Timeout member")
@app_commands.default_permissions(moderate_members=True)
async def slash_timeout(interaction: discord.Interaction, member: discord.Member, menit: int = 10, alasan: str = "Gak ada alasan"):
    until = discord.utils.utcnow() + datetime.timedelta(minutes=menit)
    await member.timeout(until, reason=alasan)
    await interaction.response.send_message(embed=dark_red_embed("⏱️ Timeout!", f"**{member.display_name}** di-timeout {menit} menit!"))

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
    em = dark_red_embed(f"🖼️ Avatar {member.display_name}")
    em.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=em)

@tree.command(name="userinfo", description="Info lengkap user")
async def slash_userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    em = dark_red_embed(f"👤 Info {member.display_name}")
    em.set_thumbnail(url=member.display_avatar.url)
    em.add_field(name="Username",  value=str(member),                                                 inline=True)
    em.add_field(name="ID",        value=member.id,                                                   inline=True)
    em.add_field(name="Join Date", value=member.joined_at.strftime("%d/%m/%Y"),                        inline=True)
    em.add_field(name="Roles",     value=", ".join([r.name for r in member.roles[1:]]) or "Gak ada",  inline=False)
    await interaction.response.send_message(embed=em)

@tree.command(name="addrole", description="Tambah role ke member")
@app_commands.default_permissions(manage_roles=True)
async def slash_addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    await interaction.response.send_message(embed=dark_red_embed("✅ Role Ditambah!", f"**{role.name}** → **{member.display_name}**!"))

@tree.command(name="removerole", description="Copot role dari member")
@app_commands.default_permissions(manage_roles=True)
async def slash_removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    await interaction.response.send_message(embed=dark_red_embed("❌ Role Dicopot!", f"**{role.name}** dicopot dari **{member.display_name}**!"))

@tree.command(name="embed", description="Kirim embed message")
@app_commands.describe(judul="Judul embed", deskripsi="Isi embed", ke_main_channel="Kirim ke main channel?")
@app_commands.default_permissions(manage_messages=True)
async def slash_embed(interaction: discord.Interaction, judul: str, deskripsi: str, ke_main_channel: bool = False):
    em = dark_red_embed(judul, deskripsi)
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
    await target_channel.send(embed=em)
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
        await interaction.response.send_message(embed=dark_red_embed("📋 Auto-Respon", text), ephemeral=True)
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

    em = discord.Embed(
        title=f"📅 EVENT: {nama}",
        description=(
            f"{deskripsi}\n\n"
            f"⏰ **Jam Mulai:** {jam_mulai} WIB\n"
            f"⏱️ **Durasi:** {durasi_str}\n\n"
            "📢 Gas ikutan! 🔥"
        ),
        color=DARK_RED
    )
    em.set_footer(text=f"Event oleh {interaction.user.display_name}")
    em.timestamp = datetime.datetime.now(tz=WIB)
    event_msg    = await target_channel.send(content="@everyone", embed=em)
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
            start_em = discord.Embed(
                title=f"🚨 EVENT MULAI: {ev_name}!",
                description=(
                    f"**{ev_desc}**\n\n"
                    f"🔥 **EVENT DIMULAI SEKARANG!**\n"
                    f"⏰ Jam Mulai: **{ev_ts} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n"
                    f"🏁 Berakhir: **{end_ts.strftime('%H:%M')} WIB**"
                ),
                color=0xFF4500
            )
            start_em.set_footer(text="Gas ikutan sebelum telat! 🔥")
            start_em.timestamp = datetime.datetime.now(tz=WIB)
            try:
                await ev_msg.edit(embed=start_em)
            except:
                pass
            try:
                await tc.send(content="@everyone 🚨 **EVENT DIMULAI SEKARANG!** 🚨")
            except:
                pass

            # === SELESAI EVENT ===
            wait_end = max(0, (end_ts - datetime.datetime.now(tz=WIB)).total_seconds())
            await asyncio.sleep(wait_end)
            end_em = discord.Embed(
                title=f"🏁 EVENT SELESAI: {ev_name}",
                description=(
                    f"**{ev_desc}**\n\n"
                    f"✅ Event telah **BERAKHIR**!\n"
                    f"⏰ Mulai: **{ev_ts} WIB** | Selesai: **{end_ts.strftime('%H:%M')} WIB**\n"
                    f"⏱️ Durasi: **{dur_str}**\n\n"
                    "Makasih udah ikutan! 🎉"
                ),
                color=0x95A5A6
            )
            end_em.set_footer(text="Event telah berakhir.")
            end_em.timestamp = datetime.datetime.now(tz=WIB)
            try:
                await ev_msg.edit(embed=end_em)
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
    await interaction.response.send_message(embed=dark_red_embed("✅ Soal Ditambah!", f"**{soal}** → {jawaban} ({reward} koin)\nTotal: **{len(custom)}**"), ephemeral=True)

@tree.command(name="coins", description="Cek koin lo")
async def slash_coins(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "coins"): return
    udata = get_user_fishing(str(interaction.user.id))
    await interaction.response.send_message(embed=dark_red_embed("🪙 Koin Lo", f"**{interaction.user.display_name}** punya **{udata['coins']} koin** 🪙"), ephemeral=True)

@tree.command(name="leaderboard", description="Lihat leaderboard level")
async def slash_leaderboard(interaction: discord.Interaction):
    if await check_premium_gate_slash(interaction, "leaderboard"): return
    levels      = get_levels()
    gid         = str(interaction.guild.id)
    guild_levels = levels.get(gid, {})
    sorted_users = sorted(guild_levels.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)[:10]
    if not sorted_users:
        await interaction.response.send_message("📊 Belum ada data level!", ephemeral=True)
        return
    text = ""
    for i, (uid, data) in enumerate(sorted_users):
        member = interaction.guild.get_member(int(uid))
        name   = member.display_name if member else f"User {uid[:6]}"
        medal  = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i+1}."
        text  += f"{medal} **{name}** — Level {data['level']} ({data['xp']} XP)\n"
    await interaction.response.send_message(embed=dark_red_embed("🏆 Leaderboard Level", text))

@tree.command(name="setlang", description="Change bot language / Ganti bahasa bot")
@app_commands.describe(
    language="Language code: id / en / de / ar / th / ja (default: en)"
)
async def slash_setlang(interaction: discord.Interaction, language: str = None):
    """Slash version of setlang command."""
    if await check_premium_gate_slash(interaction, "setlang"): return
    uid = interaction.user.id

    # Owner selalu id_gaul, tidak bisa diubah
    if uid == OWNER_ID:
        em = discord.Embed(
            title="👑 Language / Bahasa",
            description="Sebagai **Owner Bot**, bahasa lo dikunci ke **🇮🇩 Indonesia Gaul** permanen dan tidak bisa diubah.",
            color=DARK_RED
        )
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    valid_codes  = [lc for lc in SUPPORTED_LANGS if lc != "id_gaul"]
    options_text = "\n".join([f"• `{code}` — {name}" for code, name in SUPPORTED_LANGS.items() if code != "id_gaul"])

    if not language:
        current_lang = get_user_lang(uid)
        current_name = SUPPORTED_LANGS.get(current_lang, current_lang)
        em = discord.Embed(
            title=t("setlang_title", uid),
            description=t("setlang_current", uid,
                lang=current_name,
                options=options_text
            ),
            color=DARK_RED
        )
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    code = language.lower().strip()
    if code not in valid_codes:
        opts = ", ".join([f"`{lc}`" for lc in valid_codes])
        em = discord.Embed(
            title="❌ Invalid Language",
            description=t("setlang_invalid", uid, options=opts),
            color=0xFF4444
        )
        await interaction.response.send_message(embed=em, ephemeral=True)
        return

    set_user_lang(uid, code)
    lang_name = SUPPORTED_LANGS[code]
    em = discord.Embed(
        title=t("setlang_title", uid),
        description=t("setlang_changed", uid, lang=lang_name),
        color=0x00FF88
    )
    await interaction.response.send_message(embed=em, ephemeral=True)

# ===================== SET MAINTENANCE CHANNEL =====================

@tree.command(name="setmaintenancechannel", description="Pilih channel untuk nerima notifikasi maintenance bot")
@app_commands.describe(channel="Channel tujuan notifikasi maintenance")
@app_commands.default_permissions(administrator=True)
async def slash_setmaintenancechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    """Admin server bisa pilih channel notif maintenance untuk server mereka sendiri."""
    if not channel.permissions_for(interaction.guild.me).send_messages:
        await interaction.response.send_message(
            embed=dark_red_embed("❌ Bot Tidak Punya Akses", f"Bot tidak punya izin kirim pesan di {channel.mention}!"),
            ephemeral=True
        )
        return
    config = get_config()
    gid    = str(interaction.guild.id)
    config.setdefault(gid, {})["maintenance_channel_id"] = str(channel.id)
    save_config(config)
    em = discord.Embed(
        title="📡 Channel Notifikasi Maintenance Diset!",
        description=(
            f"✅ Channel **{channel.mention}** akan menerima notifikasi saat bot:\n\n"
            "• 🔧 **Masuk maintenance** (beserta alasannya)\n"
            "• ✅ **Selesai maintenance** (bot kembali online)\n\n"
            "Lo bisa ubah channel ini kapan saja dengan jalankan command ini lagi."
        ),
        color=0x00FF88
    )
    em.set_footer(text=f"DOOMINIKS PARADISE · Bot System · {interaction.guild.name}")
    await interaction.response.send_message(embed=em, ephemeral=True)
    # Kirim konfirmasi ke channel yang dipilih
    try:
        notif_em = discord.Embed(
            title="📡 Channel Ini Dipilih untuk Notifikasi Maintenance",
            description=(
                f"Channel ini akan menerima notifikasi dari bot **{bot.user.display_name}** saat:\n\n"
                "• 🔧 Bot masuk mode **Maintenance**\n"
                "• ✅ Bot kembali **Online** setelah maintenance\n\n"
                "*Pengaturan ini dilakukan oleh owner bot.*"
            ),
            color=DARK_RED
        )
        notif_em.set_footer(text="DOOMINIKS PARADISE · Bot System")
        notif_em.timestamp = datetime.datetime.now(tz=WIB)
        await channel.send(embed=notif_em)
    except:
        pass

@bot.command(name="setmaintenancechannel")
@commands.has_permissions(administrator=True)
async def prefix_setmaintenancechannel(ctx, channel: discord.TextChannel = None):
    """Admin server bisa pilih channel notif maintenance untuk server mereka sendiri."""
    if not channel:
        await ctx.reply("❓ Format: `!Doom setmaintenancechannel #channel`")
        return
    if not channel.permissions_for(ctx.guild.me).send_messages:
        await ctx.reply(embed=dark_red_embed("❌ Bot Tidak Punya Akses", f"Bot tidak punya izin kirim pesan di {channel.mention}!"))
        return
    config = get_config()
    gid    = str(ctx.guild.id)
    config.setdefault(gid, {})["maintenance_channel_id"] = str(channel.id)
    save_config(config)
    em = discord.Embed(
        title="📡 Channel Notifikasi Maintenance Diset!",
        description=(
            f"✅ Channel **{channel.mention}** akan menerima notifikasi saat bot:\n\n"
            "• 🔧 **Masuk maintenance** (beserta alasannya)\n"
            "• ✅ **Selesai maintenance** (bot kembali online)\n\n"
            "Lo bisa ubah channel ini kapan saja dengan jalankan command ini lagi."
        ),
        color=0x00FF88
    )
    em.set_footer(text=f"DOOMINIKS PARADISE · Bot System · {ctx.guild.name}")
    await ctx.reply(embed=em)
    try:
        notif_em = discord.Embed(
            title="📡 Channel Ini Dipilih untuk Notifikasi Maintenance",
            description=(
                f"Channel ini akan menerima notifikasi dari bot **{bot.user.display_name}** saat:\n\n"
                "• 🔧 Bot masuk mode **Maintenance**\n"
                "• ✅ Bot kembali **Online** setelah maintenance\n\n"
                "*Pengaturan ini dilakukan oleh owner bot.*"
            ),
            color=DARK_RED
        )
        notif_em.set_footer(text="DOOMINIKS PARADISE · Bot System")
        notif_em.timestamp = datetime.datetime.now(tz=WIB)
        await channel.send(embed=notif_em)
    except:
        pass

# ===================== VOTE TOP.GG COMMANDS =====================

@bot.command(name="vote")
async def vote_cmd(ctx):
    """Kirim link vote bot di Top.gg."""
    if await check_maintenance(ctx):
        return
    uid        = ctx.author.id
    bot_id_str = BOT_ID or str(bot.user.id)
    vote_url   = f"https://top.gg/bot/{bot_id_str}/vote"
    em = discord.Embed(
        title=t("vote_title", uid),
        description=t("vote_desc", uid,
            url=vote_url, min=VOTE_REWARD_MIN, max=VOTE_REWARD_MAX,
            pct=VOTE_BONUS_PCTS, mins=VOTE_BONUS_MINS, cd=VOTE_COOLDOWN_H
        ),
        color=DARK_RED
    )
    em.set_footer(text="DOOMINIKS PARADISE | Vote every 12 hours!")
    em.set_thumbnail(url=bot.user.display_avatar.url)
    await ctx.reply(embed=em)

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
        em = discord.Embed(
            title=t("vote_cooldown_title", uid_cv),
            description=t("vote_cooldown_desc", uid_cv,
                next_time=next_dt.strftime("%d/%m/%Y %H:%M"),
                hours=sisa_h, mins=sisa_m
            ),
            color=DARK_RED
        )
        await ctx.reply(embed=em)
        return

    # Cek apakah user sudah vote via Top.gg API atau cache webhook
    async with ctx.typing():
        voted = await check_user_voted_topgg(ctx.author.id)

    if not voted:
        bot_id_str = BOT_ID or str(bot.user.id)
        vote_url   = f"https://top.gg/bot/{bot_id_str}/vote"
        uid_nv = ctx.author.id
        em = discord.Embed(
            title=t("vote_not_voted_title", uid_nv),
            description=t("vote_not_voted_desc", uid_nv, url=vote_url),
            color=0xFF4444
        )
        em.set_footer(text="Vote dulu bro baru bisa claim reward!" if get_user_lang(uid_nv) == "id_gaul" else "Vote first to claim reward!")
        await ctx.reply(embed=em)
        return

    # Berikan reward
    reward = random.randint(VOTE_REWARD_MIN, VOTE_REWARD_MAX)
    udata  = get_user_fishing(uid)
    udata["coins"] += reward
    save_user_fishing(uid, udata)

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
    em = discord.Embed(
        title=t("vote_claimed_title", uid_cl),
        description=t("vote_claimed_desc", uid_cl,
            user=ctx.author.display_name, reward=reward,
            total=udata["coins"], pct=VOTE_BONUS_PCTS,
            mins=VOTE_BONUS_MINS, until=bonus_until,
            count=record["total_claimed"], cd=VOTE_COOLDOWN_H
        ),
        color=0x00FF88
    )
    em.set_thumbnail(url=ctx.author.display_avatar.url)
    em.set_footer(text="DOOMINIKS PARADISE | Thanks for voting! 🗳️")
    await ctx.reply(embed=em)

# ===================== TOP.GG WEBHOOK SERVER (Flask) =====================

def create_vote_webhook_app():
    """Buat Flask app untuk menerima webhook vote dari Top.gg."""
    if not FLASK_AVAILABLE:
        return None

    app = Flask(__name__)

    @app.route("/dblwebhook", methods=["POST"])
    def dbl_webhook():
        # Validasi password webhook
        auth = flask_request.headers.get("Authorization", "")
        if WEBHOOK_PASSWORD and auth != WEBHOOK_PASSWORD:
            abort(401)

        data = flask_request.get_json(silent=True)
        if not data:
            abort(400)

        user_id = str(data.get("user", ""))
        bot_id  = str(data.get("bot", ""))
        vote_type = data.get("type", "upvote")  # "upvote" atau "test"

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
    print(f"✅ Vote webhook server berjalan di port {PORT} → /dblwebhook")

# ===================== ERROR HANDLERS =====================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply(embed=dark_red_embed("❌ No Permission!", "Lo gak punya izin buat command ini!"))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.reply(embed=dark_red_embed("❌ Member Gak Ketemu!", "Member yang lo mention gak ada!"))
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Error: {error}")

# ===================== RUN =====================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
