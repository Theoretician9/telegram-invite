# Документация проекта Telegram Invite

## Обзор
Проект представляет собой веб-приложение для автоматизации работы с Telegram, включающее функционал:
- Приглашение пользователей в каналы
- Анализ книг и генерация постов
- Автопостинг в Telegram-каналы

## Основные компоненты

### 1. Система приглашений
- Поддержка множества аккаунтов Telegram
- Ротация аккаунтов для избежания ограничений
- Логирование результатов приглашений
- Поддержка приглашения по номеру телефона и username
- Массовое приглашение из файла

### 2. Анализатор книг
- Поддержка форматов: TXT, PDF, EPUB
- Разбиение текста на смысловые блоки
- Анализ блоков с помощью GPT/Together.ai
- Генерация постов на основе анализа
- Автопостинг по расписанию

### 3. API интеграции
- OpenAI GPT API
- Together.ai API
- Telegram Bot API

## Технический стек
- Backend: Python (Quart)
- Frontend: HTML, JavaScript, Bootstrap
- База данных: MySQL
- Очереди задач: Celery + Redis
- ORM: SQLAlchemy

## Конфигурация

### Основные настройки (config.json)
```json
{
    "channel_username": "channel_name",
    "pause_min_seconds": 1,
    "pause_max_seconds": 3,
    "queue_threshold": 50,
    "only_message_bot": false,
    "invite_and_message": false
}
```

### Настройки анализатора книг (book_analyzer_config.json)
```json
{
    "gpt_api_key": "your_openai_key",
    "together_api_key": "your_together_key",
    "gpt_model": "model_name",
    "telegram_bot_token": "your_bot_token",
    "chat_id": "target_chat_id",
    "analysis_prompt": "prompt for analysis",
    "post_prompt": "prompt for post generation"
}
```

## Модели данных

### Account
- id: int
- name: str
- api_id: str
- api_hash: str
- session_string: str
- is_active: bool
- last_used: datetime
- created_at: datetime
- comment: str

### InviteLog
- id: int
- task_id: str
- account_id: int
- channel_username: str
- phone: str
- status: str
- reason: str
- created_at: datetime

### GeneratedPost
- id: int
- book_filename: str
- prompt: str
- content: str
- published: bool
- published_at: datetime
- created_at: datetime

## API Endpoints

### Приглашения
- POST /api/invite - Пригласить пользователя
- POST /api/bulk_invite - Массовое приглашение
- GET /api/invite_log - Лог приглашений

### Анализатор книг
- POST /api/book_analyzer/upload_book - Загрузка книги
- POST /api/book_analyzer/analyze_book - Анализ книги
- POST /api/book_analyzer/generate_post - Генерация поста
- POST /api/book_analyzer/start_autopost - Запуск автопостинга
- GET /api/book_analyzer/summaries - Получение выжимок
- GET /api/book_analyzer/posts_log - Лог постов

## Безопасность
- Аутентификация через сессии
- Защита API ключей
- Логирование действий
- Ограничение доступа к админ-панели

## Мониторинг
- Логирование в файл
- Отслеживание статуса задач
- Уведомления о проблемах
- Статистика использования

## Развертывание
1. Установка зависимостей: `pip install -r requirements.txt`
2. Настройка конфигурации
3. Инициализация базы данных
4. Запуск Celery worker
5. Запуск веб-сервера

## Ограничения и рекомендации
- Соблюдение лимитов API Telegram
- Мониторинг использования API ключей
- Регулярное обновление сессий аккаунтов
- Резервное копирование данных 