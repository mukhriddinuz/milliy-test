# Telegram Bot API Documentation

Bu loyihada TelegramUser, Subject va Test modellari uchun to'liq CRUD API yaratilgan va Swagger dokumentatsiyasi qo'shilgan.

## Server manzili
```
http://127.0.0.1:8000/
```

## Swagger dokumentatsiya
- **Swagger UI**: http://127.0.0.1:8000/swagger/
- **ReDoc**: http://127.0.0.1:8000/redoc/
- **JSON Schema**: http://127.0.0.1:8000/swagger.json

## API Base URL
```
http://127.0.0.1:8000/api/
```

## Authentication
Hozirda authentication talab qilinmaydi, lekin keyinchalik qo'shish mumkin.

---

## 1. TelegramUser API

**Base URL: `/api/users/`**

### CRUD operatsiyalar:
- `GET /api/users/` - Barcha foydalanuvchilar ro'yxati (filtrlash va qidiruv bilan)
- `POST /api/users/` - Yangi foydalanuvchi yaratish
- `GET /api/users/{id}/` - Bitta foydalanuvchi ma'lumotlari
- `PUT /api/users/{id}/` - Foydalanuvchi ma'lumotlarini to'liq yangilash
- `PATCH /api/users/{id}/` - Foydalanuvchi ma'lumotlarini qisman yangilash
- `DELETE /api/users/{id}/` - Foydalanuvchini o'chirish

### Qo'shimcha operatsiyalar:
- `POST /api/users/{id}/ban_user/` - Foydalanuvchini bloklash
- `POST /api/users/{id}/unban_user/` - Foydalanuvchi blokini bekor qilish
- `POST /api/users/{id}/update_balance/` - Balansni yangilash

### Filtrlash parametrlari:
- `is_active` - Faol foydalanuvchilar (true/false)
- `is_banned` - Bloklangan foydalanuvchilar (true/false)
- `region` - Viloyat bo'yicha filtrlash

### Qidiruv parametrlari:
- `search` - Ism, familiya, username, telefon bo'yicha qidiruv

### Tartiblash parametrlari:
- `ordering` - created_at, balance, name bo'yicha tartiblash

---

## 2. Subject API

**Base URL: `/api/subjects/`**

### CRUD operatsiyalar:
- `GET /api/subjects/` - Barcha fanlar ro'yxati
- `POST /api/subjects/` - Yangi fan yaratish
- `GET /api/subjects/{id}/` - Bitta fan ma'lumotlari
- `PUT /api/subjects/{id}/` - Fan ma'lumotlarini to'liq yangilash
- `PATCH /api/subjects/{id}/` - Fan ma'lumotlarini qisman yangilash
- `DELETE /api/subjects/{id}/` - Fanni o'chirish

### Qo'shimcha operatsiyalar:
- `GET /api/subjects/{id}/tests/` - Fanga tegishli barcha testlar
- `POST /api/subjects/{id}/toggle_active/` - Fan holatini o'zgartirish

### Filtrlash parametrlari:
- `is_active` - Faol fanlar (true/false)

### Qidiruv parametrlari:
- `search` - Fan nomi va tavsifi bo'yicha qidiruv

---

## 3. Test API

**Base URL: `/api/tests/`**

### CRUD operatsiyalar:
- `GET /api/tests/` - Barcha testlar ro'yxati
- `POST /api/tests/` - Yangi test yaratish
- `GET /api/tests/{id}/` - Bitta test ma'lumotlari
- `PUT /api/tests/{id}/` - Test ma'lumotlarini to'liq yangilash
- `PATCH /api/tests/{id}/` - Test ma'lumotlarini qisman yangilash
- `DELETE /api/tests/{id}/` - Testni o'chirish

### Qo'shimcha operatsiyalar:
- `POST /api/tests/{id}/toggle_active/` - Test holatini o'zgartirish
- `POST /api/tests/{id}/toggle_public/` - Test ommaviyligini o'zgartirish
- `POST /api/tests/{id}/set_answers/` - Test javoblarini o'rnatish
- `GET /api/tests/public_tests/` - Barcha ommaviy testlar
- `GET /api/tests/by_subject/` - Fan bo'yicha guruhlangan testlar

### Filtrlash parametrlari:
- `subject` - Fan ID bo'yicha filtrlash
- `creator` - Yaratuvchi ID bo'yicha filtrlash
- `is_active` - Faol testlar (true/false)
- `is_public` - Ommaviy testlar (true/false)

### Qo'shimcha URL parametrlari:
- `subject_id` - Biror fan testlarini olish
- `creator_id` - Biror foydalanuvchi testlarini olish
- `public_only=true` - Faqat ommaviy testlar

---

## Ma'lumot strukturalari

### TelegramUser Model
```json
{
  "id": 1,
  "telegram_id": 123456789,
  "username": "test_user",
  "surname": "Aliyev",
  "name": "Ahmad",
  "father_name": "Karim o'g'li",
  "phone": "+998901234567",
  "region": "Toshkent",
  "district": "Chilonzor",
  "balance": "1000.00",
  "balans_formatted": "1,000.00 so'm",
  "full_name": "Aliyev Ahmad Karim o'g'li",
  "is_active": true,
  "is_banned": false,
  "created_at": "2025-09-22T18:30:00Z",
  "updated_at": "2025-09-22T18:30:00Z"
}
```

### Subject Model
```json
{
  "id": 1,
  "name": "Matematika",
  "description": "Umumiy matematika fanidan testlar",
  "is_active": true,
  "tests_count": 5,
  "created_at": "2025-09-22T18:30:00Z",
  "updated_at": "2025-09-22T18:30:00Z"
}
```

### Test Model
```json
{
  "id": 1,
  "subject": 1,
  "subject_name": "Matematika",
  "creator": 1,
  "creator_name": "Aliyev Ahmad Karim o'g'li",
  "title": "Algebra asoslari",
  "questions_count": 20,
  "is_active": true,
  "is_public": false,
  "channel_username": "@test_channel",
  "answers": {
    "1": "A",
    "2": "B",
    "3": "C"
  },
  "created_at": "2025-09-22T18:30:00Z",
  "updated_at": "2025-09-22T18:30:00Z"
}
```

---

## Misollar

### 1. Yangi foydalanuvchi yaratish
```bash
curl -X POST http://127.0.0.1:8000/api/users/ \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_id": 123456789,
    "username": "test_user",
    "surname": "Aliyev",
    "name": "Ahmad",
    "phone": "+998901234567",
    "region": "Toshkent",
    "district": "Chilonzor"
  }'
```

### 2. Balansni yangilash
```bash
curl -X POST http://127.0.0.1:8000/api/users/1/update_balance/ \
  -H "Content-Type: application/json" \
  -d '{"amount": 50000}'
```

### 3. Yangi fan yaratish
```bash
curl -X POST http://127.0.0.1:8000/api/subjects/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Matematika",
    "description": "Umumiy matematika fanidan testlar"
  }'
```

### 4. Yangi test yaratish
```bash
curl -X POST http://127.0.0.1:8000/api/tests/ \
  -H "Content-Type: application/json" \
  -d '{
    "subject": 1,
    "creator": 1,
    "title": "Algebra asoslari",
    "questions_count": 20,
    "is_public": true
  }'
```

### 5. Test javoblarini o'rnatish
```bash
curl -X POST http://127.0.0.1:8000/api/tests/1/set_answers/ \
  -H "Content-Type: application/json" \
  -d '{
    "answers": {
      "1": "A",
      "2": "B", 
      "3": "C",
      "4": "D"
    }
  }'
```

---

## Xatoliklar

API xatoliklari HTTP status kodlari bilan qaytariladi:

- `200` - Muvaffaqiyatli
- `201` - Yaratildi
- `400` - Noto'g'ri so'rov
- `404` - Topilmadi
- `500` - Server xatosi

Xatolik misolii:
```json
{
  "error": "Telefon raqami +998XXXXXXXXX formatida bo'lishi kerak"
}
```

---

## Pagination

Ro'yxat API'lari pagination bilan ishlaydi:

```json
{
  "count": 100,
  "next": "http://127.0.0.1:8000/api/users/?page=3",
  "previous": "http://127.0.0.1:8000/api/users/?page=1",
  "results": [...]
}
```

Har bir sahifada 20 ta element ko'rsatiladi.

---

## Qo'shimcha ma'lumotlar

- Swagger UI orqali API'larni to'g'ridan-to'g'ri sinab ko'rish mumkin
- Barcha API'lar JSON formatida ma'lumot qaytaradi
- DateTime maydonlari ISO 8601 formatida
- Decimal maydonlar string formatida qaytariladi