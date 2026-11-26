# Milliy Test — Telegram bot va WebApp

Milliy sertifikat, DTM (blok) va kitob testlarini yaratish, topshirish va natijalarni hisoblash uchun
Django loyihasi: Telegram bot, Telegram WebApp sahifalari, REST API (faqat adminlar uchun) va admin panel.

## Tuzilishi

| Papka | Vazifasi |
|---|---|
| `main/` | Modellar, bot (`bot.py`), REST API (`views.py`), umumiy mantiq (`services.py`), admin panel |
| `webapp/` | Telegram WebApp sahifalari (Django shablonlari) |
| `home/` | Sozlamalar va URL'lar |
| `templates/admin/` | Admin panel shablonlari (statistika) |

## Lokal ishga tushirish

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env          # qiymatlarni to'ldiring, lokal uchun DJANGO_DEBUG=1
./venv/bin/python manage.py migrate
./venv/bin/python manage.py createsuperuser
./venv/bin/python manage.py runserver
```

WebApp sahifalarini Telegram'siz brauzerda sinash uchun `.env` da `DJANGO_DEBUG=1` va
`WEBAPP_DEV_TELEGRAM_ID=<telegram_id>` qo'ying. Haqiqiy foydalanuvchilarga xabar ketmasligi uchun
sinovda test bot tokenidan foydalaning.

Testlar: `./venv/bin/python manage.py test`

## Serverga qo'yish

1. `.env` faylini yarating (`.env.example` asosida): `DJANGO_DEBUG=0`, yangi `DJANGO_SECRET_KEY`,
   `TELEGRAM_BOT_TOKEN`, `DJANGO_ALLOWED_HOSTS`.
2. `pip install -r requirements.txt`
3. `python manage.py migrate` va `python manage.py collectstatic`
4. Reklama yuborish uchun cron (har daqiqada 100 tadan yuboradi):
   ```
   * * * * * cd /loyiha/yoli && venv/bin/python manage.py send_reklama
   ```
5. Bazani ixcham saqlash uchun oyiga bir marta (foydalanuvchi ma'lumotlariga tegmaydi):
   ```
   0 4 1 * * cd /loyiha/yoli && venv/bin/python manage.py cleanup --vacuum
   ```
6. Webhook: `https://<domen>/webhook/` (ixtiyoriy `TELEGRAM_WEBHOOK_SECRET` bilan).

## Xatolarni kuzatish

Barcha xatolar (500, bot handlerlari, cron) `logs/errors.json` ga yig'iladi — bir xil xato bitta yozuv
bo'lib, faqat soni oshadi. Baza ishlatilmaydi. Ko'rish usullari:

- `python manage.py errors` (tozalash: `--clear` yoki `--clear <fingerprint>`)
- **API** (`ERROR_LOG_KEY` kaliti bilan, admin login kerak emas):
  - `GET /api/errors/?key=<kalit>` — xatolar ro'yxati (JSON; `&text=1` — oddiy matn, `&since=<unix>`, `&limit=`)
  - `GET /api/errors/<fingerprint>/?key=<kalit>` — bitta xato to'liq traceback bilan
  - `DELETE /api/errors/<fingerprint>/` — tuzatilgan xatoni o'chirish (`Authorization: Bearer <kalit>`)
  - Javobda `code_version` — serverdagi kod qaysi commit'da ekani.
- `GITHUB_ERRORS_TOKEN` berilsa — har bir yangi xato uchun `auto-error` belgili GitHub Issue.
  Telefon, Telegram ID, token va email yashiriladi. Issue yopilgach xato qaytsa, u qayta ochiladi.

## Bot buyruqlari

| Buyruq | Kim uchun | Vazifasi |
|---|---|---|
| `/start`, `/register`, `/profile` | hamma | Menyu, ro'yxatdan o'tish, profil |
| `/natija_<kod>`, `/yakunlash_<kod>` | test muallifi | Milliy test natijalari / yakunlash (Rasch, PDF) |
| `/natijablock_<kod>`, `/stop_block_<kod>` | test muallifi | DTM natijalari / yakunlash (PDF) |
| `/kitobnatija_<kod>` | muallif, admin | Kitob testi natijalari |
| `/reklama` | admin | Reklama yaratish (tasdiqlangach navbatga qo'yiladi) |
