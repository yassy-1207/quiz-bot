import os
import discord
from discord.ext import commands
import asyncio
import random
import string

# グローバル変数の定義
tank_bot = None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ルーム情報格納 {room_id: {"channel": TextChannel, "players": [Player,...], "started": bool}}
rooms: dict[str, dict] = {}

# === アクション名の定義 ===
ACTION_NAMES = {
    "barrier": "🛡️ バリア",
    "charge": "⚡ チャージ",
    "attack1": "💥 1チャージ攻撃",
    "attack2": "💥💥 2チャージ攻撃",
    "attack3": "💥💥💥 3チャージ攻撃"
}

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

def setup_tankbattle(bot: commands.Bot):
    global tank_bot
    tank_bot = bot

    async def start_game(room: dict):
        try:
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
                    return

        # ターンループ
        while all(p.hp > 0 for p in players):
                # 中断確認
                if not room.get('started', False):
                    await channel.send("🛑 ゲームが中断されました。")
                    return

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
                        return

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

        except Exception as e:
            print(f"Error in tank battle: {e}")
            await channel.send("⚠️ ゲームでエラーが発生しました。")
        finally:
            if room_id in rooms:
        del rooms[room_id]

    @bot.tree.command(name='戦車中断', description='進行中の戦車バトルを中断します')
    async def cancel_game(interaction: discord.Interaction):
        # 進行中のゲームを探す
        channel_rooms = [room for room in rooms.values() if room['channel'].id == interaction.channel.id]
        if not channel_rooms:
            await interaction.response.send_message("⚠️ このチャンネルで進行中のゲームはありません。", ephemeral=True)
            return

        room = channel_rooms[0]
        # 参加者かどうかチェック
        if not any(p.user.id == interaction.user.id for p in room['players']):
            await interaction.response.send_message("⚠️ このゲームの参加者ではありません。", ephemeral=True)
            return

        # ゲームを中断
        room['started'] = False
        await interaction.response.send_message("🛑 ゲームを中断しました。")

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
            await interaction.response.send_message(f"✅ 参加登録完了！", ephemeral=True)
            await interaction.channel.send(f"✅ {interaction.user.mention} が参加しました！")

            if len(room['players']) == 2 and not room['started']:
                room['started'] = True
                await interaction.channel.send("🎮 参加者が揃いました！ゲームを開始します...")
                await asyncio.sleep(1)
                await start_game(room)

    @bot.tree.command(name='ミニ戦車バトル', description='2人同時ターン制ミニ戦車バトル')
    async def make_room(interaction: discord.Interaction):
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        rooms[room_id] = {
            'channel': interaction.channel,
            'players': [],
            'started': False
        }
        view = JoinView(room_id)
        await interaction.response.send_message(
            f"🎮 ルーム `{room_id}` を作成しました！参加者2名で開始します。",
            view=view
        )

    async def wait_for_choice(player: Player):
        for _ in range(60):
            if player.choice is not None:
                return
            await asyncio.sleep(0.5)
        player.choice = 'charge'

# 同時解決ロジック
def resolve_turn(p1: Player, p2: Player):
    def get_attack_power(p: Player) -> int:
        # 発射系コマンドの場合、チャージ数を返す
        if p.choice and p.choice.startswith('shoot'):
            return int(p.choice[-1])
        return 0

    # ダメージ算出
    p1_attack = get_attack_power(p1)
    p2_attack = get_attack_power(p2)

    # バリア判定
    p1_blocked = p1.choice == 'barrier'
    p2_blocked = p2.choice == 'barrier'

    # ダメージ計算（バリアと相殺を考慮）
    if not p1_blocked and not p2_blocked and p1_attack > 0 and p2_attack > 0:
        # 両者が攻撃の場合、チャージの差分がダメージになる
        if p1_attack > p2_attack:
            p2.hp -= (p1_attack - p2_attack)
        elif p2_attack > p1_attack:
            p1.hp -= (p2_attack - p1_attack)
        # チャージが同じ場合は相殺
    else:
        # 通常のダメージ処理
        if not p2_blocked and p1_attack > 0:
            p2.hp -= p1_attack
        if not p1_blocked and p2_attack > 0:
            p1.hp -= p2_attack

    # チャージ管理: チャージ追加 or 消費
    for p in (p1, p2):
        if p.choice == 'charge':
            p.charge += 1
        elif p.choice and p.choice.startswith('shoot'):
            n = int(p.choice[-1])
            p.charge = max(p.charge - n, 0)

async def process_turn(p1_action, p2_action, battle_data):
    """ターンの処理を行う"""
    p1_id = battle_data["player1"]
    p2_id = battle_data["player2"]
    
    # アクション結果を記録
    battle_data["last_actions"] = {
        p1_id: p1_action,
        p2_id: p2_action
    }

    # ... (既存の処理ロジック) ...

async def show_status(channel, battle_data):
    """バトル状況を表示"""
    p1_id = battle_data["player1"]
    p2_id = battle_data["player2"]
    p1_hp = battle_data["hp"][p1_id]
    p2_hp = battle_data["hp"][p2_id]
    p1_charge = battle_data["charge"][p1_id]
    p2_charge = battle_data["charge"][p2_id]
    p1_barrier = battle_data["barrier"][p1_id]
    p2_barrier = battle_data["barrier"][p2_id]

    # 前のターンのアクションを取得
    last_actions = battle_data.get("last_actions", {})
    p1_last_action = last_actions.get(p1_id)
    p2_last_action = last_actions.get(p2_id)

    # ステータス表示用の絵文字
    hp_emoji = "❤️"
    charge_emoji = "⚡"
    barrier_emoji = "🛡️"

    # プレイヤー1のステータス行
    p1_status = [
        f"<@{p1_id}>",
        f"{hp_emoji} {p1_hp}",
        f"{charge_emoji} {p1_charge}",
    ]
    if p1_barrier:
        p1_status.append(f"{barrier_emoji}")
    if p1_last_action:
        p1_status.append(f"➡️ {ACTION_NAMES.get(p1_last_action, '不明')}")

    # プレイヤー2のステータス行
    p2_status = [
        f"<@{p2_id}>",
        f"{hp_emoji} {p2_hp}",
        f"{charge_emoji} {p2_charge}",
    ]
    if p2_barrier:
        p2_status.append(f"{barrier_emoji}")
    if p2_last_action:
        p2_status.append(f"➡️ {ACTION_NAMES.get(p2_last_action, '不明')}")

    status_message = [
        "🎮 **バトル状況**",
        "```",
        f"プレイヤー1: {' '.join(p1_status)}",
        f"プレイヤー2: {' '.join(p2_status)}",
        "```",
        "",
        "**コマンド説明**",
        "・`バリア`：全ての攻撃を防ぐ（連続使用不可）",
        "・`チャージ`：攻撃のためのエネルギーを貯める",
        "・`1〜3チャージ攻撃`：チャージを消費して攻撃"
    ]

    await channel.send("\n".join(status_message))
