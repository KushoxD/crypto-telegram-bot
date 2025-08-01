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
    """Get top 3000 coins by market cap to check for ATH"""
    try:
        async with aiohttp.ClientSession() as session:
            all_coin_ids = []
            
            # Get top 3000 coins (30 pages of 100 each, then remaining coins)
            total_pages = 30  # 3000 coins / 100 per page
            
            for page in range(1, total_pages + 1):
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
                        coin_ids = [coin['id'] for coin in data if coin.get('market_cap_rank')]
                        all_coin_ids.extend(coin_ids)
                        logger.info(f"Retrieved page {page}/{total_pages}: {len(coin_ids)} coins (Total: {len(all_coin_ids)})")
                        
                        # Progressive delay - longer delays for later pages to avoid rate limits
                        if page < total_pages:
                            if page <= 10:
                                await asyncio.sleep(1)  # 1 second for first 10 pages
                            elif page <= 20:
                                await asyncio.sleep(2)  # 2 seconds for pages 11-20
                            else:
                                await asyncio.sleep(3)  # 3 seconds for pages 21-30
                    else:
                        logger.error(f"Market data API error on page {page}: {response.status}")
                        if response.status == 429:
                            logger.warning("Rate limit hit, waiting 2 minutes...")
                            await asyncio.sleep(120)
                            continue
                        break
            
            logger.info(f"✅ Retrieved total {len(all_coin_ids)} top market cap coins for ATH monitoring")
            return all_coin_ids
    except Exception as e:
        logger.error(f"Error getting top market cap coins: {e}")
        return []

async def get_coin_ath_data(coin_ids):
    """Get detailed coin data including ATH information for 3000 coins"""
    ath_tokens = []
    
    try:
        async with aiohttp.ClientSession() as session:
            # Process coins in smaller batches with better rate limiting for 3000 coins
            batch_size = 3  # Reduced to 3 for better reliability with larger dataset
            total_batches = len(coin_ids) // batch_size + (1 if len(coin_ids) % batch_size else 0)
            
            logger.info(f"🔍 Processing {len(coin_ids)} coins in {total_batches} batches of {batch_size}")
            logger.info(f"⏱️ Estimated time: {(total_batches * batch_size * 3) / 60:.1f} minutes")
            
            processed = 0
            
            for batch_num, i in enumerate(range(0, len(coin_ids), batch_size), 1):
                batch = coin_ids[i:i + batch_size]
                
                # Progress logging every 100 coins
                if processed % 100 == 0:
                    logger.info(f"📊 Progress: {processed}/{len(coin_ids)} coins processed ({processed/len(coin_ids)*100:.1f}%)")
                
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
                                logger.warning("⚠️ Rate limit hit, waiting 3 minutes...")
                                await asyncio.sleep(180)  # Wait 3 minutes on rate limit
                            else:
                                logger.warning(f"API error for {coin_id}: {response.status}")
                        
                        processed += 1
                        
                        # Dynamic delay based on progress to maintain rate limits
                        if processed <= 1000:
                            await asyncio.sleep(2.5)  # 2.5s for first 1000
                        elif processed <= 2000:
                            await asyncio.sleep(3)    # 3s for coins 1001-2000
                        else:
                            await asyncio.sleep(3.5)  # 3.5s for coins 2001-3000
                        
                    except Exception as e:
                        logger.warning(f"Error processing {coin_id}: {e}")
                        processed += 1
                        continue
                
                # Longer delay between batches with progress-based scaling
                if batch_num < total_batches:
                    batch_delay = 15 if processed <= 1500 else 20
                    if batch_num % 50 == 0:  # Every 50 batches, log progress
                        logger.info(f"🔄 Batch {batch_num}/{total_batches} complete. Found {len(ath_tokens)} ATH tokens so far...")
                    await asyncio.sleep(batch_delay)
    
    except Exception as e:
        logger.error(f"Error getting coin ATH data: {e}")
    
    # Sort by market cap rank and take top 30
    ath_tokens.sort(key=lambda x: x.get('rank', 999))
    top_30_ath = ath_tokens[:30]
    
    logger.info(f"🏆 Found {len(ath_tokens)} total ATH tokens from top 3000, showing top 30 by market cap")
    return top_30_ath

def create_ath_message(new_tokens, all_tokens):
    """Create message for ATH tokens"""
    if not new_tokens:
        return ""
    
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🔥 **NEW ATH ACHIEVERS** 🔥\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"🏆 {len(new_tokens)} NEW token(s) entered Top 30 ATH list!\n"
    message += f"🌐 Monitored from top 3000 market cap coins\n\n"
    
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

async def send_immediate_test_post(bot):
    """Send immediate test post to verify bot is working"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    test_message = f"""🤖 **BOT TEST POST** 🤖
📅 {gmt8_time} GMT+8
✅ **ATH Monitoring Bot is LIVE!**

🔧 **Configuration:**
🌐 Monitoring: TOP 3000 market cap coins
🏆 Tracking: 24-hour ATH achievers
📊 Reporting: Top 30 by market cap rank
⏰ Schedule: Hourly checks at XX:00 GMT+8

🎯 **What happens next:**
1️⃣ Now fetching initial data from 3000 coins
2️⃣ Establishing baseline ATH list
3️⃣ Will alert on NEW entries to top 30 ATH list
4️⃣ Silent monitoring until changes detected

⚡ **This test confirms:**
✅ Bot token is working
✅ Telegram API connection successful
✅ Message delivery functional
✅ Ready to start monitoring

**Next update:** Startup report with current ATH tokens

🚀 **Bot is ready to track the market's biggest winners!**"""

    # Send to admin first, then to any existing subscribers
    ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
    sent_count = 0
    
    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=test_message, parse_mode='Markdown')
            logger.info(f"✅ Test post sent to admin: {ADMIN_CHAT_ID}")
            sent_count += 1
        except Exception as e:
            logger.warning(f"Could not send test post to admin: {e}")
    
    # Also send to any existing subscribers
    for chat_id in list(subscribers):
        try:
            await bot.send_message(chat_id=chat_id, text=test_message, parse_mode='Markdown')
            sent_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Could not send test post to {chat_id}: {e}")
    
    if sent_count == 0:
        logger.info("📝 Test post ready (no recipients configured yet)")
        logger.info("💡 Add ADMIN_CHAT_ID env var or /start the bot to receive test posts")
    else:
        logger.info(f"📤 Test post sent to {sent_count} recipient(s)")

def create_startup_report(ath_tokens):
    """Create startup report showing current ATH tokens"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🚀 **ATH MONITORING BOT STARTUP COMPLETE** 🚀\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"✅ Bot deployed and monitoring successfully!\n"
    message += f"🌐 **EXPANDED MONITORING**: Now tracking TOP 3000 coins!\n\n"
    
    if ath_tokens:
        message += f"🏆 **TOP 30 MARKET CAP TOKENS WITH 24H ATH**\n"
        message += f"🔥 Currently monitoring {len(ath_tokens)} tokens that hit ATH in last 24h\n"
        message += f"📊 Selected from top 3000 market cap coins\n\n"
        
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
        message += f"🔍 Currently no tokens in top 3000 market cap have hit ATH in last 24h\n"
        message += f"⏰ Will check again next hour\n\n"
    
    next_check_minutes = get_seconds_until_next_hour() / 60
    message += f"⏰ Next check: {next_check_minutes:.0f} minutes\n"
    message += f"🎯 Will alert when tokens enter/exit the ATH list!\n"
    message += f"📊 Ready to serve {len(subscribers)} subscribers\n"
    message += f"🌐 **3000 COIN MONITORING ACTIVE!**"
    
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
            logger.info(f"Monitoring: {len(ath_tokens)} ATH tokens from 3000 coins")
        
    except Exception as e:
        logger.error(f"Error sending startup report: {e}")

async def check_ath_tokens(bot):
    """Check for changes in ATH tokens list from 3000 coins"""
    global previous_ath_tokens
    
    try:
        # Get top 3000 market cap coins and their ATH data
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
                logger.info(f"🚨 ALERT: {len(new_ath_tokens)} new ATH tokens detected from 3000 coin scan!")
                
                # Log details for debugging
                for token in new_ath_tokens:
                    hours_ago = token.get('hours_since_ath', 0)
                    logger.info(f"  NEW ATH: #{token['rank']} {token['name']} ({token['symbol']}) - ATH {hours_ago:.1f}h ago")
        else:
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            if subscribers:
                logger.info(f"✅ No changes at {gmt8_time} GMT+8. ATH list unchanged. ({len(subscribers)} subscribers)")
            else:
                logger.info(f"ℹ️ No subscribers yet. Monitoring {len(current_ath_ids)} ATH tokens from 3000 coins.")
        
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

**🌐 EXPANDED MONITORING:**
🔥 **TOP 3000** market cap tokens (upgraded from 300!)
⚡ Top 30 that hit ATH in last 24h
📊 Send alerts ONLY when NEW tokens enter the ATH list
🏆 Track tokens that achieved new All-Time Highs recently
📈 Show current price vs ATH percentage

**How it works:**
🔍 Check top **3000 market cap coins** every hour at XX:00 GMT+8
📈 Find tokens that hit ATH within last 24 hours
🎯 Alert you when NEW tokens enter the top 30 ATH list
🚫 Silent when nothing changes (no spam!)

**Current Status:**
🌏 Time now: {gmt8_time} GMT+8
⏰ Next check: {next_check_minutes:.0f} minutes
👥 Subscribers: {len(subscribers)}
🌐 **Monitoring: 3000 coins!**

**Commands:**
/start - Subscribe to ATH alerts
/stop - Unsubscribe  
/status - Check subscription

**Track the hottest performers from 3000 coins! 🔥📈**"""
            
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

**🌐 EXPANDED MONITORING:**
🔍 **TOP 3000** coins by market cap (upgraded!)
🏆 Tokens that hit ATH in last 24 hours
📊 Top 30 by market cap ranking
⚡ NEW entries in ATH list
⏰ Hourly checks at XX:00 GMT+8

**Track the market's biggest winners from 3000 coins! 🔥📈**"""
            
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
    """Main function - Enhanced ATH Monitoring for 3000 Coins"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    bot = Bot(token=BOT_TOKEN)
    
    # Log startup
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"🏆 ATH MONITORING Bot started at {gmt8_time} GMT+8")
    logger.info(f"🌐 EXPANDED MONITORING: Top 30 market cap tokens with 24h ATH from TOP 3000 COINS!")
    logger.info(f"🎯 Focus: NEW ATH achievers only!")
    
    # IMMEDIATE TEST POST - Send right away to confirm bot is working
    logger.info("📤 Sending immediate test post...")
    await send_immediate_test_post(bot)
    
    # Initial fetch to establish baseline (this will take much longer now)
    logger.info("🔍 Establishing baseline for ATH tokens from 3000 coins...")
    logger.info("⏳ This initial scan will take approximately 2.5-3 hours due to rate limits...")
    await check_ath_tokens(bot)
    
    # Send startup report to verify bot is working with results
    logger.info("📊 Sending startup report with results...")
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
                
                logger.info(f"🕐 3000-coin ATH check starting at {now_gmt8.strftime('%H:%M')} GMT+8")
                logger.info("⏳ This will take 2.5-3 hours to complete...")
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
