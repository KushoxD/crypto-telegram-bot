import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Simple storage for ATH tokens
subscribers = set()
previous_ath_tokens = set()

# GMT+8 timezone
GMT8 = timezone(timedelta(hours=8))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_top_marketcap_coins():
    """Get top 300 coins by market cap to check for ATH"""
    try:
        async with aiohttp.ClientSession() as session:
            all_coin_ids = []
            
            # Get top 300 coins (3 pages of 100 each)
            for page in range(1, 4):
                url = "https://api.coingecko.com/api/v3/coins/markets"
                params = {
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': 100,
                    'page': page,
                    'sparkline': False,
                    'locale': 'en'
                }
                
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        coin_ids = [coin['id'] for coin in data]
                        all_coin_ids.extend(coin_ids)
                        logger.info(f"Retrieved page {page}: {len(coin_ids)} coins")
                        
                        # Small delay between pages
                        if page < 3:
                            await asyncio.sleep(1)
                    else:
                        logger.error(f"Market data API error on page {page}: {response.status}")
                        break
            
            logger.info(f"Retrieved total {len(all_coin_ids)} top market cap coins")
            return all_coin_ids
    except Exception as e:
        logger.error(f"Error getting top market cap coins: {e}")
        return []

async def get_coin_ath_data(coin_ids):
    """Get detailed coin data including ATH information"""
    ath_tokens = []
    
    try:
        async with aiohttp.ClientSession() as session:
            # Process coins in smaller batches to handle larger dataset
            batch_size = 5  # Reduced from 10 to be more conservative with 300 coins
            total_batches = len(coin_ids) // batch_size + (1 if len(coin_ids) % batch_size else 0)
            
            logger.info(f"Processing {len(coin_ids)} coins in {total_batches} batches of {batch_size}")
            
            for batch_num, i in enumerate(range(0, len(coin_ids), batch_size), 1):
                batch = coin_ids[i:i + batch_size]
                logger.info(f"Processing batch {batch_num}/{total_batches}")
                
                for coin_id in batch:
                    try:
                        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}"
                        params = {
                            'localization': False,
                            'tickers': False,
                            'market_data': True,
                            'community_data': False,
                            'developer_data': False,
                            'sparkline': False
                        }
                        
                        async with session.get(url, params=params) as response:
                            if response.status == 200:
                                data = await response.json()
                                market_data = data.get('market_data', {})
                                
                                # Get ATH date and current price info
                                ath_date_str = market_data.get('ath_date', {}).get('usd')
                                current_price = market_data.get('current_price', {}).get('usd', 0)
                                ath_price = market_data.get('ath', {}).get('usd', 0)
                                market_cap_rank = market_data.get('market_cap_rank', 0)
                                market_cap = market_data.get('market_cap', {}).get('usd', 0)
                                price_change_24h = market_data.get('price_change_percentage_24h', 0)
                                
                                if ath_date_str and current_price and ath_price and market_cap_rank:
                                    # Parse ATH date
                                    ath_date = datetime.fromisoformat(ath_date_str.replace('Z', '+00:00'))
                                    now = datetime.now(timezone.utc)
                                    hours_since_ath = (now - ath_date).total_seconds() / 3600
                                    
                                    # Check if ATH was within last 24 hours
                                    if hours_since_ath <= 24:
                                        # Calculate how close current price is to ATH
                                        ath_percentage = (current_price / ath_price) * 100
                                        
                                        token_data = {
                                            'id': coin_id,
                                            'name': data.get('name', ''),
                                            'symbol': data.get('symbol', '').upper(),
                                            'rank': market_cap_rank,
                                            'current_price': current_price,
                                            'ath_price': ath_price,
                                            'ath_date': ath_date,
                                            'hours_since_ath': hours_since_ath,
                                            'ath_percentage': ath_percentage,
                                            'market_cap': market_cap,
                                            'price_change_24h': price_change_24h
                                        }
                                        ath_tokens.append(token_data)
                                        
                            elif response.status == 429:
                                logger.warning("Rate limit hit, waiting longer...")
                                await asyncio.sleep(120)  # Wait 2 minutes on rate limit
                            else:
                                logger.warning(f"API error for {coin_id}: {response.status}")
                        
                        # Longer delay between requests for larger dataset
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        logger.warning(f"Error processing {coin_id}: {e}")
                        continue
                
                # Longer delay between batches for 300 coins
                if batch_num < total_batches:
                    logger.info(f"Completed batch {batch_num}/{total_batches}, waiting before next batch...")
                    await asyncio.sleep(10)
    
    except Exception as e:
        logger.error(f"Error getting coin ATH data: {e}")
    
    # Sort by market cap rank and take top 30
    ath_tokens.sort(key=lambda x: x.get('rank', 999))
    top_30_ath = ath_tokens[:30]
    
    logger.info(f"Found {len(ath_tokens)} total ATH tokens from top 300, showing top 30 by market cap")
    return top_30_ath

def create_ath_message(new_tokens, all_tokens):
    """Create message for ATH tokens"""
    if not new_tokens:
        return ""
    
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🔥 **NEW ATH ACHIEVERS** 🔥\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"🏆 {len(new_tokens)} NEW token(s) entered Top 30 ATH list!\n\n"
    
    # Sort new tokens by market cap rank
    new_tokens.sort(key=lambda x: x.get('rank', 999))
    
    for token in new_tokens:
        hours_ago = token.get('hours_since_ath', 0)
        ath_percentage = token.get('ath_percentage', 0)
        current_price = token.get('current_price', 0)
        ath_price = token.get('ath_price', 0)
        price_change_24h = token.get('price_change_24h', 0)
        
        change_emoji = "🟢" if price_change_24h > 0 else "🔴" if price_change_24h < 0 else "⚪"
        
        message += f"**#{token['rank']} {token['name']}** ({token['symbol']})\n"
        
        # Current price
        if current_price > 0:
            if current_price < 0.01:
                price_str = f"${current_price:.6f}"
            else:
                price_str = f"${current_price:.2f}"
            message += f"💰 Current Price: {price_str}\n"
        
        # ATH price
        if ath_price > 0:
            if ath_price < 0.01:
                ath_price_str = f"${ath_price:.6f}"
            else:
                ath_price_str = f"${ath_price:.2f}"
            message += f"🏆 ATH Price: {ath_price_str}\n"
        
        # Time since ATH
        if hours_ago < 1:
            time_str = f"{int(hours_ago * 60)} minutes ago"
        else:
            time_str = f"{hours_ago:.1f} hours ago"
        message += f"⏰ ATH Achieved: {time_str}\n"
        
        # Current vs ATH percentage
        message += f"📊 Current vs ATH: {ath_percentage:.1f}%\n"
        
        # 24h change
        if price_change_24h != 0:
            message += f"{change_emoji} 24h Change: {price_change_24h:+.2f}%\n"
        
        # Market cap
        if token.get('market_cap', 0) > 0:
            market_cap_str = format_market_cap(token['market_cap'])
            message += f"💎 Market Cap: {market_cap_str}\n"
        
        message += "\n"
    
    message += f"📊 Alert sent to {len(subscribers)} subscribers\n"
    message += f"⏰ Next check: Top of next hour (GMT+8)"
    
    return message

def format_market_cap(market_cap):
    """Format market cap in readable format"""
    if market_cap >= 1e12:
        return f"${market_cap/1e12:.2f}T"
    elif market_cap >= 1e9:
        return f"${market_cap/1e9:.2f}B"
    elif market_cap >= 1e6:
        return f"${market_cap/1e6:.2f}M"
    elif market_cap >= 1e3:
        return f"${market_cap/1e3:.2f}K"
    else:
        return f"${market_cap:.2f}"

def create_startup_report(ath_tokens):
    """Create startup report showing current ATH tokens"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🚀 **ATH MONITORING BOT STARTUP** 🚀\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"✅ Bot deployed and monitoring successfully!\n\n"
    
    if ath_tokens:
        message += f"🏆 **TOP 30 MARKET CAP TOKENS WITH 24H ATH**\n"
        message += f"🔥 Currently monitoring {len(ath_tokens)} tokens that hit ATH in last 24h\n\n"
        
        # Show top 10
        for token in ath_tokens[:10]:
            hours_ago = token.get('hours_since_ath', 0)
            ath_percentage = token.get('ath_percentage', 0)
            current_price = token.get('current_price', 0)
            
            message += f"**#{token['rank']} {token['name']}** ({token['symbol']})\n"
            
            if current_price > 0:
                if current_price < 0.01:
                    price_str = f"${current_price:.6f}"
                else:
                    price_str = f"${current_price:.2f}"
                message += f"💰 Price: {price_str}\n"
            
            if hours_ago < 1:
                time_str = f"{int(hours_ago * 60)}m ago"
            else:
                time_str = f"{hours_ago:.1f}h ago"
            message += f"⏰ ATH: {time_str}\n"
            message += f"📊 vs ATH: {ath_percentage:.1f}%\n"
            message += "\n"
        
        if len(ath_tokens) > 10:
            message += f"... and {len(ath_tokens) - 10} more ATH tokens\n\n"
    else:
        message += f"ℹ️ **NO TOKENS WITH 24H ATH FOUND**\n"
        message += f"🔍 Currently no tokens in top market cap have hit ATH in last 24h\n"
        message += f"⏰ Will check again next hour\n\n"
    
    next_check_minutes = get_seconds_until_next_hour() / 60
    message += f"⏰ Next check: {next_check_minutes:.0f} minutes\n"
    message += f"🎯 Will alert when tokens enter/exit the ATH list!\n"
    message += f"📊 Ready to serve {len(subscribers)} subscribers"
    
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
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                subscribers.discard(chat_id)
    
    logger.info(f"Sent to {sent} subscribers, {failed} failed")

async def send_startup_report_to_admin(bot):
    """Send startup report to admin"""
    try:
        coin_ids = await get_top_marketcap_coins()
        ath_tokens = await get_coin_ath_data(coin_ids)
        
        startup_message = create_startup_report(ath_tokens)
        
        ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
        
        if ADMIN_CHAT_ID:
            try:
                await bot.send_message(chat_id=ADMIN_CHAT_ID, text=startup_message, parse_mode='Markdown')
                logger.info(f"📊 Startup report sent to admin: {ADMIN_CHAT_ID}")
            except Exception as e:
                logger.warning(f"Could not send startup report to admin: {e}")
        elif subscribers:
            first_subscriber = list(subscribers)[0]
            try:
                await bot.send_message(chat_id=first_subscriber, text=startup_message, parse_mode='Markdown')
                logger.info(f"📊 Startup report sent to first subscriber: {first_subscriber}")
            except Exception as e:
                logger.warning(f"Could not send startup report: {e}")
        else:
            logger.info("📊 Startup report ready (no subscribers to send to yet)")
            logger.info(f"Monitoring: {len(ath_tokens)} ATH tokens")
        
    except Exception as e:
        logger.error(f"Error sending startup report: {e}")

async def check_ath_tokens(bot):
    """Check for changes in ATH tokens list"""
    global previous_ath_tokens
    
    try:
        # Get top market cap coins and their ATH data
        coin_ids = await get_top_marketcap_coins()
        current_ath_tokens = await get_coin_ath_data(coin_ids)
        
        current_ath_ids = {token['id'] for token in current_ath_tokens}
        
        # Find new tokens that entered the ATH list
        new_ath_ids = current_ath_ids - previous_ath_tokens
        new_ath_tokens = [token for token in current_ath_tokens if token['id'] in new_ath_ids]
        
        # Send notification if there are new ATH tokens
        if new_ath_tokens and subscribers:
            message = create_ath_message(new_ath_tokens, current_ath_tokens)
            
            if message:
                await send_notifications(bot, message)
                logger.info(f"🚨 ALERT: {len(new_ath_tokens)} new ATH tokens detected!")
                
                # Log details for debugging
                for token in new_ath_tokens:
                    hours_ago = token.get('hours_since_ath', 0)
                    logger.info(f"  NEW ATH: #{token['rank']} {token['name']} ({token['symbol']}) - ATH {hours_ago:.1f}h ago")
        else:
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            if subscribers:
                logger.info(f"✅ No changes at {gmt8_time} GMT+8. ATH list unchanged. ({len(subscribers)} subscribers)")
            else:
                logger.info(f"ℹ️ No subscribers yet. Monitoring {len(current_ath_ids)} ATH tokens.")
        
        # Update previous tokens
        previous_ath_tokens = current_ath_ids
        
    except Exception as e:
        logger.error(f"Error in ATH check: {e}")

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
            
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            next_check_minutes = get_seconds_until_next_hour() / 60
            
            welcome = f"""🏆 **Welcome {user_name}!** 🏆

✅ **You're now subscribed to ATH crypto alerts!**

**What I monitor:**
🔥 Top 30 market cap tokens that hit ATH in last 24h
⚡ Send alerts ONLY when NEW tokens enter the ATH list
🏆 Track tokens that achieved new All-Time Highs recently
📊 Show current price vs ATH percentage

**How it works:**
🔍 Check top 300 market cap coins every hour at XX:00 GMT+8
📈 Find tokens that hit ATH within last 24 hours
🎯 Alert you when NEW tokens enter the top 30 ATH list
🚫 Silent when nothing changes (no spam!)

**Current Status:**
🌏 Time now: {gmt8_time} GMT+8
⏰ Next check: {next_check_minutes:.0f} minutes
👥 Subscribers: {len(subscribers)}

**Commands:**
/start - Subscribe to ATH alerts
/stop - Unsubscribe  
/status - Check subscription

**Track the hottest performers! 🔥📈**"""
            
            await bot.send_message(chat_id=chat_id, text=welcome, parse_mode='Markdown')
            logger.info(f"New subscriber: {chat_id} ({user_name}) - Total: {len(subscribers)}")
            
        elif text == '/stop':
            subscribers.discard(chat_id)
            await bot.send_message(
                chat_id=chat_id, 
                text=f"👋 **Goodbye {user_name}!**\n\nYou're unsubscribed from ATH crypto alerts.\nUse /start anytime to re-subscribe.\n\nThanks for using the bot! 🏆"
            )
            logger.info(f"Unsubscribed: {chat_id} - Remaining: {len(subscribers)}")
            
        elif text == '/status':
            gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
            next_check_minutes = get_seconds_until_next_hour() / 60
            status = "✅ SUBSCRIBED" if chat_id in subscribers else "❌ NOT SUBSCRIBED"
            
            status_msg = f"""🏆 **ATH Bot Status Report**

**Your Status:** {status}
**Total Subscribers:** {len(subscribers)}
**Monitoring:** {len(previous_ath_tokens)} ATH tokens
**Current Time:** {gmt8_time} GMT+8
**Next Check:** {next_check_minutes:.0f} minutes

**What We're Watching:**
🔍 Top 300 coins by market cap
🏆 Tokens that hit ATH in last 24 hours
📊 Top 30 by market cap ranking
⚡ NEW entries in ATH list
⏰ Hourly checks at XX:00 GMT+8

**Track the market's biggest winners! 🔥📈**"""
            
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
    """Main function - ATH Monitoring Focus"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    bot = Bot(token=BOT_TOKEN)
    
    # Log startup
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"🏆 ATH MONITORING Bot started at {gmt8_time} GMT+8")
    logger.info(f"🔥 Monitoring: Top 30 market cap tokens with 24h ATH from top 300 coins")
    logger.info(f"🎯 Focus: NEW ATH achievers only!")
    
    # Initial fetch to establish baseline
    logger.info("🔍 Establishing baseline for ATH tokens...")
    await check_ath_tokens(bot)
    
    # Send startup report to verify bot is working
    logger.info("📊 Sending startup report...")
    await send_startup_report_to_admin(bot)
    
    # Calculate when to do first hourly check
    seconds_to_next_hour = get_seconds_until_next_hour()
    logger.info(f"⏰ Next ATH check in {seconds_to_next_hour/60:.1f} minutes")
    
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
                
                logger.info(f"🕐 ATH check at {now_gmt8.strftime('%H:%M')} GMT+8")
                await check_ath_tokens(bot)
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
