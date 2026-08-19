# MAVIS Registry — серверное приложение для Bitrix24

## Назначение
Серверный MVP для Bitrix24. Backend работает на Render и читает опубликованный индекс реестров из GitHub Pages.

## Render
- Runtime: Python 3
- Root Directory: `registry-server-app`
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --workers 2 --threads 4 --timeout 120`
- Health Check Path: `/health`
- ENV `REGISTRY_BASE_URL=https://mavisgroupiishki-alt.github.io/mavis-kp-generator/registry-mvp`

## Bitrix24
Создать локальное **серверное приложение с интерфейсом**.
- Путь обработчика: `https://ВАШ-СЕРВИС.onrender.com/`
- Путь первоначальной установки: на первом MVP можно не указывать.
- Права REST: для текущего поиска не требуются. Если следующим шагом добавляется автоподстановка УНП из CRM — дать право CRM.

## Важно
`/install` присутствует как заготовка для следующего этапа OAuth/событий, но текущий MVP не хранит OAuth-токены и не вызывает REST Bitrix24.
