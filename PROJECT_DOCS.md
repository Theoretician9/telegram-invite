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