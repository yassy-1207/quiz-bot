import os
import discord
from discord.ext import commands
import asyncio
import random
import string
from datetime import datetime
from discord.ext import tasks
from discord import app_commands
from typing import Optional

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

# 1. 定数の整理
GAME_SETTINGS = {
    "INITIAL_HP": 10,
    "MAX_CHARGE": 3,
    "COMMAND_TIMEOUT": 30,
    "JOIN_TIMEOUT": 180
}

class Player:
    def __init__(self, user: discord.User):
        self.user = user
        self.hp: int = GAME_SETTINGS["INITIAL_HP"]
        self.charge: int = 0
        self.choice: str | None = None
        self.last_choice: str | None = None
        self.total_damage_dealt: int = 0  # 与ダメージ合計
        self.total_damage_taken: int = 0  # 被ダメージ合計

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def apply_damage(self, damage: int):
        self.hp = max(0, self.hp - damage)
        self.total_damage_taken += damage

    def add_charge(self):
        self.charge = min(self.charge + 1, GAME_SETTINGS["MAX_CHARGE"])

class CommandSelectionView(discord.ui.View):
    def __init__(self, player: Player):
        super().__init__(timeout=GAME_SETTINGS["COMMAND_TIMEOUT"])
        self.player = player
        self.update_buttons()

    def update_buttons(self):
        """ボタンの状態を更新"""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                # バリア連続使用禁止
                if child.label == "バリア" and self.player.last_choice == 'barrier':
                    child.disabled = True
                    child.style = discord.ButtonStyle.secondary
                
                # チャージ不足の攻撃を無効化
                elif child.label.endswith('チャージ発射'):
                    required = int(child.label[0])
                    if self.player.charge < required:
                        child.disabled = True
                        child.style = discord.ButtonStyle.secondary

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

    # エラーハンドラーをsetup_tankbattle関数の中に移動
    @bot.tree.error
    async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
        error_messages = {
            app_commands.CommandOnCooldown: lambda e: f"⏳ クールダウン中です（{e.retry_after:.1f}秒）",
            app_commands.MissingPermissions: "⚠️ 権限がありません",
            Exception: "❌ エラーが発生しました"
        }
        message = error_messages.get(type(error), str(error))
        await interaction.response.send_message(message, ephemeral=True)

    # 戦績表示コマンドもsetup_tankbattle関数の中に移動
    @bot.tree.command(name='戦車戦績', description='ミニ戦車バトルの戦績を表示')
    async def show_stats(interaction: discord.Interaction, target: Optional[discord.User] = None):
        user = target or interaction.user
        stats = GameStats(user.id).stats
        
        if stats["total_games"] == 0:
            await interaction.response.send_message(
                f"{user.mention} の戦績はありません",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🎮 {user.display_name} の戦車バトル戦績",
            color=discord.Color.blue()
        )
        
        win_rate = stats["wins"] / stats["total_games"] * 100
        avg_damage = stats["total_damage_dealt"] / stats["total_games"]
        
        embed.add_field(
            name="基本統計",
            value=(
                f"総対戦数: {stats['total_games']}\n"
                f"勝利: {stats['wins']}\n"
                f"敗北: {stats['losses']}\n"
                f"勝率: {win_rate:.1f}%"
            ),
            inline=False
        )
        
        embed.add_field(
            name="戦闘統計",
            value=(
                f"最大ダメージ: {stats['max_damage_dealt']}\n"
                f"平均ダメージ: {avg_damage:.1f}\n"
                f"完全勝利: {stats['perfect_wins']}"
            ),
            inline=False
        )
        
        await interaction.response.send_message(embed=embed)

    # クリーンアップタスクの開始
    cleanup_inactive_rooms.start()

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

                    # 前のターンの行動を表示（2ターン目以降）
                    if p.last_choice is not None and opponent.last_choice is not None:
                        your_action = ACTION_NAMES.get(p.last_choice, p.last_choice)
                        opp_action = ACTION_NAMES.get(opponent.last_choice, opponent.last_choice)
                        embed.add_field(name='前回の行動', value=f"あなた: {your_action}\n相手: {opp_action}", inline=False)

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
                turn_result = resolve_turn(players[0], players[1])
                
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

    # チャージ処理
    for p in [p1, p2]:
        if p.choice == 'charge':
            p.charge = min(p.charge + 1, 3)  # 最大3チャージまで
        elif p.choice and p.choice.startswith('shoot'):
            p.charge -= int(p.choice[-1])

    # アクション結果を返す
    return {
        'p1_action': p1.choice,
        'p2_action': p2.choice,
        'p1_blocked': p1_blocked,
        'p2_blocked': p2_blocked,
        'p1_attack': p1_attack,
        'p2_attack': p2_attack
    }

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

@tasks.loop(minutes=5)
async def cleanup_inactive_rooms():
    current_time = datetime.now()
    inactive_rooms = []
    for room_id, room in rooms.items():
        if not room['started']:
            created_at = room.get('created_at', current_time)
            if (current_time - created_at).total_seconds() > 180:  # 3分
                inactive_rooms.append(room_id)
    for room_id in inactive_rooms:
        del rooms[room_id]

async def send_dm_or_channel(user: discord.User, channel: discord.TextChannel, content: str, **kwargs):
    try:
        await user.send(content, **kwargs)
        return True
    except discord.Forbidden:
        # DMが送れない場合はチャンネルで代替
        await channel.send(f"{user.mention} {content}", **kwargs)
        return False

# 3. ゲーム状態管理の改善
class TankBattleGame:
    def __init__(self, channel: discord.TextChannel):
        self.channel = channel
        self.players: list[Player] = []
        self.started: bool = False
        self.created_at = datetime.now()
        self.turn_count: int = 0

    async def add_player(self, user: discord.User) -> bool:
        if len(self.players) >= 2:
            return False
        player = Player(user)
        self.players.append(player)
        return True

    def is_player(self, user_id: int) -> bool:
        return any(p.user.id == user_id for p in self.players)

# 1. 戦績管理クラス
class GameStats:
    def __init__(self, user_id: int):
        self.stats = player_stats.setdefault(user_id, {
            "wins": 0,
            "losses": 0,
            "total_games": 0,
            "max_damage_dealt": 0,
            "perfect_wins": 0,  # ノーダメージ勝利
            "total_damage_dealt": 0,
            "total_damage_taken": 0
        })

    def add_result(self, won: bool, damage_dealt: int, damage_taken: int):
        self.stats["total_games"] += 1
        if won:
            self.stats["wins"] += 1
            if damage_taken == 0:
                self.stats["perfect_wins"] += 1
        else:
            self.stats["losses"] += 1
        
        self.stats["max_damage_dealt"] = max(
            self.stats["max_damage_dealt"], 
            damage_dealt
        )
        self.stats["total_damage_dealt"] += damage_dealt
        self.stats["total_damage_taken"] += damage_taken

# 1. ダメージ計算の改善
def calculate_damage(attacker: Player, defender: Player) -> int:
    """より戦略的なダメージ計算"""
    if defender.choice == 'barrier':
        return 0
    
    attack_power = int(attacker.choice[-1]) if attacker.choice.startswith('shoot') else 0
    if not attack_power:
        return 0
        
    # チャージ量に応じたボーナスダメージ
    bonus = attack_power * 0.2  # 20%ボーナス
    return attack_power + round(bonus)

# テストケース
def test_game_mechanics():
    # 1. 基本的な攻撃テスト
    p1 = Player(None)
    p2 = Player(None)
    p1.charge = 2
    p1.choice = 'shoot2'
    p2.choice = 'charge'
    
    result = resolve_turn(p1, p2)
    assert p2.hp == 8  # 2ダメージ
    assert p1.charge == 0  # チャージ消費
    assert p2.charge == 1  # チャージ増加

    # 2. バリアテスト
    p1 = Player(None)
    p2 = Player(None)
    p1.charge = 3
    p1.choice = 'shoot3'
    p2.choice = 'barrier'
    
    result = resolve_turn(p1, p2)
    assert p2.hp == 10  # ダメージなし
    assert p1.charge == 0  # チャージ消費
    assert p2.charge == 0  # バリアはチャージ増加なし

    # 3. 相殺テスト
    p1 = Player(None)
    p2 = Player(None)
    p1.charge = 2
    p2.charge = 2
    p1.choice = 'shoot2'
    p2.choice = 'shoot2'
    
    result = resolve_turn(p1, p2)
    assert p1.hp == 10  # ダメージなし
    assert p2.hp == 10  # ダメージなし
    assert p1.charge == 0  # チャージ消費
    assert p2.charge == 0  # チャージ消費
