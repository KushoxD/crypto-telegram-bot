import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Simple storage for both lists
subscribers = set()
previous_trending_tokens = set()
previous_gainer_tokens = set()

# GMT+8 timezone
GMT8 = timezone(timedelta(hours=8))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_trending_tokens():
    """Get trending crypto tokens from CoinGecko - POSITIVE RETURNS ONLY, NO SUPPLEMENTS"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/search/trending"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    positive_tokens = []
                    
                    for index, item in enumerate(data.get('coins', []), 1):
                        coin = item.get('item', {})
                        price_data = coin.get('data', {})
                        price_change = price_data.get('price_change_percentage_24h', {}).get('usd', 0) if price_data else 0
                        
                        # Only include tokens with POSITIVE returns
                        if price_change > 0:
                            token_data = {
                                'id': coin.get('id', ''),
                                'name': coin.get('name', ''),
                                'symbol': coin.get('symbol', '').upper(),
                                'rank': coin.get('market_cap_rank', 0),
                                'price_change': price_change,
                                'price': price_data.get('price', 0) if price_data else 0,
                                'trending_position': index  # Original position in trending list
                            }
                            positive_tokens.append(token_data)
                    
                    # Keep original trending order (by trending rank, not by gains)
                    # Already in correct order from API response
                    
                    logger.info(f"Found {len(positive_tokens)} POSITIVE trending tokens (independent, no supplements)")
                    return positive_tokens  # Return all positive trending tokens (may be less than 30)
                else:
                    logger.error(f"Trending API error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error getting positive trending tokens: {e}")
        return []

async def get_top_gainers():
    """Get top 30 gainers from CoinGecko"""
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/coins/top_gainers_losers"
            params = {'vs_currency': 'usd', 'duration': '24h'}
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    gainers = []
                    
                    for index, gainer in enumerate(data.get('top_gainers', []), 1):
                        gainers.append({
                            'id': gainer.get('id', ''),
                            'name': gainer.get('name', ''),
                            'symbol': gainer.get('symbol', '').upper(),
                            'rank': gainer.get('market_cap_rank', 0),
                            'price_change': gainer.get('usd_24h_change', 0),
                            'price': gainer.get('usd', 0),
                            'gainer_position': index  # Actual position in gainers list
                        })
                    
                    logger.info(f"Found {len(gainers)} top gainers")
                    return gainers[:30]  # Top 30
                else:
                    logger.error(f"Gainers API error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error getting top gainers: {e}")
        return []

def create_section_message(section_type, new_tokens, all_tokens):
    """Create message section for either trending or gainers"""
    if not new_tokens:
        return ""
    
    # Section header
    if section_type == "trending":
        section_header = f"📈 **NEW POSITIVE TRENDING TOKENS**\n🔥 {len(new_tokens)} NEW positive token(s) entered Trending!\n\n"
    else:  # gainers
        section_header = f"🚀 **NEW TOP GAINERS**\n💰 {len(new_tokens)} NEW token(s) entered Top 30 Gainers!\n\n"
    
    # Create position mapping based on section type
    if section_type == "trending":
        # For trending: use trending_position (their actual rank in trending list)
        token_positions = {token['id']: token.get('trending_position', idx + 1) for idx, token in enumerate(all_tokens)}
    else:
        # For gainers: use gainer_position (their actual rank in gainers list)
        token_positions = {token['id']: token.get('gainer_position', idx + 1) for idx, token in enumerate(all_tokens)}
    
    # Sort new tokens by their position
    new_tokens_with_position = []
    for token in new_tokens:
        position = token_positions.get(token['id'], 999)
        new_tokens_with_position.append((position, token))
    
    new_tokens_with_position.sort(key=lambda x: x[0])
    
    section_content = ""
    for position, token in new_tokens_with_position:
        # All should be positive now
        change_emoji = "🟢"  
        price = token.get('price', 0)
        
        section_content += f"**#{position} {token['name']}** ({token['symbol']})\n"
        
        if price > 0:
            if price < 0.01:
                price_str = f"${price:.6f}"
            else:
                price_str = f"${price:.2f}"
            section_content += f"💰 Price: {price_str}\n"
        
        # Always show positive change
        section_content += f"{change_emoji} 24h Change: +{token.get('price_change', 0):.2f}%\n"
        
        if token.get('rank', 0) > 0:
            section_content += f"🏆 Market Cap Rank: #{token.get('rank')}\n"
        
        section_content += "\n"
    
    return section_header + section_content

def create_combined_message(new_trending, all_trending, new_gainers, all_gainers):
    """Create combined notification message"""
    if not new_trending and not new_gainers:
        return ""
    
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    total_new = len(new_trending) + len(new_gainers)
    
    message = f"🎯 **CRYPTO MARKET CHANGES** 🎯\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"⚡ {total_new} NEW token(s) detected!\n\n"
    
    # Add trending section if there are new trending tokens
    if new_trending:
        trending_section = create_section_message("trending", new_trending, all_trending)
        message += trending_section
        
        # Add separator if we have both sections
        if new_gainers:
            message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Add gainers section if there are new gainers
    if new_gainers:
        gainers_section = create_section_message("gainers", new_gainers, all_gainers)
        message += gainers_section
    
    message += f"📊 Alert sent to {len(subscribers)} subscribers\n"
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

async def check_both_lists(bot):
    """Check for changes in both trending and gainers lists"""
    global previous_trending_tokens, previous_gainer_tokens
    
    try:
        # Get both lists
        current_trending = await get_trending_tokens()
        current_gainers = await get_top_gainers()
        
        current_trending_ids = {token['id'] for token in current_trending if token['id']}
        current_gainer_ids = {token['id'] for token in current_gainers if token['id']}
        
        # Find new tokens in each list
        new_trending_ids = current_trending_ids - previous_trending_tokens
        new_gainer_ids = current_gainer_ids - previous_gainer_tokens
        
        new_trending = [token for token in current_trending if token['id'] in new_trending_ids]
        new_gainers = [token for token in current_gainers if token['id'] in new_gainer_ids]
        
        # Send notification if there are any changes
        if (new_trending or new_gainers) and subscribers:
            message = create_combined_message(new_trending, current_trending, new_gainers, current_gainers)
            
            if message:
                await send_notifications(bot, message)
                logger.info(f"🚨 ALERT: {len(new_trending)} new trending + {len(new_gainers)} new gainers!")
                
                # Log details for debugging
                if new_trending:
                    for token in new_trending:
                        position = token.get('trending_position', '?')
                        logger.info(f"  NEW TRENDING #{position}: {token['name']} ({token['symbol']}) - +{token.get('price_change', 0):.2f}%")
                
                if new_gainers:
                    for token in new_gainers:
                        position = token.get('gainer_position', '?')
                        logger.info(f"  NEW GAINER #{position}: {token['name']} ({token['symbol']}) - +{token.get('price_change', 0):.2f}%")
        else:
            gmt8_time = datetime.now(GMT8).strftime('%H:%M')
            if subscribers:
                logger.info(f"✅ No changes at {gmt8_time} GMT+8. Both lists unchanged. ({len(subscribers)} subscribers)")
            else:
                logger.info(f"ℹ️ No subscribers yet. Monitoring {len(current_trending_ids)} positive trending + {len(current_gainer_ids)} gainers.")
        
        # Update previous tokens
        previous_trending_tokens = current_trending_ids
        previous_gainer_tokens = current_gainer_ids
        
    except Exception as e:
        logger.error(f"Error in dual check: {e}")

def create_startup_report(trending_tokens, gainer_tokens):
    """Create startup report showing both lists"""
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"🚀 **BOT STARTUP REPORT** 🚀\n"
    message += f"📅 {gmt8_time} GMT+8\n"
    message += f"✅ Bot deployed and monitoring successfully!\n\n"
    
    # Trending section
    if trending_tokens:
        message += f"📈 **TOP 30 TRENDING TOKENS**\n"
        message += f"🔥 Currently monitoring {len(trending_tokens)} trending tokens\n\n"
        
        # Show top 10 trending (positive only, in trending rank order)
        for token in trending_tokens[:10]:
            # All should be positive now
            if token.get('price_change', 0) > 0:
                position = token.get('trending_position', '?')
                price = token.get('price', 0)
                
                message += f"**#{position} {token['name']}** ({token['symbol']})\n"
                
                if price > 0:
                    if price < 0.01:
                        price_str = f"${price:.6f}"
                    else:
                        price_str = f"${price:.2f}"
                    message += f"💰 Price: {price_str}\n"
                
                message += f"🟢 24h: +{token.get('price_change', 0):.2f}%\n"
                message += "\n"
        
        if len(trending_tokens) > 10:
            message += f"... and {len(trending_tokens) - 10} more trending tokens\n\n"
    
    message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    # Gainers section
    if gainer_tokens:
        message += f"🚀 **TOP 30 GAINERS**\n"
        message += f"💰 Currently monitoring {len(gainer_tokens)} top gainers\n\n"
        
        # Show top 10 gainers (in gainer rank order)
        for token in gainer_tokens[:10]:
            position = token.get('gainer_position', '?')
            change_emoji = "🟢" if token.get('price_change', 0) > 0 else "🔴" if token.get('price_change', 0) < 0 else "⚪"
            price = token.get('price', 0)
            
            message += f"**#{position} {token['name']}** ({token['symbol']})\n"
            
            if price > 0:
                if price < 0.01:
                    price_str = f"${price:.6f}"
                else:
                    price_str = f"${price:.2f}"
                message += f"💰 Price: {price_str}\n"
            
            message += f"{change_emoji} 24h: {token.get('price_change', 0):+.2f}%\n"
            message += "\n"
        
        if len(gainer_tokens) > 10:
            message += f"... and {len(gainer_tokens) - 10} more gainers\n\n"
    
    next_check_minutes = get_seconds_until_next_hour() / 60
    message += f"⏰ Next check: {next_check_minutes:.0f} minutes\n"
    message += f"🎯 Will alert on changes to either list!\n"
    message += f"📊 Ready to serve {len(subscribers)} subscribers"
    
    return message
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
            
            welcome = f"""🎯 **Welcome {user_name}!** 🎯

✅ **You're now subscribed to DUAL crypto alerts!**

**What I monitor:**
📈 Top Positive Trending tokens (NEW entries only!)
🚀 Top 30 Gainers (NEW entries only!)
⚡ Send alerts ONLY when NEW tokens enter either list
🎯 Two sections: Changes in BOTH lists!

**How it works:**
🔍 Check both lists every hour at XX:00 GMT+8
📊 Alert you when tokens enter/exit either Top 30
🚫 Silent when nothing changes (no spam!)

**Current Status:**
🌏 Time now: {gmt8_time} GMT+8
⏰ Next check: {next_check_minutes:.0f} minutes
👥 Subscribers: {len(subscribers)}

**Commands:**
/start - Subscribe to dual alerts
/stop - Unsubscribe  
/status - Check subscription

**Double the insights, zero spam!** 📈🚀"""
            
            await bot.send_message(chat_id=chat_id, text=welcome, parse_mode='Markdown')
            logger.info(f"New subscriber: {chat_id} ({user_name}) - Total: {len(subscribers)}")
            
        elif text == '/stop':
            subscribers.discard(chat_id)
            await bot.send_message(
                chat_id=chat_id, 
                text=f"👋 **Goodbye {user_name}!**\n\nYou're unsubscribed from dual crypto alerts.\nUse /start anytime to re-subscribe.\n\nThanks for using the bot! 🎯"
            )
            logger.info(f"Unsubscribed: {chat_id} - Remaining: {len(subscribers)}")
            
        elif text == '/status':
            gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
            next_check_minutes = get_seconds_until_next_hour() / 60
            status = "✅ SUBSCRIBED" if chat_id in subscribers else "❌ NOT SUBSCRIBED"
            
            status_msg = f"""🎯 **Dual Bot Status Report**

**Your Status:** {status}
**Total Subscribers:** {len(subscribers)}
**Monitoring:**
  📈 {len(previous_trending_tokens)} Trending tokens
  🚀 {len(previous_gainer_tokens)} Top Gainers
**Current Time:** {gmt8_time} GMT+8
**Next Check:** {next_check_minutes:.0f} minutes

**What We're Watching:**
🔍 Positive Trending (NEW entries with actual trending rank)
💰 Top 30 Gainers (NEW entries with actual gainer rank)
⚡ NEW entries in either list
⏰ Hourly checks at XX:00 GMT+8

**Double coverage, maximum insights!** 📊🎯"""
            
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
    """Main function - Dual Tracking Focus"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN environment variable not set!")
        return
    
    bot = Bot(token=BOT_TOKEN)
    
    # Log startup
    gmt8_time = datetime.now(GMT8).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"🎯 DUAL TRACKING Bot started at {gmt8_time} GMT+8")
    logger.info(f"📈 Monitoring: Top 30 Positive Trending + Top 30 Gainers")
    logger.info(f"🎯 Focus: CHANGES in both lists (positive trending only!)")
    
    # Initial fetch to establish baseline
    logger.info("🔍 Establishing baseline for both lists...")
    await check_both_lists(bot)
    
    # Send startup report to verify bot is working
    logger.info("📊 Sending startup report...")
    await send_startup_report_to_admin(bot)
    
    # Calculate when to do first hourly check
    seconds_to_next_hour = get_seconds_until_next_hour()
    logger.info(f"⏰ Next dual check in {seconds_to_next_hour/60:.1f} minutes")
    
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
                
                logger.info(f"🕐 Dual check at {now_gmt8.strftime('%H:%M')} GMT+8")
                await check_both_lists(bot)
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
