from dotenv import load_dotenv
import discord
from discord.ext import commands
import random
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from collections import Counter

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# .env読み込み
load_dotenv()
# JSONファイルからクイズ問題を読み込む
QUIZ_FILE = "questions.json"
if os.path.exists(QUIZ_FILE):
    with open(QUIZ_FILE, "r", encoding="utf-8") as f:
        quiz_data = json.load(f)
else:
    quiz_data = []

# 各種ステート管理
date_scores = {}           # 日付ごとの累積スコア
tmp_sessions = {}         # 実行中セッションフラグ
tmp_participants = {}     # 参加者リスト
tmp_ready = {}            # 開始準備フラグ
tmp_settings = {}         # クイズ設定保存 {channel_id: {category, difficulty, count}}

# 定数
MAX_COUNT = 50
DEFAULT_TIMEOUT = 15  # 秒

def get_today_key():
    return datetime.now().strftime("%Y-%m-%d")

# カテゴリ候補取得
def get_categories():
    cats = sorted({q.get("category", "未分類") for q in quiz_data})
    return ["全カテゴリ"] + cats

# 難易度候補取得
def get_difficulties():
    return ["初級", "中級", "上級"]

# ビュー: 参加＆締切ボタン
class QuizSetupView(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = interaction.user.id
        lst = tmp_participants.setdefault(self.channel_id, set())
        lst.add(uid)
        await interaction.response.send_message(f"✅ {interaction.user.mention} が参加登録されました", ephemeral=True)

    @discord.ui.button(label="締切・開始する", style=discord.ButtonStyle.success)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        cid = self.channel_id
        # 必要設定取得
        settings = tmp_settings.get(cid)
        if not settings:
            await interaction.response.send_message("❌ 設定情報が見つかりません。再度/くいずを実行してください。", ephemeral=True)
            return
        # 参加締切
        tmp_ready[cid] = True
        await interaction.response.send_message("🚀 参加締切＆クイズ開始します！", ephemeral=False)
        # 開始
        await run_quiz(interaction.channel, **settings)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} は起動しました")

# /くいず コマンド: 設定 + 参加ボタン表示
@bot.tree.command(name="くいず", description="カテゴリ・難易度・問題数を指定してクイズを準備")
@discord.app_commands.describe(
    category="出題カテゴリ",
    difficulty="難易度",
    count="問題数（最大50問）"
)
@discord.app_commands.choices(
    category=[discord.app_commands.Choice(name=c, value=c) for c in get_categories()],
    difficulty=[discord.app_commands.Choice(name=d, value=d) for d in get_difficulties()]
)
async def quiz(interaction: discord.Interaction, category: str, difficulty: str, count: int = 5):
    cid = interaction.channel.id
    # 実行中チェック
    if tmp_sessions.get(cid):
        await interaction.response.send_message("⚠️ 既に実行中のクイズがあります。", ephemeral=True)
        return
    # パラチェック
    if count < 1 or count > MAX_COUNT:
        await interaction.response.send_message(f"⚠️ 問題数は1〜{MAX_COUNT}の範囲で指定してください。", ephemeral=True)
        return
    # 設定保存
    tmp_settings[cid] = {"category": category, "difficulty": difficulty, "count": count}
    tmp_participants[cid] = set()
    tmp_ready[cid] = False
    # 参加ボタン送信
    view = QuizSetupView(cid)
    await interaction.response.send_message(
        f"🎯 クイズ準備中: カテゴリ='{category}', 難易度='{difficulty}', 問数={count}\n参加する方は下をクリック。準備が整ったら'締切・開始する'でスタート。",
        view=view
    )

# 実際のクイズ実行ルーチン
async def run_quiz(channel: discord.TextChannel, category: str, difficulty: str, count: int):
    cid = channel.id
    # フラグ立て
    tmp_sessions[cid] = True
    # 設定参照
    qs = quiz_data
    if category != "全カテゴリ":
        qs = [q for q in qs if q.get("category") == category]
    qs = [q for q in qs if q.get("difficulty") == difficulty]
    if not qs:
        await channel.send(f"❌ 問題が見つかりません (カテゴリ='{category}', 難易度='{difficulty}')")
        tmp_sessions.pop(cid, None)
        return
    # 出題
    questions = random.sample(qs, k=min(count, len(qs)))
    scores = {}
    # 選択者リスト
    participants = tmp_participants.get(cid, set())
    # 一問ずつ
    for i, q in enumerate(questions, 1):
        # 途中中断?
        if not tmp_ready.get(cid):
            await channel.send("🛑 クイズが中断されました。")
            tmp_sessions.pop(cid, None)
            return
        await channel.send(f"**第{i}問/{count}問**\n{q['question']}\n⏰ {DEFAULT_TIMEOUT}秒で回答")
        def check(m):
            return m.channel.id == cid and m.author.id in participants and m.content.strip() == q['answer']
        try:
            msg = await bot.wait_for('message', timeout=DEFAULT_TIMEOUT, check=check)
            scores[msg.author.id] = scores.get(msg.author.id, 0) + 1
            await channel.send(f"🎉 {msg.author.mention} 正解！")
        except asyncio.TimeoutError:
            await channel.send(f"⏰ 時間切れ！ 正解は「{q['answer']}」でした。")
    # 結果発表
    tmp_sessions.pop(cid, None)
    tmp_ready.pop(cid, None)
    tmp_participants.pop(cid, None)
    if scores:
        sorted_list = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        text = "\n".join([f"<@{uid}>: {pts}点" for uid, pts in sorted_list])
        await channel.send(f"🏁 このセッションの結果：\n{text}")
    else:
        await channel.send("😢 正解者なしでした。")

# 中断コマンド
@bot.tree.command(name="中断", description="クイズを中断します")
async def cancel(interaction: discord.Interaction):
    cid = interaction.channel.id
    if tmp_sessions.get(cid):
        tmp_ready[cid] = False
        tmp_sessions.pop(cid, None)
        await interaction.response.send_message("🛑 クイズを中断しました。", ephemeral=False)
    else:
        await interaction.response.send_message("⚠️ 実行中のクイズがありません。", ephemeral=True)

# その他コマンド省略…

token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("Environment variable DISCORD_TOKEN is not set.")
# 日本時間での現在時刻を取得（UTC+9）
now = datetime.utcnow() + timedelta(hours=9)
current_hour = now.hour

# 許可された時間（13時〜翌4時）以外なら即終了
if not (13 <= current_hour or current_hour < 4):
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Bot is outside operating hours. Shutting down.")
    sys.exit()

bot.run(token)
