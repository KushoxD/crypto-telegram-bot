import requests
import time
import json
import os
from datetime import datetime, timedelta
import pytz

# Configuration - Set these as environment variables in Railway
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Set your bot token here
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")     # Set your chat ID here
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")   # Set your CoinGecko API key here

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
            json.dump(sent_tokens, f, indent=2)
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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram credentials not set!")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, data=data, timeout=30)
        if response.status_code == 200:
            print("✅ Message sent successfully")
            return True
        else:
            print(f"❌ Failed to send message: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending message: {e}")
        return False

def get_top_coins_data(max_coins=5000):
    """Fetch top coins from CoinGecko with Pro API optimization"""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    
    headers = {
        "accept": "application/json",
        "x-cg-pro-api-key": COINGECKO_API_KEY  # Pro API key header
    }
    
    all_coins = []
    per_page = 250
    max_pages = max_coins // per_page  # Up to 20 pages (5000 coins) for pro tier
    
    print(f"📊 Fetching top {max_pages * per_page} coins with Pro API...")
    
    for page in range(1, max_pages + 1):
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": False,
            "price_change_percentage": "24h"
        }
        
        try:
            print(f"📄 Fetching page {page}/{max_pages}...")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Page {page}: Got {len(data)} coins")
                all_coins.extend(data)
                
                # Minimal delay for Pro API - much higher rate limits
                if page < max_pages:
                    time.sleep(0.1)  # Very short delay for Pro API
                    
            elif response.status_code == 429:
                print(f"⚠️ Rate limited on page {page}. Waiting 10 seconds...")
                time.sleep(10)
                continue
            else:
                print(f"❌ Error fetching page {page}: {response.status_code} - {response.text}")
                break
                
        except Exception as e:
            print(f"❌ Error fetching page {page}: {e}")
            break
    
    print(f"📊 Total coins fetched: {len(all_coins)}")
    return all_coins

def check_ath_tokens():
    """Check for tokens that hit ATH in the last 24 hours"""
    print("🔍 Checking for ATH tokens...")
    
    # Load previously sent tokens and clean old entries
    sent_tokens = load_sent_tokens()
    sent_tokens = clean_old_entries(sent_tokens)
    print(f"📋 Tracking {len(sent_tokens)} previously sent tokens")
    
    # Get coin data
    coins_data = get_top_coins_data()
    
    if not coins_data:
        error_msg = "❌ No coin data received from API"
        print(error_msg)
        send_telegram_message(error_msg)
        return
    
    print(f"🔍 Checking {len(coins_data)} coins for ATH...")
    
    # Find tokens that hit ATH
    ath_tokens = []
    current_time = datetime.now(pytz.UTC)
    
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
            time_diff = current_time - ath_datetime
            
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
                        'market_cap_rank': coin.get('market_cap_rank', 'N/A'),
                        'market_cap': coin.get('market_cap', 0)
                    })
                    
                    # Mark this token as sent
                    sent_tokens[coin_id] = current_time.isoformat()
                    print(f"🆕 Found new ATH: {coin_name} ({coin.get('symbol', '').upper()})")
        
        except Exception as e:
            print(f"⚠️ Error processing coin {coin.get('name', 'Unknown')}: {e}")
            continue
    
    # Save updated sent tokens
    save_sent_tokens(sent_tokens)
    
    # Send results
    if ath_tokens:
        # Sort by market cap (largest first)
        ath_tokens.sort(key=lambda x: x.get('market_cap', 0), reverse=True)
        
        message = f"🚀 <b>{len(ath_tokens)} Token(s) hitting ATH in last 24h:</b>\n\n"
        
        for i, token in enumerate(ath_tokens[:10], 1):  # Limit to 10
            message += f"{i}. 📈 <b>{token['name']}</b> ({token['symbol']})\n"
            message += f"💰 Price: ${token['current_price']:,.6f}\n"
            message += f"🏆 ATH: ${token['ath']:,.6f}\n"
            message += f"📊 Rank: #{token['market_cap_rank']}\n"
            
            # Format time nicely
            ath_time = datetime.fromisoformat(token['ath_date'].replace('Z', '+00:00'))
            formatted_time = ath_time.strftime("%m/%d %H:%M UTC")
            message += f"⏰ ATH Time: {formatted_time}\n\n"
        
        if len(ath_tokens) > 10:
            message += f"... and {len(ath_tokens) - 10} more tokens hit ATH!"
        
        print(f"🎉 Found {len(ath_tokens)} new ATH tokens!")
        send_telegram_message(message)
    else:
        status_msg = "📊 No new ATH tokens found in the last 24 hours."
        print(status_msg)
        # Only send "no results" message every 6 hours to avoid spam
        last_no_result = sent_tokens.get('_last_no_result', '')
        if last_no_result:
            last_time = datetime.fromisoformat(last_no_result)
            if current_time - last_time < timedelta(hours=6):
                return
        
        sent_tokens['_last_no_result'] = current_time.isoformat()
        save_sent_tokens(sent_tokens)
        send_telegram_message(status_msg)

def test_credentials():
    """Test if credentials are working"""
    print("🧪 Testing credentials...")
    
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set!")
        return False
    
    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID not set!")
        return False
        
    # Test Telegram
    test_msg = "🧪 ATH Monitor Bot - Credential Test (Pro API)"
    if send_telegram_message(test_msg):
        print("✅ Telegram credentials working!")
    else:
        print("❌ Telegram credentials failed!")
        return False
    
    # Test CoinGecko Pro API
    try:
        url = "https://api.coingecko.com/api/v3/ping"
        headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
        
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            print("✅ CoinGecko Pro API working!")
            
            # Test rate limits by checking plan info
            plan_url = "https://api.coingecko.com/api/v3/key"
            plan_response = requests.get(plan_url, headers=headers, timeout=10)
            if plan_response.status_code == 200:
                plan_data = plan_response.json()
                print(f"✅ API Plan: {plan_data.get('plan', 'Unknown')}")
                print(f"✅ Monthly calls: {plan_data.get('monthly_call_limit', 'Unknown')}")
            
            return True
        else:
            print(f"⚠️ CoinGecko API issue: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ CoinGecko API test failed: {e}")
        return False

def main():
    """Main function to run the bot"""
    print("🤖 ATH Monitor Bot Starting on Railway...")
    
    # Test credentials first
    if not test_credentials():
        print("❌ Credential test failed. Please check your Railway environment variables.")
        return
    
    # Set timezone to GMT+8
    gmt8 = pytz.timezone('Asia/Singapore')
    
    # Send startup message
    startup_time = datetime.now(gmt8).strftime("%Y-%m-%d %H:%M:%S GMT+8")
    send_telegram_message(f"🤖 ATH Monitor Bot started on Railway at {startup_time}")
    
    main_interval = 3600  # 1 hour schedule
    
    # FIRST RUN - Execute immediately to test
    print(f"\n{'='*60}")
    print(f"🚀 INITIAL TEST RUN - Running immediately to verify bot works")
    print(f"{'='*60}")
    
    try:
        current_time = datetime.now(gmt8)
        print(f"🕐 Test run at {current_time.strftime('%Y-%m-%d %H:%M:%S GMT+8')}")
        
        check_ath_tokens()
        
        print(f"✅ Initial test completed successfully!")
        print(f"🔄 Bot will now run every {main_interval//60} minutes")
        send_telegram_message(f"✅ Initial test completed! Bot is working on Railway and will check every {main_interval//60} minutes.")
        
    except Exception as e:
        error_msg = f"❌ Initial test failed: {e}"
        print(error_msg)
        send_telegram_message(f"❌ Initial test failed: {str(e)[:100]}...")
        print("🛑 Stopping bot due to initial test failure")
        return
    
    # Continue with regular schedule
    while True:
        try:
            print(f"\n⏰ Waiting {main_interval//60} minutes until next check...")
            time.sleep(main_interval)
            
            current_time = datetime.now(gmt8)
            print(f"\n{'='*50}")
            print(f"🕐 Scheduled check at {current_time.strftime('%Y-%m-%d %H:%M:%S GMT+8')}")
            print(f"{'='*50}")
            
            check_ath_tokens()
            
            print(f"✅ Scheduled check completed.")
            
        except KeyboardInterrupt:
            print("\n👋 Bot stopped by user")
            send_telegram_message("👋 ATH Monitor Bot stopped")
            break
        except Exception as e:
            error_msg = f"❌ Error in main loop: {e}"
            print(error_msg)
            send_telegram_message(f"⚠️ Bot error: {str(e)[:100]}...")
            
            # Wait 5 minutes before retrying if there's an error
            print("⏰ Waiting 5 minutes before retry...")
            time.sleep(300)

if __name__ == "__main__":
    # Print Railway deployment info
    print("🚂 Railway ATH Monitor Bot")
    print("📋 Required Railway Environment Variables:")
    print("- TELEGRAM_BOT_TOKEN")
    print("- TELEGRAM_CHAT_ID") 
    print("- COINGECKO_API_KEY")
    print("-" * 50)
    
    main()
