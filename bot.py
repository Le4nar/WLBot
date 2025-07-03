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
DATA_FILE = "data.cfg"
STEAM_API_KEY = "steamkey"
ALLOWED_CHANNEL_ID = 134  # ID вашого каналу

def get_steam_nickname(steam_id):
    """Отримати нікнейм Steam за SteamID64"""
    url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={STEAM_API_KEY}&steamids={steam_id}"
    try:
        response = requests.get(url)
        data = response.json()
        return data['response']['players'][0]['personaname']
    except:
        return "Невідомий нікнейм"

def load_data():
    """Завантажити дані з data.cfg"""
    data = {"groups": [], "admins": []}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
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
    with open(DATA_FILE, "w", encoding="utf-8") as f:
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

        data = load_data()
        nickname = get_steam_nickname(steam_id)
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
            send_to_channel(message),
            bot.loop
        )

        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

async def send_to_channel(message):
    """Надсилання повідомлення у дозволений канал"""
    channel = bot.get_channel(ALLOWED_CHANNEL_ID)
    if channel:
        await channel.send(message)

# Блокування всіх повідомлень/команд поза дозволеним каналом
@bot.check
async def channel_check(ctx):
    return ctx.channel.id == ALLOWED_CHANNEL_ID

@bot.event
async def on_message(message):
    """Ігнорувати всі повідомлення поза дозволеним каналом"""
    if message.channel.id != ALLOWED_CHANNEL_ID:
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
        
# Додайте цей маршрут після інших Flask-ендпоінтів
@app.route("/config")
def get_config():
    """Повертає вміст data.cfg"""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return content, 200, {"Content-Type": "text/plain"}
    except FileNotFoundError:
        return "Файл не знайдено", 404

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
    bot.run("")
