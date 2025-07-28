import os
import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from typing import Set, Dict, List

from telegram import Bot

class CryptoBot:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token)
        self.previous_top_30: Set[str] = set()
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    async def get_trending_tokens(self):
        try:
            async with aiohttp.ClientSession() as session:
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
        if not new_tokens:
            return ""
            
        message = f"🚀 **NEW TRENDING TOKENS** 🚀\n"
        message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"🔥 {len(new_tokens)} new token(s) in Top 30!\n\n"
        
        for i, token in enumerate(new_tokens, 1):
            change_emoji = "🟢" if token.get('price_change', 0) > 0 else "🔴"
            price = token.get('price', 0)
            price_str = f"${price:.6f}" if price < 0.01 else f"${price:.2f}"
            
            message += f"**{i}. {token['name']}** ({token['symbol']})\n"
            message += f"{change_emoji} Change: {token.get('price_change', 0):.2f}%\n"
            message += f"🏆 Rank: #{token.get('rank', 'N/A')}\n\n"
        
        return message

    async def check_for_new_tokens(self):
        try:
            current_tokens = await self.get_trending_tokens()
            current_ids = {token['id'] for token in current_tokens if token['id']}
            
            new_token_ids = current_ids - self.previous_top_30
            
            if new_token_ids:
                new_tokens = [token for token in current_tokens if token['id'] in new_token_ids]
                message = self.format_message(new_tokens)
                
                if message:
                    await self.bot.send_message(
                        chat_id=self.chat_id, 
                        text=message, 
                        parse_mode='Markdown'
                    )
                    self.logger.info(f"✅ Sent notification for {len(new_tokens)} new tokens")
            else:
                self.logger.info("ℹ️ No new tokens found")
            
            self.previous_top_30 = current_ids
            
        except Exception as e:
            self.logger.error(f"❌ Error checking tokens: {e}")

    async def run(self):
        self.logger.info("🤖 Crypto Bot Started on Railway Cloud!")
        
        await self.check_for_new_tokens()
        
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                await self.check_for_new_tokens()
            except Exception as e:
                self.logger.error(f"Error: {e}")
                await asyncio.sleep(60)

async def main():
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    CHAT_ID = os.getenv('CHAT_ID')
    
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ BOT_TOKEN and CHAT_ID environment variables must be set!")
        return
    
    bot = CryptoBot(BOT_TOKEN, CHAT_ID)
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
