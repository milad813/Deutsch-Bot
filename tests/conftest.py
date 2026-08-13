import os
import tempfile

# ✅ جلوگیری از اتصال به دیتابیس اصلی هنگام اجرای تست‌ها
os.environ.setdefault(
    "DB_PATH",
    os.path.join(tempfile.gettempdir(), "deutsch_bot_test.db"),
)

os.environ.setdefault("BOT_MODE", "offline")
os.environ.setdefault("ALLOW_PUBLIC_ACCESS", "1")
os.environ.setdefault("GROQ_API_KEYS", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
