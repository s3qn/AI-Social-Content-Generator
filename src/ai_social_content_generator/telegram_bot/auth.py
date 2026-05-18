from functools import wraps

"""Authorization for the Telegram bot. Whitelisted to selected few"""

# USER WHITELIST
USER_WHITELIST = [6552355280, 399244724]

def require_auth(func):
    @wraps(func)
    async def wrapped(update, context):
        if update.effective_user.id not in USER_WHITELIST:
            return
        return await func(update, context)
    return wrapped

