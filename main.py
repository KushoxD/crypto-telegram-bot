import os
import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from typing import Set, Dict, List
import sqlite3

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

class MultiUserCryptoBot:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.bot = Bot(token=bot_token)
        self.previous_top_30: Set[str] = set()
        self.subscribers: Set[str] = set()  # Store all subscribers
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Setup database for subscribers
        self.setup_database()

    def setup_database(self):
        """Create database to store subscribers"""
        try:
            conn = sqlite3.connect('subscribers.db')
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            conn.commit()
            conn.close()
            
            # Load existing subscribers
            self.load_subscribers()
            self.logger.info(f"Database setup complete. {len(self.subscribers)} subscribers loaded.")
        except Exception as e:
            self.logger.error(f"Database setup error: {e}")

    def load_subscribers(self):
        """Load subscribers from database"""
        try:
            conn = sqlite3.connect('subscribers.db')
            cursor = conn.cursor()
            cursor.execute('SELECT chat_id FROM subscribers WHERE is_active = TRUE')
            self.subscribers = {str(row[0]) for row in cursor.fetchall()}
            conn.close()
        except Exception as e:
            self.logger.error(f"Error loading subscribers: {e}")

    def add_subscriber(self, chat_id: str, username: str = None, first_name: str = None):
        """Add new subscriber to database"""
        try:
            conn = sqlite3.connect('subscribers.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO subscribers (chat_id, username, first_name, is_active)
                VALUES (?, ?, ?, TRUE)
            ''', (chat_id, username, first_name))
            conn.commit()
            conn.close()
            
            self.subscribers.add(str(chat_id))
            self.logger.info(f"Added subscriber: {chat_id} ({first_name})")
            return True
        except Exception as e:
            self.logger.error(f"Error adding subscriber: {e}")
            return False

    def remove_subscriber(self, chat_id: str):
        """Remove subscriber from database"""
        try:
            conn = sqlite3.connect('subscribers.db')
            cursor = conn.cursor()
            cursor.execute('UPDATE subscribers SET is_active = FALSE WHERE chat_id = ?', (chat_id,))
            conn.commit()
            conn.close()
            
            self.subscribers.discard(str(chat_id))
            self.logger.info(f"Removed subscriber: {chat_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error removing subscriber: {e}")
            return False

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        
        # Add user to subscribers
        success = self.add_subscriber(
            chat_id=chat_id,
            username=user.username,
            first_name=user.first_name
        )
        
        if success:
            welcome_message = f"""
🚀 **Welcome to Crypto Trending Bot!** 🚀

Hi {user.first_name}! I'm your personal crypto assistant.

**What I do:**
📈 Monitor top 30 trending tokens every hour
🔥 Send you notifications ONLY when NEW tokens enter the trending list
💰 Show price, 24h change, and market cap rank
⏰ Work 24/7 automatically

**Commands:**
/start - Subscribe to notifications
/stop - Unsubscribe from notifications  
/status - Check your subscription
/stats - See bot statistics

**You're now subscribed!** 🎉
I'll notify you when new trending tokens appear.

*Next check in less than 1 hour...*
            """
            
            await update.message.reply_text(welcome_message, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Sorry, there was an error subscribing you. Please try again.")

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command"""
        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        
        success = self.remove_subscriber(chat_id)
        
        if success:
            goodbye_message = f"""
👋 **Goodbye {user.first_name}!**

You've been unsubscribed from crypto notifications.

You can always come back by sending /start

Thanks for using Crypto Trending Bot! 🚀
            """
            await update.message.reply_text(goodbye_message, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Error unsubscribing. Please try again.")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        
        if chat_id in self.subscribers:
            status_message = f"""
✅ **Subscription Status: ACTIVE**

Hi {user.first_name}!

📊 You're subscribed to trending crypto notifications
⏰ Next check: Within the hour
🔥 I'll notify you when new tokens enter top 30

Use /stop to unsubscribe anytime.
            """
        else:
            status_message = f"""
❌ **Subscription Status: INACTIVE**

Hi {user.first_name}!

You're not currently subscribed to notifications.

Use /start to subscribe and get trending crypto alerts!
            """
        
        await update.message.reply_text(status_message, parse_mode='Markdown')

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        total_subscribers = len(self.subscribers)
        
        stats_message = f"""
📊 **Bot Statistics**

👥 Total Subscribers: {total_subscribers}
🤖 Status: Running 24/7
⏰ Check Frequency: Every hour
🔥 Monitoring: Top 30 trending tokens

**Recent Activity:**
- Last check: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC
- Previous top 30 size: {len(self.previous_top_30)}

Join the community! Share with friends! 🚀
        """
        
        await update.message.reply_text(stats_message, parse_mode='Markdown')

    async def get_trending_tokens(self):
        """Get trending tokens from CoinGecko"""
        try:
            async with aiohttp.ClientSession() as session:
                # Get trending tokens
                url = "https://api.coingecko.com/api/v3/search/trending"
                async with session.get(url) as response:
                    data = await response.json()
                    
                    trending_tokens = []
                    for item in data.get('coins', []):
                        coin = item.get('item', {})
                        trending_tokens.append({
                            'id': coin.get('id', ''),
                            'name': coin.get('name', ''),
                            'symbol': coin.get('symbol', '').upper(),
                            'rank': coin.get('market_cap_rank', 0),
                            'price_change': coin.get('data', {}).get('price_change_percentage_24h', {}).get('usd', 0)
                        })
                    
                    # Get top gainers to supplement
                    url2 = "https://api.coingecko.com/api/v3/coins/top_gainers_losers"
                    async with session.get(url2, params={'vs_currency': 'usd', 'duration': '24h'}) as response2:
                        if response2.status == 200:
                            gainers_data = await response2.json()
                            existing_ids = {token['id'] for token in trending_tokens}
                            
                            for gainer in gainers_data.get('top_gainers', []):
                                if len(trending_tokens) >= 30:
                                    break
                                if gainer.get('id') not in existing_ids:
                                    trending_tokens.append({
                                        'id': gainer.get('id', ''),
                                        'name': gainer.get('name', ''),
                                        'symbol': gainer.get('symbol', '').upper(),
                                        'rank': gainer.get('market_cap_rank', 0),
                                        'price_change': gainer.get('usd_24h_change', 0),
                                        'price': gainer.get('usd', 0)
                                    })
                    
                    return trending_tokens[:30]
                    
        except Exception as e:
            self.logger.error(f"Error getting trending tokens: {e}")
            return []

    def format_message(self, new_tokens):
        """Create a nice message for new tokens"""
        if not new_tokens:
            return ""
            
        message = f"🚀 **NEW TRENDING TOKENS** 🚀\n"
        message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        message += f"🔥 {len(new_tokens)} new token(s) entered Top 30!\n\n"
        
        for i, token in enumerate(new_tokens, 1):
            change_emoji = "🟢" if token.get('price_change', 0) > 0 else "🔴"
            price = token.get('price', 0)
            price_str = f"${price:.6f}" if price < 0.01 else f"${price:.2f}"
            
            message += f"**{i}. {token['name']}** ({token['symbol']})\n"
            message += f"{change_emoji} Change: {token.get('price_change', 0):.2f}%\n"
            message += f"🏆 Rank: #{token.get('rank', 'N/A')}\n\n"
        
        message += f"📊 Shared with {len(self.subscribers)} subscribers\n"
        message += f"💡 Use /stop to unsubscribe anytime"
        
        return message

    async def send_to_all_subscribers(self, message: str):
        """Send message to all subscribers"""
        if not message or not self.subscribers:
            return
        
        successful_sends = 0
        failed_sends = 0
        
        for chat_id in self.subscribers.copy():  # Use copy to avoid modification during iteration
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode='Markdown'
                )
                successful_sends += 1
                await asyncio.sleep(0.1)  # Small delay to avoid rate limits
                
            except Exception as e:
                failed_sends += 1
                self.logger.warning(f"Failed to send to {chat_id}: {e}")
                
                # Remove subscriber if bot was blocked
                if "blocked" in str(e).lower() or "chat not found" in str(e).lower():
                    self.remove_subscriber(chat_id)
        
        self.logger.info(f"Message sent: {successful_sends} successful, {failed_sends} failed")

    async def check_for_new_tokens(self):
        """Check for new tokens and send notifications"""
        try:
            current_tokens = await self.get_trending_tokens()
            current_ids = {token['id'] for token in current_tokens if token['id']}
            
            # Find new tokens
            new_token_ids = current_ids - self.previous_top_30
            
            if new_token_ids and self.subscribers:
                new_tokens = [token for token in current_tokens if token['id'] in new_token_ids]
                message = self.format_message(new_tokens)
                
                if message:
                    await self.send_to_all_subscribers(message)
                    self.logger.info(f"✅ Sent notifications for {len(new_tokens)} new tokens to {len(self.subscribers)} subscribers")
            else:
                self.logger.info(f"ℹ️ No new tokens found. Monitoring {len(self.subscribers)} subscribers.")
            
            # Update previous top 30
            self.previous_top_30 = current_ids
            
        except Exception as e:
            self.logger.error(f"❌ Error checking tokens: {e}")

    async def run_bot_commands(self):
        """Setup and run telegram bot commands"""
        application = Application.builder().token(self.bot_token).build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("stop", self.stop_command))
        application.add_handler(CommandHandler("status", self.status_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        
        # Start the bot
        await application.initialize()
        await application.start()
        
        self.logger.info("🤖 Telegram command handlers started!")
        
        return application

    async def run_monitoring_loop(self):
        """Run the monitoring loop"""
        self.logger.info("🔍 Starting crypto monitoring loop...")
        
        # Initial check
        await self.check_for_new_tokens()
        
        # Check every hour
        while True:
            try:
                await asyncio.sleep(3600)  # Wait 1 hour
                await self.check_for_new_tokens()
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry

    async def run(self):
        """Run both bot commands and monitoring"""
        self.logger.info("🚀 Multi-User Crypto Bot Starting!")
        
        # Start telegram bot commands
        application = await self.run_bot_commands()
        
        try:
            # Run monitoring loop
            await self.run_monitoring_loop()
        finally:
            # Cleanup
            await application.stop()
            await application.shutdown()

async def main():
    """Main function"""
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN environment variable must be set!")
        return
    
    bot = MultiUserCryptoBot(BOT_TOKEN)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
