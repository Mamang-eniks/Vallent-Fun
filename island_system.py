"""
island_system.py — Sistem Pulau (progresi mancing per-area) StartDoom
Sengaja dipisah dari bot.py biar file utamanya gak numpuk.

Konsep: ada TOTAL_ISLANDS pulau (default 7). Tiap pulau punya daftar ikan
SENDIRI (di-setup owner lewat panel `dsetisland`) + gambar pulau (owner
upload langsung lewat Discord). User mulai di Pulau 1 — begitu SEMUA jenis
ikan di pulau itu udah pernah ketangkep (masuk fish_dex), otomatis pindah
ke pulau berikutnya. Kalau pulau belum di-setup ikannya sama sekali, sistem
fallback pakai daftar ikan umum (gak nge-block gameplay selama owner belum
sempat setup).

Cara pakai (taruh di bot.py PALING BAWAH, setelah semua dependency ini
kedefinisi, DAN sebelum FishingMainView dipakai user — makanya `island_hooks`
di bot.py dideklarasiin placeholder duluan di atas, baru di-assign ulang
di sini):

    from island_system import setup_islands
    island_hooks = setup_islands(bot, {
        "get_user_fishing":   get_user_fishing,
        "emoji":              emoji,
        "DARK_RED":           DARK_RED,
        "OWNER_ID":           OWNER_ID,
        "check_maintenance":  check_maintenance,
        "check_premium_gate": check_premium_gate,
        "load_json":          load_json,
        "save_json":          save_json,
    })

`island_hooks` yang di-return itu dict berisi:
    get_current_fish_pool(uid)          -> list[fish_dict] | None (None = fallback global)
    record_catch_and_maybe_advance(uid) -> str | None (notif kalau naik pulau)
    get_island_status_line(uid)         -> str (buat ditampilin di panel dfish)

Command:
    dpulau / disland          — liat progress pulau sendiri (+ gambar)
    dsetisland                — panel owner buat atur ikan & gambar tiap pulau
"""
import discord
import asyncio

TOTAL_ISLANDS = 7


def setup_islands(bot, deps: dict):
    get_user_fishing    = deps["get_user_fishing"]
    emoji                = deps["emoji"]
    DARK_RED             = deps["DARK_RED"]
    OWNER_ID             = deps["OWNER_ID"]
    check_maintenance    = deps["check_maintenance"]
    check_premium_gate   = deps["check_premium_gate"]
    load_json            = deps["load_json"]
    save_json            = deps["save_json"]

    # ---------------------------------------------------------------
    # Data
    # ---------------------------------------------------------------
    def get_island_config() -> dict:
        cfg = load_json("island_config.json", {})
        islands = cfg.get("islands") or {}
        changed = False
        for i in range(1, TOTAL_ISLANDS + 1):
            if str(i) not in islands:
                islands[str(i)] = {"name": f"Pulau {i}", "image_url": None, "fishes": []}
                changed = True
        if changed:
            save_json("island_config.json", {"islands": islands})
        return islands

    def save_island_config(islands: dict):
        save_json("island_config.json", {"islands": islands})

    def get_user_island(uid: str) -> int:
        data = load_json("island_progress.json", {})
        return data.get(uid, {}).get("island", 1)

    def set_user_island(uid: str, island_id: int):
        data = load_json("island_progress.json", {})
        data.setdefault(uid, {})["island"] = island_id
        save_json("island_progress.json", data)

    # ---------------------------------------------------------------
    # Hooks buat dipanggil dari bot.py (fishing core)
    # ---------------------------------------------------------------
    def get_current_fish_pool(uid: str):
        islands = get_island_config()
        cur = get_user_island(uid)
        isl = islands.get(str(cur))
        if isl and isl["fishes"]:
            return isl["fishes"]
        return None  # pulau ini belum ada ikan spesifik -> fallback daftar global

    def record_catch_and_maybe_advance(uid: str):
        islands = get_island_config()
        cur = get_user_island(uid)
        isl = islands.get(str(cur))
        if not isl or not isl["fishes"]:
            return None  # gak ada yang bisa dicek progress-nya
        udata = get_user_fishing(uid)
        dex = set(udata.get("fish_dex", []))
        fish_names = {f["name"] for f in isl["fishes"]}
        if not fish_names.issubset(dex):
            return None  # belum lengkap
        if cur >= TOTAL_ISLANDS:
            return f"🏆 **SELAMAT!** Lo udah nyelesain ikan di **SEMUA {TOTAL_ISLANDS} PULAU**! Pemancing sejati! 🎣👑"
        next_id = cur + 1
        set_user_island(uid, next_id)
        next_name = islands.get(str(next_id), {}).get("name", f"Pulau {next_id}")
        return f"🏝️ **Pulau {cur} ({isl['name']}) SELESAI!** Semua ikan di situ udah lo tangkep. Lanjut ke **Pulau {next_id}: {next_name}**!"

    def get_island_status_line(uid: str) -> str:
        islands = get_island_config()
        cur = get_user_island(uid)
        isl = islands.get(str(cur), {})
        name = isl.get("name", f"Pulau {cur}")
        fishes = isl.get("fishes", [])
        if not fishes:
            return f"📍 **Pulau {cur}: {name}**"
        udata = get_user_fishing(uid)
        dex = set(udata.get("fish_dex", []))
        got = sum(1 for f in fishes if f["name"] in dex)
        return f"📍 **Pulau {cur}: {name}** ({got}/{len(fishes)} ikan)"

    # ---------------------------------------------------------------
    # Command user: liat progress pulau
    # ---------------------------------------------------------------
    @bot.command(name="pulau", aliases=["island", "islands"])
    async def pulau_cmd(ctx, member: discord.Member = None):
        if await check_maintenance(ctx):
            return
        if await check_premium_gate(ctx, "pulau"):
            return
        target = member or ctx.author
        uid = str(target.id)
        islands = get_island_config()
        cur = get_user_island(uid)
        isl = islands.get(str(cur), {})
        udata = get_user_fishing(uid)
        dex = set(udata.get("fish_dex", []))
        fishes = isl.get("fishes", [])

        em = discord.Embed(title=f"🏝️ {target.display_name} — Pulau {cur}: {isl.get('name', '?')}", color=DARK_RED)
        if fishes:
            got = sum(1 for f in fishes if f["name"] in dex)
            lines = []
            for f in fishes:
                if f["name"] in dex:
                    lines.append(f"✅ {f.get('emoji', '🐟')} {f['name']}")
                else:
                    lines.append("❔ ???")
            em.description = f"**Progress pulau ini:** {got}/{len(fishes)} ikan\n\n" + "\n".join(lines)
        else:
            em.description = "_Pulau ini belum di-setup ikan spesifiknya sama owner. Ikan yang keluar masih dari daftar umum (`dsetfishing`)._"
        if isl.get("image_url"):
            em.set_image(url=isl["image_url"])
        em.set_footer(text=f"Total {TOTAL_ISLANDS} pulau. Selesein semua ikan pulau ini buat auto-lanjut ke pulau berikutnya!")
        await ctx.reply(embed=em)

    # ---------------------------------------------------------------
    # Panel owner: atur ikan & gambar tiap pulau
    # ---------------------------------------------------------------
    def build_admin_embed(island_id: int) -> discord.Embed:
        islands = get_island_config()
        isl = islands.get(str(island_id), {})
        fishes = isl.get("fishes", [])
        fish_lines = "\n".join(f"{f.get('emoji', '🐟')} {f['name']} — {f.get('sell_price', 0)} koin, luck {f.get('luck', 0)}%" for f in fishes) or "_Belum ada ikan di-setup._"
        em = discord.Embed(title=f"⚙️ Setup Pulau {island_id}: {isl.get('name', '?')}", color=DARK_RED)
        em.description = (
            f"**Jumlah ikan:** {len(fishes)}\n"
            f"**Gambar:** {'✅ udah di-set' if isl.get('image_url') else '❌ belum di-set'}\n\n"
            f"**Daftar Ikan:**\n{fish_lines}"
        )
        if isl.get("image_url"):
            em.set_thumbnail(url=isl["image_url"])
        em.set_footer(text="Ganti pulau yang diatur lewat dropdown di bawah.")
        return em

    class IslandPickSelect(discord.ui.Select):
        def __init__(self, current: int):
            options = [discord.SelectOption(label=f"Pulau {i}", value=str(i), default=(i == current)) for i in range(1, TOTAL_ISLANDS + 1)]
            super().__init__(placeholder=f"Lagi ngatur Pulau {current}...", options=options, row=0)

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ Cuma Owner Bot yang bisa pake panel ini!", ephemeral=True)
                return
            new_id = int(self.values[0])
            await interaction.response.edit_message(embed=build_admin_embed(new_id), view=IslandSetupView(new_id))

    class IslandSetupView(discord.ui.View):
        def __init__(self, island_id: int = 1):
            super().__init__(timeout=300)
            self.island_id = island_id
            self.add_item(IslandPickSelect(island_id))

        async def _owner_only(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != OWNER_ID:
                await interaction.response.send_message("❌ Cuma Owner Bot yang bisa pake panel ini!", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Tambah Ikan", emoji="➕", style=discord.ButtonStyle.success, row=1)
        async def add_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._owner_only(interaction):
                return
            await interaction.response.send_message(
                f"➕ **Tambah ikan ke Pulau {self.island_id}** — format: `nama|emoji|sell_price|luck_persen`\n"
                f"Contoh: `Ikan Karang|🐠|60|10`\n"
                f"⚠️ Kalau nama udah ada di pulau ini, datanya di-UPDATE (bukan dobel). Kirim dalam 60 detik.",
                ephemeral=True
            )
            try:
                msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
                parts = [p.strip() for p in msg.content.strip().split("|")]
                if len(parts) < 4:
                    await interaction.followup.send("❌ Format salah! Butuh 4 bagian dipisah `|`.", ephemeral=True)
                    return
                item = {"name": parts[0], "emoji": parts[1], "sell_price": int(parts[2]), "luck": float(parts[3])}
                islands = get_island_config()
                fishes = islands[str(self.island_id)]["fishes"]
                existing = next((x for x in fishes if x["name"] == item["name"]), None)
                if existing:
                    fishes[fishes.index(existing)] = item
                    verb = "diupdate"
                else:
                    fishes.append(item)
                    verb = "ditambahin"
                save_island_config(islands)
                await interaction.followup.send(f"✅ **{item['name']}** berhasil {verb} ke Pulau {self.island_id}!", ephemeral=True)
            except (ValueError, IndexError):
                await interaction.followup.send("❌ Format value salah (angka harus angka)!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout!", ephemeral=True)

        @discord.ui.button(label="Hapus Ikan", emoji="➖", style=discord.ButtonStyle.danger, row=1)
        async def remove_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._owner_only(interaction):
                return
            islands = get_island_config()
            fishes = islands[str(self.island_id)]["fishes"]
            names = ", ".join(f["name"] for f in fishes) or "-"
            await interaction.response.send_message(f"➖ Ketik nama ikan yang mau dihapus dari Pulau {self.island_id}:\n`{names}`\nKirim dalam 60 detik.", ephemeral=True)
            try:
                msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
                name = msg.content.strip()
                match = next((f for f in fishes if f["name"].lower() == name.lower()), None)
                if not match:
                    await interaction.followup.send(f"❌ **{name}** gak ketemu di Pulau {self.island_id}!", ephemeral=True)
                    return
                fishes.remove(match)
                save_island_config(islands)
                await interaction.followup.send(f"✅ **{match['name']}** dihapus dari Pulau {self.island_id}!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout!", ephemeral=True)

        @discord.ui.button(label="Set Gambar", emoji="🖼️", style=discord.ButtonStyle.primary, row=1)
        async def set_image(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._owner_only(interaction):
                return
            await interaction.response.send_message(
                f"🖼️ Upload gambar buat Pulau {self.island_id} sekarang (kirim sebagai attachment/lampiran gambar). Kirim dalam 90 detik.",
                ephemeral=True
            )
            try:
                msg = await bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == interaction.user.id and m.attachments,
                    timeout=90
                )
                url = msg.attachments[0].url
                islands = get_island_config()
                islands[str(self.island_id)]["image_url"] = url
                save_island_config(islands)
                await interaction.followup.send(f"✅ Gambar Pulau {self.island_id} berhasil di-set!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout, gak ada gambar yang dikirim!", ephemeral=True)

        @discord.ui.button(label="Ganti Nama", emoji="✏️", style=discord.ButtonStyle.secondary, row=1)
        async def rename(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._owner_only(interaction):
                return
            await interaction.response.send_message(f"✏️ Ketik nama baru buat Pulau {self.island_id} (dalam 60 detik):", ephemeral=True)
            try:
                msg = await bot.wait_for("message", check=lambda m: m.author.id == interaction.user.id, timeout=60)
                new_name = msg.content.strip()[:80]
                islands = get_island_config()
                islands[str(self.island_id)]["name"] = new_name
                save_island_config(islands)
                await interaction.followup.send(f"✅ Pulau {self.island_id} sekarang bernama **{new_name}**!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout!", ephemeral=True)

    @bot.command(name="setisland", aliases=["islandsetup", "setpulau"])
    async def setisland_cmd(ctx):
        if ctx.author.id != OWNER_ID:
            await ctx.reply(f"{emoji('fail')} Cuma Owner Bot yang bisa pake command ini!")
            return
        await ctx.reply(embed=build_admin_embed(1), view=IslandSetupView(1))

    # ---------------------------------------------------------------
    # Return hooks buat dipanggil dari bot.py
    # ---------------------------------------------------------------
    return {
        "get_current_fish_pool": get_current_fish_pool,
        "record_catch_and_maybe_advance": record_catch_and_maybe_advance,
        "get_island_status_line": get_island_status_line,
    }
