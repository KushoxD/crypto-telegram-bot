// railway.json (Railway configuration)
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "npm start",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}

// .env.example (copy to .env and fill in your values)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
COINGECKO_API_KEY=your_coingecko_pro_api_key_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
PORT=3000

// package.json
{
  "name": "coingecko-ath-monitor",
  "version": "1.0.0",
  "description": "Telegram bot that monitors CoinGecko for all-time high tokens",
  "main": "index.js",
  "scripts": {
    "start": "node index.js",
    "dev": "nodemon index.js"
  },
  "dependencies": {
    "node-telegram-bot-api": "^0.66.0",
    "axios": "^1.6.0",
    "node-cron": "^3.0.3",
    "moment-timezone": "^0.5.43",
    "express": "^4.18.2"
  },
  "devDependencies": {
    "nodemon": "^3.0.0"
  }
}

// index.js
const TelegramBot = require('node-telegram-bot-api');
const axios = require('axios');
const cron = require('node-cron');
const moment = require('moment-timezone');

// Environment variables
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const COINGECKO_API_KEY = process.env.COINGECKO_API_KEY;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

// Initialize bot
const bot = new TelegramBot(TELEGRAM_BOT_TOKEN, { polling: false });

// In-memory storage for last check times (use Redis in production)
const lastCheckedTokens = new Map();

class CoinGeckoATHMonitor {
  constructor() {
    this.apiBaseUrl = 'https://pro-api.coingecko.com/api/v3';
    this.timezone = 'Asia/Singapore'; // GMT+8
  }

  async makeApiRequest(endpoint, params = {}) {
    try {
      const response = await axios.get(`${this.apiBaseUrl}${endpoint}`, {
        headers: {
          'X-Cg-Pro-Api-Key': COINGECKO_API_KEY
        },
        params
      });
      return response.data;
    } catch (error) {
      console.error(`API request failed: ${error.message}`);
      throw error;
    }
  }

  async getTop3000Tokens() {
    try {
      const allTokens = [];
      const perPage = 250; // CoinGecko max per page
      const totalPages = Math.ceil(3000 / perPage);

      for (let page = 1; page <= totalPages; page++) {
        console.log(`Fetching page ${page}/${totalPages}...`);
        
        const tokens = await this.makeApiRequest('/coins/markets', {
          vs_currency: 'usd',
          order: 'market_cap_desc',
          per_page: perPage,
          page: page,
          sparkline: false,
          price_change_percentage: '1h,24h'
        });

        allTokens.push(...tokens);
        
        // Rate limiting - wait 1 second between requests
        await new Promise(resolve => setTimeout(resolve, 1000));
      }

      return allTokens.slice(0, 3000); // Ensure we only get top 3000
    } catch (error) {
      console.error('Error fetching top 3000 tokens:', error.message);
      throw error;
    }
  }

  async checkTokenATH(tokenId) {
    try {
      const tokenData = await this.makeApiRequest(`/coins/${tokenId}`, {
        localization: false,
        tickers: false,
        market_data: true,
        community_data: false,
        developer_data: false
      });

      const currentPrice = tokenData.market_data.current_price.usd;
      const ath = tokenData.market_data.ath.usd;
      const athDate = new Date(tokenData.market_data.ath_date.usd);
      
      // Check if current price is at or very close to ATH (within 0.1%)
      const isAtATH = currentPrice >= (ath * 0.999);
      
      // Check if ATH was achieved in the last hour
      const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
      const isRecentATH = athDate > oneHourAgo;

      return {
        id: tokenId,
        name: tokenData.name,
        symbol: tokenData.symbol.toUpperCase(),
        currentPrice,
        ath,
        athDate,
        isAtATH,
        isRecentATH,
        priceChange1h: tokenData.market_data.price_change_percentage_1h || 0,
        priceChange24h: tokenData.market_data.price_change_percentage_24h || 0
      };
    } catch (error) {
      console.error(`Error checking ATH for token ${tokenId}:`, error.message);
      return null;
    }
  }

  async findATHTokens(isInitialCheck = false) {
    try {
      console.log('Starting ATH token search...');
      const tokens = await this.getTop3000Tokens();
      const athTokens = [];
      const now = Date.now();

      for (let i = 0; i < tokens.length; i++) {
        const token = tokens[i];
        
        // Skip if we've checked this token in the last 24 hours
        const lastChecked = lastCheckedTokens.get(token.id);
        if (lastChecked && (now - lastChecked) < 24 * 60 * 60 * 1000) {
          continue;
        }

        console.log(`Checking ${token.name} (${i + 1}/${tokens.length})...`);
        
        const athInfo = await this.checkTokenATH(token.id);
        
        if (athInfo) {
          if (isInitialCheck) {
            // For initial check, look for tokens that hit ATH in the past hour
            if (athInfo.isRecentATH) {
              athTokens.push(athInfo);
              lastCheckedTokens.set(token.id, now);
            }
          } else {
            // For regular checks, look for current ATH tokens
            if (athInfo.isAtATH) {
              athTokens.push(athInfo);
              lastCheckedTokens.set(token.id, now);
            }
          }
        }

        // Rate limiting - wait 1.2 seconds between detailed requests
        await new Promise(resolve => setTimeout(resolve, 1200));
      }

      return athTokens;
    } catch (error) {
      console.error('Error finding ATH tokens:', error.message);
      throw error;
    }
  }

  formatATHMessage(athTokens) {
    if (athTokens.length === 0) {
      return '🔍 No tokens made all-time high during the monitored period.';
    }

    let message = `🚀 *ALL-TIME HIGH ALERT* 🚀\n\n`;
    message += `Found ${athTokens.length} token(s) at all-time high:\n\n`;

    athTokens.forEach((token, index) => {
      message += `${index + 1}. *${token.name}* (${token.symbol})\n`;
      message += `   💰 Price: $${token.currentPrice.toLocaleString()}\n`;
      message += `   📈 ATH: $${token.ath.toLocaleString()}\n`;
      message += `   📅 ATH Date: ${moment(token.athDate).tz(this.timezone).format('YYYY-MM-DD HH:mm:ss')} GMT+8\n`;
      message += `   📊 1h: ${token.priceChange1h.toFixed(2)}% | 24h: ${token.priceChange24h.toFixed(2)}%\n\n`;
    });

    message += `_Last updated: ${moment().tz(this.timezone).format('YYYY-MM-DD HH:mm:ss')} GMT+8_`;
    
    return message;
  }

  async sendTelegramMessage(message) {
    try {
      await bot.sendMessage(TELEGRAM_CHAT_ID, message, {
        parse_mode: 'Markdown'
      });
      console.log('Telegram message sent successfully');
    } catch (error) {
      console.error('Error sending Telegram message:', error.message);
    }
  }
}

// Initialize monitor
const monitor = new CoinGeckoATHMonitor();

// Initial check on startup
async function initialCheck() {
  console.log('Performing initial check for tokens with ATH in the past hour...');
  try {
    const athTokens = await monitor.findATHTokens(true);
    const message = monitor.formatATHMessage(athTokens);
    await monitor.sendTelegramMessage(message);
  } catch (error) {
    console.error('Initial check failed:', error.message);
    await monitor.sendTelegramMessage('❌ Initial ATH check failed. Please check the logs.');
  }
}

// Daily check at 00:00 GMT+8
cron.schedule('0 0 * * *', async () => {
  console.log('Running daily ATH check at 00:00 GMT+8...');
  try {
    const athTokens = await monitor.findATHTokens(false);
    const message = monitor.formatATHMessage(athTokens);
    await monitor.sendTelegramMessage(message);
  } catch (error) {
    console.error('Daily check failed:', error.message);
    await monitor.sendTelegramMessage('❌ Daily ATH check failed. Please check the logs.');
  }
}, {
  timezone: "Asia/Singapore"
});

// Health check endpoint for Railway
const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.json({ 
    status: 'running',
    message: 'CoinGecko ATH Monitor is active',
    lastCheckedTokens: lastCheckedTokens.size,
    timezone: 'GMT+8'
  });
});

app.get('/health', (req, res) => {
  res.json({ status: 'healthy' });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log('CoinGecko ATH Monitor started');
  
  // Run initial check after 30 seconds to allow server to fully start
  setTimeout(() => {
    initialCheck();
  }, 30000);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('Received SIGTERM, shutting down gracefully');
  process.exit(0);
});

process.on('SIGINT', () => {
  console.log('Received SIGINT, shutting down gracefully');
  process.exit(0);
});
