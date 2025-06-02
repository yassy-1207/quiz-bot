# quizking.py

import os
import json
import random
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from dotenv import load_dotenv

# ======================================
# グローバル領域: データと定数の定義
# ======================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

# .env から読み込み
load_dotenv()

# JSONファイルからクイズ問題を読み込む
QUIZ_FILE = "questions.json"
if os.path.exists(QUIZ_FILE):
    with open(QUIZ_FILE, "r", encoding="utf-8") as f:
        quiz_data = json.load(f)
else:
    quiz_data = []

# 各種ステート管理
date_scores = {}        # 日付ごとの累積スコア（使っていない場合は残しておいてOK）
tmp_sessions = {}       # {channel_id: True} 実行中フラグ
tmp_participants = {}   # {channel_id: set(user_id)} 参加者IDの集合
tmp_ready = {}          # {channel_id: bool} 開始準備フラグ
tmp_settings = {}       # {channel_id: {"category": str, "difficulty": str, "count": int}}

# 定数
MAX_COUNT = 50
DEFAULT_TIMEOUT = 15  # 秒

# グローバル変数の定義
quiz_bot = None

def get_today_key():
    return datetime.now().strftime("%Y-%m-%d")

def get_categories():
    cats = sorted({q.get("category", "未分類") for q in quiz_data})
    return ["全カテゴリ"] + cats

def get_difficulties():
    return ["初級", "中級", "上級"]

# ======================================
# run_quiz 関数をグローバル定義
# ======================================
async def run_quiz(channel: discord.TextChannel, category: str, difficulty: str, count: int):
    cid = channel.id
    # フラグ立て
    tmp_sessions[cid] = True

    # 問題プールを絞り込み
    qs = quiz_data
    if category != "全カテゴリ":
        qs = [q for q in qs if q.get("category") == category]
    qs = [q for q in qs if q.get("difficulty") == difficulty]

    if not qs:
        await channel.send(f"❌ 問題が見つかりません (カテゴリ='{category}', 難易度='{difficulty}')")
        tmp_sessions.pop(cid, None)
        return

    # 出題数分ランダム抽出
    questions = random.sample(qs, k=min(count, len(qs)))
    scores = {}
    participants = tmp_participants.get(cid, set())

    for i, q in enumerate(questions, 1):
        # 途中中断チェック
        if not tmp_ready.get(cid):
            await channel.send("🛑 クイズが中断されました。")
            tmp_sessions.pop(cid, None)
            return

        # 問題を送信
        await channel.send(f"**第{i}問/{count}問**\n{q['question']}\n⏰ {DEFAULT_TIMEOUT}秒で回答")

        def check(m):
            return (
                m.channel.id == cid
                and m.author.id in participants
                and not m.author.bot
            )

        answered = False
        try:
            while not answered and tmp_ready.get(cid):
                try:
                    msg = await quiz_bot.wait_for('message', timeout=DEFAULT_TIMEOUT, check=check)
                    if msg.content.strip() == q['answer']:
            scores[msg.author.id] = scores.get(msg.author.id, 0) + 1
            await channel.send(f"🎉 {msg.author.mention} 正解！")
                        answered = True
                        # 少し待ってから次の問題へ
                        await asyncio.sleep(2)
        except asyncio.TimeoutError:
            await channel.send(f"⏰ 時間切れ！ 正解は「{q['answer']}」でした。")
                    # 少し待ってから次の問題へ
                    await asyncio.sleep(2)
                    break
        except Exception as e:
            print(f"Error in quiz: {e}")
            continue

    # 結果発表＆クリーンアップ
    tmp_sessions.pop(cid, None)
    tmp_ready.pop(cid, None)
    tmp_participants.pop(cid, None)

    if scores:
        sorted_list = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        text = "\n".join([f"<@{uid}>: {pts}点" for uid, pts in sorted_list])
        await channel.send(f"🏁 このセッションの結果：\n{text}")
    else:
        await channel.send("😢 正解者なしでした。")

# ======================================
# QuizSetupView: 「参加する」「締切・開始する」ボタン付き View
# ======================================
class QuizSetupView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        cid = self.channel_id
        uid = interaction.user.id

        lst = tmp_participants.setdefault(cid, set())
        lst.add(uid)
        await interaction.response.send_message(f"✅ {interaction.user.mention} が参加登録されました", ephemeral=False)

    @discord.ui.button(label="締切・開始する", style=discord.ButtonStyle.success)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        cid = self.channel_id
        settings = tmp_settings.get(cid)
        if not settings:
            return await interaction.response.send_message(
                "❌ 設定情報が見つかりません。再度[/クイズ大会]を実行してください。", ephemeral=True
            )

        # 参加締切フラグを立てる
        tmp_ready[cid] = True

        # 参加者一覧を作成
        participant_ids = tmp_participants.get(cid, set())
        if participant_ids:
            members = [f"・<@{uid}>" for uid in participant_ids]
            participant_text = "\n".join(members)
            summary_text = f"🧑‍🤝‍🧑 参加者一覧：\n{participant_text}"
        else:
            summary_text = "⚠️ 参加者が確認できませんでした。"

        # Interaction には最初にこれだけ返す（1回だけ）
        await interaction.response.send_message(
            f"{summary_text}\n\n🚀 参加締切＆クイズ開始します！", ephemeral=False
        )

        # 調査用ログ（必要な場合はコメントアウト可）
        print(f"[DEBUG] run_quiz を呼び出します: channel={cid}, settings={settings}")

        # クイズ開始：通常メッセージ送信 → run_quiz
        await interaction.channel.send("🔍 クイズをスタートします…")
        await run_quiz(interaction.channel, **settings)

# ======================================
# setup_quizking 関数
# ======================================
def setup_quizking(bot: commands.Bot):
    global quiz_bot
    quiz_bot = bot

    async def run_quiz(channel: discord.TextChannel, category: str, difficulty: str, count: int):
        cid = channel.id
        # フラグ立て
        tmp_sessions[cid] = True

        # 問題プールを絞り込み
        qs = quiz_data
        if category != "全カテゴリ":
            qs = [q for q in qs if q.get("category") == category]
        qs = [q for q in qs if q.get("difficulty") == difficulty]

        if not qs:
            await channel.send(f"❌ 問題が見つかりません (カテゴリ='{category}', 難易度='{difficulty}')")
            tmp_sessions.pop(cid, None)
            return

        # 出題数分ランダム抽出
        questions = random.sample(qs, k=min(count, len(qs)))
        scores = {}
        participants = tmp_participants.get(cid, set())

        for i, q in enumerate(questions, 1):
            # 途中中断チェック
            if not tmp_ready.get(cid):
                await channel.send("🛑 クイズが中断されました。")
                tmp_sessions.pop(cid, None)
                return

            # 問題を送信
            await channel.send(f"**第{i}問/{count}問**\n{q['question']}\n⏰ {DEFAULT_TIMEOUT}秒で回答")

            def check(m):
                return (
                    m.channel.id == cid
                    and m.author.id in participants
                    and not m.author.bot
                )

            answered = False
            try:
                while not answered and tmp_ready.get(cid):
                    try:
                        msg = await quiz_bot.wait_for('message', timeout=DEFAULT_TIMEOUT, check=check)
                        if msg.content.strip() == q['answer']:
                            scores[msg.author.id] = scores.get(msg.author.id, 0) + 1
                            await channel.send(f"🎉 {msg.author.mention} 正解！")
                            answered = True
                            # 少し待ってから次の問題へ
                            await asyncio.sleep(2)
                    except asyncio.TimeoutError:
                        await channel.send(f"⏰ 時間切れ！ 正解は「{q['answer']}」でした。")
                        # 少し待ってから次の問題へ
                        await asyncio.sleep(2)
                        break
            except Exception as e:
                print(f"Error in quiz: {e}")
                continue

        # 結果発表＆クリーンアップ
        tmp_sessions.pop(cid, None)
        tmp_ready.pop(cid, None)
        tmp_participants.pop(cid, None)

        if scores:
            sorted_list = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            text = "\n".join([f"<@{uid}>: {pts}点" for uid, pts in sorted_list])
            await channel.send(f"🏁 このセッションの結果：\n{text}")
        else:
            await channel.send("�� 正解者なしでした。")

    # スラッシュコマンド /クイズ大会
    @bot.tree.command(name="クイズ大会", description="カテゴリ・難易度・問題数を指定してクイズを準備")
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
            return await interaction.response.send_message("⚠️ 既に実行中のクイズがあります。", ephemeral=True)

        # パラチェック
        if count < 1 or count > MAX_COUNT:
            return await interaction.response.send_message(
                f"⚠️ 問題数は1〜{MAX_COUNT}の範囲で指定してください。", ephemeral=True
            )

        # 設定保存
        tmp_settings[cid] = {"category": category, "difficulty": difficulty, "count": count}
        tmp_participants[cid] = set()
        tmp_ready[cid] = False

        # 参加ボタンつきメッセージを送信
        view = QuizSetupView(cid)
        await interaction.response.send_message(
            f"🎯 クイズ準備中: カテゴリ='{category}', 難易度='{difficulty}', 問数={count}\n"
            "参加する方は下をクリック。準備が整ったら'締切・開始する'でスタート。",
            view=view
        )

    # スラッシュコマンド /クイズ中断
    @bot.tree.command(name="クイズ中断", description="クイズを中断します")
    async def cancel(interaction: discord.Interaction):
        cid = interaction.channel.id
        if tmp_sessions.get(cid):
            tmp_ready[cid] = False
            tmp_sessions.pop(cid, None)
            await interaction.response.send_message("🛑 クイズを中断しました。", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ 実行中のクイズがありません。", ephemeral=True)

# ======================================
# Bot 起動部分
# ======================================
# これを main ファイルなどから呼ぶ：
# from quizking import setup_quizking
# setup_quizking(bot)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} は起動しました")

# もしこのファイル単体でテストしたい場合は以下をアンコメント
#load_dotenv()
#token = os.getenv("DISCORD_TOKEN")
#bot.run(token)
