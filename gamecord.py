import os
import sys
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
import discord
from discord.ext import commands

# === 時間制限設定 ===
now = datetime.utcnow() + timedelta(hours=9)
current_hour = now.hour
if not (current_hour >= 12 or current_hour < 4):
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Bot is outside operating hours. Shutting down.")
    #sys.exit(0)

# === Discord Bot 基本設定 ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# === 環境変数読み込み ===
load_dotenv()
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Environment variable DISCORD_TOKEN is not set.")

# === quizkingの機能（関数・コマンド）を読み込む ===
from quizking import setup_quizking
setup_quizking(bot)

# === minitankの機能（関数・コマンド）を読み込む ===
from tankbattle import setup_tankbattle
setup_tankbattle(bot)

# === Bot起動イベント ===
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} は起動しました")

bot.run(token)
