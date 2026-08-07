"""
leveling_system.py — Sistem Level/XP + Rank Card StartDoom
Sengaja dipisah dari bot.py biar file utamanya gak numpuk.

XP didapet dari NGIRIM PESAN (ada cooldown per user biar gak spam-XP), dan
disimpen GLOBAL di data fishing user yang sama (bukan per-server) — konsisten
sama sistem ekonomi (koin/ikan/rod) yang emang udah didesain global.

Cara pakai (taruh di bot.py, PALING BAWAH, setelah semua dependency ini
kedefinisi):

    from leveling_system import setup_leveling
    setup_leveling(bot, {
        "get_user_fishing":   get_user_fishing,
        "save_user_fishing":  save_user_fishing,
        "get_fishing_data":   get_fishing_data,
        "emoji":              emoji,
        "DARK_RED":           DARK_RED,
        "check_maintenance":  check_maintenance,
        "check_premium_gate": check_premium_gate,
        "load_json":          load_json,
        "save_json":          save_json,
    })

Command:
    dlevel / drank [@user]     — liat rank card (gambar)
    dleveltoggle on/off        — admin server toggle notif level-up (per server)
    dlevelchannel [#channel]   — admin server set channel notif level-up
                                  (kosongin arg buat balikin ke "channel yang
                                  lagi dipakai orangnya pas level up")
"""
import discord
import random
import time
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_FONT_CACHE: dict = {}


def _font(weight: str, size: int):
    key = (weight, size)
    if key not in _FONT_CACHE:
        path = FONT_DIR / f"Poppins-{weight}.ttf"
        try:
            _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
        except Exception:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def _rounded(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _gradient_bg(w: int, h: int, top=(22, 14, 14), bottom=(52, 12, 12)) -> Image.Image:
    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        d.line((0, y, w, y), fill=(r, g, b))
    return img


def _paste_avatar(img: Image.Image, avatar_bytes: bytes | None, x: int, y: int, size: int, ring_color=(178, 34, 34)):
    d = ImageDraw.Draw(img)
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            img.paste(av, (x, y), mask)
        except Exception:
            _rounded(d, (x, y, x + size, y + size), size // 2, fill=(60, 30, 30))
    else:
        _rounded(d, (x, y, x + size, y + size), size // 2, fill=(60, 30, 30))
    d.ellipse((x - 4, y - 4, x + size + 4, y + size + 4), outline=ring_color, width=4)


# ===================== XP & LEVEL MATH =====================
XP_MESSAGE_COOLDOWN = 80        # detik, minimal jeda per user biar dapet XP lagi
XP_MIN, XP_MAX       = 45, 75   # XP acak per pesan valid

LEVEL_TITLES = [
    (0,   "Newbie Server"),
    (10,  "Petarung Amatir"),
    (25,  "Veteran Aktif"),
    (50,  "Legenda Hidup"),
    (100, "Yang Mulia Raja"),
]


def get_level_title(level: int) -> str:
    title = LEVEL_TITLES[0][1]
    for min_lv, t in LEVEL_TITLES:
        if level >= min_lv:
            title = t
    return title


def xp_needed_for_level(level: int) -> int:
    """Total XP dibutuhin buat naik dari `level` ke `level+1`. Kurva makin
    curam makin tinggi level (standar bot leveling kayak MEE6/Arcane)."""
    return 5 * (level ** 2) + 50 * level + 100


def get_level_from_xp(total_xp: int):
    """total_xp kumulatif -> (level, xp_in_level, xp_needed_buat_level_ini)."""
    level = 0
    remaining = max(total_xp, 0)
    while True:
        needed = xp_needed_for_level(level)
        if remaining < needed:
            return level, remaining, needed
        remaining -= needed
        level += 1


def level_up_rewards(new_level: int) -> dict:
    """Reward pas naik level — disambungin ke ekonomi fishing yang udah ada."""
    return {
        "coins": 1500 * new_level,
        "materials": 3,
        "lootbox": 1 if new_level % 5 == 0 else 0,
    }


# ===================== RENDER GAMBAR =====================
def render_rank_card(avatar_bytes, username: str, title: str, level: int,
                      xp_in_level: int, xp_needed: int, rank: int) -> io.BytesIO:
    W, H = 700, 220
    img = _gradient_bg(W, H)
    d = ImageDraw.Draw(img)

    av_size = 150
    av_x, av_y = 35, (H - av_size) // 2
    _paste_avatar(img, avatar_bytes, av_x, av_y, av_size)

    tx = av_x + av_size + 30

    d.text((tx, 22), username[:20], font=_font("Bold", 34), fill=(240, 235, 232))
    d.text((tx, 64), title, font=_font("Medium", 20), fill=(225, 160, 160))
    d.text((tx, 94), f"LVL {level}", font=_font("Bold", 46), fill=(255, 215, 0))

    rank_font = _font("SemiBold", 20)
    rank_text = f"Rank #{rank:,}".replace(",", ".")
    rb = d.textbbox((0, 0), rank_text, font=rank_font)
    d.text((W - 30 - (rb[2] - rb[0]), 28), rank_text, font=rank_font, fill=(205, 205, 210))

    xp_font = _font("Medium", 18)
    xp_text = f"XP: {xp_in_level:,}/{xp_needed:,}".replace(",", ".")
    xb = d.textbbox((0, 0), xp_text, font=xp_font)
    d.text((W - 30 - (xb[2] - xb[0]), 58), xp_text, font=xp_font, fill=(205, 205, 210))

    bar_x, bar_y, bar_w, bar_h = tx, 160, W - tx - 30, 22
    _rounded(d, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), bar_h // 2, fill=(50, 24, 24))
    pct = min(xp_in_level / xp_needed, 1.0) if xp_needed else 0.0
    fill_w = int(bar_w * pct)
    if fill_w > 0:
        _rounded(d, (bar_x, bar_y, bar_x + max(fill_w, bar_h), bar_y + bar_h), bar_h // 2, fill=(178, 34, 34))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def render_levelup_card(avatar_bytes, username: str, new_level: int, rewards: dict) -> io.BytesIO:
    W, H = 500, 260
    img = _gradient_bg(W, H, top=(26, 14, 14), bottom=(64, 10, 10))
    d = ImageDraw.Draw(img)

    av_size = 90
    av_x, av_y = (W - av_size) // 2, 22
    _paste_avatar(img, avatar_bytes, av_x, av_y, av_size, ring_color=(255, 215, 0))

    banner_font = _font("Bold", 26)
    banner_text = "LEVEL UP!"
    bb = d.textbbox((0, 0), banner_text, font=banner_font)
    d.text((W / 2 - (bb[2] - bb[0]) / 2, 122), banner_text, font=banner_font, fill=(255, 90, 90))

    lvl_font = _font("Bold", 54)
    lvl_text = str(new_level)
    lb = d.textbbox((0, 0), lvl_text, font=lvl_font)
    d.text((W / 2 - (lb[2] - lb[0]) / 2, 150), lvl_text, font=lvl_font, fill=(255, 255, 255))

    name_font = _font("Medium", 16)
    nb = d.textbbox((0, 0), username, font=name_font)
    d.text((W / 2 - (nb[2] - nb[0]) / 2, 210), username[:24], font=name_font, fill=(200, 200, 205))

    reward_font = _font("Medium", 17)
    parts = []
    if rewards.get("coins"):
        parts.append(f"+{rewards['coins']} Koin")
    if rewards.get("materials"):
        parts.append(f"+{rewards['materials']} Serpihan Tempa")
    if rewards.get("lootbox"):
        parts.append(f"+{rewards['lootbox']} Lootbox")
    reward_text = "   •   ".join(parts)
    rb2 = d.textbbox((0, 0), reward_text, font=reward_font)
    d.text((W / 2 - (rb2[2] - rb2[0]) / 2, 232), reward_text, font=reward_font, fill=(240, 190, 90))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ===================== SETUP =====================
def setup_leveling(bot, deps: dict):
    get_user_fishing    = deps["get_user_fishing"]
    save_user_fishing   = deps["save_user_fishing"]
    get_fishing_data    = deps["get_fishing_data"]
    emoji                = deps["emoji"]
    DARK_RED             = deps["DARK_RED"]
    check_maintenance    = deps["check_maintenance"]
    check_premium_gate   = deps["check_premium_gate"]
    load_json            = deps["load_json"]
    save_json            = deps["save_json"]

    xp_cooldowns: dict = {}   # uid -> timestamp XP terakhir didapet

    def get_level_config() -> dict:
        return load_json("level_config.json", {})

    def get_guild_cfg(guild_id: int) -> dict:
        return get_level_config().get(str(guild_id), {})

    def is_announce_enabled(guild_id: int) -> bool:
        return get_guild_cfg(guild_id).get("announce", True)

    def set_announce(guild_id: int, enabled: bool):
        cfg = get_level_config()
        cfg.setdefault(str(guild_id), {})["announce"] = enabled
        save_json("level_config.json", cfg)

    def get_announce_channel_id(guild_id: int):
        return get_guild_cfg(guild_id).get("channel_id")

    def set_announce_channel(guild_id: int, channel_id: int | None):
        cfg = get_level_config()
        cfg.setdefault(str(guild_id), {})["channel_id"] = channel_id
        save_json("level_config.json", cfg)

    async def _fetch_avatar(user: discord.abc.User) -> bytes | None:
        try:
            return await user.display_avatar.replace(size=128, format="png").read()
        except Exception:
            return None

    # ---------------------------------------------------------------
    # XP dari chat (listener TERPISAH — gak nimpa on_message bot.py,
    # dua-duanya jalan bareng karena add_listener beda dari @bot.event)
    # ---------------------------------------------------------------
    async def on_message_xp(message: discord.Message):
        if message.author.bot or not message.guild:
            return
        uid = str(message.author.id)
        now = time.time()
        if uid in xp_cooldowns and now - xp_cooldowns[uid] < XP_MESSAGE_COOLDOWN:
            return
        xp_cooldowns[uid] = now

        udata = get_user_fishing(uid)
        old_level, _, _ = get_level_from_xp(udata.get("xp", 0))
        udata["xp"] = udata.get("xp", 0) + random.randint(XP_MIN, XP_MAX)
        new_level, _, _ = get_level_from_xp(udata["xp"])

        if new_level > old_level:
            rewards = level_up_rewards(new_level)
            udata["coins"]    += rewards["coins"]
            udata["materials"] = udata.get("materials", 0) + rewards["materials"]
            if rewards["lootbox"]:
                udata["lootbox"] = udata.get("lootbox", 0) + rewards["lootbox"]
                udata["lootbox_collected"] = udata.get("lootbox_collected", 0) + rewards["lootbox"]
            save_user_fishing(uid, udata)

            if is_announce_enabled(message.guild.id):
                # Kirim ke channel yang di-set owner/admin lewat dlevelchannel,
                # kalau belum di-set, fallback ke channel tempat dia lagi ngobrol.
                target_channel = message.channel
                chan_id = get_announce_channel_id(message.guild.id)
                if chan_id:
                    ch = message.guild.get_channel(chan_id)
                    if ch:
                        target_channel = ch
                avatar_bytes = await _fetch_avatar(message.author)
                buf  = render_levelup_card(avatar_bytes, message.author.display_name, new_level, rewards)
                file = discord.File(buf, filename="levelup.png")
                try:
                    await target_channel.send(
                        content=f"🎉 {message.author.mention} naik ke **Level {new_level}**!",
                        file=file
                    )
                except Exception:
                    pass
        else:
            save_user_fishing(uid, udata)

    bot.add_listener(on_message_xp, "on_message")

    # ---------------------------------------------------------------
    # Command
    # ---------------------------------------------------------------
    @bot.command(name="level", aliases=["rank", "lvl"])
    async def level_cmd(ctx, member: discord.Member = None):
        if await check_maintenance(ctx):
            return
        if await check_premium_gate(ctx, "level"):
            return
        target = member or ctx.author
        uid = str(target.id)
        udata = get_user_fishing(uid)
        level, xp_in_level, xp_needed = get_level_from_xp(udata.get("xp", 0))
        title = get_level_title(level)

        fdata = get_fishing_data()
        ranked = sorted(fdata.items(), key=lambda x: x[1].get("xp", 0), reverse=True)
        rank_pos = next((i + 1 for i, (u, _) in enumerate(ranked) if u == uid), len(ranked) or 1)

        avatar_bytes = await _fetch_avatar(target)
        buf  = render_rank_card(avatar_bytes, target.display_name, title, level, xp_in_level, xp_needed, rank_pos)
        file = discord.File(buf, filename="rank.png")
        await ctx.reply(file=file)

    @bot.command(name="leveltoggle")
    async def leveltoggle_cmd(ctx, mode: str = None):
        """Admin server toggle notif level-up di server ini. `dleveltoggle on/off`"""
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.reply(f"{emoji('fail')} Butuh permission **Manage Server** buat atur ini!")
            return
        if mode is None or mode.lower() not in ("on", "off"):
            cur = is_announce_enabled(ctx.guild.id)
            await ctx.reply(
                f"Notifikasi level-up di server ini: **{'ON' if cur else 'OFF'}**.\n"
                f"Ketik `dleveltoggle on` atau `dleveltoggle off` buat ganti."
            )
            return
        enabled = mode.lower() == "on"
        set_announce(ctx.guild.id, enabled)
        await ctx.reply(f"{emoji('success')} Notifikasi level-up di server ini sekarang **{'ON' if enabled else 'OFF'}**.")

    @bot.command(name="levelchannel", aliases=["setlevelchannel"])
    async def levelchannel_cmd(ctx, channel: discord.TextChannel = None):
        """Admin server atur channel KHUSUS buat notif level-up.
        `dlevelchannel #channel` — set channel-nya
        `dlevelchannel reset` (atau tanpa argumen valid) — balikin ke default
        (notif dikirim di channel tempat orangnya lagi ngobrol pas naik level)"""
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.reply(f"{emoji('fail')} Butuh permission **Manage Server** buat atur ini!")
            return

        raw_arg = ctx.message.content.split(maxsplit=1)[1].strip() if len(ctx.message.content.split(maxsplit=1)) > 1 else ""

        if channel is None:
            if raw_arg.lower() in ("reset", "off", "default", "hapus", ""):
                set_announce_channel(ctx.guild.id, None)
                await ctx.reply(f"{emoji('success')} Channel notif level-up di-reset ke default (channel tempat orangnya lagi ngobrol pas naik level).")
                return
            cur_id = get_announce_channel_id(ctx.guild.id)
            cur_ch = ctx.guild.get_channel(cur_id) if cur_id else None
            await ctx.reply(
                f"📍 Channel notif level-up sekarang: {cur_ch.mention if cur_ch else '_default (channel tempat chat)_'}\n"
                f"Ketik `dlevelchannel #channel` buat set, atau `dlevelchannel reset` buat balikin default."
            )
            return

        set_announce_channel(ctx.guild.id, channel.id)
        await ctx.reply(f"{emoji('success')} Notif level-up sekarang selalu dikirim ke {channel.mention}!")
