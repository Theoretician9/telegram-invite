from worker import worker
from telethon import TelegramClient
from telethon.errors import FloodWaitError, UserDeactivatedError
import asyncio
import os
from datetime import datetime
from models.invite import InviteLog

# Get Telegram API credentials from environment
api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")

@worker.task(name="tasks.invite.start_invite")
def start_invite(task_id: str, target: str, message: str):
    """
    Start inviting users to a target chat
    """
    try:
        # Create event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run invite process
        result = loop.run_until_complete(invite_process(task_id, target, message))
        
        return result
    except Exception as e:
        # Update task status
        loop.run_until_complete(update_task_status(task_id, "failed", error=str(e)))
        raise
    finally:
        loop.close()

async def invite_process(task_id: str, target: str, message: str):
    """
    Process of inviting users
    """
    # Get invite log
    invite_log = await InviteLog.get_by_task_id(task_id)
    if not invite_log:
        raise Exception("Task not found")

    try:
        # Update status
        invite_log.status = "running"
        await invite_log.save()

        # Create Telegram client
        client = TelegramClient("invite_session", api_id, api_hash)
        await client.start()

        # Get target chat
        target_entity = await client.get_entity(target)
        
        # Get users to invite
        users = await get_users_to_invite(client)
        
        # Update total
        invite_log.total = len(users)
        await invite_log.save()

        # Invite users
        success = 0
        failed = 0
        
        for user in users:
            try:
                # Add user to chat
                await client(InviteToChannelRequest(
                    target_entity,
                    [user]
                ))
                
                # Send message
                await client.send_message(user, message)
                
                success += 1
            except (FloodWaitError, UserDeactivatedError) as e:
                failed += 1
            except Exception as e:
                failed += 1
            
            # Update progress
            invite_log.progress += 1
            invite_log.success = success
            invite_log.failed = failed
            await invite_log.save()
            
            # Add delay
            await asyncio.sleep(1)

        # Update final status
        invite_log.status = "completed"
        await invite_log.save()

        return {
            "task_id": task_id,
            "status": "completed",
            "success": success,
            "failed": failed
        }

    except Exception as e:
        # Update error status
        invite_log.status = "failed"
        invite_log.error = str(e)
        await invite_log.save()
        raise

async def get_users_to_invite(client):
    """
    Get list of users to invite
    This is a placeholder - implement your user selection logic
    """
    # TODO: Implement user selection logic
    return []

async def update_task_status(task_id: str, status: str, error: str = None):
    """
    Update task status
    """
    invite_log = await InviteLog.get_by_task_id(task_id)
    if invite_log:
        invite_log.status = status
        if error:
            invite_log.error = error
        await invite_log.save() 