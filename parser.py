import os
import json
import logging
import asyncio
from typing import Set, List, Optional
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import User, Channel, Chat, Message
import redis

# Настройка логгера
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REDIS_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
redis_client = redis.Redis.from_url(REDIS_URL)

class GroupParser:
    def __init__(self, client: TelegramClient, task_id: str = 'default'):
        self.client = client
        self.unique_ids: Set[str] = set()
        self.bot_ids: Set[str] = set()
        self.task_id = task_id
        
    async def is_bot(self, user: User) -> bool:
        """Проверяет, является ли пользователь ботом"""
        return user.bot if hasattr(user, 'bot') else False

    async def get_username(self, user: User) -> Optional[str]:
        """Получает username пользователя, если он есть"""
        if hasattr(user, 'username') and user.username:
            return user.username
        return None

    async def parse_messages(self, entity: Channel | Chat, limit: int = 100) -> List[str]:
        """Парсит сообщения из группы и собирает уникальные username'ы"""
        offset_id = 0
        total_messages = 0
        total_usernames = 0
        print('=== ПАРСЕР ЗАПУЩЕН ===')
        redis_client.hset(f'parse_status:{self.task_id}', mapping={
            'status': 'in_progress',
            'progress': 0,
            'total': 0
        })
        while True:
            try:
                history = await self.client(GetHistoryRequest(
                    peer=entity,
                    offset_id=offset_id,
                    offset_date=None,
                    add_offset=0,
                    limit=limit,
                    max_id=0,
                    min_id=0,
                    hash=0
                ))

                if not history.messages:
                    break

                messages = history.messages
                offset_id = messages[-1].id

                for message in messages:
                    if message.from_id:
                        user = await self.client.get_entity(message.from_id)
                        if not await self.is_bot(user):
                            username = await self.get_username(user)
                            if username and username not in self.unique_ids:
                                self.unique_ids.add(username)
                                total_usernames += 1
                                logger.info(f"Найден новый username: {username}")
                    # Обновляем прогресс после каждой итерации
                    progress = int(100 * min(total_usernames, limit) / limit)
                    redis_client.hset(f'parse_status:{self.task_id}', mapping={
                        'progress': progress,
                        'total': total_usernames
                    })

                total_messages += len(messages)
                logger.info(f"Обработано сообщений: {total_messages}, найдено username'ов: {total_usernames}")

                if total_usernames >= limit:
                    break

            except Exception as e:
                logger.error(f"Ошибка при парсинге сообщений: {str(e)}")
                break
        # Завершаем статус
        redis_client.hset(f'parse_status:{self.task_id}', mapping={
            'status': 'completed',
            'progress': 100,
            'total': total_usernames
        })
        return list(self.unique_ids)

    def normalize_group_link(self, group_link: str) -> str:
        """Преобразует любой ввод в корректный username/ссылку для Telethon"""
        group_link = group_link.strip()
        if group_link.startswith('https://t.me/'):
            group_link = group_link[len('https://t.me/'):]
        if group_link.startswith('@'):
            group_link = group_link[1:]
        return group_link

    async def parse_group(self, group_link: str, limit: int = 100) -> List[str]:
        """Основной метод для парсинга группы"""
        try:
            # Нормализуем ссылку/username
            group_link_norm = self.normalize_group_link(group_link)
            # Получаем информацию о группе
            entity = await self.client.get_entity(group_link_norm)
            if not isinstance(entity, (Channel, Chat)):
                raise ValueError("Указанная ссылка не является группой или каналом")
            # Парсим сообщения и собираем username'ы
            usernames = await self.parse_messages(entity, limit)
            # Сохраняем результаты в файл
            output_file = f"chat-logs/{self.task_id}.csv"
            os.makedirs('chat-logs', exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                for username in usernames:
                    f.write(f"{username}\n")
            logger.info(f"Парсинг завершен. Найдено {len(usernames)} уникальных username'ов")
            return usernames
        except Exception as e:
            logger.error(f"Ошибка при парсинге группы: {str(e)}")
            raise

async def parse_group_with_account(group_link: str, limit: int, account_config: dict, task_id: str = 'default') -> List[str]:
    """Функция для парсинга группы с использованием указанного аккаунта"""
    try:
        client = TelegramClient(
            account_config['session_file'],
            account_config['api_id'],
            account_config['api_hash']
        )
        await client.start()
        parser = GroupParser(client, task_id)
        # Нормализуем ссылку/username
        group_link_norm = parser.normalize_group_link(group_link)
        usernames = await parser.parse_group(group_link_norm, limit)
        await client.disconnect()
        return usernames
    except Exception as e:
        logger.error(f"Ошибка при работе с аккаунтом: {str(e)}")
        # В случае ошибки обновляем статус
        redis_client.hset(f'parse_status:{task_id}', mapping={
            'status': 'error',
            'progress': 0,
            'total': 0,
            'error': str(e)
        })
        raise 