import os
import re
import time
import random
import requests
import hashlib
import sqlite3
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Настройки
TWITTER_USERS = [
    'openai', 'aicoin_eth', 'whale_alert', 'bitcoinmagazine', 'rovercrc',
    'cryptobeastreal', 'bitcoin', 'cryptojack', 'watcherguru',
    'ali_charts', 'WuBlockchain', 'CryptoMichNL', 'rektcapital', 'glassnode',
    'intocryptoverse', 'woonomic', 'cryptoquant_com', 'Lookonchain', 'ToneVays',
    'ashcryptoreal'
]
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MAX_TWEETS_PER_USER = 3

bot = Bot(token=TELEGRAM_BOT_TOKEN)
last_post_times = {}
DB_FILE = 'posted.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS posted_hashes (
            hash TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def is_hash_posted(text_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT 1 FROM posted_hashes WHERE hash = ?', (text_hash,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def mark_hash_as_posted(text_hash):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO posted_hashes (hash) VALUES (?)', (text_hash,))
    conn.commit()
    conn.close()

def get_text_hash(text):
    return hashlib.sha256(text.strip().lower().encode('utf-8')).hexdigest()

def clean_text(text):
    if '· ' in text:
        text = text.split('· ', 1)[1]

    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\b\d+[kKmM]?\b', '', text)
    text = text.replace('\u2026', '').replace('...', '')
    text = re.sub(r'\b(reposted|retweeted)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'@\w+', '', text)
    text = re.sub(r'\b(Bitcoin Magazine|BitcoinConfAsia)\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(\b\w+\b)( \1\b)+[\s\u00B7\u00B7]*', r'\1 ', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(\w+)( \1)+\b', r'\1', text, flags=re.IGNORECASE)
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

def send_to_telegram(original_text, cleaned_text, image_urls, user):
    text_hash = get_text_hash(cleaned_text)
    if not cleaned_text or len(cleaned_text) < 10:
        print("[-] Пропущено: слишком короткий или пустой текст")
        return
    if len(cleaned_text) > 1024 or contains_link_or_dots(cleaned_text) or is_retweet(cleaned_text):
        print("[-] Сообщение отфильтровано")
        return
    if is_hash_posted(text_hash):
        print("[-] Сообщение уже отправлено ранее, пропускаем")
        return

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
            media[0].caption = cleaned_text
            bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media)
        else:
            bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=cleaned_text)

        print(f"[+] Отправлено сообщение: {cleaned_text[:60]}...")
        mark_hash_as_posted(text_hash)
    except Exception as e:
        print(f"Ошибка при отправке в Telegram: {e}")
    finally:
        for file, path in opened_files:
            file.close()
            os.remove(path)

def should_skip_user(user):
    last_time = last_post_times.get(user)
    return last_time and time.time() - last_time < 900  # 15 минут

def process_tweets():
    random.shuffle(TWITTER_USERS)
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
                    cleaned = clean_text(content)
                    images = [img.get('src') for img in soup.find_all('img') if 'profile_images' not in img.get('src') and 'emoji' not in img.get('src')]

                    timestamp_tag = soup.find('time')
                    if timestamp_tag and timestamp_tag.has_attr('datetime'):
                        tweet_time = datetime.strptime(timestamp_tag['datetime'], '%Y-%m-%dT%H:%M:%S.000Z')
                        if tweet_time < datetime.utcnow() - timedelta(hours=5):
                            print(f"[-] Пропущен старый твит от {user}")
                            continue

                    send_to_telegram(content, cleaned, images, user)
                    new_posts_found = True
                    time.sleep(random.randint(45, 90))

                if new_posts_found:
                    last_post_times[user] = time.time()

            except PlaywrightTimeoutError:
                print(f"[!] Превышено время ожидания для пользователя: {user}")
            except Exception as e:
                print(f"[!] Ошибка при обработке пользователя {user}: {e}")

        browser.close()

if __name__ == "__main__":
    print(f"\n===== Запуск сканирования: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC =====")
    init_db()
    process_tweets()
    print("[✓] Завершено.")
