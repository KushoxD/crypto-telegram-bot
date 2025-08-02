import requests
import time
import json
import os
from datetime import datetime, timedelta
import pytz

# Configuration - Replace these with your actual values
TELEGRAM_BOT_TOKEN = os.getenv("8359324368:AAHgi3n2xTSyB5trTnd456CHa7_Ad2U2vsY")
TELEGRAM_CHAT_ID = os.getenv("81589364")
COINGECKO_API_KEY = os.getenv("CG-N6zCRMeBS6jnx2WnMFUgpB1t")

# File to store tokens that already hit ATH in last 24h
SENT_TOKENS_FILE = "sent_tokens.json"

def load_sent_tokens():
    """Load the list of tokens we've already sent notifications for"""
    try:
        if os.path.exists(SENT_TOKENS_FILE):
            with open(SENT_TOKENS_FILE, 'r') as f:
                data = json.load(f)
                return data
        return {}
    except Exception as e:
        print(f"Error loading sent tokens: {e}")
        return {}

def save_sent_tokens(sent_tokens):
    """Save the list of tokens we've sent notifications for"""
    try:
        with open(SENT_TOKENS_FILE, 'w') as f:
            json.dump(sent_tokens, f)
    except Exception as e:
        print(f"Error saving sent tokens: {e}")

def clean_old_entries(sent_tokens):
    """Remove entries older than 24 hours"""
    current_time = datetime.now()
    cleaned = {}
    
    for token_id, timestamp_str in sent_tokens.items():
        try:
            token_time = datetime.fromisoformat(timestamp_str)
            if current_time - token_time < timedelta(hours=24):
                cleaned[token_id] = timestamp_str
        except:
            continue
    
    return cleaned

def send_telegram_message(message):
    """Send a message to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, data=data)
        if response.status_code == 200:
            print("Message sent successfully")
            return True
        else:
            print(f"Failed to send message: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending message: {e}")
        return False

def get_top_coins_data():
    """Fetch top 3000 coins from CoinGecko"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": COINGECKO_API_KEY
    }
    
    all_coins = []
    
    # CoinGecko API returns max 250 coins per page, so we need multiple requests
    for page in range(1, 13):  # 12 pages * 250 = 3000 coins
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": page,
            "sparkline": False,
            "price_change_percentage": "24h"
        }
        
        try:
            print(f"Fetching page {page}...")
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                all_coins.extend(data)
                time.sleep(1)  # Rate limiting - wait 1 second between requests
            else:
                print(f"Error fetching page {page}: {response.status_code}")
                break
                
        except Exception as e:
            print(f"Error fetching page {page}: {e}")
            break
    
    return all_coins

def check_ath_tokens():
    """Check for tokens that hit ATH in the last 24 hours"""
    print("Checking for ATH tokens...")
    
    # Load previously sent tokens and clean old entries
    sent_tokens = load_sent_tokens()
    sent_tokens = clean_old_entries(sent_tokens)
    
    # Get coin data
    coins_data = get_top_coins_data()
    
    if not coins_data:
        print("No coin data received")
        return
    
    print(f"Checking {len(coins_data)} coins for ATH...")
    
    # Find tokens that hit ATH
    ath_tokens = []
    current_time = datetime.now()
    
    for coin in coins_data:
        try:
            coin_id = coin.get('id')
            coin_name = coin.get('name')
            current_price = coin.get('current_price')
            ath = coin.get('ath')
            ath_date = coin.get('ath_date')
            
            if not all([coin_id, coin_name, current_price, ath, ath_date]):
                continue
            
            # Parse ATH date
            ath_datetime = datetime.fromisoformat(ath_date.replace('Z', '+00:00'))
            
            # Check if ATH was hit in the last 24 hours
            time_diff = current_time.replace(tzinfo=pytz.UTC) - ath_datetime
            
            if time_diff <= timedelta(hours=24):
                # Check if we haven't already sent this token
                if coin_id not in sent_tokens:
                    ath_tokens.append({
                        'id': coin_id,
                        'name': coin_name,
                        'symbol': coin.get('symbol', '').upper(),
                        'current_price': current_price,
                        'ath': ath,
                        'ath_date': ath_date,
                        'market_cap_rank': coin.get('market_cap_rank', 'N/A')
                    })
                    
                    # Mark this token as sent
                    sent_tokens[coin_id] = current_time.isoformat()
        
        except Exception as e:
            print(f"Error processing coin {coin.get('name', 'Unknown')}: {e}")
            continue
    
    # Save updated sent tokens
    save_sent_tokens(sent_tokens)
    
    # Send results
    if ath_tokens:
        message = f"🚀 <b>Tokens hitting ATH in last 24h:</b>\n\n"
        
        for token in ath_tokens[:10]:  # Limit to 10 to avoid message being too long
            message += f"📈 <b>{token['name']}</b> ({token['symbol']})\n"
            message += f"💰 Price: ${token['current_price']:,.6f}\n"
            message += f"🏆 ATH: ${token['ath']:,.6f}\n"
            message += f"📊 Rank: #{token['market_cap_rank']}\n"
            message += f"⏰ ATH Time: {token['ath_date'][:19]}Z\n\n"
        
        if len(ath_tokens) > 10:
            message += f"... and {len(ath_tokens) - 10} more tokens hit ATH!"
        
        print(f"Found {len(ath_tokens)} tokens that hit ATH")
        send_telegram_message(message)
    else:
        print("No new ATH tokens found")
        send_telegram_message("📊 No tokens hit ATH in the last 24 hours.")

def main():
    """Main function to run the bot"""
    print("ATH Monitor Bot Starting...")
    
    # Set timezone to GMT+8
    gmt8 = pytz.timezone('Asia/Singapore')
    
    # Send startup message
    startup_time = datetime.now(gmt8).strftime("%Y-%m-%d %H:%M:%S GMT+8")
    send_telegram_message(f"🤖 ATH Monitor Bot started at {startup_time}")
    
    while True:
        try:
            current_time = datetime.now(gmt8)
            print(f"Running check at {current_time.strftime('%Y-%m-%d %H:%M:%S GMT+8')}")
            
            check_ath_tokens()
            
            # Wait for 1 hour (3600 seconds)
            print("Waiting for next check in 1 hour...")
            time.sleep(3600)
            
        except KeyboardInterrupt:
            print("Bot stopped by user")
            break
        except Exception as e:
            print(f"Error in main loop: {e}")
            # Wait 5 minutes before retrying if there's an error
            time.sleep(300)

if __name__ == "__main__":
    main()
