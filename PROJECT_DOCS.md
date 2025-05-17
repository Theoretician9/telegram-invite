# Документация системы Telegram Invite

## Обзор проекта
Telegram Invite — это автоматизированная система для массового приглашения пользователей в Telegram-каналы по номерам телефонов. Система включает дашборд, мониторинг очереди, фоновую обработку задач (Celery) и веб-интерфейс управления. Все обновления и деплой осуществляются исключительно через GitHub Actions.

## Архитектура системы

### Фронтенд
- **Технологии**: Vite + React (SPA)
- **Расположение**: `/frontend/`
- **Процесс сборки**: `npm ci && npm run build`
- **Результат сборки**: `/frontend/dist/`
- **Конфигурация**: Внешний JS-конфиг в `/frontend/public/config/config.js`

### Бэкенд
- **Основное приложение**: Flask (`app.py`)
  - REST API эндпоинты
  - Админ-панель
  - Просмотр логов
  - Раздача статики
- **Очередь задач**: Celery (`celery_app.py`, `tasks.py`)
  - Redis как брокер сообщений
  - Фоновая обработка задач
- **База данных**: MariaDB/MySQL
  - Имя базы: `telegraminvi`
  - Пользователь: `telegraminvi`
  - Пароль: `QyA9fWbh56Ln`

### Инфраструктура сервера
- **ОС**: Ubuntu 24.04
- **Расположение проекта**: `/home/admin/telegram_invite`
- **Python окружение**: `/home/admin/telegram_invite/venv`
- **Веб-сервер**: Nginx
  - Конфиг: `/etc/nginx/sites-available/telegram_invite.conf`
  - Симлинк: `/etc/nginx/sites-enabled/telegram_invite.conf`

## API Эндпоинты

### Мониторинг и проверка состояния
- `GET /api/health` - Проверка статуса сервиса Flask
- `GET /api/queue_length` - Получение текущей длины очереди Celery
- `GET /api/stats` - Получение статистики приглашений
- `GET /api/stats/history` - Получение исторической статистики
  - Параметры запроса: `period=day|week`

### Управление
- `GET /admin` - Админ-панель для настройки канала и сообщений
- `GET /logs` - Интерфейс просмотра логов
- `GET /api/logs` - Эндпоинт для получения сырых логов
- `GET /api/logs/csv` - Скачивание логов в формате CSV
- `GET /api/accounts` - Список доступных Telegram-аккаунтов

### Основной функционал
- `POST/GET /webhook` - Точка входа для обработки номеров телефонов
  - Принимает номера через POST JSON или GET параметры
  - Ставит задачу приглашения в очередь Celery

### Парсер подписчиков
- `GET /parser` - Веб-интерфейс парсера
- `POST /api/parse` - Запуск процесса парсинга
  - Параметры: `group_link`, `limit`
  - Возвращает `task_id` для отслеживания
- `GET /api/parse/status` - Проверка статуса парсинга
  - Параметр: `task_id`
  - Возвращает прогресс и количество найденных ID
- `GET /api/parse/download/latest` - Скачивание последнего результата
- `GET /api/parse/download/<filename>` - Скачивание конкретного файла

## Схема базы данных

### invite_logs
- `id` - Первичный ключ
- `task_id` - ID задачи Celery
- `account_name` - Использованный Telegram-аккаунт
- `channel_username` - Целевой канал
- `phone` - Целевой номер телефона
- `status` - Один из: invited, link_sent, failed, skipped
- `reason` - Причина ошибки (если есть)
- `created_at` - Временная метка

### accounts
- `name` - Идентификатор аккаунта
- `last_used` - Время последнего использования
- `invites_left` - Оставшаяся квота приглашений

## Конфигурация

### config.json
```json
{
  "channel_username": "channel_name",
  "failure_message": "Шаблон сообщения с {{channel}}",
  "queue_threshold": 50,
  "pause_min_seconds": 1,
  "pause_max_seconds": 3,
  "only_message_bot": false,
  "invite_and_message": false,
  "accounts": [
    {
      "name": "account1",
      "session_file": "session1",
      "api_id": "your_api_id",
      "api_hash": "your_api_hash",
      "is_active": true
    }
  ]
}
```

## Процесс деплоя

1. Все изменения должны вноситься через репозиторий GitHub
2. GitHub Actions workflow (.github/workflows/deploy.yml) выполняет:
   - SSH подключение к серверу
   - Git pull из ветки main
   - Обновление Python-зависимостей
   - Сборку фронтенда
   - Перезапуск сервисов
   - Обновление конфига Nginx

## Управление сервисами

### Systemd сервисы
- `telegram_inviter_flask.service` - Приложение Flask
- `telegram_inviter_celery.service` - Воркер Celery

### Расположение логов
- Логи приложения: `app.log`
- Логи Nginx: `/var/log/nginx/error.log`
- Логи systemd: `journalctl -u telegram_inviter_*.service`

## Примечания по безопасности
- Все чувствительные данные (API ключи, пароли) хранятся в переменных окружения
- Запрещено прямое редактирование файлов на сервере
- Все изменения должны проходить через репозиторий GitHub
- SSH ключи и учетные данные хранятся в секретах GitHub Actions

## Мониторинг и оповещения
- Мониторинг длины очереди с пороговыми оповещениями
- Отслеживание статуса задач в базе данных
- Агрегация и просмотр логов через веб-интерфейс
- Функционал экспорта логов в CSV

## Рекомендации по разработке
1. Все изменения кода должны вноситься через GitHub
2. Запрещено прямое редактирование файлов на сервере
3. Тестировать изменения локально перед отправкой
4. Отслеживать статус GitHub Actions workflow после отправки
5. Проверять статус сервисов после деплоя
6. Поддерживать документацию в актуальном состоянии

## Устранение неполадок
1. Проверить статус GitHub Actions workflow
2. Просмотреть логи приложения
3. Проверить статус сервисов: `systemctl status telegram_inviter_*.service`
4. Проверить логи Nginx на наличие проблем с прокси
5. Проверить подключение к базе данных
6. Мониторить статус очереди Redis

## Экстренное восстановление
При необходимости ручного вмешательства:
```bash
cd ~/telegram_invite
git fetch --all
git reset --hard origin/main
source venv/bin/activate
pip install -r requirements.txt
cd frontend
npm ci
npm run build
sudo systemctl restart telegram_inviter_flask.service
sudo systemctl restart telegram_inviter_celery.service
sudo systemctl reload nginx
```

## Планируемые улучшения
- [ ] Обновление дашборда в реальном времени
- [ ] Расширенная аналитика и отчетность
- [ ] Улучшенное управление логами
- [ ] Аналитика по аккаунтам
- [ ] Аутентификация админки
- [ ] Интеграция HTTPS
- [ ] Документация API
- [ ] Автоматизированное тестирование

## Модули системы

### Модуль парсинга подписчиков
- **Файлы**: 
  - `parser.py` - основной модуль парсинга
  - `templates/parser.html` - интерфейс парсера
- **Функционал**:
  - Парсинг подписчиков из групп и каналов Telegram
  - Сбор уникальных username'ов
  - Фильтрация ботов
  - Отслеживание прогресса в реальном времени
  - Экспорт результатов в текстовый файл
- **Технические детали**:
  - Асинхронная обработка через Telethon
  - Хранение прогресса в Redis
  - Автоматическое сохранение результатов
  - Возможность скачивания последнего результата
- **Ограничения**:
  - Максимальное количество ID для сбора: 1000
  - Только публичные группы и каналы
  - Требуется активный Telegram-аккаунт
- **Процесс работы**:
  1. Пользователь вводит ссылку на группу и лимит
  2. Система создает задачу парсинга
  3. Парсер собирает username'ы из сообщений
  4. Прогресс отображается в реальном времени
  5. Результаты сохраняются в файл
  6. Пользователь может скачать результаты

### Модуль приглашения
// ... existing code ...

## Процесс работы с парсером
1. Открыть страницу `/parser`
2. Ввести ссылку на группу и желаемое количество ID
3. Нажать "Начать парсинг"
4. Дождаться завершения процесса
5. Скачать результаты
6. Использовать полученный файл для массового приглашения

// ... rest of existing code ... 

# Изменения в проекте (bulk invite, логи, Celery, Nginx)

## 1. Исправления и улучшения Celery-задачи приглашения (`tasks.py`)
- Исправлена ошибка с переменной `account`, чтобы она всегда была определена даже при ошибках.
- Добавлена загрузка конфига внутри задачи, чтобы не было ошибки с неопределённой переменной `config`.
- Исправлен способ работы с PyMySQL: убран несуществующий аргумент `dictionary=True` из `conn.cursor()`, так как `DictCursor` уже задаётся при создании соединения.
- Полностью переписана логика приглашения:
  - Для номера телефона: сначала импорт контакта через `ImportContactsRequest`, затем приглашение через `InviteToChannelRequest`, после чего контакт удаляется через `DeleteContactsRequest`.
  - Для username: получение entity через `get_entity`, затем приглашение через `InviteToChannelRequest`.
- Исправлена обработка дубликатов при логировании: если возникает ошибка MySQL с кодом 1062 (дубликат), она корректно обрабатывается.
- Все ошибки логируются с привязкой к task_id, account_name, идентификатору пользователя и причине.

## 2. Изменения в Nginx-конфиге (`deploy/nginx/telegram_invite.conf`)
- Добавлены отдельные location-блоки для `/bulk_invite` и `/api/bulk_invite`, чтобы корректно проксировать эти запросы на Flask, а не отдавать SPA-роутинг.

## 3. Изменения во Flask-приложении (`app.py`)
- Добавлен API-эндпоинт `/api/invite_log`, который возвращает последние 100 записей из таблицы invite_logs (поля: phone, status, reason, created_at).
- Весь backend работает с MySQL через mysql-connector, все параметры БД берутся из переменных окружения или конфига.
- Вся логика bulk invite (загрузка файла, постановка задач в очередь, возврат статуса) реализована через отдельный endpoint `/api/bulk_invite`.

## 4. Изменения в шаблоне страницы массового приглашения (`templates/bulk_invite.html`)
- Добавлен блок "Подробный лог" под прогресс-баром, который отображает статус по каждому id (добавлен/не добавлен/ошибка).
- Добавлен JS-код, который раз в 3 секунды запрашивает `/api/invite_log` и обновляет содержимое блока лога.
- Лог отображает: id пользователя, статус (invited/failed/skipped и т.д.), причину (если есть).

## 5. Общие рекомендации и отладка
- Для корректной работы задержек между приглашениями рекомендуется реализовать паузы непосредственно в Celery-задаче (например, через `time.sleep` между инвайтами, если это требуется по логике).
- Для отладки использовались команды curl, просмотр логов Flask и Nginx, а также прямой просмотр invite_logs в базе данных.
- Все изменения были протестированы: приглашения работают, логи отображаются на странице, ошибки корректно логируются.

---

## Рекомендации для дальнейшей доработки

- **Задержки между приглашениями:** если требуется пауза между каждым инвайтом, её нужно реализовать в самой Celery-задаче или через отдельный воркер, так как сейчас задачи ставятся в очередь одновременно.
- **Фильтрация логов:** для более удобного отображения логов на странице можно добавить фильтрацию по текущей задаче или по времени.
- **Более подробные статусы:** можно расширить invite_logs, чтобы хранить дополнительные детали (например, тип ошибки, попытки, время выполнения и т.д.).
- **UI/UX:** добавить индикатор загрузки, авто-скролл лога, фильтры по статусу.

---

## Краткое резюме новых и изменённых файлов

- `tasks.py` — исправлена логика инвайта, обработка ошибок, работа с PyMySQL.
- `deploy/nginx/telegram_invite.conf` — добавлены location для bulk_invite.
- `app.py` — добавлен API для invite_log, улучшена обработка bulk invite.
- `templates/bulk_invite.html` — добавлен подробный лог, обновлён JS.
- (Рекомендация) Для задержек между инвайтами требуется дополнительная реализация.

## Миграция на мультиаккаунтность и учёт лимитов (июнь 2024)

### Новые таблицы
- **accounts**: id, name, api_id, api_hash, session_string, is_active, last_used, created_at, comment
- **account_channel_limits**: id, account_id, channel_username, invites_left, last_invited_at
- **invite_logs** (расширено): добавлен account_id, channel_username, reason, status, created_at

### Основные изменения
- Все данные по аккаунтам и лимитам теперь хранятся в БД (MySQL), а не в файлах.
- Поддержка мультиаккаунтности и учёта лимитов по каждому паблику.
- Подготовлен Alembic для миграций, создана первая миграция с новыми таблицами.
- Весь процесс миграции и настройки описан в истории чата (см. chat_history.md).

### Alembic: настройка и миграция
1. Установить alembic и pymysql: `pip install alembic pymysql`
2. Инициализировать Alembic: `alembic init alembic`
3. Настроить строку подключения в alembic.ini:
   ```
   sqlalchemy.url = mysql+pymysql://user:password@host/dbname
   ```
4. В alembic/env.py добавить:
   ```python
   import sys, os
   sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
   from models import Base
   target_metadata = Base.metadata
   ```
5. Сгенерировать миграцию: `alembic revision --autogenerate -m "init accounts and limits"`
6. Применить миграцию: `alembic upgrade head`

## Recent Updates
- Added endpoint `/api/accounts/add` to save account details after QR authorization.
- Updated JS on `/admin/accounts` page to send account data to the backend and display the list of accounts.
- Updated endpoint `/api/accounts` to return the list of accounts from the database.
- Fixed issues with missing Python libraries (Pillow and qrcode) causing 502 Bad Gateway errors.

## Setup Instructions
1. Install the required Python packages:
   ```bash
   pip install pillow qrcode[pil]
   ```
2. Ensure the Flask service is running:
   ```bash
   sudo systemctl restart telegram_inviter_flask.service
   ```

## API Endpoints
- `POST /api/accounts/add`: Save account details after QR authorization.
- `GET /api/accounts`: Retrieve the list of accounts from the database. 