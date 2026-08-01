# 🔥 RepublikDooms Discord Bot

Bot Discord gaul lengkap buat server lo! Semua fitur ada, dari AI chat sampai fishing game.

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
set ANTHROPIC_API_KEY=API_KEY_ANTHROPIC_LO
```

**Linux/Mac:**
```bash
export DISCORD_TOKEN="TOKEN_BOT_DISCORD_LO"
export ANTHROPIC_API_KEY="API_KEY_ANTHROPIC_LO"
```

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

### Anthropic API Key (buat fitur AI):
1. Daftar/login di https://console.anthropic.com
2. Pergi ke **API Keys** → **Create Key**
3. Copy key-nya

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
Environment=ANTHROPIC_API_KEY=api_key_lo
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

### Prefix: `!Doom`

| Command | Deskripsi |
|---------|-----------|
| `!Doom ai [pertanyaan]` | Tanya AI |
| `!Doom fish` | Mulai mancing |
| `!Doom coins` | Cek koin |
| `!Doom tebak` | Main tebak-tebakan |
| `!Doom warn @user [alasan]` | Warn member |
| `!Doom warns @user` | Cek warns member |
| `!Doom kick @user [alasan]` | Kick member |
| `!Doom ban @user [alasan]` | Ban member |
| `!Doom timeout @user [menit]` | Timeout member |
| `!Doom move @user #channel` | Pindah member ke VC |
| `!Doom addrole @user @role` | Tambah role |
| `!Doom removerole @user @role` | Copot role |
| `!Doom avatar [@user]` | Lihat avatar |
| `!Doom userinfo [@user]` | Info user |
| `!Doom clear [jumlah]` | Hapus pesan |
| `!Doom embed Judul\|Deskripsi` | Kirim embed |
| `!Doom ar add/remove/list` | Auto response |
| `!Doom sticky set/remove` | Sticky message |
| `!Doom giveaway [durasi] [hadiah]` | Mulai giveaway |
| `!Doom event Nama\|Deskripsi\|Jam` | Event message |
| `!Doom addemoji` | Tambah emoji |
| `!Doom help` | Tampilkan help |

### Slash Commands `/`

| Command | Deskripsi |
|---------|-----------|
| `/ai` | AI chat |
| `/fish` | Fishing game |
| `/ticket` | Setup panel ticket |
| `/leveling` | Setup leveling |
| `/reactionrole` | Setup reaction role |
| `/giveaway` | Buat giveaway |
| `/warn` `/kick` `/ban` | Moderasi |
| `/timeout` `/clear` | Moderasi |
| `/avatar` `/userinfo` | Info member |
| `/addrole` `/removerole` | Manage role |
| `/embed` `/sticky` | Utility |
| `/autoresponse` | Auto response |
| `/event` | Event message |
| `/tebak` | Tebak-tebakan |
| `/coins` | Cek koin |
| `/leaderboard` | Top level |

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

> ⏰ Cooldown mancing: **10 detik**
> 🔒 Inventori bersifat privat, hanya bisa dilihat sendiri

---

## 📁 File Data (auto-generate)
- `data/fishing.json` - Data fishing & koin user
- `data/levels.json` - Data level user
- `data/warns.json` - Data warn
- `data/config.json` - Konfigurasi server
- `data/autoresponse.json` - Auto response
- `data/sticky.json` - Sticky messages
- `data/giveaways.json` - Data giveaway
- `data/tickets.json` - Data ticket

---

Made with ❤️ for RepublikDooms
