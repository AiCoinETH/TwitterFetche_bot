import os
import re
import requests
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto
from playwright.sync_api import sync_playwright

# Настройки
TWITTER_USERS = ['ashcryptoreal', 'cointelegraph', 'senseibr_btc', 'cryptobeastreal', 'rovercrc', 'bitcoinmagazine', 'whale_alert', 'aicoin_eth', 'aicoin_eth', 'openai']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MAX_TWEETS_PER_USER = 3

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def clean_text(text):
    text = re.sub(r'\b\d+[kKmM]?\b', '', text)  # Удаляет изолированные числа (включая 1.5k, 7M и т.п.)
    return ' '.join(word for word in text.split() if not word.startswith('#'))

def download_image(url, filename):
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename
    return None

def send_to_telegram(text, image_urls):
    if len(text) > 1024:
        return  # Пропускаем слишком длинные посты

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
    page = browser.new_page()

    for user in TWITTER_USERS:
        page.goto(f'https://twitter.com/{user}')
        page.wait_for_selector('article')
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

    browser.close()
