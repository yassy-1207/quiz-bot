import os
import sys
import asyncio
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands

# === 時間制限設定 ===
now = datetime.utcnow() + timedelta(hours=9)
current_hour = now.hour
if not (current_hour >= 12 or current_hour < 4):
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Bot is outside operating hours. Shutting down.")
    sys.exit(0)

# === Discord Bot 基本設定 ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

class GameCordBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="/", intents=intents)
        
    async def setup_hook(self):
        await self.tree.sync()
        print("Command tree synced")

bot = GameCordBot()

# === 環境変数読み込み ===
load_dotenv()
token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Environment variable DISCORD_TOKEN is not set.")

# === quizkingの機能（関数・コマンド）を読み込む ===
from quizking import setup_quizking
setup_quizking(bot)

# === tankbattleの機能（関数・コマンド）を読み込む ===
from tankbattle import setup_tankbattle
setup_tankbattle(bot)

# === werewolfの機能（関数・コマンド）を読み込む ===
#from werewolf import setup_werewolf
#setup_werewolf(bot)

# === ルール表示コマンド ===
@bot.tree.command(name="ルール", description="各ゲームのルールを表示します")
@discord.app_commands.describe(game="対象ゲーム名を選んでください")
@discord.app_commands.choices(game=[
    discord.app_commands.Choice(name="クイズ", value="quiz"),
    discord.app_commands.Choice(name="ミニ戦車バトル", value="tank"),
    discord.app_commands.Choice(name="人狼（準備中）", value="werewolf")
])
async def rule(interaction: discord.Interaction, game: str):
    if game == "quiz":
        text = (
            "📚 **クイズのルール**\n"
            "- カテゴリと難易度を選んでクイズを出題！\n"
            "- 参加者全員で競い合い、最も正解数が多い人が勝利。\n"
            "- 制限時間内に答えないと不正解になるよ。\n"
        )
    elif game == "tank":
        text = (
            "🔫 **ミニ戦車バトルのルール**\n"
            "- 2人1対1でターン制バトル。\n"
            "- 毎ターン、5つのコマンドから1つを選択：\n"
            "  ・バリア（全攻撃を無効、連続不可）\n"
            "  ・チャージ（攻撃のためのエネルギーを蓄積）\n"
            "  ・1～3チャージ発射（チャージ量に応じた攻撃）\n"
            "- HPが0になったら敗北！DMで選択、非公開バトル！"
        )
    elif game == "werewolf":
        text = (
            "🐺 **人狼ゲーム（準備中）**\n"
            "- 参加者にランダムで役職が割り振られます。\n"
            "- 昼に議論、夜に人狼が行動。\n"
            "- 生き残るのは村人か人狼か！？（詳細は後日）"
        )
    else:
        text = "❌ 不明なゲーム名です。"

    await interaction.response.send_message(text, ephemeral=True)


# === Bot起動イベント ===
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} は起動しました")

bot.run(token)
