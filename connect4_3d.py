import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import List, Optional, Dict, Set, Tuple
from datetime import datetime

# グローバル変数の定義
connect4_3d_bot = None

# ゲームの状態を表す定数
EMPTY = "⚪"  # 空きマス
RED = "🔴"    # プレイヤー1
YELLOW = "🟡" # プレイヤー2
NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]  # 座標番号

# エラーメッセージの定数
ERROR_MESSAGES = {
    "not_your_turn": "あなたの手番ではありません！",
    "invalid_position": "その位置は選択できません！",
    "bot_participation": "Botは参加できません！",
    "already_in_game": "あなたは既に他のゲームに参加しています！",
    "already_joined": "あなたは既に参加しています！",
    "game_in_progress": "このチャンネルでは既にゲームが進行中です！",
}

# 進行中のゲーム情報を保持
active_games: Dict[int, Set[int]] = {}  # channel_id -> set of player_ids

# プレイヤーの戦績を保持
player_stats: Dict[int, Dict[str, int]] = {}  # user_id -> stats

class GameStats:
    def __init__(self, user_id: int):
        self.stats = player_stats.setdefault(user_id, {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "total_games": 0
        })

    def add_win(self):
        self.stats["wins"] += 1
        self.stats["total_games"] += 1

    def add_loss(self):
        self.stats["losses"] += 1
        self.stats["total_games"] += 1

    def add_draw(self):
        self.stats["draws"] += 1
        self.stats["total_games"] += 1

    def get_stats_display(self) -> str:
        return (
            f"🎮 総対戦数: {self.stats['total_games']}\n"
            f"🏆 勝利: {self.stats['wins']}\n"
            f"💔 敗北: {self.stats['losses']}\n"
            f"🤝 引分: {self.stats['draws']}\n"
            f"📊 勝率: {self.stats['wins'] / max(1, self.stats['total_games']):.1%}"
        )

class Connect4_3DGame:
    def __init__(self, player1: discord.User, player2: discord.User):
        self.board = [[[EMPTY for _ in range(4)] for _ in range(4)] for _ in range(4)]
        self.player1 = player1  # 🔴
        self.player2 = player2  # 🟡
        self.current_player = player1
        self.winner = None
        self.is_finished = False
        self.start_time = datetime.now()
        self.moves = []  # 手の履歴

    def make_move(self, x: int, y: int) -> bool:
        """
        指定された位置(x, y)に駒を配置する
        戻り値: 配置成功したかどうか
        """
        if not (0 <= x < 4 and 0 <= y < 4):
            return False

        # 一番下の空きマスを探す
        for z in range(3, -1, -1):
            if self.board[z][y][x] == EMPTY:
                self.board[z][y][x] = RED if self.current_player == self.player1 else YELLOW
                self.moves.append((self.current_player.id, (x, y, z)))
                return True
        return False

    def get_board_display(self) -> str:
        """ゲームボードの文字列表現を返す（視認性向上版）"""
        display = []
        
        # 各層の表示
        for z in range(3, -1, -1):  # 上から下へ
            display.append(f"\n📊 Layer {z+1}")
            display.append("  " + " ".join(NUMBERS))  # x座標
            display.append("  " + "─" * 15)  # 区切り線
            
            for y in range(4):
                row = [NUMBERS[y]]  # y座標
                row.extend(self.board[z][y])
                display.append("│ " + " ".join(row) + " │")
            
            display.append("  " + "─" * 15)  # 区切り線
        
        # 現在のプレイヤーの表示
        display.append(f"\n手番: {self.current_player.mention}")
        if self.current_player == self.player1:
            display.append(f"({RED})")
        else:
            display.append(f"({YELLOW})")
        
        # 経過時間の表示
        elapsed = datetime.now() - self.start_time
        display.append(f"\n⏱️ 経過時間: {elapsed.seconds // 60}分{elapsed.seconds % 60}秒")
            
        return "\n".join(display)

    def get_game_summary(self) -> str:
        """ゲームの要約を返す"""
        return (
            f"🎮 ゲーム結果\n"
            f"赤 {RED}: {self.player1.mention}\n"
            f"黄 {YELLOW}: {self.player2.mention}\n"
            f"手数: {len(self.moves)}\n"
            f"経過時間: {(datetime.now() - self.start_time).seconds // 60}分"
        )

    def check_winner(self) -> Optional[discord.User]:
        """
        勝者を判定する
        戻り値: 勝者のUser、引き分けはNone
        """
        # 全方向のチェック
        directions = [
            # 水平方向
            [(0,0,0), (0,0,1), (0,0,2), (0,0,3)],
            [(0,1,0), (0,1,1), (0,1,2), (0,1,3)],
            [(0,2,0), (0,2,1), (0,2,2), (0,2,3)],
            [(0,3,0), (0,3,1), (0,3,2), (0,3,3)],
            # 垂直方向
            [(0,0,0), (1,0,0), (2,0,0), (3,0,0)],
            [(0,1,0), (1,1,0), (2,1,0), (3,1,0)],
            [(0,2,0), (1,2,0), (2,2,0), (3,2,0)],
            [(0,3,0), (1,3,0), (2,3,0), (3,3,0)],
            # 奥行き方向
            [(0,0,0), (0,1,0), (0,2,0), (0,3,0)],
            [(1,0,0), (1,1,0), (1,2,0), (1,3,0)],
            [(2,0,0), (2,1,0), (2,2,0), (2,3,0)],
            [(3,0,0), (3,1,0), (3,2,0), (3,3,0)],
            # 斜め方向（平面）
            [(0,0,0), (1,1,0), (2,2,0), (3,3,0)],
            [(0,3,0), (1,2,0), (2,1,0), (3,0,0)],
            # 斜め方向（立体）
            [(0,0,0), (1,1,1), (2,2,2), (3,3,3)],
            [(0,3,0), (1,2,1), (2,1,2), (3,0,3)],
            [(3,0,0), (2,1,1), (1,2,2), (0,3,3)],
            [(3,3,0), (2,2,1), (1,1,2), (0,0,3)]
        ]

        for direction in directions:
            for x in range(4):
                for y in range(4):
                    for z in range(4):
                        # 各方向について4つ分チェック
                        pieces = []
                        for dx, dy, dz in direction:
                            nx, ny, nz = x + dx, y + dy, z + dz
                            if 0 <= nx < 4 and 0 <= ny < 4 and 0 <= nz < 4:
                                pieces.append(self.board[nz][ny][nx])
                        
                        if len(pieces) == 4:
                            if all(p == RED for p in pieces):
                                return self.player1
                            elif all(p == YELLOW for p in pieces):
                                return self.player2

        # 引き分けチェック（全マスが埋まっている）
        is_full = all(self.board[z][y][x] != EMPTY 
                     for x in range(4) 
                     for y in range(4) 
                     for z in range(4))
        return None if is_full else False

class SurrenderButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="投了",
            style=discord.ButtonStyle.danger,
            row=4  # ボードの下に配置
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if interaction.user not in [view.game.player1, view.game.player2]:
            await interaction.response.send_message("このゲームのプレイヤーではありません！", ephemeral=True)
            return

        # 投了したプレイヤーの敗北として処理
        winner = view.game.player2 if interaction.user == view.game.player1 else view.game.player1
        await view.end_game(interaction, f"👋 {interaction.user.mention} が投了しました。{winner.mention} の勝利！")

class Connect4_3DView(discord.ui.View):
    def __init__(self, game: Connect4_3DGame):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.game = game
        self.message = None
        self.update_buttons()
        self.add_item(SurrenderButton())  # 投了ボタンを追加

    async def end_game(self, interaction: discord.Interaction, result: str):
        """ゲーム終了時の共通処理"""
        self.game.is_finished = True
        
        # 戦績の更新
        if "勝利" in result:
            winner = self.game.player1 if self.game.current_player == self.game.player2 else self.game.player2
            loser = self.game.player2 if winner == self.game.player1 else self.game.player1
            GameStats(winner.id).add_win()
            GameStats(loser.id).add_loss()
        elif "引き分け" in result:
            GameStats(self.game.player1.id).add_draw()
            GameStats(self.game.player2.id).add_draw()
        
        # 最終盤面の表示
        final_display = (
            f"{self.game.get_board_display()}\n"
            f"{result}\n\n"
            f"{self.game.get_game_summary()}\n\n"
            f"🏆 {self.game.player1.mention} の戦績:\n"
            f"{GameStats(self.game.player1.id).get_stats_display()}\n\n"
            f"🏆 {self.game.player2.mention} の戦績:\n"
            f"{GameStats(self.game.player2.id).get_stats_display()}"
        )
        
        # ボタンを無効化して表示を更新
        self.clear_items()
        await interaction.response.edit_message(content=final_display, view=None)
        
        # プレイヤーの解放
        channel_id = interaction.channel.id
        player_ids = [self.game.player1.id, self.game.player2.id]
        await connect4_3d_bot.on_game_end(channel_id, player_ids)

    def update_buttons(self):
        """ボタンの状態を更新"""
        # x座標選択ボタン
        for x in range(4):
            for y in range(4):
                # その列が満杯かどうかチェック
                is_full = self.game.board[0][y][x] != EMPTY
                button = discord.ui.Button(
                    label=f"({x+1}, {y+1})",
                    style=discord.ButtonStyle.primary if not is_full else discord.ButtonStyle.secondary,
                    disabled=is_full or self.game.is_finished,
                    custom_id=f"pos_{x}_{y}",
                    row=y  # y座標ごとに行を分ける
                )
                button.callback = self.make_move
                self.add_item(button)

    async def make_move(self, interaction: discord.Interaction):
        """ボタンが押されたときの処理"""
        try:
            # 手番チェック
            if interaction.user != self.game.current_player:
                await interaction.response.send_message(ERROR_MESSAGES["not_your_turn"], ephemeral=True)
                return

            # 座標の取得と手の実行
            x, y = map(int, interaction.custom_id.split("_")[1:])
            if not self.game.make_move(x, y):
                await interaction.response.send_message(ERROR_MESSAGES["invalid_position"], ephemeral=True)
                return

            # 勝敗チェック
            winner = self.game.check_winner()
            if winner is not None:
                self.game.is_finished = True
                if winner:
                    result = f"🎉 {winner.mention} の勝利！"
                else:
                    result = "😅 引き分けです！"
                await self.end_game(interaction, result)
            else:
                # プレイヤーの交代
                self.game.current_player = self.game.player2 if self.game.current_player == self.game.player1 else self.game.player1
                
                # ビューの更新
                self.clear_items()
                self.update_buttons()
                await interaction.response.edit_message(content=self.game.get_board_display(), view=self)

        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {str(e)}\n"
                "もう一度お試しください。",
                ephemeral=True
            )
            print(f"Error in make_move: {e}")  # エラーログ

    async def on_timeout(self):
        """タイムアウト時の処理"""
        if not self.game.is_finished and self.message:
            self.game.is_finished = True
            await self.message.edit(
                content=f"{self.game.get_board_display()}\n⏰ タイムアウトしました。ゲームを終了します。",
                view=None
            )
            # プレイヤーの解放
            channel_id = self.message.channel.id
            player_ids = [self.game.player1.id, self.game.player2.id]
            await connect4_3d_bot.on_game_end(channel_id, player_ids)

class JoinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="参加する", style=discord.ButtonStyle.primary)
        self.players = []

    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.user.bot:
                await interaction.response.send_message(ERROR_MESSAGES["bot_participation"], ephemeral=True)
                return

            if interaction.user.id in active_games.get(interaction.channel.id, set()):
                await interaction.response.send_message(ERROR_MESSAGES["already_in_game"], ephemeral=True)
                return

            if interaction.user in self.players:
                await interaction.response.send_message(ERROR_MESSAGES["already_joined"], ephemeral=True)
                return

            self.players.append(interaction.user)
            await interaction.response.send_message(f"{interaction.user.mention} が参加しました！", ephemeral=False)

            if len(self.players) == 2:
                # ゲームの作成と開始
                game = Connect4_3DGame(self.players[0], self.players[1])
                view = Connect4_3DView(game)
                
                # アクティブゲームに登録
                channel_id = interaction.channel.id
                if channel_id not in active_games:
                    active_games[channel_id] = set()
                active_games[channel_id].update(player.id for player in self.players)
                
                # 募集メッセージを削除し、ゲーム開始
                if hasattr(self.view, 'message'):
                    await self.view.message.delete()
                
                # ゲーム開始メッセージを送信
                message = await interaction.channel.send(
                    f"🎮 立体コネクトフォーを開始します！\n"
                    f"{self.players[0].mention} ({RED}) vs {self.players[1].mention} ({YELLOW})\n\n"
                    f"{game.get_board_display()}",
                    view=view
                )
                view.message = message
                self.view.stop()

        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {str(e)}\n"
                "もう一度お試しください。",
                ephemeral=True
            )
            print(f"Error in JoinButton callback: {e}")

class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.add_item(JoinButton())
        self.message = None

    async def on_timeout(self):
        if self.message:
            await self.message.edit(content="⏰ 参加者が揃わなかったため、募集を終了します。", view=None)

def setup_connect4_3d(bot: commands.Bot):
    """立体コネクトフォーの機能をbotに設定する"""
    global connect4_3d_bot
    connect4_3d_bot = bot
    
    @bot.tree.command(name="立体コネクトフォー", description="立体コネクトフォー（3D四目並べ）を開始します")
    async def connect4_3d(interaction: discord.Interaction):
        """立体コネクトフォーを開始するコマンド"""
        try:
            # 既存のゲームチェック
            if interaction.channel.id in active_games and active_games[interaction.channel.id]:
                await interaction.response.send_message(ERROR_MESSAGES["game_in_progress"], ephemeral=True)
                return

            # 参加ビューの作成と送信
            view = JoinView()
            await interaction.response.send_message(
                "🎮 立体コネクトフォーの参加者を募集します！\n"
                "2人揃うと開始します。\n"
                "制限時間: 3分",
                view=view
            )
            view.message = await interaction.original_response()

        except Exception as e:
            await interaction.response.send_message(
                f"エラーが発生しました: {str(e)}\n"
                "もう一度お試しください。",
                ephemeral=True
            )
            print(f"Error in connect4_3d command: {e}")

    @bot.tree.command(name="立体コネクトフォー戦績", description="立体コネクトフォーの戦績を表示します")
    async def connect4_3d_stats(interaction: discord.Interaction, target: Optional[discord.User] = None):
        """戦績表示コマンド"""
        user = target or interaction.user
        stats = GameStats(user.id)
        await interaction.response.send_message(
            f"🏆 {user.mention} の立体コネクトフォー戦績\n"
            f"{stats.get_stats_display()}",
            ephemeral=True
        )

    @bot.event
    async def on_game_end(channel_id: int, player_ids: List[int]):
        """ゲーム終了時のクリーンアップ"""
        if channel_id in active_games:
            active_games[channel_id].difference_update(player_ids)
            if not active_games[channel_id]:
                del active_games[channel_id]

    return bot 