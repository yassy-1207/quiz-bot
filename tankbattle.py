import os
import discord
from discord.ext import commands
import asyncio
import random
import string

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ルーム情報格納 {room_id: {"channel": TextChannel, "players": [Player,...], "started": bool}}
rooms: dict[str, dict] = {}

class Player:
    def __init__(self, user: discord.User):
        self.user = user
        self.hp: int = 10
        self.charge: int = 0
        self.choice: str | None = None
        self.last_choice: str | None = None

class CommandSelectionView(discord.ui.View):
    def __init__(self, player: Player):
        super().__init__(timeout=30)
        self.player = player
        # 連続バリア禁止
        if player.last_choice == 'barrier':
            for child in self.children:
                if getattr(child, 'label', None) == 'バリア':
                    child.disabled = True
        # チャージ残量で発射ボタンを制御
        charge = player.charge
        for child in self.children:
            label = getattr(child, 'label', '')
            if label.endswith('チャージ発射'):
                n = int(label[0])
                if charge < n:
                    child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.player.user.id

    async def process(self, interaction: discord.Interaction, cmd: str):
        self.player.choice = cmd
        await interaction.response.send_message(f"✅ 選択: **{cmd}**", ephemeral=True)
        self.stop()

    @discord.ui.button(label="バリア", style=discord.ButtonStyle.secondary)
    async def barrier(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, 'barrier')

    @discord.ui.button(label="チャージ", style=discord.ButtonStyle.primary)
    async def charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, 'charge')

    @discord.ui.button(label="1チャージ発射", style=discord.ButtonStyle.danger)
    async def shoot1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, 'shoot1')

    @discord.ui.button(label="2チャージ発射", style=discord.ButtonStyle.danger)
    async def shoot2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, 'shoot2')

    @discord.ui.button(label="3チャージ発射", style=discord.ButtonStyle.success)
    async def shoot3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.process(interaction, 'shoot3')

class JoinView(discord.ui.View):
    def __init__(self, room_id: str):
        super().__init__(timeout=None)
        self.room_id = room_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.primary)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = rooms.get(self.room_id)
        if not room:
            return await interaction.response.send_message("⚠️ このルームは存在しません。", ephemeral=True)
        if any(p.user.id == interaction.user.id for p in room['players']):
            return await interaction.response.send_message("⚠️ 既に参加済みです。", ephemeral=True)
        if len(room['players']) >= 2:
            return await interaction.response.send_message("⚠️ 満員です。", ephemeral=True)

        player = Player(interaction.user)
        room['players'].append(player)
        await interaction.channel.send(f"✅ {interaction.user.mention} が参加しました！")
        await interaction.response.defer()

        if len(room['players']) == 2 and not room['started']:
            await asyncio.sleep(1)
            await start_game(room)
            

# 同時解決ロジック
def resolve_turn(p1: Player, p2: Player):
    def damage(a: Player, d: Player) -> int:
        # 相手がバリアなら無効
        if d.choice == 'barrier':
            return 0
        # 発射系
        if a.choice and a.choice.startswith('shoot'):
            return int(a.choice[-1])
        return 0

    # ダメージ算出
    d1 = damage(p1, p2)
    d2 = damage(p2, p1)
    p1.hp -= d2
    p2.hp -= d1

    # チャージ管理: チャージ追加 or 消費
    for p in (p1, p2):
        if p.choice == 'charge':
            p.charge += 1
        elif p.choice and p.choice.startswith('shoot'):
            n = int(p.choice[-1])
            p.charge = max(p.charge - n, 0)

def setup_tankbattle(bot: commands.Bot):

    @bot.tree.command(name='ミニ戦車バトル', description='2人同時ターン制ミニ戦車バトル')
    async def make_room(interaction: discord.Interaction):
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        rooms[room_id] = {'channel': interaction.channel, 'players': [], 'started': False}
        await interaction.response.send_message(
            f"🎮 ルーム `{room_id}` を作成しました！参加者2名で開始します。",
            view=JoinView(room_id)
        )

    async def start_game(room: dict):
        room_id = next(k for k,v in rooms.items() if v is room)
        channel = room['channel']
        players = room['players']
        room['started'] = True

        # ゲーム開始DM
        for p in players:
            try:
                await p.user.send(f"🔥 ゲーム開始！HP={p.hp} / Charge={p.charge}\n" +
                                "(※30秒以内に未選択時は自動で『チャージ』が選択されます)")
                p.last_choice = None
            except discord.Forbidden:
                await channel.send(f"⚠️ {p.user.mention} へのDMが送れません。DMを有効にしてください。")

        # ターンループ
        while all(p.hp > 0 for p in players):
            # 各プレイヤーへ結果と選択DM
            for p in players:
                opponent = players[1] if p is players[0] else players[0]
                embed = discord.Embed(title='💥 ターン結果', color=discord.Color.blue())
                embed.add_field(name='あなた', value=f"HP: {p.hp}\nCharge: {p.charge}", inline=True)
                embed.add_field(name='相手', value=f"HP: {opponent.hp}\nCharge: {opponent.charge}", inline=True)
                embed.set_footer(text='コマンドを選択 (30秒以内; 未選択時はチャージ)')
                view = CommandSelectionView(p)
                try:
                    await p.user.send(embed=embed, view=view)
                except discord.Forbidden:
                    await channel.send(f"⚠️ {p.user.mention} へのDMが送れません。")
            # 選択待機
            await asyncio.gather(*[wait_for_choice(p) for p in players])
            # 解決
            resolve_turn(players[0], players[1])
            # choiceとlast_choice更新
            for p in players:
                p.last_choice = p.choice
                p.choice = None

        # 勝敗
        winner, loser = (players[0], players[1]) if players[0].hp > 0 else (players[1], players[0])
        await channel.send(f"🏆 {winner.user.mention} の勝利！{loser.user.mention} を撃破！")
        # DM勝敗通知
        for p in players:
            try:
                result = '勝利' if p is winner else '敗北'
                opp = loser if p is winner else winner
                await p.user.send(
                    f"🏁 ゲーム終了 — {result}\n"
                    f"あなた: HP={p.hp} / Charge={p.charge}\n"
                    f"相手: HP={opp.hp} / Charge={opp.charge}"
                )
            except discord.Forbidden:
                pass
        del rooms[room_id]

    async def wait_for_choice(player: Player):
        for _ in range(60):
            if player.choice is not None:
                return
            await asyncio.sleep(0.5)
        player.choice = 'charge'
