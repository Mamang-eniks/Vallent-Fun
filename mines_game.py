"""
mines_game.py — Mines (kartu gosok/minesweeper taruhan) StartDoom
Sengaja dipisah dari bot.py biar file utamanya gak numpuk.

Cara pakai (di bot.py, taruh di paling bawah, SETELAH semua fungsi/konstanta
yang dibutuhin di bawah ini udah kedefinisi):

    from mines_game import setup_mines
    setup_mines(bot, {
        "get_user_fishing":   get_user_fishing,
        "save_user_fishing":  save_user_fishing,
        "emoji":              emoji,
        "DARK_RED":           DARK_RED,
        "check_maintenance":  check_maintenance,
        "check_premium_gate": check_premium_gate,
    })

===============================================================================
MATEMATIKA MULTIPLIER (biar akurat, bukan angka asal)
===============================================================================
Grid isinya TOTAL_TILES kotak, MINES di antaranya adalah bom (posisi acak).
Kalau user buka `k` kotak aman BERTURUT-TURUT tanpa kena bom, peluang itu
terjadi murni (tanpa house edge) adalah:

    P(k aman) = C(safe, k) / C(total, k)
              = product_{i=0}^{k-1} (safe - i) / (total - i)

Multiplier "adil" (fair, kalau gak ada house edge) itu kebalikan dari
peluangnya:

    fair_multiplier(k) = 1 / P(k aman)
                       = product_{i=0}^{k-1} (total - i) / (safe - i)

Ini persis rumus yang dipakai game Mines di Stake dkk. Bot ambil untung
kecil (house edge 3%) dengan ngaliin fair_multiplier * 0.97, jadi player
EV per taruhan sedikit di bawah 1.0 (rata-rata bot untung 3% dalam jangka
panjang) — tapi tetep transparan & konsisten, bukan diakalin per-game.
===============================================================================
"""
import discord
import random


GRID_ROWS     = 4
GRID_COLS     = 5
TOTAL_TILES   = GRID_ROWS * GRID_COLS   # 20 kotak — pas 4 baris tile + 1 baris tombol Cash Out (max 5 row Discord)
HOUSE_EDGE    = 0.97                    # bot ambil untung 3% jangka panjang
DEFAULT_MINES = 3
MINES_TIMEOUT = 180                     # detik, auto cash-out/refund kalau didiemin


def fair_multiplier(total: int, mines: int, revealed: int) -> float:
    """Multiplier MURNI dari probabilitas (belum dipotong house edge)."""
    safe = total - mines
    if revealed <= 0:
        return 1.0
    m = 1.0
    for i in range(revealed):
        denom = safe - i
        if denom <= 0:
            break
        m *= (total - i) / denom
    return m


def compute_multiplier(total: int, mines: int, revealed: int) -> float:
    """Multiplier FINAL (udah dipotong house edge) — ini yang dipakai buat
    hitung coin beneran."""
    if revealed <= 0:
        return 1.0
    return fair_multiplier(total, mines, revealed) * HOUSE_EDGE


class MinesSession:
    def __init__(self, user_id: int, bet: int, mines: int):
        self.user_id  = user_id
        self.bet      = bet
        self.mines    = mines
        self.mine_positions = set(random.sample(range(TOTAL_TILES), mines))
        self.revealed   = set()
        self.game_over  = False
        self.cashed_out = False
        self.message: discord.Message | None = None

    @property
    def safe_tiles(self) -> int:
        return TOTAL_TILES - self.mines

    @property
    def current_multiplier(self) -> float:
        return compute_multiplier(TOTAL_TILES, self.mines, len(self.revealed))

    @property
    def next_multiplier(self) -> float:
        return compute_multiplier(TOTAL_TILES, self.mines, len(self.revealed) + 1)

    @property
    def current_winnings(self) -> int:
        return round(self.bet * self.current_multiplier)


def setup_mines(bot, deps: dict):
    """Daftarin command & semua logic Mines ke `bot`."""

    get_user_fishing    = deps["get_user_fishing"]
    save_user_fishing   = deps["save_user_fishing"]
    emoji                = deps["emoji"]
    DARK_RED             = deps["DARK_RED"]
    check_maintenance    = deps["check_maintenance"]
    check_premium_gate   = deps["check_premium_gate"]

    active_games: dict = {}   # uid -> MinesSession, cegah user buka 2 game bareng

    # ---------------------------------------------------------------
    # Tampilan
    # ---------------------------------------------------------------
    def build_embed(session: MinesSession, status: str | None = None) -> discord.Embed:
        em = discord.Embed(title="💣 Mines", color=DARK_RED)
        lines = [
            f"**Taruhan:** {session.bet} {emoji('coin')}",
            f"**Jumlah Bom:** {session.mines}/{TOTAL_TILES}",
        ]
        if not session.game_over and not session.cashed_out:
            lines.append(f"**Kotak aman terbuka:** {len(session.revealed)}/{session.safe_tiles}")
            lines.append(f"**Multiplier sekarang:** `{session.current_multiplier:.2f}x` → **{session.current_winnings}** {emoji('coin')}")
            if len(session.revealed) < session.safe_tiles:
                nxt_win = round(session.bet * session.next_multiplier)
                lines.append(f"**Kalau aman lagi:** `{session.next_multiplier:.2f}x` → {nxt_win} {emoji('coin')}")
        em.description = "\n".join(lines)
        if status:
            em.add_field(name="\u200b", value=status, inline=False)
        em.set_footer(text="Klik kotak buat buka. Klik Cash Out kapan aja buat amanin koin lo.")
        return em

    # ---------------------------------------------------------------
    # Tombol
    # ---------------------------------------------------------------
    class TileButton(discord.ui.Button):
        def __init__(self, idx: int):
            super().__init__(style=discord.ButtonStyle.secondary, label="❔", row=idx // GRID_COLS)
            self.idx = idx

        async def callback(self, interaction: discord.Interaction):
            view: "MinesView" = self.view
            session = view.session
            if interaction.user.id != session.user_id:
                await interaction.response.send_message("❌ Bukan permainan lo!", ephemeral=True)
                return
            if session.game_over or session.cashed_out:
                await interaction.response.send_message("⚠️ Game ini udah selesai, mulai baru pake `dmines`.", ephemeral=True)
                return
            if self.idx in session.revealed or self.disabled:
                await interaction.response.send_message("⚠️ Kotak ini udah dibuka!", ephemeral=True)
                return

            if self.idx in session.mine_positions:
                # KENA BOM — game over, hangus, reveal semua kotak
                session.game_over = True
                active_games.pop(session.user_id, None)
                view.reveal_all(hit_idx=self.idx)
                await interaction.response.edit_message(
                    embed=build_embed(session, f"💥 **KENA BOM!** Taruhan **{session.bet}** {emoji('coin')} hangus semuanya."),
                    view=view
                )
                return

            # Aman!
            session.revealed.add(self.idx)
            self.style = discord.ButtonStyle.success
            self.label = "💎"
            self.disabled = True

            if len(session.revealed) >= session.safe_tiles:
                # Semua kotak aman udah kebuka semua — otomatis cash out full win
                await _do_cashout(interaction, session, view, auto_full_clear=True)
                return

            view.update_cashout_button()
            await interaction.response.edit_message(embed=build_embed(session), view=view)

    class CashOutButton(discord.ui.Button):
        def __init__(self):
            super().__init__(style=discord.ButtonStyle.success, label="💰 Cash Out", row=GRID_ROWS, disabled=True)

        async def callback(self, interaction: discord.Interaction):
            view: "MinesView" = self.view
            session = view.session
            if interaction.user.id != session.user_id:
                await interaction.response.send_message("❌ Bukan permainan lo!", ephemeral=True)
                return
            if session.game_over or session.cashed_out or not session.revealed:
                await interaction.response.send_message("⚠️ Belum ada yang bisa di-cash out — buka minimal 1 kotak dulu!", ephemeral=True)
                return
            await _do_cashout(interaction, session, view, auto_full_clear=False)

    async def _do_cashout(interaction: discord.Interaction, session: MinesSession, view: "MinesView", auto_full_clear: bool):
        session.cashed_out = True
        active_games.pop(session.user_id, None)
        winnings = session.current_winnings
        udata = get_user_fishing(str(session.user_id))
        udata["coins"] += winnings
        save_user_fishing(str(session.user_id), udata)
        view.reveal_all(hit_idx=None)
        prefix = "🏆 **SEMUA KOTAK AMAN TERBUKA!** " if auto_full_clear else "✅ **Cash Out!** "
        status = (
            f"{prefix}Menang **{winnings}** {emoji('coin')} (`{session.current_multiplier:.2f}x` dari taruhan {session.bet}). "
            f"Koin sekarang: **{udata['coins']}**."
        )
        await interaction.response.edit_message(embed=build_embed(session, status), view=view)

    class MinesView(discord.ui.View):
        def __init__(self, session: MinesSession):
            super().__init__(timeout=MINES_TIMEOUT)
            self.session = session
            self.tiles: list[TileButton] = []
            for i in range(TOTAL_TILES):
                btn = TileButton(i)
                self.tiles.append(btn)
                self.add_item(btn)
            self.cashout_btn = CashOutButton()
            self.add_item(self.cashout_btn)

        def update_cashout_button(self):
            s = self.session
            self.cashout_btn.disabled = len(s.revealed) == 0
            if s.revealed:
                self.cashout_btn.label = f"💰 Cash Out ({s.current_winnings} koin)"

        def reveal_all(self, hit_idx: int | None):
            """Buka SEMUA kotak (dipanggil pas kalah/cash out/timeout) —
            bom ditandain 💣 (yang bener2 diinjek jadi 💥), sisanya 💎."""
            s = self.session
            for i, btn in enumerate(self.tiles):
                btn.disabled = True
                if i in s.mine_positions:
                    btn.style = discord.ButtonStyle.danger
                    btn.label = "💥" if i == hit_idx else "💣"
                else:
                    btn.style = discord.ButtonStyle.success
                    btn.label = "💎"
            self.cashout_btn.disabled = True

        async def on_timeout(self):
            s = self.session
            if s.game_over or s.cashed_out:
                return  # udah kelar duluan, gak perlu apa-apa lagi
            active_games.pop(s.user_id, None)
            if s.revealed:
                # Udah sempat ambil resiko & buka kotak → auto cash-out di
                # multiplier terakhir, adil buat player (bukan dianggurin ilang).
                s.cashed_out = True
                udata = get_user_fishing(str(s.user_id))
                udata["coins"] += s.current_winnings
                save_user_fishing(str(s.user_id), udata)
                status = f"⏰ Timeout — auto Cash Out **{s.current_winnings}** {emoji('coin')} (`{s.current_multiplier:.2f}x`)."
            else:
                # Belum buka kotak SAMA SEKALI → refund taruhan penuh,
                # gak fair kalau ilang gara-gara nganggur doang.
                udata = get_user_fishing(str(s.user_id))
                udata["coins"] += s.bet
                save_user_fishing(str(s.user_id), udata)
                status = f"⏰ Timeout — taruhan **{s.bet}** {emoji('coin')} di-refund penuh (belum sempat ambil resiko)."
            self.reveal_all(hit_idx=None)
            if s.message:
                try:
                    await s.message.edit(embed=build_embed(s, status), view=self)
                except Exception:
                    pass

    # ---------------------------------------------------------------
    # Command
    # ---------------------------------------------------------------
    @bot.command(name="mines", aliases=["minesweeper", "gosok"])
    async def mines_cmd(ctx, bet: int = None, mines: int = DEFAULT_MINES):
        if await check_maintenance(ctx):
            return
        if await check_premium_gate(ctx, "mines"):
            return
        if ctx.author.id in active_games:
            await ctx.reply("⚠️ Lo masih ada game Mines yang aktif! Beresin/Cash Out dulu ya.")
            return
        if bet is None or bet <= 0:
            await ctx.reply(
                f"⚠️ **Cara main:** `dmines <taruhan> [jumlah_bom]`\n"
                f"Contoh: `dmines 100` (default {DEFAULT_MINES} bom) atau `dmines 100 8` (8 bom).\n"
                f"Grid isinya **{TOTAL_TILES} kotak**. Makin banyak bom yang dipilih, makin gede multiplier tiap kotak aman — tapi makin gampang kena bom juga.\n"
                f"Bisa Cash Out kapan aja abis buka minimal 1 kotak, biar koinnya keamanin."
            )
            return
        if mines < 1 or mines >= TOTAL_TILES:
            await ctx.reply(f"❌ Jumlah bom harus antara **1-{TOTAL_TILES - 1}**!")
            return
        udata = get_user_fishing(str(ctx.author.id))
        if udata["coins"] < bet:
            await ctx.reply(f"❌ Koin lo kurang! Taruhan **{bet}**, koin lo cuma **{udata['coins']}**.")
            return

        udata["coins"] -= bet
        save_user_fishing(str(ctx.author.id), udata)

        session = MinesSession(ctx.author.id, bet, mines)
        active_games[ctx.author.id] = session
        view = MinesView(session)
        msg = await ctx.reply(embed=build_embed(session), view=view)
        session.message = msg
