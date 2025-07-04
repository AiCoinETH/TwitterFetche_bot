import os
import certifi
import requests
import snscrape.modules.twitter as sntwitter
from telegram import Bot, InputMediaPhoto

# Установка правильного пути к SSL-сертификатам
os.environ['SSL_CERT_FILE'] = certifi.where()

# === НАСТРОЙКИ ===
TWITTER_USERS = ['nasa', 'elonmusk']  # список пользователей
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MAX_TWEETS_PER_USER = 5  # количество твитов с одного аккаунта

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def clean_text(text):
    return ' '.join(word for word in text.split() if not word.startswith('#'))

def download_image(url, filename):
    response = requests.get(url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename
    return None

def send_to_telegram(text, image_urls):
    media = []
    for idx, url in enumerate(image_urls):
        filename = f'image_{idx}.jpg'
        path = download_image(url, filename)
        if path:
            media.append(InputMediaPhoto(open(path, 'rb')))

    if media:
        bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text)
        bot.send_media_group(chat_id=TELEGRAM_CHANNEL_ID, media=media)
        for m in media:
            m.media.close()
            os.remove(m.media.name)
    else:
        bot.send_message(chat_id=TELEGRAM_CHANNEL_ID, text=text)

for user in TWITTER_USERS:
    scraper = sntwitter.TwitterUserScraper(user)
    for i, tweet in enumerate(scraper.get_items()):
        if i >= MAX_TWEETS_PER_USER:
            break
        if tweet.content:
            text = clean_text(tweet.content)
            images = [media.fullUrl for media in tweet.media if hasattr(media, 'fullUrl')] if tweet.media else []
            send_to_telegram(text, images)
