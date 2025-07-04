import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto
from playwright.sync_api import sync_playwright

# Настройки
TWITTER_USERS = ['openai',  'aicoin_eth',  'whale_alert',  'bitcoinmagazine',  'rovercrc',  'cryptobeastreal']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MAX_TWEETS_PER_USER = 3

bot = Bot(token=TELEGRAM_BOT_TOKEN)

posted_texts = set()

def clean_text(text):
    text = re.sub(r'https?://\S+', '', text)  # Удаляет ссылки
    text = re.sub(r'\b\d+[kKmM]?\b', '', text)  # Удаляет изолированные числа
    text = text.replace('\u2026', '')  # Удаляет троеточия из Unicode (…)
    text = text.replace('...', '')  # Удаляет обычные троеточия
    return ' '.join(word for word in text.split() if not word.startswith('#'))

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
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename
    return None

def send_to_telegram(text, image_urls):
    if len(text) > 1024 or not text.strip() or contains_link_or_dots(text) or is_retweet(text) or text in posted_texts:
        return  # Пропускаем неподходящие или повторяющиеся посты

    posted_texts.add(text)
    media = []
    opened_files = []

    for idx, url in enumerate(image_urls):
        filename = f'image_{idx}.jpg'
        path = download_image(url, filename)
        if path:
            file = open(path, 'rb')
            opened_files.append((file, path))
            media.append(InputMediaPhoto(file))

    if media:
        media[0].caption = text  # Текст прикрепляется к первой картинке
        bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media)
    else:
        bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text)

    for file, path in opened_files:
        file.close()
        os.remove(path)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    for user in TWITTER_USERS:
        page.goto(f'https://twitter.com/{user}')
        page.wait_for_timeout(5000)  # Дать странице загрузиться
        page.wait_for_selector('article', timeout=300000)  # Увеличен таймаут до 5 минут
        tweets = page.query_selector_all('article')[:MAX_TWEETS_PER_USER]

        for tweet in tweets:
            html = tweet.inner_html()
            soup = BeautifulSoup(html, 'html.parser')
            content = ' '.join([el.get_text() for el in soup.find_all('span')])
            text = clean_text(content)

            images = []
            for img in soup.find_all('img'):
                src = img.get('src')
                if 'profile_images' not in src and 'emoji' not in src:
                    images.append(src)

            send_to_telegram(text, images)
            time.sleep(random.randint(45, 90))  # Перерыв между публикациями

    browser.close()
