# 🤖 Telegram Account Shop Bot

## Features
- 🛍 Buy Telegram accounts by country (paginated list)
- 💳 Wallet — add funds via UPI, check balance
- 🔐 **Auto OTP** — fetched directly from account's 777000 chat
- 📦 Order history with phone, password, OTP
- 🆘 Support — messages forwarded to admin
- 🔧 Admin panel — add stock, approve payments, broadcast

---

## 📁 Project Structure
```
tgbot/
├── bot.py                  # Entry point
├── config.py               # ← Edit this first!
├── database.py             # SQLite layer
├── checker.py              # Session validity checker
├── otp_fetcher.py          # Auto OTP reader from 777000
├── requirements.txt
└── handlers/
    ├── user_handlers.py    # Start, wallet, profile, orders, support
    ├── payment_handlers.py # UPI add-funds flow
    ├── account_handlers.py # Buy flow + Get Code button
    └── admin_handlers.py   # Admin panel, stock, payments, /otp
```

---

## 🚀 Setup

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Fill config.py
```python
BOT_TOKEN         = "YOUR_TOKEN"       # @BotFather
ADMIN_IDS         = [YOUR_USER_ID]     # @userinfobot
UPI_ID            = "yourname@upi"
UPI_NAME          = "Your Shop Name"
UPI_QR_PATH       = "qr.png"          # put your QR image here
TELEGRAM_API_ID   = 12345678          # my.telegram.org
TELEGRAM_API_HASH = "abc123..."
```

### 3. Run
```bash
python bot.py
```

---

## ➕ Adding Stock

### With session string (Auto OTP — recommended)
```
/addstock
India|55
+91XXXXXXXXXX|password123|BQACAgIAAxk...long_session_string
+91XXXXXXXXXX|password456|BQACAgIAAxk...long_session_string
```

### Without session string (Manual OTP via /otp)
```
/addstock
India|55
+91XXXXXXXXXX|password123
+91XXXXXXXXXX|password456
```

**Format:** `CountryName|price` on first line, one account per line after.

---

## 🔐 OTP Flow

### Automatic (session string present)
```
User buys → sees phone + password + [🔐 Get Code] button
              ↓
         Clicks Get Code
              ↓
    Pyrogram connects with session_string
              ↓
    Reads latest message from 777000
              ↓
    Regex extracts 5-digit OTP
              ↓
    Deducts money + marks sold + delivers OTP
```

### Manual (no session string)
```
User buys → sees phone + password → waits
              ↓
         Admin sees notification
              ↓
         /otp 42 84523
              ↓
    Deducts money + marks sold + delivers OTP
```

---

## 🔧 Admin Commands

| Command | Description |
|---------|-------------|
| `/admin` | Admin panel |
| `/addstock` | Add accounts |
| `/pendingpay` | Pending payment requests |
| `/otp <order_id> <code>` | Manually send OTP |
| `/checksessions` | Bulk verify all sessions |
| `/broadcast <msg>` | Message all users |

---

## ☁️ Deploy (24/7)

```bash
# systemd service
sudo nano /etc/systemd/system/tgbot.service

[Unit]
Description=Telegram Shop Bot
After=network.target

[Service]
WorkingDirectory=/path/to/tgbot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target

sudo systemctl enable tgbot
sudo systemctl start tgbot
sudo systemctl status tgbot
```

## 📊 How to Get Session Strings

```python
# generate_session.py
from pyrogram import Client

api_id   = YOUR_API_ID
api_hash = "YOUR_API_HASH"

with Client("gen", api_id, api_hash) as app:
    print(app.export_session_string())
```

Run → enter phone → enter OTP → copy the printed session string.
