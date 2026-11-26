# Milliy Test — Claude uchun yo'riqnoma

Django 5 loyihasi: Telegram bot (pyTelegramBotAPI, webhook), Telegram WebApp sahifalari (Django
shablonlari), admin panel. Baza — SQLite. Server Ubuntu'da Passenger bilan, **bir nechta jarayonda**
ishlaydi va boshqa loyihalar bilan bir serverda turadi. Foydalanuvchilar bilan o'zbek tilida yozing.

## Xatoni tuzatish tartibi

1. Xatolar manbai:
   - GitHub Issues, `auto-error` belgisi (server avtomatik ochadi). Sarlavhada `[xato <fingerprint>]`.
   - Xatolar API'si: `GET https://<domen>/api/errors/?key=<kalit>` (JSON). Kalitni foydalanuvchi beradi —
     uni hech qayerga (kod, commit, issue) yozmang. `&text=1` — matn, `&since=<unix vaqt>` — faqat yangilari.
     Bitta xato: `GET /api/errors/<fingerprint>/?key=...`. Javobdagi `code_version` — serverdagi commit;
     repo'dagi kod undan yangi bo'lsa, xato allaqachon tuzatilgan bo'lishi mumkin.
   Ma'lumotlar yashirilgan: `<PHONE>`, `<ID>`, `<EMAIL>`, `<BOT_TOKEN>` — bu haqiqiy qiymat emas.
2. Traceback'dagi "Joyi" (`fayl:qator (funksiya)`) — loyiha kodidagi eng ichki qator. Shu yerdan boshlang.
3. Tuzatishga test yozing (`webapp/tests.py`), keyin hammasini ishga tushiring:
   `python manage.py test webapp`
4. Commit xabarida fingerprint yoki issue raqamini yozing (`Fixes #12`). Serverga yuklangach
   `DELETE /api/errors/<fingerprint>/` bilan ro'yxatdan olib tashlash mumkin — xato qaytsa yana paydo bo'ladi.

## Tuzilishi

| Fayl | Vazifasi |
|---|---|
| `main/bot.py` | Bot handlerlari, majburiy obuna (`check_user_membership`), webhook |
| `main/services.py` | Test javoblarini tekshirish/saqlash (WebApp va API umumiy mantig'i) |
| `main/models.py` | Modellar; ball hisoblash `Test.check_answer`, `BlockTest.calculate_score` |
| `main/reklama.py`, `main/management/commands/send_reklama.py` | Reklama: cron har daqiqada 100 tadan yuboradi |
| `main/state.py` | Bot suhbat holati — jarayonlararo umumiy fayl keshi (oddiy dict ishlatmang!) |
| `main/errorlog.py`, `main/errors_api.py` | Xatolar jurnali (`logs/errors.json`), `/api/errors/`, GitHub Issues |
| `main/views.py` | REST API — faqat staff (`IsAdminUser`) |
| `webapp/auth.py` | WebApp kirish: Telegram initData -> imzolangan cookie sessiya; obuna tekshiruvi |
| `webapp/views.py`, `webapp/templates/webapp/` | WebApp sahifalari |

## Qoidalar

- **Resurs:** server umumiy. Og'ir kutubxona, fon jarayoni, Celery/Redis qo'shmang. Har so'rovda
  Telegram API yoki bazaga ortiqcha murojaat qilmang.
- **Baza:** SQLite, bir nechta jarayon yozadi. Uzun tranzaksiyalardan qoching. Tez o'sadigan jadval
  (log, har-foydalanuvchi-uchun qator) qo'shmang; kerak bo'lsa tozalashni `cleanup` buyrug'iga qo'shing.
- **Holat:** jarayon xotirasidagi o'zgaruvchiga (global dict) holat saqlamang — `main/state.py` dan foydalaning.
- **Maxfiylik:** `.env`, `db.sqlite3`, `logs/`, shaxsiy ma'lumotlarni commit qilmang.
- **Funksionallik:** foydalanuvchi ko'radigan xatti-harakatni so'ralmasa o'zgartirmang. Bot va WebApp
  URL'lari (`webapp/urls.py`) bot tugmalarida ishlatiladi — nomini o'zgartirmang.
- Telegram xabarlari HTML parse_mode bilan — foydalanuvchi matnini `html.escape` qiling.
