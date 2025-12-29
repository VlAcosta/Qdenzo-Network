# Qdenzo Network — Telegram Bot (prod-ready)

Полностью переписанный бот под продашен‑запуск и первичный тест.

## Что реализовано

- aiogram 3, HTML parse mode, безопасное экранирование текстов (без `can't parse entities`)
- Postgres + Redis в `docker-compose`
- Идемпотентные миграции (чинят типовую проблему `column ... does not exist` при обновлении схемы)
- Подписки:
  - Trial: 48 часов, 1 устройство
  - Start: 1/3/6/12 мес (3 устройства) — 249/499/999/1999 ₽
  - Pro: 1/3/6/12 мес (5 устройств) — 399/899/1399/2499 ₽
  - Family: 3/6/12 мес (10 устройств) — 1099/1599/2999 ₽
- Устройства: 1 устройство = 1 пользователь Marzban, выдача ссылки (link/subscription)
- Профили (режимы): Smart / Streaming / Gaming / Work / Low Internet / Kids
- Трафик: показывает суммарный used_traffic по устройствам (через Marzban API) + лимит из `.env`
- Рефералка: начисления по таблице из ТЗ, кап 15 дней на 30 дней, поддержан откат (refund)
- Админ‑панель в боте: список pending‑заказов, approve/cancel

## Быстрый запуск (Docker)

1) Скопируйте проект на сервер, например в `/opt/qdenzo-bot`:

```bash
mkdir -p /opt/qdenzo-bot
cd /opt/qdenzo-bot
# распакуйте архив сюда
```

2) Создайте `.env`:

```bash
cp .env.example .env
nano .env
```

Минимально обязательно заполнить:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL`
- `MARZBAN_BASE_URL`, `MARZBAN_USERNAME`, `MARZBAN_PASSWORD`

3) Запустите:

```bash
docker compose up -d --build
```

4) Посмотрите логи:

```bash
docker compose logs -f bot
```

## Как зайти в Postgres

```bash
docker compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB
\dt
```

## Полная очистка старых версий (если надо)

⚠️ ВНИМАНИЕ: команды ниже удаляют volume Postgres и тестовые данные.

### Вариант 1 (самый простой)

В каталоге текущего бота:

```bash
docker compose down -v --remove-orphans
```

### Вариант 2 (если на сервере остались старые проекты/контейнеры)

```bash
bash scripts/cleanup_old_bot.sh
```

## Оплаты

Сейчас прод‑тест рассчитан на ручное подтверждение оплаты админом.

Если хотите уже сейчас принимать оплату «ссылкой», заполните:
- `YOOKASSA_PAY_URL` — ссылка на оплату картой/СБП (любая ваша страница/инвойс)
- `CRYPTO_PAY_URL` — ссылка на оплату криптой

Дальше можно добавить вебхуки YooKassa / Stars (Telegram) отдельным сервисом.
