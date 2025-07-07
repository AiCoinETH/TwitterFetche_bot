import os
import re
import time
import random
import requests
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Настройки
TWITTER_USERS = ['openai', 'aicoin_eth', 'whale_alert', 'bitcoinmagazine', 'rovercrc', 'cryptobeastreal', 'bitcoin', 'cryptojack', 'watcherguru']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MAX_TWEETS_PER_USER = 3
POSTED_TEXTS_FILE = 'posted_texts.json'
POSTED_TEXTS_EXPIRY_DAYS = 2

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Загрузка истории отправленных сообщений
if os.path.exists(POSTED_TEXTS_FILE):
    with open(POSTED_TEXTS_FILE, 'r') as f:
        try:
            posted_texts = json.load(f)
            if isinstance(posted_texts, list):
                posted_texts = {item['text']: item['timestamp'] for item in posted_texts if isinstance(item, dict)}
        except json.JSONDecodeError:
            posted_texts = {}
else:
    posted_texts = {}

last_post_times = {}

def save_posted_texts():
    now = time.time()
    filtered = [
        {"text": text, "timestamp": timestamp}
        for text, timestamp in posted_texts.items()
        if now - timestamp < POSTED_TEXTS_EXPIRY_DAYS * 86400
    ]
    with open(POSTED_TEXTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)

def clean_text(text):
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\b\d+[kKmM]?\b', '', text)
    text = text.replace('\u2026', '')
    text = text.replace('...', '')

    text = re.sub(r'\b(reposted|retweeted)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'\b(Bitcoin Magazine|BitcoinConfAsia)\b', '', text, flags=re.IGNORECASE)

    # Удалить повторы слов в начале (например: "Crypto Rover Crypto Rover ·")
    text = re.sub(r'^(\b\w+\b)( \1\b)+[\s·]*', r'\1 ', text, flags=re.IGNORECASE)

    text = re.sub(r'\s+', ' ', text)
    text = ' '.join(word for word in text.split() if not word.startswith('#'))
    return text.strip()

def contains_link_or_dots(text):
    return (
        'http://' in text or
        'https://' in text or
        '...' in text or
        '\u2026' in text or
        text.strip().endswith('.') or
        text.strip().endswith('…')
    )

def is_retweet(text):
    return text.startswith("Retweeted") or text.startswith("@")

def download_image(url, filename):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return filename
    except Exception as e:
        print(f"Ошибка при загрузке изображения: {e}")
    return None

def send_to_telegram(text, image_urls):
    now = time.time()
    text = clean_text(text)

    if len(text) > 1024 or not text.strip() or contains_link_or_dots(text) or is_retweet(text):
        return

    if text in posted_texts and now - posted_texts[text] < POSTED_TEXTS_EXPIRY_DAYS * 86400:
        return

    posted_texts[text] = now
    save_posted_texts()

    media = []
    opened_files = []

    for idx, url in enumerate(image_urls):
        filename = f'image_{idx}.jpg'
        path = download_image(url, filename)
        if path:
            file = open(path, 'rb')
            opened_files.append((file, path))
            media.append(InputMediaPhoto(file))

    try:
        if media:
            media[0].caption = text
            bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media)
        else:
            bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text)
    except Exception as e:
        print(f"Ошибка при отправке в Telegram: {e}")
    finally:
        for file, path in opened_files:
            file.close()
            os.remove(path)

def should_skip_user(user):
    last_time = last_post_times.get(user)
    if last_time and time.time() - last_time < 3600:
        return True
    return False

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    for user in TWITTER_USERS:
        if should_skip_user(user):
            print(f"[-] Пропускаем {user}, недавно публиковали.")
            continue

        try:
            page.goto(f'https://twitter.com/{user}')
            page.wait_for_timeout(5000)
            page.wait_for_selector('article', timeout=30000)
            tweets = page.query_selector_all('article')[:MAX_TWEETS_PER_USER]

            new_posts_found = False

            for tweet in tweets:
                html = tweet.inner_html()
                soup = BeautifulSoup(html, 'html.parser')
                content = ' '.join([el.get_text() for el in soup.find_all('span')])
                images = [img.get('src') for img in soup.find_all('img') if 'profile_images' not in img.get('src') and 'emoji' not in img.get('src')]

                send_to_telegram(content, images)
                new_posts_found = True
                time.sleep(random.randint(45, 90))

            if new_posts_found:
                last_post_times[user] = time.time()

        except PlaywrightTimeoutError:
            print(f"[!] Превышено время ожидания для пользователя: {user}")
        except Exception as e:
            print(f"[!] Ошибка при обработке пользователя {user}: {e}")

    browser.close()
