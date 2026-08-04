"""
trade_system.py — Sistem Trade Item StartDoom
Sengaja dipisah dari bot.py biar file utamanya gak numpuk.

Cara pakai (di bot.py, taruh di paling bawah, SETELAH semua fungsi/konstanta
yang dibutuhin di bawah ini udah kedefinisi):

    from trade_system import setup_trade
    setup_trade(bot, {
        "get_user_fishing":   get_user_fishing,
        "save_user_fishing":  save_user_fishing,
        "get_fishing_config": get_fishing_config,
        "emoji":              emoji,
        "DARK_RED":           DARK_RED,
        "MATERIAL_NAME":      MATERIAL_NAME,
        "MATERIAL_EMOJI":     MATERIAL_EMOJI,
        "check_maintenance":  check_maintenance,
        "check_premium_gate": check_premium_gate,
    })

Item yang bisa ditrade: ikan (dari inventori), rod (yang dimiliki), koin,
Serpihan Tempa (material upgrade rod).

Alur:
1. `dtrade @user` — kirim ajakan trade, target Accept/Decline (60 detik).
2. Diterima → muncul panel trade bareng, masing-masing user pilih item pake
   tombol (Ikan/Rod/Koin/Material), lalu kunci tawaran (🔒).
3. Begitu DUA-DUANYA kunci → countdown 8 detik. Klik Batal kapan aja
   sebelum itu buat batalin. Kalau gak dibatalin, item otomatis ketuker.
"""
import discord
import asyncio


TRADE_INVITE_TIMEOUT = 60   # detik, invite trade expire kalau gak direspon
TRADE_LOCK_COUNTDOWN = 8    # detik jeda sebelum item otomatis ketuker
STARTER_ROD_FALLBACK = "Pancing Bambu"


class TradeSession:
    """State 1 sesi trade antara 2 user."""
    def __init__(self, user_a: discord.abc.User, user_b: discord.abc.User):
        self.user_a = user_a
        self.user_b = user_b
        self.offer = {
            user_a.id: {"fish": {}, "rods": [], "coins": 0, "materials": 0},
            user_b.id: {"fish": {}, "rods": [], "coins": 0, "materials": 0},
        }
        self.locked = {user_a.id: False, user_b.id: False}
        self.message: discord.Message | None = None
        self.cancelled = False
        self.executing = False
        self.countdown_task: asyncio.Task | None = None

    def participant(self, uid: int) -> bool:
        return uid in (self.user_a.id, self.user_b.id)

    def other_user(self, uid: int) -> discord.abc.User:
        return self.user_b if uid == self.user_a.id else self.user_a


def setup_trade(bot, deps: dict):
    """Daftarin command & semua logic trade ke `bot`. Panggil sekali aja
    dari bot.py setelah semua dependency di `deps` udah kedefinisi."""

    get_user_fishing    = deps["get_user_fishing"]
    save_user_fishing   = deps["save_user_fishing"]
    get_fishing_config  = deps["get_fishing_config"]
    emoji                = deps["emoji"]
    DARK_RED             = deps["DARK_RED"]
    MATERIAL_NAME        = deps["MATERIAL_NAME"]
    MATERIAL_EMOJI       = deps["MATERIAL_EMOJI"]
    check_maintenance    = deps["check_maintenance"]
    check_premium_gate   = deps["check_premium_gate"]

    # uid -> TradeSession (dua-duanya nunjuk ke session yang sama), dipake
    # buat cek "user ini lagi trade aktif gak" & routing interaksi.
    active_trades: dict = {}

    # ---------------------------------------------------------------
    # Helper tampilan
    # ---------------------------------------------------------------
    def offer_lines(session: TradeSession, uid: int) -> str:
        o = session.offer[uid]
        lines = []
        for name, qty in o["fish"].items():
            lines.append(f"🐟 {name} x{qty}")
        if o["rods"]:
            _, rods, _ = get_fishing_config()
            rod_map = {r["name"]: r for r in rods}
            for rname in o["rods"]:
                remoji = rod_map.get(rname, {}).get("emoji") or emoji("fish")
                lines.append(f"{remoji} {rname}")
        if o["coins"] > 0:
            lines.append(f"{emoji('coin')} {o['coins']} koin")
        if o["materials"] > 0:
            lines.append(f"{MATERIAL_EMOJI} {o['materials']}x {MATERIAL_NAME}")
        if not lines:
            lines.append("_(kosong, belum ada item)_")
        lock_mark = "🔒 **TERKUNCI**" if session.locked[uid] else "🔓 Belum dikunci"
        return "\n".join(lines) + f"\n\n{lock_mark}"

    def build_embed(session: TradeSession, status: str | None = None) -> discord.Embed:
        em = discord.Embed(title="🔄 Trade Item", color=DARK_RED)
        if status:
            em.description = status
        em.add_field(name=f"📦 Tawaran {session.user_a.display_name}",
                      value=offer_lines(session, session.user_a.id), inline=True)
        em.add_field(name=f"📦 Tawaran {session.user_b.display_name}",
                      value=offer_lines(session, session.user_b.id), inline=True)
        em.set_footer(text="Pilih item lewat tombol di bawah, lalu kunci tawaran lo. "
                            f"Trade jalan otomatis {TRADE_LOCK_COUNTDOWN} detik setelah DUA-DUANYA kunci.")
        return em

    async def refresh_main(session: TradeSession, status: str | None = None):
        if session.message:
            try:
                await session.message.edit(embed=build_embed(session, status), view=TradeMainView(session))
            except Exception:
                pass

    def cleanup(session: TradeSession):
        active_trades.pop(session.user_a.id, None)
        active_trades.pop(session.user_b.id, None)
        if session.countdown_task and not session.countdown_task.done():
            session.countdown_task.cancel()

    # ---------------------------------------------------------------
    # Select buat nambahin Ikan / Rod ke tawaran
    # ---------------------------------------------------------------
    class FishOfferSelect(discord.ui.Select):
        def __init__(self, session: TradeSession, uid: int):
            udata = get_user_fishing(str(uid))
            inv_count = {}
            for item in udata.get("inventory", []):
                inv_count[item] = inv_count.get(item, 0) + 1
            options = [discord.SelectOption(label=f"{name} (x{qty})", value=name)
                       for name, qty in list(inv_count.items())[:25]]
            if not options:
                options = [discord.SelectOption(label="Inventori ikan kosong", value="__none__")]
            super().__init__(placeholder="🐟 Pilih ikan (semua stok jenis itu ditawarin)...", options=options)
            self.session = session
            self.uid = uid

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.uid:
                await interaction.response.send_message("❌ Bukan tawaran lo!", ephemeral=True)
                return
            if self.session.locked[self.uid]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            if self.values[0] == "__none__":
                await interaction.response.send_message("⚠️ Inventori ikan lo kosong, mancing dulu bro!", ephemeral=True)
                return
            udata = get_user_fishing(str(self.uid))
            name  = self.values[0]
            qty   = udata.get("inventory", []).count(name)
            if qty <= 0:
                await interaction.response.send_message("❌ Ikan itu udah gak ada di inventori lo!", ephemeral=True)
                return
            self.session.offer[self.uid]["fish"][name] = qty
            await interaction.response.send_message(f"✅ **{name} x{qty}** ditambahin ke tawaran lo!", ephemeral=True)
            await refresh_main(self.session)

    class RodOfferSelect(discord.ui.Select):
        def __init__(self, session: TradeSession, uid: int):
            udata      = get_user_fishing(str(uid))
            owned_rods = udata.get("owned_rods") or [udata.get("rod", STARTER_ROD_FALLBACK)]
            already    = session.offer[uid]["rods"]
            _, rods, _ = get_fishing_config()
            rod_map    = {r["name"]: r for r in rods}
            available  = [r for r in owned_rods if r not in already]
            options = [
                discord.SelectOption(label=name, value=name,
                                      emoji=rod_map.get(name, {}).get("emoji") or emoji("fish"))
                for name in available[:25]
            ]
            if not options:
                options = [discord.SelectOption(label="Gak ada rod tersisa buat ditawarin", value="__none__")]
            super().__init__(placeholder="🎣 Pilih rod buat ditawarin...", options=options)
            self.session = session
            self.uid = uid

        async def callback(self, interaction: discord.Interaction):
            if interaction.user.id != self.uid:
                await interaction.response.send_message("❌ Bukan tawaran lo!", ephemeral=True)
                return
            if self.session.locked[self.uid]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            if self.values[0] == "__none__":
                await interaction.response.send_message("⚠️ Gak ada rod tersisa buat ditawarin!", ephemeral=True)
                return
            udata = get_user_fishing(str(self.uid))
            name  = self.values[0]
            if name not in (udata.get("owned_rods") or []):
                await interaction.response.send_message("❌ Rod itu udah bukan punya lo!", ephemeral=True)
                return
            self.session.offer[self.uid]["rods"].append(name)
            await interaction.response.send_message(f"✅ **{name}** ditambahin ke tawaran lo!", ephemeral=True)
            await refresh_main(self.session)

    # ---------------------------------------------------------------
    # View utama trade (tombol Ikan/Rod/Koin/Material/Reset/Kunci/Batal)
    # ---------------------------------------------------------------
    class TradeMainView(discord.ui.View):
        def __init__(self, session: TradeSession):
            super().__init__(timeout=600)
            self.session = session

        async def _guard(self, interaction: discord.Interaction) -> bool:
            if not self.session.participant(interaction.user.id):
                await interaction.response.send_message("❌ Ini bukan trade lo!", ephemeral=True)
                return False
            if self.session.cancelled or self.session.executing:
                await interaction.response.send_message("⚠️ Trade ini udah gak aktif lagi.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Ikan", emoji="🐟", style=discord.ButtonStyle.secondary, row=0)
        async def add_fish(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            if self.session.locked[interaction.user.id]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            view = discord.ui.View(timeout=60)
            view.add_item(FishOfferSelect(self.session, interaction.user.id))
            await interaction.response.send_message(view=view, ephemeral=True)

        @discord.ui.button(label="Rod", emoji="🎣", style=discord.ButtonStyle.secondary, row=0)
        async def add_rod(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            if self.session.locked[interaction.user.id]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            view = discord.ui.View(timeout=60)
            view.add_item(RodOfferSelect(self.session, interaction.user.id))
            await interaction.response.send_message(view=view, ephemeral=True)

        @discord.ui.button(label="Koin", emoji="🪙", style=discord.ButtonStyle.secondary, row=0)
        async def add_coins(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            if self.session.locked[interaction.user.id]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            udata = get_user_fishing(str(interaction.user.id))
            await interaction.response.send_message(
                f"{emoji('coin')} Koin lo: **{udata['coins']}**. Ketik jumlah koin yang mau ditawarin (dalam 30 detik):",
                ephemeral=True
            )
            try:
                msg = await bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == interaction.user.id and m.channel.id == interaction.channel.id,
                    timeout=30
                )
                amount = int(msg.content.strip())
                udata  = get_user_fishing(str(interaction.user.id))
                if amount < 0 or amount > udata["coins"]:
                    await interaction.followup.send(f"❌ Jumlah gak valid! Koin lo cuma {udata['coins']}.", ephemeral=True)
                    return
                self.session.offer[interaction.user.id]["coins"] = amount
                await interaction.followup.send(f"✅ **{amount} koin** ditawarin!", ephemeral=True)
                await refresh_main(self.session)
            except ValueError:
                await interaction.followup.send("❌ Itu bukan angka!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout!", ephemeral=True)

        @discord.ui.button(label="Serpihan Tempa", emoji="⚒️", style=discord.ButtonStyle.secondary, row=0)
        async def add_materials(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            if self.session.locked[interaction.user.id]:
                await interaction.response.send_message("🔒 Tawaran lo udah dikunci! Reset dulu kalau mau ubah.", ephemeral=True)
                return
            udata = get_user_fishing(str(interaction.user.id))
            have  = udata.get("materials", 0)
            await interaction.response.send_message(
                f"{MATERIAL_EMOJI} {MATERIAL_NAME} lo: **{have}**. Ketik jumlah yang mau ditawarin (dalam 30 detik):",
                ephemeral=True
            )
            try:
                msg = await bot.wait_for(
                    "message",
                    check=lambda m: m.author.id == interaction.user.id and m.channel.id == interaction.channel.id,
                    timeout=30
                )
                amount = int(msg.content.strip())
                udata  = get_user_fishing(str(interaction.user.id))
                if amount < 0 or amount > udata.get("materials", 0):
                    await interaction.followup.send(f"❌ Jumlah gak valid! {MATERIAL_NAME} lo cuma {udata.get('materials', 0)}.", ephemeral=True)
                    return
                self.session.offer[interaction.user.id]["materials"] = amount
                await interaction.followup.send(f"✅ **{amount}x {MATERIAL_NAME}** ditawarin!", ephemeral=True)
                await refresh_main(self.session)
            except ValueError:
                await interaction.followup.send("❌ Itu bukan angka!", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("⏰ Timeout!", ephemeral=True)

        @discord.ui.button(label="Reset Tawaran", emoji="♻️", style=discord.ButtonStyle.secondary, row=1)
        async def reset_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            uid = interaction.user.id
            self.session.offer[uid] = {"fish": {}, "rods": [], "coins": 0, "materials": 0}
            self.session.locked[uid] = False
            if self.session.countdown_task and not self.session.countdown_task.done():
                self.session.countdown_task.cancel()
            await interaction.response.send_message("♻️ Tawaran lo direset!", ephemeral=True)
            await refresh_main(self.session, "🔓 Salah satu tawaran direset, countdown dibatalin (kalau lagi jalan).")

        @discord.ui.button(label="Kunci Tawaran", emoji="🔒", style=discord.ButtonStyle.success, row=1)
        async def lock_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            uid = interaction.user.id
            self.session.locked[uid] = not self.session.locked[uid]  # toggle
            action = "dikunci 🔒" if self.session.locked[uid] else "dibuka lagi 🔓"
            await interaction.response.send_message(f"Tawaran lo {action}.", ephemeral=True)

            if all(self.session.locked.values()):
                await refresh_main(self.session, f"⏳ **DUA-DUANYA UDAH KUNCI!** Trade otomatis jalan dalam **{TRADE_LOCK_COUNTDOWN} detik**. Klik Batal kalau berubah pikiran!")
                self.session.countdown_task = asyncio.create_task(run_countdown(self.session))
            else:
                if self.session.countdown_task and not self.session.countdown_task.done():
                    self.session.countdown_task.cancel()
                await refresh_main(self.session)

        @discord.ui.button(label="Batalin Trade", emoji="❌", style=discord.ButtonStyle.danger, row=1)
        async def cancel_trade(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._guard(interaction):
                return
            self.session.cancelled = True
            cleanup(self.session)
            await interaction.response.send_message("❌ Trade dibatalin.", ephemeral=True)
            await refresh_main(self.session, f"❌ **Trade dibatalin oleh {interaction.user.display_name}.**")

    # ---------------------------------------------------------------
    # Countdown & eksekusi swap
    # ---------------------------------------------------------------
    async def run_countdown(session: TradeSession):
        try:
            for sisa in range(TRADE_LOCK_COUNTDOWN, 0, -1):
                await asyncio.sleep(1)
                if session.cancelled or not all(session.locked.values()):
                    return
            await execute_trade(session)
        except asyncio.CancelledError:
            return

    def _validate_offer(uid: int, offer: dict) -> str | None:
        """Return pesan error kalau tawaran user itu udah gak valid lagi
        (item kejual/kepake pas countdown jalan). None kalau valid."""
        udata = get_user_fishing(str(uid))
        for name, qty in offer["fish"].items():
            if udata.get("inventory", []).count(name) < qty:
                return f"ikan **{name}** udah gak cukup"
        for rname in offer["rods"]:
            if rname not in (udata.get("owned_rods") or []):
                return f"rod **{rname}** udah bukan miliknya lagi"
        if udata["coins"] < offer["coins"]:
            return "koin udah gak cukup"
        if udata.get("materials", 0) < offer["materials"]:
            return f"{MATERIAL_NAME} udah gak cukup"
        return None

    async def execute_trade(session: TradeSession):
        session.executing = True
        uid_a, uid_b = session.user_a.id, session.user_b.id
        offer_a, offer_b = session.offer[uid_a], session.offer[uid_b]

        # Re-validasi terakhir — jaga-jaga item kepake/kejual pas countdown jalan
        err_a = _validate_offer(uid_a, offer_a)
        err_b = _validate_offer(uid_b, offer_b)
        if err_a or err_b:
            who  = session.user_a.display_name if err_a else session.user_b.display_name
            reason = err_a or err_b
            cleanup(session)
            await refresh_main(session, f"❌ **Trade DIBATALIN OTOMATIS!** Tawaran {who} udah gak valid ({reason}). Gak ada item yang ketuker.")
            return

        def apply(giver_uid: int, receiver_uid: int, offer: dict):
            gdata = get_user_fishing(str(giver_uid))
            rdata = get_user_fishing(str(receiver_uid))

            # Ikan
            for name, qty in offer["fish"].items():
                for _ in range(qty):
                    if name in gdata["inventory"]:
                        gdata["inventory"].remove(name)
                rdata.setdefault("inventory", []).extend([name] * qty)
                if name not in rdata.get("fish_dex", []):
                    rdata.setdefault("fish_dex", []).append(name)

            # Rod
            for rname in offer["rods"]:
                owned_g = gdata.setdefault("owned_rods", [])
                if rname in owned_g:
                    owned_g.remove(rname)
                if gdata.get("rod") == rname:
                    gdata["rod"] = owned_g[0] if owned_g else STARTER_ROD_FALLBACK
                lvl = gdata.get("rod_levels", {}).pop(rname, 0)
                owned_r = rdata.setdefault("owned_rods", [])
                if rname not in owned_r:
                    owned_r.append(rname)
                if lvl and rname not in rdata.get("rod_levels", {}):
                    rdata.setdefault("rod_levels", {})[rname] = lvl

            # Koin & Material
            gdata["coins"] -= offer["coins"]
            rdata["coins"] += offer["coins"]
            gdata["materials"] = gdata.get("materials", 0) - offer["materials"]
            rdata["materials"] = rdata.get("materials", 0) + offer["materials"]

            save_user_fishing(str(giver_uid), gdata)
            save_user_fishing(str(receiver_uid), rdata)

        apply(uid_a, uid_b, offer_a)
        apply(uid_b, uid_a, offer_b)

        cleanup(session)
        em = discord.Embed(title="✅ Trade Berhasil!", color=DARK_RED)
        em.add_field(name=f"{session.user_a.display_name} dapet", value=offer_lines_static(offer_b, receiver_label=True), inline=True)
        em.add_field(name=f"{session.user_b.display_name} dapet", value=offer_lines_static(offer_a, receiver_label=True), inline=True)
        if session.message:
            try:
                await session.message.edit(embed=em, view=None)
            except Exception:
                pass

    def offer_lines_static(offer: dict, receiver_label: bool = False) -> str:
        lines = []
        for name, qty in offer["fish"].items():
            lines.append(f"🐟 {name} x{qty}")
        if offer["rods"]:
            _, rods, _ = get_fishing_config()
            rod_map = {r["name"]: r for r in rods}
            for rname in offer["rods"]:
                remoji = rod_map.get(rname, {}).get("emoji") or emoji("fish")
                lines.append(f"{remoji} {rname}")
        if offer["coins"] > 0:
            lines.append(f"{emoji('coin')} {offer['coins']} koin")
        if offer["materials"] > 0:
            lines.append(f"{MATERIAL_EMOJI} {offer['materials']}x {MATERIAL_NAME}")
        return "\n".join(lines) if lines else "_(gak ada)_"

    # ---------------------------------------------------------------
    # Invite (accept/decline)
    # ---------------------------------------------------------------
    class TradeInviteView(discord.ui.View):
        def __init__(self, inviter: discord.abc.User, target: discord.abc.User):
            super().__init__(timeout=TRADE_INVITE_TIMEOUT)
            self.inviter = inviter
            self.target  = target

        async def on_timeout(self):
            active_trades.pop(self.inviter.id, None)
            active_trades.pop(self.target.id, None)
            if self.message:
                try:
                    await self.message.edit(content=f"⏰ Ajakan trade dari {self.inviter.mention} ke {self.target.mention} expired.", view=None)
                except Exception:
                    pass

        @discord.ui.button(label="Terima", emoji="✅", style=discord.ButtonStyle.success)
        async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.target.id:
                await interaction.response.send_message("❌ Ajakan ini bukan buat lo!", ephemeral=True)
                return
            session = TradeSession(self.inviter, self.target)
            active_trades[self.inviter.id] = session
            active_trades[self.target.id]  = session
            await interaction.response.edit_message(
                content=None, embed=build_embed(session), view=TradeMainView(session)
            )
            session.message = await interaction.original_response()

        @discord.ui.button(label="Tolak", emoji="✖️", style=discord.ButtonStyle.danger)
        async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != self.target.id:
                await interaction.response.send_message("❌ Ajakan ini bukan buat lo!", ephemeral=True)
                return
            active_trades.pop(self.inviter.id, None)
            active_trades.pop(self.target.id, None)
            await interaction.response.edit_message(content=f"❌ {self.target.mention} nolak ajakan trade.", embed=None, view=None)

    # ---------------------------------------------------------------
    # Command
    # ---------------------------------------------------------------
    @bot.command(name="trade", aliases=["tradeitem", "tuker"])
    async def trade_cmd(ctx, target: discord.Member = None):
        if await check_maintenance(ctx):
            return
        if await check_premium_gate(ctx, "trade"):
            return
        if target is None:
            await ctx.reply("⚠️ Mention user yang mau diajak trade! Contoh: `dtrade @user`")
            return
        if target.id == ctx.author.id:
            await ctx.reply("❌ Gak bisa trade sama diri sendiri bro!")
            return
        if target.bot:
            await ctx.reply("❌ Gak bisa trade sama bot!")
            return
        if ctx.author.id in active_trades:
            await ctx.reply("⚠️ Lo lagi ada trade aktif! Beresin/batalin itu dulu.")
            return
        if target.id in active_trades:
            await ctx.reply(f"⚠️ {target.mention} lagi ada trade aktif sama orang lain, coba lagi nanti.")
            return

        # Placeholder biar dua-duanya "kereserve" pas invite masih pending
        # (dihapus lagi kalau ditolak/timeout, atau dilanjut kalau diterima).
        placeholder = TradeSession(ctx.author, target)
        active_trades[ctx.author.id] = placeholder
        active_trades[target.id] = placeholder

        view = TradeInviteView(ctx.author, target)
        msg = await ctx.reply(
            f"🔄 {ctx.author.mention} ngajakin trade sama {target.mention}!\n"
            f"{target.mention}, mau terima?",
            view=view
        )
        view.message = msg
