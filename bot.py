import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import os
import requests
from flask import Flask, request, jsonify
import threading
import asyncio

# Налаштування Flask
app = Flask(__name__)

# Налаштування бота Discord
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None  # Вимкнути стандартну команду допомоги
)

# Конфігураційні константи
CONFIG_FILE = "config.cfg"

def load_config():
    """Завантажити конфігурацію з файлу config.cfg"""
    if not os.path.exists(CONFIG_FILE):
        create_config_file()

    config = {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f.readlines():
            line = line.strip()
            if line.startswith("STEAM_API_KEY="):
                config["STEAM_API_KEY"] = line.split("=")[1]
            elif line.startswith("DISCORD_API_KEY="):
                config["DISCORD_API_KEY"] = line.split("=")[1]
            elif line.startswith("ALLOWED_CHANNEL_ID="):
                config["ALLOWED_CHANNEL_ID"] = int(line.split("=")[1])

    return config

def create_config_file():
    """Створити файл конфігурації, якщо його немає"""
    print("Файл конфігурації не знайдено. Створюємо новий файл та запитуємо необхідні дані.")
    
    # Перевірка на наявність правильних значень для кожного ключа
    steam_api_key = input("Введіть ваш Steam API Key: ")
    discord_api_key = input("Введіть ваш Discord API Token: ")
    allowed_channel_id = input("Введіть ID вашого Discord каналу: ")

    # Перевіряємо, чи введені всі дані
    if not steam_api_key or not discord_api_key or not allowed_channel_id:
        print("Всі поля повинні бути заповнені! Завершення.")
        exit()  # Зупиняємо програму, якщо є пропущені поля

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(f"STEAM_API_KEY={steam_api_key}\n")
            f.write(f"DISCORD_API_KEY={discord_api_key}\n")
            f.write(f"ALLOWED_CHANNEL_ID={allowed_channel_id}\n")

        print(f"Файл конфігурації створено успішно: {CONFIG_FILE}. Тепер запустіть програму знову.")
    except Exception as e:
        print(f"Сталася помилка при створенні конфігураційного файлу: {e}")
        exit()

def get_steam_nickname(steam_id, steam_api_key):
    """Отримати нікнейм Steam за SteamID64"""
    url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={steam_api_key}&steamids={steam_id}"
    try:
        response = requests.get(url)
        data = response.json()
        return data['response']['players'][0]['personaname']
    except:
        return "Невідомий нікнейм"

def load_data():
    """Завантажити дані з data.cfg"""
    data = {"groups": [], "admins": []}
    if os.path.exists("data.cfg"):
        with open("data.cfg", "r", encoding="utf-8") as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("Group="):
                    data["groups"].append(line)
                elif line.startswith("Admin="):
                    parts = line.split(" // ")
                    steam_part = parts[0].split("=")[1]
                    steam_id, group = steam_part.split(":")
                    nickname = parts[1] if len(parts) > 1 else "Невідомий"
                    expires = parts[2] if len(parts) > 2 else datetime.now().isoformat()
                    data["admins"].append({
                        "steam_id": steam_id,
                        "group": group,
                        "nickname": nickname,
                        "expires": expires
                    })
    return data

def save_data(data):
    """Зберегти дані у data.cfg"""
    with open("data.cfg", "w", encoding="utf-8") as f:
        for group in data["groups"]:
            f.write(f"{group}\n")
        for admin in data["admins"]:
            line = f"Admin={admin['steam_id']}:{admin['group']} // {admin['nickname']} // {admin['expires']}"
            f.write(f"{line}\n")

# Веб-хук
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        content = request.json
        steam_id = str(content.get("steam_id"))
        discord_user_id = str(content.get("user_id"))

        config = load_config()  # Завантажуємо конфігурацію
        steam_api_key = config["STEAM_API_KEY"]
        discord_api_key = config["DISCORD_API_KEY"]
        allowed_channel_id = config["ALLOWED_CHANNEL_ID"]

        data = load_data()
        nickname = get_steam_nickname(steam_id, steam_api_key)
        expires = (datetime.now() + timedelta(days=3)).isoformat()
        
        new_admin = {
            "steam_id": steam_id,
            "group": "Seeder",
            "nickname": nickname,
            "expires": expires
        }
        data["admins"].append(new_admin)
        save_data(data)

        # Відправка повідомлення у вказаний канал
        message = f"Admin={steam_id}:Seeder // {nickname} // {expires}"
        asyncio.run_coroutine_threadsafe(
            send_to_channel(message, discord_api_key, allowed_channel_id),
            bot.loop
        )

        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

async def send_to_channel(message, discord_api_key, allowed_channel_id):
    """Надсилання повідомлення у дозволений канал"""
    channel = bot.get_channel(allowed_channel_id)
    if channel:
        await channel.send(message)

# Блокування всіх повідомлень/команд поза дозволеним каналом
@bot.check
async def channel_check(ctx):
    return ctx.channel.id == allowed_channel_id

@bot.event
async def on_message(message):
    """Ігнорувати всі повідомлення поза дозволеним каналом"""
    if message.channel.id != allowed_channel_id:
        return
    await bot.process_commands(message)

# Фонова задача для очистки
@tasks.loop(hours=1)
async def check_expired():
    try:
        data = load_data()
        now = datetime.now()
        data["admins"] = [
            admin for admin in data["admins"]
            if datetime.fromisoformat(admin["expires"]) > now
        ]
        save_data(data)
    except Exception as e:
        print(f"Помилка очистки: {e}")

# Події бота
@bot.event
async def on_ready():
    print(f"Бот {bot.user} активовано!")
    check_expired.start()

# Запуск сервера Flask у потоці
threading.Thread(
    target=lambda: app.run(
        host="0.0.0.0",
        port=5054,
        debug=False,
        use_reloader=False
    )
).start()

# Запуск бота
if __name__ == "__main__":
    config = load_config()  # Завантажуємо конфігурацію
    bot.run(config["DISCORD_API_KEY"])
