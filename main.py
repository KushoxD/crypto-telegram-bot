import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Simple storage
subscribers = set()
previous_tokens = set()

# GMT+8 timezone
GMT8 = timezone(timedelta(hours=8))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_trending_tokens():
    """Get trending crypto tokens from CoinGecko"""
    try:
        async with aiohttp.ClientSession() as session:
            # Get trending tokens
            url = "https://api.coingecko.com/api/v3/search/trending"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    tokens = []
                    
                    for item in data.get('coins', []):
                        coin = item.get('item', {})
                        price_data = coin.get('data', {})
                        price_change = price_data.get('price_change_percentage_24h', {}).get('usd', 0) if price_data else 0
                        
                        tokens.append({
                            'id': coin.get('id', ''),
                            'name': coin.get('name', ''),
                            'symbol': coin.get('symbol', '').upper(),
                            'rank': coin.get('market_cap_rank', 0),
                            'price_change': price_change
                        })
                    
                    # Try to get more tokens from top gainers
                    try:
                        url2 = "https://api.coingecko.com/api/v3/coins/top_gainers_losers"
                        async with session.get(url2, params={'vs_currency': 'usd', 'duration': '24h'}) as response2:
                            if response2.status == 200:
                                gainers_data = await response2.json()
                                existing_ids = {token['id'] for token in tokens}
                                
                                for gainer in gainers_data.get('top_gainers', [])[:10]:
                                    if len(tokens) >= 25:
                                        break
                                    if gainer.get('id') not in existing_ids:
                                        tokens.append({
                                            'id': gainer.get('id', ''),
                                            'name': gainer.get('name', ''),
                                            'symbol': gainer.get('symbol', '').upper(),
                                            'rank': gainer.get('market_cap_rank', 0),
                                            'price_change': gainer.get('usd_24h_change', 0),
                                            'price': gainer.get('usd', 0)
                                        })
                    except Exception as e:
                        logger.warning(f"Could not get gainers: {e}")
                    
                    logger.info(f"Found {len(tokens)} trending tokens")
                    return tokens[:25]  # Top 25
                else:
                    logger.error(f"Trending API error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error getting trending tokens: {e}")
        return []

def create_message(tokens, is_instant=False):
    """Create notification message"""
    if not tokens:
        return ""
    
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    if is_instant:
        message = f"📊 **INSTANT TRENDING REPORT** 📊\n"
        message += f"📅 {gmt8_time} GMT+8\n"
        message += f"🔥 Current top {len(tokens)} trending tokens:\n\n"
    else:
        message = f"🚀 **NEW TRENDING TOKENS** 🚀\n"
        message += f"📅 {gmt8_time} GMT+8\n"
        message += f"🔥 {len(tokens)} new token(s) entered trending!\n\n"
    
    for i, token in enumerate(tokens, 1):
        change_emoji = "🟢" if token.get('price_change', 0) > 0 else "🔴" if token.get('price_change', 0) < 0 else "⚪"
        price = token.get('price', 0)
        
        message += f"**{i}. {token['name']}** ({token['symbol']})\n"
        
        if price > 0:
            if price < 0.01:
                price_str = f"${price:.6f}"
            else:
                price_str = f"${price:.2f}"
            message += f"💰 Price: {price_str}\n"
        
        if token.get('price_change', 0) != 0:
            message += f"{change_emoji} 24h Change: {token.get('price_change', 0):.2f}%\n"
        
        if token.get('rank', 0) > 0:
            message += f"🏆 Rank: #{token.get('rank')}\n"
        
        message += "\n"
    
    if not is_instant:
        message += f"📊 Sent to {len(subscribers)} subscribers\n"
    message += f"⏰ Next check: Top of next hour (GMT+8)"
    
    return message

async def send_notifications(bot, message):
    """Send to all subscribers"""
    if not message or not subscribers:
        return
    
    sent = 0
    failed = 0
    
    for chat_id in list(subscribers):
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            sent += 1
            await asyncio.sleep(0.1)  # Rate limiting
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                subscribers.discard(chat_id)
    
    logger.info(f"Sent to {sent} subscribers, {failed} failed")

async def send_instant_report(bot, chat_id):
    """Send instant trending report when user sends /start"""
    try:
        tokens = await get_trending_tokens()
        if tokens:
            message = create_message(tokens, is_instant=True)
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            logger.info(f"Sent instant report to {chat_id}")
        else:
            await bot.send_message(
                chat_id=chat_id, 
                text="⚠️ Could not fetch trending data right now. Try again in a few minutes."
            )
    except Exception as e:
        logger.error(f"Error sending instant report: {e}")

async def check_new_tokens(bot):
    """Check for new trending tokens (hourly check)"""
    global previous_tokens
    
    try:
        current_tokens = await get_trending_tokens()
        current_ids = {token['id'] for token in current_tokens if token['id']}
        
        # Find new tokens
        new_ids = current_ids - previous_tokens
        
        if new_ids and subscribers:
            new_tokens = [token for token in current_tokens if token['id'] in new_ids]
            message = create_message(new_tokens, is_instant=False)
            
            if message:
                await send_notifications(bot, message)
                logger.info(f"✅ Notified about {len(new_tokens)} new tokens")
        else:
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            logger.info(f"ℹ️ No new tokens found at {gmt8_time} GMT+8. Monitoring {len(subscribers)} subscribers.")
        
        # Update previous tokens
        previous_tokens = current_ids
        
    except Exception as e:
        logger.error(f"Error in hourly check: {e}")

def get_seconds_until_next_hour():
    """Calculate seconds until next GMT+8 hour (XX:00:00)"""
    now = datetime.now(GMT8)
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return (next_hour - now).total_seconds()

async def handle_message(bot, update_data):
    """Handle incoming messages"""
    try:
        if 'message' not in update_data:
            return
        
        message = update_data['message']
        chat_id = str(message['chat']['id'])
        text = message.get('text', '').strip()
        user_name = message.get('from', {}).get('first_name', 'User')
        
        if text == '/start':
            subscribers.add(chat_id)
            
            # Send welcome message
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            welcome = f"""🚀 **Welcome {user_name}!** 🚀

✅ You're now subscribed to crypto alerts!

**What I do:**
📊 Send instant trending report (right now!)
🔥 Notify you when NEW tokens enter trending
⏰ Check every hour at XX:00 GMT+8
🌏 Current time: {gmt8_time} GMT+8

**Commands:**
/start - Subscribe + get instant report
/stop - Unsubscribe
/status - Check subscription

Getting your trending report now..."""
            
            await bot.send_message(chat_id=chat_id, text=welcome, parse_mode='Markdown')
            
            # Send instant trending report
            await asyncio.sleep(1)  # Small delay
            await send_instant_report(bot, chat_id)
            
            logger.info(f"New subscriber: {chat_id} ({user_name})")
            
        elif text == '/stop':
            subscribers.discard(chat_id)
            await bot.send_message(
                chat_id=chat_id, 
                text=f"👋 Goodbye {user_name}!\n\nYou're unsubscribed from crypto alerts.\nUse /start anytime to re-subscribe."
            )
            logger.info(f"Unsubscribed: {chat_id}")
            
        elif text == '/status':
            gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
            status = "✅ SUBSCRIBED" if chat_id in subscribers else "❌ NOT SUBSCRIBED"
            
            status_msg = f"""📊 **Bot Status**

**Your Status:** {status}
**Total Subscribers:** {len(subscribers)}
**Current Time:** {gmt8_time} GMT+8
**Next Check:** Top of next hour
**Monitoring:** Top 25 trending tokens

Use /start to subscribe and get instant report!"""
            
            await bot.send_message(chat_id=chat_id, text=status_msg, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Error handling message: {e}")

async def get_updates(bot, offset=0):
    """Get updates from Telegram"""
    try:
        url = f"https://api.telegram.org/bot{bot.token}/getUpdates"
        params = {'offset': offset, 'timeout': 10}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('result', [])
                else:
                    logger.error(f"getUpdates error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return []

async def main():
    """Main function optimized for Railway"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    bot = Bot(token=BOT_TOKEN)
    
    # Log startup
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"🚀 Railway Crypto Bot started at {gmt8_time} GMT+8")
    
    # Initial token fetch
    await check_new_tokens(bot)
    
    # Calculate when to do first hourly check (at next XX:00:00)
    seconds_to_next_hour = get_seconds_until_next_hour()
    logger.info(f"⏰ Next hourly check in {seconds_to_next_hour/60:.1f} minutes")
    
    offset = 0
    last_hourly_check = 0
    
    while True:
        try:
            # Handle Telegram messages
            updates = await get_updates(bot, offset)
            for update in updates:
                await handle_message(bot, update)
                offset = update['update_id'] + 1
            
            # Check if it's time for hourly check (at XX:00:00 GMT+8)
            now_gmt8 = datetime.now(GMT8)
            current_time = asyncio.get_event_loop().time()
            
            # Check if we're at the top of the hour and haven't checked in this hour
            if (now_gmt8.minute == 0 and now_gmt8.second < 30 and 
                current_time - last_hourly_check > 3500):  # At least 58+ minutes since last check
                
                logger.info(f"🕐 Hourly check at {now_gmt8.strftime('%H:%M')} GMT+8")
                await check_new_tokens(bot)
                last_hourly_check = current_time
            
            await asyncio.sleep(10)  # Check every 10 seconds for hourly timing
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            await asyncio.sleep(30)  # Wait before retry

if __name__ == "__main__":
    asyncio.run(main())
