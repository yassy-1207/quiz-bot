import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# 役職プリセット
ROLE_PRESETS = {
    3: [["村人", "村人", "人狼"], ["村人", "占い師", "人狼"]],
    4: [["村人", "村人", "村人", "人狼"], ["村人", "占い師", "村人", "人狼"]],
    5: [["村人", "村人", "占い師", "狂人", "人狼"]]
}

werewolf_rooms = {}  # channel_id: {...}

class RoleSetButton(discord.ui.Button):
    def __init__(self, role_set, index):
        label = f"セット{index+1}: " + "・".join(role_set)
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role_set = role_set

    async def callback(self, interaction: discord.Interaction):
        cid = interaction.channel.id
        if cid not in werewolf_rooms:
            werewolf_rooms[cid] = {}
        werewolf_rooms[cid]["role_set"] = self.role_set
        werewolf_rooms[cid]["players"] = []
        view = JoinView(cid)
        await interaction.response.send_message("🧩 役職が決まりました！参加者はボタンを押してください。", view=view)

class RoleSelectionView(discord.ui.View):
    def __init__(self, role_sets):
        super().__init__(timeout=60)
        for i, rs in enumerate(role_sets):
            self.add_item(RoleSetButton(rs, i))

class JoinView(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        cid = self.channel_id
        room = werewolf_rooms.get(cid)
        if not room:
            await interaction.response.send_message("❌ ルームが見つかりません。", ephemeral=True)
            return

        if interaction.user.id in [p.id for p in room["players"]]:
            await interaction.response.send_message("⚠️ すでに参加しています。", ephemeral=True)
            return

        room["players"].append(interaction.user)
        await interaction.response.send_message(f"✅ {interaction.user.mention} が参加しました！")

        if len(room["players"]) == len(room["role_set"]):
            await asyncio.sleep(1)
            await send_roles_and_start(cid)

async def send_roles_and_start(cid):
    room = werewolf_rooms[cid]
    players = room["players"]
    roles = room["role_set"][:]
    random.shuffle(roles)
    random.shuffle(players)
    for user, role in zip(players, roles):
        try:
            await user.send(f"あなたの役職は **{role}** です。内緒にしてね！")
        except discord.Forbidden:
            channel = bot.get_channel(cid)
            await channel.send(f"⚠️ {user.mention} にDMが送れませんでした。設定をご確認ください。")
    channel = bot.get_channel(cid)
    await channel.send("🌙 夜が始まります（夜の処理未実装）")

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 起動完了")

@bot.tree.command(name="じんろう", description="人狼ゲームを始めます")
@app_commands.describe(players="プレイヤー数（3〜5）")
async def werewolf(interaction: discord.Interaction, players: int):
    if not 3 <= players <= 5:
        await interaction.response.send_message("❌ 3〜5人の範囲で指定してください。", ephemeral=True)
        return

    sets = ROLE_PRESETS.get(players)
    if not sets:
        await interaction.response.send_message("❌ その人数の役職セットがありません。", ephemeral=True)
        return

    view = RoleSelectionView(sets)
    await interaction.response.send_message(f"🎲 {players}人の役職セットを選んでください：", view=view)

# 実行
load_dotenv()
token=os.getenv("DISCORD_TOKEN")
bot.run(token)
