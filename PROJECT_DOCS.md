# Документация проекта Telegram Invite

## Обзор
Проект представляет собой веб-приложение для автоматизации работы с Telegram, включающее функционал:
- Приглашение пользователей в каналы с поддержкой множества аккаунтов
- Анализ книг и генерация постов с использованием различных AI моделей
- Автопостинг в Telegram-каналы по расписанию
- Управление аккаунтами Telegram через QR-авторизацию
- Мониторинг и статистика всех операций

## Основные компоненты

### 1. Система приглашений
- Поддержка множества аккаунтов Telegram с автоматической ротацией
- QR-авторизация новых аккаунтов
- Учет лимитов приглашений для каждого аккаунта
- Логирование результатов приглашений в базу данных
- Поддержка приглашения по номеру телефона и username
- Массовое приглашение из файла с прогресс-баром
- Автоматическая обработка ошибок и повторные попытки
- Защита от блокировок через случайные задержки

### 2. Анализатор книг
- Поддержка форматов: TXT, PDF, EPUB
- Разбиение текста на смысловые блоки с учетом контекста
- Анализ блоков с помощью:
  - OpenAI GPT-4/GPT-3.5
  - Together.ai (DeepSeek V3, Llama 4 Maverick 17B, Llama 3.3 70B)
- Параллельный анализ книги и генерация постов
- Автоматический сброс флагов использованных выжимок
- Генерация постов на основе анализа с форматированием
- Автопостинг по расписанию с поддержкой московского времени
- Возможность остановки и возобновления автопостинга

### 3. API интеграции
- OpenAI GPT API (GPT-4, GPT-3.5-turbo)
- Together.ai API (DeepSeek, Llama)
- Telegram Bot API (python-telegram-bot 22.x+)
- Telegram Client API (Telethon)

## Технический стек
- Backend: Python (Quart + Hypercorn)
- Frontend: HTML, JavaScript, Bootstrap 5
- База данных: MySQL 8.0+
- Очереди задач: Celery + Redis
- ORM: SQLAlchemy 2.0+
- Сессии: Redis (quart-session)
- Асинхронные операции: asyncio
- Логирование: logging + Redis

## Конфигурация

### Основные настройки (config.json)
```json
{
    "channel_username": "channel_name",
    "pause_min_seconds": 1,
    "pause_max_seconds": 3,
    "queue_threshold": 50,
    "only_message_bot": false,
    "invite_and_message": false,
    "redis_url": "redis://localhost:6379/0",
    "mysql_host": "localhost",
    "mysql_user": "user",
    "mysql_password": "password",
    "mysql_database": "telegram_invite",
    "session_secret": "your-secret-key",
    "admin_username": "admin",
    "admin_password": "hashed-password"
}
```

### Настройки анализатора книг (book_analyzer_config.json)
```json
{
    "gpt_api_key": "your_openai_key",
    "together_api_key": "your_together_key",
    "gpt_model": "gpt-4",
    "together_model": "deepseek-ai/DeepSeek-V3",
    "telegram_bot_token": "your_bot_token",
    "chat_id": "target_chat_id",
    "analysis_prompt": "Analyze the following text block and provide a detailed summary...",
    "post_prompt": "Generate an engaging post based on the following summary...",
    "chunk_size": 32000,
    "max_retries": 3,
    "retry_delay": 5,
    "timezone": "Europe/Moscow"
}
```

## Модели данных

### Account
```python
class Account(Base):
    __tablename__ = 'accounts'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    api_id = Column(String(255), nullable=False)
    api_hash = Column(String(255), nullable=False)
    session_string = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    last_used = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    comment = Column(Text)
    invite_limit = Column(Integer, default=200)
    invite_count = Column(Integer, default=0)
    reset_date = Column(DateTime)
```

### InviteLog
```python
class InviteLog(Base):
    __tablename__ = 'invite_logs'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(String(255), nullable=False)
    account_id = Column(Integer, ForeignKey('accounts.id'))
    channel_username = Column(String(255), nullable=False)
    phone = Column(String(255))
    username = Column(String(255))
    status = Column(String(50), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    retry_count = Column(Integer, default=0)
    last_retry = Column(DateTime)
```

### GeneratedPost
```python
class GeneratedPost(Base):
    __tablename__ = 'generated_posts'
    
    id = Column(Integer, primary_key=True)
    book_filename = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    published = Column(Boolean, default=False)
    published_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    model_used = Column(String(255))
    block_index = Column(Integer)
    used = Column(Boolean, default=False)
    error = Column(Text)
```

## API Endpoints

### Приглашения
- POST /api/invite
  - Параметры: phone/username, channel_username
  - Возвращает: task_id, status
- POST /api/bulk_invite
  - Параметры: file (CSV), channel_username
  - Возвращает: task_id, total_count
- GET /api/invite_log
  - Параметры: task_id, status, date_from, date_to
  - Возвращает: список логов с пагинацией

### Анализатор книг
- POST /api/book_analyzer/upload_book
  - Параметры: file (PDF/EPUB/TXT)
  - Возвращает: filename, status
- POST /api/book_analyzer/analyze_book
  - Параметры: filename, model, prompt
  - Возвращает: task_id, status
- POST /api/book_analyzer/generate_post
  - Параметры: filename, model, prompt
  - Возвращает: post_id, content
- POST /api/book_analyzer/start_autopost
  - Параметры: filename, schedule, model
  - Возвращает: task_id, status
- GET /api/book_analyzer/summaries
  - Параметры: filename, used
  - Возвращает: список выжимок
- GET /api/book_analyzer/posts_log
  - Параметры: date_from, date_to
  - Возвращает: список постов

### Управление аккаунтами
- POST /api/accounts/add
  - Параметры: name, api_id, api_hash
  - Возвращает: account_id, qr_code
- GET /api/accounts
  - Возвращает: список аккаунтов
- POST /api/accounts/update
  - Параметры: account_id, name, is_active
  - Возвращает: status

## Безопасность
- Аутентификация через сессии в Redis
- Защита API ключей в конфигурационных файлах
- Логирование всех действий в базу данных
- Ограничение доступа к админ-панели
- Защита от CSRF атак
- Валидация всех входных данных
- Безопасное хранение сессий Telegram
- Ротация аккаунтов для избежания блокировок

## Мониторинг
- Логирование в файл и Redis
- Отслеживание статуса задач через Redis
- Уведомления о проблемах через Telegram
- Статистика использования в реальном времени
- Мониторинг лимитов API
- Отслеживание ошибок и повторных попыток
- Графики и отчеты по активности
- Алерты при превышении лимитов

## Развертывание
1. Установка зависимостей:
   ```bash
   python -m venv venv
   source venv/bin/activate  # или venv\Scripts\activate на Windows
   pip install -r requirements.txt
   ```

2. Настройка конфигурации:
   - Создать config.json
   - Создать book_analyzer_config.json
   - Настроить переменные окружения

3. Инициализация базы данных:
   ```bash
   alembic upgrade head
   ```

4. Запуск Redis:
   ```bash
   redis-server
   ```

5. Запуск Celery worker:
   ```bash
   celery -A tasks worker --loglevel=info
   ```

6. Запуск веб-сервера:
   ```bash
   hypercorn app:app --bind 0.0.0.0:8000
   ```

7. Настройка systemd сервисов:
   - telegram_inviter_hypercorn.service
   - telegram_inviter_celery.service

## Ограничения и рекомендации
- Соблюдение лимитов API Telegram (200 приглашений в день на аккаунт)
- Мониторинг использования API ключей (OpenAI, Together.ai)
- Регулярное обновление сессий аккаунтов
- Резервное копирование данных (база данных, сессии)
- Использование разных моделей для анализа и генерации
- Настройка задержек между операциями
- Мониторинг ошибок и автоматические повторные попытки
- Регулярное обновление зависимостей
- Проверка логов на наличие проблем
- Настройка алертов при критических ошибках 