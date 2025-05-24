# Telegram Invite

Автоматизированная система для массового приглашения пользователей в Telegram-каналы и управления контентом.

## Основные возможности

### Приглашение пользователей
- Массовое приглашение по номерам телефонов и username'ам
- Поддержка мультиаккаунтности с QR-авторизацией
- Учёт лимитов приглашений по каждому паблику
- Подробный лог приглашений с причинами ошибок
- Автоматическое распределение нагрузки между аккаунтами

### Анализ книг и автопостинг
- Разбиение книги на главы и создание выжимок
- Генерация постов по выжимкам через AI (OpenAI, Together.ai)
- Ежедневный автопостинг по расписанию (МСК)
- Поддержка остановки/перезапуска автопостинга
- Сохранение статуса и расписания между перезагрузками

### Парсинг подписчиков
- Сбор подписчиков из групп и каналов
- Фильтрация ботов и дубликатов
- Экспорт результатов в текстовый файл
- Отслеживание прогресса в реальном времени

## Технический стек

### Бэкенд
- **Фреймворк**: Quart + Hypercorn (асинхронный)
- **Очередь задач**: Celery + Redis
- **База данных**: MariaDB/MySQL
- **Сессии**: quart-session + redis.asyncio
- **Telegram API**: Telethon, python-telegram-bot 22.x+

### Фронтенд
- **Фреймворк**: Vite + React (SPA)
- **Стили**: Tailwind CSS
- **Конфигурация**: Внешний JS-конфиг

### AI/ML
- **OpenAI**: GPT-4, GPT-3.5 Turbo
- **Together.ai**: 
  - DeepSeek V3
  - Llama 4 Maverick 17B
  - Llama 3.3 70B Instruct

## Установка и настройка

### Требования
- Python 3.10+
- Node.js 18+
- MariaDB/MySQL
- Redis

### Установка зависимостей
```bash
# Python
pip install -r requirements.txt

# Frontend
cd frontend
npm ci
npm run build
```

### Конфигурация
1. Создайте `.env` файл с необходимыми переменными окружения:
```env
DB_HOST=localhost
DB_USER=telegraminvi
DB_PASSWORD=your_password
DB_NAME=telegraminvi
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=your_key
TOGETHER_API_KEY=your_key
```

2. Настройте конфигурацию фронтенда в `/frontend/public/config/config.js`

### Миграции базы данных
```bash
alembic upgrade head
```

## Запуск

### Systemd сервисы
```bash
# Quart + Hypercorn
sudo systemctl start telegram_inviter_hypercorn.service

# Celery
sudo systemctl start telegram_inviter_celery.service
```

### Nginx
```bash
sudo ln -s /etc/nginx/sites-available/telegram_invite.conf /etc/nginx/sites-enabled/
sudo systemctl reload nginx
```

## Использование

### Авторизация
1. Откройте главную страницу
2. Войдите через форму авторизации
3. Для добавления Telegram-аккаунта используйте QR-код

### Массовое приглашение
1. Загрузите файл с номерами телефонов или username'ами
2. Выберите целевой канал
3. Настройте параметры приглашения
4. Запустите процесс

### Анализ книги и автопостинг
1. Загрузите книгу в формате TXT
2. Выберите модель AI для анализа
3. Дождитесь создания выжимок
4. Настройте расписание автопостинга
5. Запустите автопостинг

## Мониторинг и логи

### Логи приложения
- Логи Quart: `app.log`
- Логи Celery: `celery.log`
- Логи Nginx: `/var/log/nginx/error.log`

### Мониторинг
- Статус автопостинга: `/admin/autopost`
- Статистика приглашений: `/stats`
- Логи приглашений: `/admin/logs`

## Безопасность
- Все чувствительные данные хранятся в переменных окружения
- Сессии хранятся в Redis
- Поддержка 2FA для Telegram-аккаунтов
- Защита от дублирования приглашений

## Разработка
- Все изменения через GitHub
- Автоматический деплой через GitHub Actions
- Тестирование перед деплоем
- Документация в PROJECT_DOCS.md

## Лицензия
MIT