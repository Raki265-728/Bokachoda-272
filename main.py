import asyncio
import aiohttp
import json
import logging
import random
import ssl
from datetime import datetime
from collections import Counter, deque
import threading

from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter

# --- Flask App ---
app = Flask(__name__)

# --- Configuration ---
BOT_TOKEN = "8421396575:AAHTcG-fNAp6r1iq9yg-xMhNL-jWgVHPRcY"
CHANNEL_USERNAME = "-1003723520077"

WIN_STICKER = "CAACAgUAAxkBAAEC4G9pifQIzVJ60qpe_n0aZRqPjOqXfgACXxoAAo_FYFaOLtZ5d3HjojoE"
LOSS_STICKER = "CAACAgUAAxkBAAEC4INpifhHjjiCUzXA_Z87dWdNqXtEkAACNxYAAqXy8Fbys0mlir6tpzoE"
JACKPOT_STICKER = "CAACAgUAAxkBAAEC4JNpijzPzEMqyQP-MnWjPR9LOSrnggAC-RQAAhjt6VegzLnRRkH9azoE"

API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Content-Type': 'application/json',
    'Origin': 'https://draw.ar-lottery01.com',
    'Referer': 'https://draw.ar-lottery01.com/',
    'Connection': 'keep-alive',
}

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# Global state
last_processed_id = None
current_prediction = None
current_numbers = []
current_win_rate = "92%"
current_pattern = ""
win_count = 0
loss_count = 0
jackpot_count = 0
total_predictions = 0
loss_streak = 0
session_profit = 0
recent_signals_history = []
number_frequency = Counter()
accuracy_history = deque(maxlen=30)

BET_PROGRESSION = [10, 35]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FixedBot')

bot = Bot(token=BOT_TOKEN)

# --- Prediction Logic ---
def predict_trend(history):
    if not history or len(history) < 5:
        return 'BIG', "90%", "🎲 AI STARTING"
    
    recent_5 = history[:5]
    big_count = sum(1 for n in recent_5 if n >= 5)
    
    if big_count >= 4:
        return 'BIG', "95%", "🔥 DRAGON RUN"
    elif big_count <= 1:
        return 'SMALL', "95%", "🔥 DRAGON RUN"
    elif big_count >= 3:
        return 'BIG', "88%", "📈 TREND"
    else:
        return 'SMALL', "88%", "📈 TREND"

def generate_numbers(prediction, history):
    pool = [5, 6, 7, 8, 9] if prediction == 'BIG' else [0, 1, 2, 3, 4]
    
    if not history or len(history) < 5:
        return sorted(random.sample(pool, 2))
    
    recent = history[:10]
    matched = [n for n in recent if n in pool]
    
    if matched:
        counts = Counter(matched)
        hot = [num for num, _ in counts.most_common()]
        if len(hot) >= 2:
            return sorted(hot[:2])
        elif len(hot) == 1:
            remaining = [n for n in pool if n != hot[0]]
            return sorted([hot[0], random.choice(remaining)])
    
    return sorted(random.sample(pool, 2))

# --- Message Functions ---
async def send_signal(period, prediction, numbers, bet, win_rate, pattern):
    current_time = datetime.now().strftime("%I:%M:%S %p")
    pred_emoji = '🟢' if prediction == 'BIG' else '🔴'
    
    message = f"""
🎰 <b>TK CLUB 30S SIGNAL</b>
━━━━━━━━━━━━━━━━━━━━━━━━
🕐 <b>TIME:</b> <code>{current_time}</code>
📅 <b>PERIOD:</b> <code>{period}</code>

{pred_emoji} <b>PREDICTION:</b> <b>{prediction}</b>
🎯 <b>CONFIDENCE:</b> <code>{win_rate}</code>

🎲 <b>LUCKY NUMBERS:</b>
<code>┌───────┐</code>
<code>│   {numbers[0]}   │</code>
<code>└───────┘</code>
<code>┌───────┐</code>
<code>│   {numbers[1]}   │</code>
<code>└───────┘</code>

💰 <b>BET:</b> <code>{bet} TK</code>
📈 <b>PROFIT:</b> <code>{bet * 0.95:.2f} TK</code>

🧠 <b>PATTERN:</b> <i>{pattern}</i>
━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>STATS:</b>
├ Wins: <code>{win_count}</code>
├ Losses: <code>{loss_count}</code>
└ Profit: <code>{session_profit:.2f} TK</code>
━━━━━━━━━━━━━━━━━━━━━━━━
♻️ <b>AMVIPTEAM</b>
"""
    
    try:
        await bot.send_message(CHANNEL_USERNAME, message, parse_mode=ParseMode.HTML)
        logger.info(f"Signal sent: Period {period}")
        return True
    except RetryAfter as e:
        logger.warning(f"Rate limited, waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        await bot.send_message(CHANNEL_USERNAME, message, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.error(f"Signal error: {e}")
        return False

async def send_result(period, number, won, jackpot, bet_amount):
    actual_size = 'BIG' if number >= 5 else 'SMALL'
    
    if jackpot:
        emoji = '👑'
        title = 'JACKPOT!'
        profit = bet_amount * 2.5
    elif won:
        emoji = '✅'
        title = 'WIN!'
        profit = bet_amount * 0.95
    else:
        emoji = '❌'
        title = 'LOSS'
        profit = -bet_amount
    
    msg = f"""
{emoji} <b>{title}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
📅 <b>PERIOD:</b> <code>{period}</code>
🔢 <b>NUMBER:</b> <code>{number}</code>
📊 <b>RESULT:</b> <code>{actual_size}</code>
💰 <b>BET:</b> <code>{bet_amount} TK</code>
💵 <b>PROFIT:</b> <code>{profit:.2f} TK</code>
━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    try:
        await bot.send_message(CHANNEL_USERNAME, msg, parse_mode=ParseMode.HTML)
        sticker = JACKPOT_STICKER if jackpot else (WIN_STICKER if won else LOSS_STICKER)
        await bot.send_sticker(CHANNEL_USERNAME, sticker)
    except Exception as e:
        logger.error(f"Result error: {e}")

async def send_report():
    global recent_signals_history
    
    if not recent_signals_history:
        return
    
    win_rate = (win_count / (win_count + loss_count) * 100) if (win_count + loss_count) > 0 else 0
    
    report = f"""
📊 <b>TK CLUB REPORT</b>
━━━━━━━━━━━━━━━━━━━━━━━━
✅ <b>WINS:</b> <code>{win_count}</code>
❌ <b>LOSSES:</b> <code>{loss_count}</code>
👑 <b>JACKPOTS:</b> <code>{jackpot_count}</code>
📈 <b>WIN RATE:</b> <code>{win_rate:.1f}%</code>
💰 <b>PROFIT:</b> <code>{session_profit:.2f} TK</code>

<b>LAST 10:</b>
"""
    
    for idx, item in enumerate(recent_signals_history, 1):
        emoji = '✅' if item['status'] == 'WIN' else '❌'
        report += f"{idx}. {item['period']} | {item['pred']} → {item['act_num']} {emoji}\n"
    
    report += "━━━━━━━━━━━━━━━━━━━━━━━━"
    
    try:
        sent = await bot.send_message(CHANNEL_USERNAME, report, parse_mode=ParseMode.HTML)
        await bot.pin_chat_message(CHANNEL_USERNAME, sent.message_id)
        logger.info("Report sent and pinned")
    except Exception as e:
        logger.error(f"Report error: {e}")
    
    recent_signals_history = []

# --- Main Function ---
async def fetch_data(session):
    try:
        async with session.get(
            API_URL,
            headers=HEADERS,
            ssl=SSL_CONTEXT,
            timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            logger.info(f"API Status: {response.status}")
            
            if response.status == 200:
                text = await response.text()
                data = json.loads(text)
                
                if data.get('data') and data['data'].get('list'):
                    history_list = data['data']['list']
                    logger.info(f"Got {len(history_list)} records")
                    return history_list
                else:
                    logger.error(f"Invalid data structure")
                    return None
            else:
                logger.error(f"HTTP {response.status}")
                return None
                
    except Exception as e:
        logger.error(f"Error: {e}")
        return None

async def process_result(actual_number, period):
    global win_count, loss_count, jackpot_count, total_predictions, loss_streak, session_profit
    
    if not current_prediction:
        return
    
    total_predictions += 1
    actual_size = 'BIG' if actual_number >= 5 else 'SMALL'
    is_win = (actual_size == current_prediction)
    is_jackpot = (actual_number in current_numbers)
    
    bet_amount = BET_PROGRESSION[min(loss_streak, len(BET_PROGRESSION) - 1)]
    
    if is_jackpot or is_win:
        win_count += 1
        profit = bet_amount * (2.5 if is_jackpot else 0.95)
        session_profit += profit
        loss_streak = 0
        if is_jackpot:
            jackpot_count += 1
        status = 'WIN'
    else:
        loss_count += 1
        session_profit -= bet_amount
        loss_streak += 1
        status = 'LOSS'
    
    await send_result(period, actual_number, is_win, is_jackpot, bet_amount)
    
    recent_signals_history.append({
        'period': period,
        'pred': current_prediction,
        'act_num': actual_number,
        'status': status
    })
    
    if len(recent_signals_history) >= 10:
        await send_report()

async def main_loop():
    global last_processed_id, current_prediction, current_numbers, current_win_rate, current_pattern, loss_streak
    
    print("🚀 TK Club 30s Bot Started")
    
    try:
        me = await bot.get_me()
        print(f"✅ Bot connected: @{me.username}")
    except Exception as e:
        print(f"❌ Bot connection failed: {e}")
        return
    
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        print(f"✅ Channel: {chat.title}")
    except Exception as e:
        print(f"❌ Channel access failed: {e}")
        return
    
    async with aiohttp.ClientSession() as session:
        test_data = await fetch_data(session)
        if test_data:
            print(f"✅ API working! Got {len(test_data)} records")
        else:
            print("❌ API not working!")
            return
        
        while True:
            try:
                history = await fetch_data(session)
                
                if history:
                    latest = history[0]
                    current_id = latest['issueNumber']
                    current_number = int(latest['number'])
                    
                    if last_processed_id is None or current_id != last_processed_id:
                        
                        if last_processed_id:
                            await process_result(current_number, last_processed_id)
                        
                        history_nums = [int(item['number']) for item in history[:20]]
                        
                        current_prediction, current_win_rate, current_pattern = predict_trend(history_nums)
                        current_numbers = generate_numbers(current_prediction, history_nums)
                        
                        next_period = str(int(current_id) + 1)
                        bet = BET_PROGRESSION[min(loss_streak, len(BET_PROGRESSION) - 1)]
                        
                        await send_signal(next_period, current_prediction, current_numbers, bet, current_win_rate, current_pattern)
                        
                        last_processed_id = current_id
                        logger.info(f"Signal sent for Period {next_period}")
                
                await asyncio.sleep(3)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(5)

# --- Flask Routes ---
@app.route('/')
def home():
    return "✅ TK Club Bot is Running!"

@app.route('/start')
def start():
    def run_bot():
        asyncio.run(main_loop())
    
    thread = threading.Thread(target=run_bot)
    thread.daemon = True
    thread.start()
    return "🤖 Bot Started Successfully!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FixedBot')

bot = Bot(token=BOT_TOKEN)

# --- Prediction Logic ---
def predict_trend(history):
    if not history or len(history) < 5:
        return 'BIG', "90%", "🎲 AI STARTING"
    
    recent_5 = history[:5]
    big_count = sum(1 for n in recent_5 if n >= 5)
    
    if big_count >= 4:
        return 'BIG', "95%", "🔥 DRAGON RUN"
    elif big_count <= 1:
        return 'SMALL', "95%", "🔥 DRAGON RUN"
    elif big_count >= 3:
        return 'BIG', "88%", "📈 TREND"
    else:
        return 'SMALL', "88%", "📈 TREND"

def generate_numbers(prediction, history):
    pool = [5, 6, 7, 8, 9] if prediction == 'BIG' else [0, 1, 2, 3, 4]
    
    if not history or len(history) < 5:
        return sorted(random.sample(pool, 2))
    
    recent = history[:10]
    matched = [n for n in recent if n in pool]
    
    if matched:
        counts = Counter(matched)
        hot = [num for num, _ in counts.most_common()]
        if len(hot) >= 2:
            return sorted(hot[:2])
        elif len(hot) == 1:
            remaining = [n for n in pool if n != hot[0]]
            return sorted([hot[0], random.choice(remaining)])
    
    return sorted(random.sample(pool, 2))

# --- Message Functions ---
async def send_signal(period, prediction, numbers, bet, win_rate, pattern):
    current_time = datetime.now().strftime("%I:%M:%S %p")
    pred_emoji = '🟢' if prediction == 'BIG' else '🔴'
    
    message = f"""
🎰 <b>TK CLUB 30S SIGNAL</b>
━━━━━━━━━━━━━━━━━━━━━━━━
🕐 <b>TIME:</b> <code>{current_time}</code>
📅 <b>PERIOD:</b> <code>{period}</code>

{pred_emoji} <b>PREDICTION:</b> <b>{prediction}</b>
🎯 <b>CONFIDENCE:</b> <code>{win_rate}</code>

🎲 <b>LUCKY NUMBERS:</b>
<code>┌───────┐</code>
<code>│   {numbers[0]}   │</code>
<code>└───────┘</code>
<code>┌───────┐</code>
<code>│   {numbers[1]}   │</code>
<code>└───────┘</code>

💰 <b>BET:</b> <code>{bet} TK</code>
📈 <b>PROFIT:</b> <code>{bet * 0.95:.2f} TK</code>

🧠 <b>PATTERN:</b> <i>{pattern}</i>
━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>STATS:</b>
├ Wins: <code>{win_count}</code>
├ Losses: <code>{loss_count}</code>
└ Profit: <code>{session_profit:.2f} TK</code>
━━━━━━━━━━━━━━━━━━━━━━━━
♻️ <b>AMVIPTEAM</b>
"""
    
    try:
        await bot.send_message(CHANNEL_USERNAME, message, parse_mode=ParseMode.HTML)
        logger.info(f"Signal sent: Period {period}")
        return True
    except RetryAfter as e:
        logger.warning(f"Rate limited, waiting {e.retry_after}s")
        await asyncio.sleep(e.retry_after)
        await bot.send_message(CHANNEL_USERNAME, message, parse_mode=ParseMode.HTML)
        return True
    except Exception as e:
        logger.error(f"Signal error: {e}")
        return False

async def send_result(period, number, won, jackpot, bet_amount):
    actual_size = 'BIG' if number >= 5 else 'SMALL'
    
    if jackpot:
        emoji = '👑'
        title = 'JACKPOT!'
        profit = bet_amount * 2.5
    elif won:
        emoji = '✅'
        title = 'WIN!'
        profit = bet_amount * 0.95
    else:
        emoji = '❌'
        title = 'LOSS'
        profit = -bet_amount
    
    msg = f"""
{emoji} <b>{title}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
📅 <b>PERIOD:</b> <code>{period}</code>
🔢 <b>NUMBER:</b> <code>{number}</code>
📊 <b>RESULT:</b> <code>{actual_size}</code>
💰 <b>BET:</b> <code>{bet_amount} TK</code>
💵 <b>PROFIT:</b> <code>{profit:.2f} TK</code>
━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    try:
        await bot.send_message(CHANNEL_USERNAME, msg, parse_mode=ParseMode.HTML)
        sticker = JACKPOT_STICKER if jackpot else (WIN_STICKER if won else LOSS_STICKER)
        await bot.send_sticker(CHANNEL_USERNAME, sticker)
    except Exception as e:
        logger.error(f"Result error: {e}")

async def send_report():
    global recent_signals_history
    
    if not recent_signals_history:
        return
    
    win_rate = (win_count / (win_count + loss_count) * 100) if (win_count + loss_count) > 0 else 0
    
    report = f"""
📊 <b>TK CLUB REPORT</b>
━━━━━━━━━━━━━━━━━━━━━━━━
✅ <b>WINS:</b> <code>{win_count}</code>
❌ <b>LOSSES:</b> <code>{loss_count}</code>
👑 <b>JACKPOTS:</b> <code>{jackpot_count}</code>
📈 <b>WIN RATE:</b> <code>{win_rate:.1f}%</code>
💰 <b>PROFIT:</b> <code>{session_profit:.2f} TK</code>

<b>LAST 10:</b>
"""
    
    for idx, item in enumerate(recent_signals_history, 1):
        emoji = '✅' if item['status'] == 'WIN' else '❌'
        report += f"{idx}. {item['period']} | {item['pred']} → {item['act_num']} {emoji}\n"
    
    report += "━━━━━━━━━━━━━━━━━━━━━━━━"
    
    try:
        sent = await bot.send_message(CHANNEL_USERNAME, report, parse_mode=ParseMode.HTML)
        await bot.pin_chat_message(CHANNEL_USERNAME, sent.message_id)
        logger.info("Report sent and pinned")
    except Exception as e:
        logger.error(f"Report error: {e}")
    
    recent_signals_history = []

# --- Main Function with Multiple API Support ---
async def fetch_data(session):
    """Try multiple API URLs"""
    for url in API_URLS:
        try:
            logger.info(f"Trying API: {url}")
            async with session.get(
                url,
                headers=HEADERS,
                ssl=SSL_CONTEXT,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                logger.info(f"API Status: {response.status} for {url}")
                
                if response.status == 200:
                    text = await response.text()
                    data = json.loads(text)
                    
                    if data.get('data') and data['data'].get('list'):
                        history_list = data['data']['list']
                        logger.info(f"✅ Got {len(history_list)} records from {url}")
                        return history_list
                else:
                    logger.warning(f"❌ {url} returned status {response.status}")
                    
        except Exception as e:
            logger.warning(f"❌ {url} failed: {e}")
            continue
    
    logger.error("❌ All APIs failed!")
    return None

async def process_result(actual_number, period):
    global win_count, loss_count, jackpot_count, total_predictions, loss_streak, session_profit
    
    if not current_prediction:
        return
    
    total_predictions += 1
    actual_size = 'BIG' if actual_number >= 5 else 'SMALL'
    is_win = (actual_size == current_prediction)
    is_jackpot = (actual_number in current_numbers)
    
    bet_amount = BET_PROGRESSION[min(loss_streak, len(BET_PROGRESSION) - 1)]
    
    if is_jackpot or is_win:
        win_count += 1
        profit = bet_amount * (2.5 if is_jackpot else 0.95)
        session_profit += profit
        loss_streak = 0
        if is_jackpot:
            jackpot_count += 1
        status = 'WIN'
    else:
        loss_count += 1
        session_profit -= bet_amount
        loss_streak += 1
        status = 'LOSS'
    
    await send_result(period, actual_number, is_win, is_jackpot, bet_amount)
    
    recent_signals_history.append({
        'period': period,
        'pred': current_prediction,
        'act_num': actual_number,
        'status': status
    })
    
    if len(recent_signals_history) >= 10:
        await send_report()

async def main_loop():
    global last_processed_id, current_prediction, current_numbers, current_win_rate, current_pattern, loss_streak
    
    print("🚀 TK Club 30s Bot Started")
    
    try:
        me = await bot.get_me()
        print(f"✅ Bot connected: @{me.username}")
    except Exception as e:
        print(f"❌ Bot connection failed: {e}")
        return
    
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        print(f"✅ Channel: {chat.title}")
    except Exception as e:
        print(f"❌ Channel access failed: {e}")
        return
    
    async with aiohttp.ClientSession() as session:
        test_data = await fetch_data(session)
        if test_data:
            print(f"✅ API working! Got {len(test_data)} records")
        else:
            print("❌ All APIs failed! Retrying in 30 seconds...")
            await asyncio.sleep(30)
            # Retry logic
            retry_count = 0
            while retry_count < 5 and not test_data:
                test_data = await fetch_data(session)
                if not test_data:
                    retry_count += 1
                    print(f"Retry {retry_count}/5 failed. Waiting 30s...")
                    await asyncio.sleep(30)
            if not test_data:
                print("❌ API still not working. Exiting...")
                return
        
        while True:
            try:
                history = await fetch_data(session)
                
                if history:
                    latest = history[0]
                    current_id = latest['issueNumber']
                    current_number = int(latest['number'])
                    
                    if last_processed_id is None or current_id != last_processed_id:
                        
                        if last_processed_id:
                            await process_result(current_number, last_processed_id)
                        
                        history_nums = [int(item['number']) for item in history[:20] if item.get('number')]
                        
                        if history_nums:
                            current_prediction, current_win_rate, current_pattern = predict_trend(history_nums)
                            current_numbers = generate_numbers(current_prediction, history_nums)
                            
                            next_period = str(int(current_id) + 1)
                            bet = BET_PROGRESSION[min(loss_streak, len(BET_PROGRESSION) - 1)]
                            
                            await send_signal(next_period, current_prediction, current_numbers, bet, current_win_rate, current_pattern)
                            
                            last_processed_id = current_id
                            logger.info(f"Signal sent for Period {next_period}")
                        else:
                            logger.error("No valid numbers in history")
                
                await asyncio.sleep(5)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(10)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
        print(f"✅ Wins: {win_count}")
        print(f"❌ Losses: {loss_count}")
        print(f"💰 Profit: {session_profit:.2f} TK")
