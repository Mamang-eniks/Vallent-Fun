# 🔥 RepublikDooms Discord Bot

Bot Discord gaul lengkap buat server lo! Fishing game, moderation, quest, daily login, sampai sistem premium QRIS — semua ada.

---

## ⚡ Setup Cepat

### 1. Install Python & Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables
Buat file `.env` atau set langsung di terminal:

**Windows:**
```cmd
set DISCORD_TOKEN=TOKEN_BOT_DISCORD_LO
set OWNER_ID=USER_ID_DISCORD_LO
```

**Linux/Mac:**
```bash
export DISCORD_TOKEN="TOKEN_BOT_DISCORD_LO"
export OWNER_ID="USER_ID_DISCORD_LO"
```

> `OWNER_ID` wajib diisi — dipakai buat fitur owner-only kayak `noprefix`, `setemoji`, panel premium, dan panel maintenance.

### 3. Jalankan Bot
```bash
python bot.py
```

---

## 🔑 Cara Dapet Token

### Discord Bot Token:
1. Buka https://discord.com/developers/applications
2. Klik **New Application** → kasih nama **RepublikDooms**
3. Pergi ke tab **Bot** → klik **Add Bot**
4. Klik **Reset Token** → copy token-nya
5. Di bagian **Privileged Gateway Intents**, aktifkan:
   - ✅ Presence Intent
   - ✅ Server Members Intent
   - ✅ Message Content Intent

### Owner ID:
1. Aktifkan **Developer Mode** di Discord (Settings → Advanced)
2. Klik kanan nama lo → **Copy User ID**

### Invite Bot ke Server:
1. Di Discord Developer Portal, pergi ke **OAuth2 > URL Generator**
2. Centang: `bot` + `applications.commands`
3. Di Bot Permissions centang: `Administrator` (atau pilih manual)
4. Buka URL yang generate, pilih server lo

---

## 🚀 Jalankan 24 Jam (VPS/Server)

### Pake PM2 (recommended):
```bash
npm install -g pm2
pm2 start bot.py --interpreter python3 --name RepublikDooms
pm2 save
pm2 startup
```

### Pake Screen:
```bash
screen -S dooms
python bot.py
# Ctrl+A lalu D buat detach
```

### Pake Systemd (Linux):
```ini
# /etc/systemd/system/dooms.service
[Unit]
Description=RepublikDooms Discord Bot
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/path/to/RepublikDooms
Environment=DISCORD_TOKEN=token_lo
Environment=OWNER_ID=owner_id_lo
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable dooms
sudo systemctl start dooms
```

---

## 📋 Daftar Command Lengkap

### Prefix: `!Doom` (juga bisa `!Kingdoom`)

| Command | Alias | Deskripsi |
|---------|-------|-----------|
| `!Doom fish` | `mancing`, `fishing` | Mulai mancing |
| `!Doom coins` | `koin`, `saldo` | Cek koin |
| `!Doom daily` | `login`, `harian`, `claim` | Klaim koin harian (streak makin gede bonusnya) |
| `!Doom quest` | `quests`, `misi` | Buka panel quest log (tab Daily/Quests) + klaim reward |
| `!Doom tebak` | `riddle`, `tebakan` | Main tebak-tebakan |
| `!Doom addtebak` | `addriddle`, `tambahtebak` | Tambah soal tebakan custom |
| `!Doom listtebak` | `listriddle`, `tebaklist` | List soal tebakan custom |
| `!Doom removetebak` | `deltebak`, `hapustebak` | Hapus soal tebakan custom |
| `!Doom warn @user [alasan]` | `peringatan` | Warn member |
| `!Doom warns @user` | `warnlist`, `cekwarn` | Cek warns member |
| `!Doom kick @user [alasan]` | `tendang` | Kick member |
| `!Doom ban @user [alasan]` | `banned` | Ban member |
| `!Doom timeout @user [menit]` | `mute` | Timeout member |
| `!Doom move @user #channel` | `pindah`, `vcmove` | Pindah member ke VC |
| `!Doom addrole @user @role` | `arole`, `giverole` | Tambah role |
| `!Doom removerole @user @role` | `rrole`, `delrole` | Copot role |
| `!Doom avatar [@user]` | `av` | Lihat avatar |
| `!Doom userinfo [@user]` | `ui`, `whois` | Info user |
| `!Doom clear [jumlah]` | `purge` | Hapus pesan |
| `!Doom embed Judul\|Deskripsi` | `em` | Kirim embed |
| `!Doom setmainchannel #channel` | `mainchannel`, `setmc` | Set channel utama |
| `!Doom autoresponse add/remove/list` | `ar` | Auto response |
| `!Doom sticky set/remove` | `stickymsg` | Sticky message |
| `!Doom giveaway [durasi] [hadiah]` | `ga` | Mulai giveaway |
| `!Doom event Nama\|Deskripsi\|Jam` | `announce`, `pengumuman` | Event message |
| `!Doom addemoji` | `ae`, `addemote` | Tambah custom emoji ke server (dari emoji di pesan) |
| `!Doom premium` | `prem`, `vip` | Info & order premium (QRIS) |
| `!Doom vote` | `upvote` | Link vote Top.gg |
| `!Doom claimvote` | `voteclaim` | Klaim reward vote |
| `!Doom help` | `h` | Tampilkan help |

### 👑 Owner Only
*(Section ini otomatis disembunyikan dari `!Doom help` kalau yang buka bukan Owner Bot — cuma didaftar di sini buat referensi lo)*

| Command | Alias | Deskripsi |
|---------|-------|-----------|
| `!Doom noprefix add/remove/list @user` | `np` | Kasih/cabut akses command tanpa prefix ke user lain |
| `!Doom setemoji <key> <emoji>` | `emojiset`, `seteemoji` | Ganti emoji default bot pakai emoji custom server. Ketik `!Doom setemoji list` buat lihat semua key |
| `!Doom setmaintenancechannel #channel` | `setmaintchannel`, `maintchannel` | Channel notifikasi maintenance |

**Cara kerja No-Prefix:** Owner bot otomatis punya akses ini. Kalau owner kasih akses ke user lain lewat `noprefix add @user`, user itu bisa ketik nama command langsung (misal `fish`, `daily`, `coins`) tanpa perlu ketik `!Doom` di depannya.

**Cara kerja Emoji Server:** Semua emoji "sistem" bot (koin, quest, daily, status sukses/gagal, dll) bisa diganti ke emoji custom server lewat `setemoji`. Contoh: `!Doom setemoji coin <:coingw:123456789012345678>`. Ketik `!Doom setemoji list` untuk lihat semua key yang bisa diatur (`coin`, `fish`, `success`, `fail`, `legendary`, `rare`, `uncommon`, `common`, `trash`, `quest`, `daily`, `vote`, `streak`). Emoji ikan/rod/bait di sistem fishing sendiri sudah bisa diatur bebas lewat `!Kingdoom setfishing`.

### Slash Commands `/`

| Command | Deskripsi |
|---------|-----------|
| `/fish` | Fishing game |
| `/daily` | Klaim koin harian |
| `/quest` | Buka panel quest log (tab Daily/Quests) + klaim reward |
| `/tebak` | Buka Arena Tebak-Tebakan |
| `/tambahsoal` | Tambah soal Arena Tebak yang aktif |
| `/addtebak` | Tambah soal tebakan custom |
| `/reactionrole` | Setup reaction role |
| `/giveaway` | Buat giveaway |
| `/warn` `/kick` `/ban` `/timeout` `/clear` | Moderasi |
| `/avatar` `/userinfo` | Info member |
| `/addrole` `/removerole` | Manage role |
| `/embed` `/sticky` `/autoresponse` | Utility |
| `/event` | Event message dengan auto-timer |
| `/coins` | Cek koin |
| `/leaderboard` | Leaderboard koin terbanyak |
| `/noprefix` | *(Owner)* Atur akses no-prefix |
| `/setemoji` | *(Owner)* Atur emoji custom server |
| `/setmaintenancechannel` | *(Admin)* Channel notifikasi maintenance |

---

## 🎣 Panduan Fishing

### Rod (Pancing):
| Nama | Tier | Harga | Bonus |
|------|------|-------|-------|
| Pancing Bambu | 1 | 50 🪙 | x1.0 |
| Pancing Kayu | 2 | 150 🪙 | x1.3 |
| Pancing Besi | 3 | 400 🪙 | x1.7 |
| Pancing Karbon | 4 | 900 🪙 | x2.2 |
| Pancing Titan | 5 | 2000 🪙 | x3.0 |
| Pancing Legenda | 6 | 5000 🪙 | x5.0 |

### Umpan:
| Nama | Harga | Bonus |
|------|-------|-------|
| Cacing Biasa | 10 🪙 | x1.0 |
| Cacing Gemuk | 25 🪙 | x1.5 |
| Jangkrik | 40 🪙 | x2.0 |
| Udang Kecil | 60 🪙 | x2.5 |
| Ikan Kecil | 100 🪙 | x3.5 |

### Ikan:
- 🐟 Common: Lele (15), Mas (25)
- 🐡 Uncommon: Gurame (40), Salmon (60)
- 🦈 Rare: Tuna (100), Hiu Kecil (200)
- 🐉 Legendary: Duyung (500), Naga (1000)

> ⏰ Cooldown mancing: **10 detik** (notif cooldown otomatis ilang sendiri pas waktunya abis)
> 🔒 Inventori bersifat privat, hanya bisa dilihat sendiri

### 🎯 Quest Log Panel
`!Doom quest` / `/quest` buka panel quest log interaktif (gaya tab Daily/Quests) dengan tombol **Claim**. Beda dari sebelumnya, reward quest **gak otomatis masuk** — begitu target kecapai, quest berstatus "🎁 SIAP DIKLAIM", tinggal buka panel dan pencet **Claim**:

| Quest | Target | Reward |
|-------|--------|--------|
| 🎣 Pemula Mancing | 5 ikan | 100 koin |
| 🐟 Mancing Rajin | 15 ikan | 250 koin + Pancing Kayu gratis |
| 🦈 Mancing Handal | 30 ikan | 500 koin + Pancing Besi gratis |
| 🔱 Master Pemancing | 60 ikan | 1000 koin + Pancing Karbon gratis |
| 🐉 Legenda Mancing | 100 ikan | 2500 koin + Pancing Titan gratis |
| 🗳️ Vote Bot di Top.gg | 1x vote | 150 koin |

Panel yang sama juga punya tab **Daily** buat lihat status & klaim daily login lo tanpa perlu command terpisah.

### 🎁 Daily Login
- `!Doom daily` / `/daily` / tab **Daily** di panel quest — klaim koin tiap 24 jam (100–250 koin base)
- Streak berturut-turut nambah bonus (+15 koin/hari, cap 300 koin)
- Kalau lewat 48 jam gak klaim, streak reset ke 1

---

## 📁 File Data (auto-generate di folder `data/`)
- `fishing.json` — Data fishing, koin, quest progress user
- `fishing_config.json` — Konfigurasi ikan/rod/umpan custom
- `daily.json` — Data streak & klaim daily login
- `noprefix.json` — Daftar user dengan akses no-prefix
- `emoji_config.json` — Emoji custom server yang sudah diset owner
- `warns.json` — Data warn
- `config.json` — Konfigurasi server
- `autoresponse.json` — Auto response
- `sticky.json` — Sticky messages
- `giveaways.json` — Data giveaway
- `custom_tebakan.json` — Soal tebak-tebakan custom
- `premium.json` / `premium_orders.json` — Data & order premium
- `maintenance.json` — Status maintenance bot
- `vote.json` — Data vote Top.gg

---

## 🗑️ Fitur yang Sudah Dihapus
Ticket system, leveling/XP, dan ganti bahasa (`setlang`) sudah dihapus dari bot ini. Bot sekarang fixed pakai Bahasa Indonesia gaul untuk semua user.

> ℹ️ Footer di embed sekarang pakai nama **"Nikoliesamphink"**, sementara judul/nama bot di berbagai tempat lain (activity status, judul embed, dll) tetap **"DOOMINIKS PARADISE"**.

---

Made with ❤️ for RepublikDooms
