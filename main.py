import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Enhanced storage for ATH tokens with cooldown tracking
subscribers = set()
previous_ath_tokens = set()
ath_cooldowns = {}  # Format: {token_id: last_alert_timestamp}

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
            
            # Get top 3000 coins (30 pages of 100 each)
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
    """Get detailed coin data including ATH information for 3000 coins - Returns ALL ATH tokens"""
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
    
    # Sort by market cap rank for display purposes, but return ALL ATH tokens
    ath_tokens.sort(key=lambda x: x.get('rank', 999))
    
    logger.info(f"🏆 Found {len(ath_tokens)} total ATH tokens from top 3000 coins")
    return ath_tokens

def clean_old_cooldowns():
    """Remove cooldown entries older than 24 hours"""
    global ath_cooldowns
    now = datetime.now(timezone.utc)
    expired_tokens = []
    
    for token_id, last_alert_time in ath_cooldowns.items():
        if (now - last_alert_time).total_seconds() > 86400:  # 24 hours in seconds
            expired_tokens.append(token_id)
    
    for token_id in expired_tokens:
        del ath_cooldowns[token_id]
    
    if expired_tokens:
        logger.info(f"🧹 Cleaned {len(expired_tokens)} expired cooldowns")

def filter_new_ath_tokens(all_ath_tokens):
    """Filter tokens that are not in cooldown period"""
    now = datetime.now(timezone.utc)
    new_tokens = []
    cooldown_tokens = []
    
    for token in all_ath_tokens:
        token_id = token['id']
        last_alert_time = ath_cooldowns.get(token_id)
        
        if last_alert_time:
            # Check if 24 hours have passed since last alert
            time_since_alert = (now - last_alert_time).total_seconds()
            if time_since_alert >= 86400:  # 24 hours
                # Cooldown expired, can alert again
                new_tokens.append(token)
            else:
                # Still in cooldown
                cooldown_tokens.append(token)
        else:
            # Never alerted for this token before
            new_tokens.append(token)
    
    logger.info(f"📊 ATH Analysis: {len(all_ath_tokens)} total ATH tokens, {len(new_tokens)} new/eligible, {len(cooldown_tokens)} in cooldown")
    return new_tokens

def create_ath_message(new_tokens, total_ath_count):
    """Create message for new ATH tokens"""
    if not new_tokens:
        return ""
    
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    # Sort by market cap rank for better display
    new_tokens.sort(key=lambda x: x.get('rank', 999))
    
    message = f"🔥 **NEW ATH ACHIEVERS DETECTED** 🔥\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"🆕 **{len(new_tokens)}** NEW tokens hit ATH (not alerted in last 24h)\n"
    message += f"📊 Total ATH tokens found: **{total_ath_count}** from 3000 coins\n"
    message += f"🌐 Monitored from top 3000 market cap coins\n\n"
    
    # Show all new tokens (no limit to 30 since we want all changes)
    for i, token in enumerate(new_tokens, 1):
        hours_ago = token.get('hours_since_ath', 0)
        ath_percentage = token.get('ath_percentage', 0)
        current_price = token.get('current_price', 0)
        ath_price = token.get('ath_price', 0)
        price_change_24h = token.get('price_change_24h', 0)
        
        change_emoji = "🟢" if price_change_24h > 0 else "🔴" if price_change_24h < 0 else "⚪"
        
        message += f"**{i}. #{token['rank']} {token['name']}** ({token['symbol']})\n"
        
        # Current price
        if current_price > 0:
            if current_price < 0.01:
                price_str = f"${current_price:.6f}"
            else:
                price_str = f"${current_price:.2f}"
            message += f"💰 Current: {price_str}"
        
        # ATH price
        if ath_price > 0:
            if ath_price < 0.01:
                ath_price_str = f"${ath_price:.6f}"
            else:
                ath_price_str = f"${ath_price:.2f}"
            message += f" | 🏆 ATH: {ath_price_str}"
        
        # Time since ATH
        if hours_ago < 1:
            time_str = f"{int(hours_ago * 60)}m ago"
        else:
            time_str = f"{hours_ago:.1f}h ago"
        message += f" | ⏰ {time_str}\n"
        
        # Current vs ATH percentage and 24h change
        message += f"📊 vs ATH: {ath_percentage:.1f}%"
        if price_change_24h != 0:
            message += f" | {change_emoji} 24h: {price_change_24h:+.2f}%"
        
        # Market cap
        if token.get('market_cap', 0) > 0:
            market_cap_str = format_market_cap(token['market_cap'])
            message += f" | 💎 {market_cap_str}"
        
        message += "\n\n"
        
        # Add a break every 10 tokens to prevent overly long messages
        if i % 10 == 0 and i < len(new_tokens):
            message += f"--- Showing {i}/{len(new_tokens)} tokens ---\n\n"
    
    message += f"🔕 These tokens won't be alerted again for 24 hours\n"
    message += f"📊 Alert sent to {len(subscribers)} subscribers\n"
    message += f"⏰ Next check: Top of next hour (GMT+8)"
    
    return message

def create_no_changes_message(total_ath_count):
    """Create message when no new ATH tokens found"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    if total_ath_count == 0:
        message = f"😴 **NO ATH TOKENS FOUND** 😴\n"
        message += f"📅 {gmt8_time} GMT+8\n"
        message += f"🔍 No tokens among top 3000 coins hit ATH in last 24h\n"
        message += f"💤 Market is consolidating - no new ATH achievers\n"
        message += f"⏰ Will check again next hour"
    else:
        message = f"🔄 **NO NEW ATH CHANGES** 🔄\n"
        message += f"📅 {gmt8_time} GMT+8\n"
        message += f"📊 Found {total_ath_count} ATH tokens, but all were already alerted\n"
        message += f"🔕 All ATH tokens are in 24h cooldown period\n"
        message += f"⏰ Will check again next hour for new ATH achievers"
    
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

🔧 **Enhanced Configuration:**
🌐 Monitoring: TOP 3000 market cap coins
🏆 Tracking: ALL tokens that hit ATH in last 24h
🆕 Alerts: ONLY new/changed ATH tokens (no spam)
🔕 Cooldown: 24h per token (avoid repeated alerts)
⏰ Schedule: Hourly checks at XX:00 GMT+8

🎯 **Smart Alert System:**
✅ Alert when token hits ATH (first time)
🔕 Skip alerts if same token hits ATH again within 24h
✅ Alert again after 24h cooldown expires
📊 Always show total ATH count vs new changes

⚡ **This test confirms:**
✅ Bot token is working
✅ Telegram API connection successful
✅ Message delivery functional
✅ Ready to start monitoring

**Next update:** Startup report with current ATH baseline

🚀 **Bot ready to track ALL ATH changes intelligently!**"""

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
    """Create startup report showing current ATH tokens baseline"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🚀 **ATH MONITORING BOT STARTUP COMPLETE** 🚀\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"✅ Bot deployed and monitoring successfully!\n"
    message += f"🌐 **ENHANCED MONITORING**: Tracking ALL ATH changes from 3000 coins!\n\n"
    
    if ath_tokens:
        message += f"🏆 **BASELINE ESTABLISHED**\n"
        message += f"📊 Found **{len(ath_tokens)}** tokens that hit ATH in last 24h\n"
        message += f"🔍 Scanned top 3000 market cap coins\n"
        message += f"🔕 All current ATH tokens added to cooldown list\n\n"
        
        # Show top 15 as sample
        message += f"**📈 Sample ATH Tokens (Top 15 by Rank):**\n"
        for i, token in enumerate(ath_tokens[:15], 1):
            hours_ago = token.get('hours_since_ath', 0)
            current_price = token.get('current_price', 0)
            
            if current_price > 0:
                if current_price < 0.01:
                    price_str = f"${current_price:.6f}"
                else:
                    price_str = f"${current_price:.2f}"
            else:
                price_str = "N/A"
            
            if hours_ago < 1:
                time_str = f"{int(hours_ago * 60)}m ago"
            else:
                time_str = f"{hours_ago:.1f}h ago"
            
            message += f"{i}. #{token['rank']} {token['symbol']} - {price_str} ({time_str})\n"
        
        if len(ath_tokens) > 15:
            message += f"... and {len(ath_tokens) - 15} more ATH tokens\n\n"
    else:
        message += f"ℹ️ **NO ATH TOKENS FOUND**\n"
        message += f"🔍 No tokens in top 3000 coins hit ATH in last 24h\n"
        message += f"💤 Market is consolidating - ready to catch next ATH wave\n\n"
    
    next_check_minutes = get_seconds_until_next_hour() / 60
    message += f"⏰ Next check: {next_check_minutes:.0f} minutes\n"
    message += f"🎯 Will alert ONLY on NEW ATH tokens (24h cooldown)\n"
    message += f"📊 Ready to serve {len(subscribers)} subscribers\n"
    message += f"🌐 **SMART ATH CHANGE TRACKING ACTIVE!**"
    
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
        
        # Initialize cooldowns for all current ATH tokens
        now = datetime.now(timezone.utc)
        for token in ath_tokens:
            ath_cooldowns[token['id']] = now
        
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
            logger.info(f"Baseline: {len(ath_tokens)} ATH tokens from 3000 coins")
        
    except Exception as e:
        logger.error(f"Error sending startup report: {e}")

async def check_ath_tokens(bot):
    """Check for NEW ATH tokens with 24h cooldown system"""
    try:
        # Clean old cooldowns first
        clean_old_cooldowns()
        
        # Get all current ATH tokens from 3000 coins
        coin_ids = await get_top_marketcap_coins()
        all_current_ath_tokens = await get_coin_ath_data(coin_ids)
        
        # Filter out tokens that are in cooldown period
        new_ath_tokens = filter_new_ath_tokens(all_current_ath_tokens)
        
        # Always send a message - either new tokens or no changes
        if new_ath_tokens:
            # Update cooldowns for new tokens
            now = datetime.now(timezone.utc)
            for token in new_ath_tokens:
                ath_cooldowns[token['id']] = now
            
            # Send alert for new ATH tokens
            message = create_ath_message(new_ath_tokens, len(all_current_ath_tokens))
            if message and subscribers:
                await send_notifications(bot, message)
                logger.info(f"🚨 ALERT: {len(new_ath_tokens)} new ATH tokens detected from 3000 coin scan!")
                
                # Log details for debugging
                for token in new_ath_tokens[:5]:  # Show first 5 in logs
                    hours_ago = token.get('hours_since_ath', 0)
                    logger.info(f"  NEW ATH: #{token['rank']} {token['name']} ({token['symbol']}) - ATH {hours_ago:.1f}h ago")
                
                if len(new_ath_tokens) > 5:
                    logger.info(f"  ... and {len(new_ath_tokens) - 5} more new ATH tokens")
        else:
            # Send no changes message
            message = create_no_changes_message(len(all_current_ath_tokens))
            if message and subscribers:
                await send_notifications(bot, message)
                gmt8_time = datetime.now(GMT8).strftime('%H:%M')
                logger.info(f"📊 No changes at {gmt8_time} GMT+8. Found {len(all_current_ath_tokens)} ATH tokens, all in cooldown.")
        
        # Log cooldown status
        active_cooldowns = len([cd for cd in ath_cooldowns.values() 
                               if (datetime.now(timezone.utc) - cd).total_seconds() < 86400])
        logger.info(f"🔕 Cooldown status: {active_cooldowns} tokens in 24h cooldown")
        
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

✅ **You're now subscribed to SMART ATH crypto alerts!**

**🧠 INTELLIGENT MONITORING:**
🌐 **TOP 3000** market cap tokens (maximum coverage!)
🆕 Alert on **ALL NEW** ATH tokens (no top 30 limit)
🔕 **24-hour cooldown** per token (no spam)
📊 Always show total ATH count vs new changes
⚡ Alert ONLY on changes, not repeats

**How the smart system works:**
🔍 Check top **3000 coins** every hour at XX:00 GMT+8
📈 Find ALL tokens that hit ATH within last 24 hours
🆕 Alert you ONLY on tokens not alerted in last 24h
🔕 Skip tokens already alerted (24h cooldown)
✅ Alert again after cooldown expires
📊 Show "No changes" when no new ATH tokens

**Current Status:**
🌏 Time now: {gmt8_time} GMT+8
⏰ Next check: {next_check_minutes:.0f} minutes
👥 Subscribers: {len(subscribers)}
🔕 Cooldowns: {len(ath_cooldowns)} tokens
🌐 **Monitoring: 3000 coins intelligently!**

**Commands:**
/start - Subscribe to smart ATH alerts
/stop - Unsubscribe  
/status - Check subscription & cooldown status

**Track ALL ATH changes smartly - no spam! 🔥📈**"""
            
            await bot.send_message(chat_id=chat_id, text=welcome, parse_mode='Markdown')
            logger.info(f"New subscriber: {chat_id} ({user_name}) - Total: {len(subscribers)}")
            
        elif text == '/stop':
            subscribers.discard(chat_id)
            await bot.send_message(
                chat_id=chat_id, 
                text=f"👋 **Goodbye {user_name}!**\n\nYou're unsubscribed from smart ATH crypto alerts.\nUse /start anytime to re-subscribe.\n\nThanks for using the bot! 🏆"
            )
            logger.info(f"Unsubscribed: {chat_id} - Remaining: {len(subscribers)}")
            
        elif text == '/status':
            gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
            next_check_minutes = get_seconds_until_next_hour() / 60
            status = "✅ SUBSCRIBED" if chat_id in subscribers else "❌ NOT SUBSCRIBED"
            
            # Count active cooldowns
            now = datetime.now(timezone.utc)
            active_cooldowns = len([cd for cd in ath_cooldowns.values() 
                                  if (now - cd).total_seconds() < 86400])
            
            status_msg = f"""🏆 **Smart ATH Bot Status Report**

**Your Status:** {status}
**Total Subscribers:** {len(subscribers)}
**Current Time:** {gmt8_time} GMT+8
**Next Check:** {next_check_minutes:.0f} minutes

**🧠 SMART MONITORING STATUS:**
🌐 **TOP 3000** coins by market cap
🔕 **{active_cooldowns}** tokens in 24h cooldown
🆕 Tracking: ALL new ATH tokens (no limit)
⚡ Alert: ONLY on changes (no spam)
⏰ Hourly checks at XX:00 GMT+8

**📊 How it works:**
✅ Alert when token hits ATH (first time)
🔕 Skip if same token hits ATH again < 24h
✅ Alert again after 24h cooldown expires
📊 Always show total vs new changes

**Track ALL ATH changes intelligently! 🔥📈**"""
            
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
    """Main function - Smart ATH Change Monitoring for 3000 Coins"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    bot = Bot(token=BOT_TOKEN)
    
    # Log startup
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"🏆 SMART ATH MONITORING Bot started at {gmt8_time} GMT+8")
    logger.info(f"🧠 INTELLIGENT SYSTEM: Track ALL ATH changes from 3000 coins with 24h cooldown!")
    logger.info(f"🎯 Focus: NEW ATH tokens only, no spam, smart alerts!")
    
    # IMMEDIATE TEST POST - Send right away to confirm bot is working
    logger.info("📤 Sending immediate test post...")
    await send_immediate_test_post(bot)
    
    # Initial fetch to establish baseline (this will take much longer now)
    logger.info("🔍 Establishing ATH baseline from 3000 coins...")
    logger.info("⏳ This initial scan will take approximately 2.5-3 hours due to rate limits...")
    await send_startup_report_to_admin(bot)
    
    # Calculate when to do first hourly check
    seconds_to_next_hour = get_seconds_until_next_hour()
    logger.info(f"⏰ Next ATH change check in {seconds_to_next_hour/60:.1f} minutes")
    
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
                
                logger.info(f"🕐 Smart ATH change check starting at {now_gmt8.strftime('%H:%M')} GMT+8")
                logger.info("⏳ Scanning 3000 coins for ATH changes (2.5-3 hours)...")
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
