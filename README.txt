MAVIS Registry v30 — проверка реестров во всех воронках Bitrix24

Изменение:
- удалено ограничение "только воронки продаж";
- вкладка "Проверка реестров" работает в любой карточке сделки, независимо от CATEGORY_ID;
- общая база/индекс/еженедельный парсинг не меняются;
- переустанавливать приложение Bitrix24 не нужно.

Установка:
1) cd "$HOME/Downloads/mavis-registry-all-funnels-v30"
2) python3 publish_server_v10.py
3) дождаться Live на Render
4) проверить https://mavis-registry.onrender.com/health -> version 10.0-all-funnels
