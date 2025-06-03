# werewolf.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, Set, List, Optional, Union, Tuple, FrozenSet
from functools import lru_cache

# === 定数定義 ===
VOTE_WARNING_TIME = 30  # 投票終了30秒前に警告
VOTE_TIME = 180  # 投票時間3分
DISCUSSION_TIME = 300  # 議論時間5分
NIGHT_TIME = 180  # 夜のアクション時間3分
FIRST_NIGHT_TIME = 60  # 初日夜のアクション時間1分
JOIN_TIMEOUT = 180  # 参加募集のタイムアウト時間3分

# フェーズの定数定義を追加
PHASE_NIGHT = "night"    # 夜フェーズ
PHASE_DAY = "day"       # 昼フェーズ（議論）
PHASE_VOTE = "vote"     # 投票フェーズ

# グローバル変数の定義
werewolf_bot = None
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# プレイヤーの戦績を保持
player_stats: Dict[int, Dict[str, Dict[str, int]]] = {}  # user_id -> role -> stats

class GameStats:
    def __init__(self, user_id: int):
        if user_id not in player_stats:
            player_stats[user_id] = {
                "村人陣営": {"wins": 0, "losses": 0, "total_games": 0},
                "人狼陣営": {"wins": 0, "losses": 0, "total_games": 0}
            }
        self.stats = player_stats[user_id]

    def add_result(self, role: str, is_win: bool):
        """戦績を更新する"""
        team = "人狼陣営" if role in ["人狼", "狂人"] else "村人陣営"
        if is_win:
            self.stats[team]["wins"] += 1
        else:
            self.stats[team]["losses"] += 1
        self.stats[team]["total_games"] += 1

    def get_stats_display(self) -> str:
        """戦績の表示文字列を生成"""
        display = []
        for team, stats in self.stats.items():
            total = stats["total_games"]
            if total > 0:
                win_rate = stats["wins"] / total * 100
                display.append(
                    f"**{team}**\n"
                    f"🎮 総対戦数: {total}\n"
                    f"🏆 勝利: {stats['wins']}\n"
                    f"💔 敗北: {stats['losses']}\n"
                    f"📊 勝率: {win_rate:.1f}%\n"
                )
        return "\n".join(display) if display else "まだ対戦記録がありません"

# =============================
# 役職プリセットを改善（バランス調整）
# =============================
ROLE_PRESETS = {
    4: [
        ["村人", "村人", "占い師", "人狼"],  # 基本セット
        ["村人", "占い師", "狂人", "人狼"],  # 狂人セット
        ["村人", "騎士", "占い師", "人狼"],  # 騎士セット
    ],
    5: [
        ["村人", "村人", "占い師", "狂人", "人狼"],  # 基本セット
        ["村人", "騎士", "占い師", "狂人", "人狼"],  # 騎士セット
        ["村人", "霊媒師", "占い師", "狂人", "人狼"],  # 霊媒師セット
    ],
    6: [
        ["村人", "村人", "占い師", "騎士", "狂人", "人狼"],  # 基本セット
        ["村人", "村人", "占い師", "霊媒師", "狂人", "人狼"],  # 霊媒師セット
        ["村人", "騎士", "占い師", "霊媒師", "狂人", "人狼"],  # フルセット
    ],
    7: [
        ["村人", "村人", "占い師", "騎士", "霊媒師", "狂人", "人狼"],  # 基本セット
        ["村人", "村人", "占い師", "騎士", "狂人", "人狼", "人狼"],  # 人狼2セット
        ["村人", "村人", "占い師", "霊媒師", "狂人", "人狼", "人狼"],  # 霊媒師セット
    ],
    8: [  # 8人用セットを追加
        ["村人", "村人", "村人", "占い師", "騎士", "霊媒師", "狂人", "人狼"],  # バランスセット
        ["村人", "村人", "占い師", "騎士", "霊媒師", "狂人", "人狼", "人狼"],  # 人狼2セット
    ]
}

# 役職の説明文を改善（より詳細な説明）
ROLE_DESCRIPTIONS = {
    "村人": "特別な能力は持ちませんが、話し合いで人狼を見つけ出しましょう。投票の際は、各プレイヤーの発言や行動を注意深く観察することが重要です。",
    "人狼": "夜フェーズで村人を襲撃できます。村人に悟られないように立ち回りましょう。他の人狼と協力して、村人たちを欺く必要があります。",
    "占い師": "夜フェーズで1人を占い、人狼かどうかを知ることができます。初日はランダムな対象を占います。結果は「人狼」か「村人陣営」のどちらかです。",
    "狂人": "人狼陣営の村人です。人狼のことを知っていますが、村人のふりをして人狼を勝利に導きましょう。ただし、人狼は狂人が誰かを知りません。",
    "騎士": "夜フェーズで1人を守ることができます。その人が人狼に襲撃されても死亡しません。自分自身は守れません。",
    "霊媒師": "夜フェーズで処刑された人の役職を知ることができます。占い師の情報と組み合わせることで、より正確な推理が可能です。"
}

# フェーズごとの制限時間を調整
PHASE_TIMERS = {
    "join": 180,      # 参加募集時間（3分）
    "first_night": 60,  # 初日夜（1分）
    "night": 120,      # 夜フェーズ（2分）
    "discussion": 300,  # 議論フェーズ（5分）
    "vote": 120,       # 投票フェーズ（2分）
}

# =============================
# 部屋（ルーム）データ構造
# =============================
# werewolf_rooms[channel_id] = {
#   "role_set": [...],        # 選択された役職リスト
#   "players": [...],         # 参加者のdiscord.Userオブジェクトリスト
#   "role_map": {user_id: role},  # 役職割当てマップ
#   "alive": set(user_id, ...),   # 生存者のID集合
#   "dead": set(),                # 死亡者のID集合
#   "phase": str,                 # "night" / "day" / "vote"
#   "day_count": int,            # 経過日数（1日目から開始）
#   "night_actions": {
#       "werewolf_targets": [user_id, ...],  # 人狼が襲撃したID
#       "seer_target": Optional[user_id],    # 占い師が占ったID
#       "knight_target": Optional[user_id],  # 騎士が守ったID
#       "medium_result": Optional[str],      # 霊媒結果
#       "madman_info": Optional[str],        # 狂人が得た情報
#   },
#   "votes": {voter_id: target_id, ...},     # 投票マップ
#   "vote_deadline": datetime,               # 投票期限
#   "last_executed": Optional[user_id],      # 最後に処刑された人のID
# }
werewolf_rooms: dict[int, dict] = {}

# === エラーメッセージ定数 ===
ERROR_MESSAGES = {
    "room_not_exists": "❌ この部屋は存在しません。",
    "already_joined": "⚠️ すでに参加しています。",
    "room_full": "⚠️ 定員に達しています。",
    "dm_disabled": "⚠️ DM が送れませんでした。チャンネルでの通知に切り替えます。",
    "not_in_vote_phase": "⚠️ 今は投票フェーズではありません。",
    "not_werewolf": "⚠️ あなたには襲撃権限がありません。",
    "not_seer": "⚠️ あなたには占い権限がありません。",
    "game_in_progress": "⚠️ このチャンネルではすでにゲームが進行中です。",
    "no_game_in_progress": "⚠️ このチャンネルでは人狼ゲームが進行していません。",
    "not_player": "⚠️ このゲームの参加者ではありません。",
}

def setup_werewolf(bot: commands.Bot):
    """
    人狼ゲームの機能をbotに設定する
    """
    global werewolf_bot
    werewolf_bot = bot

    # === コマンド定義 ===
    @bot.tree.command(name="じんろう", description="人狼ゲームを始めます")
    @app_commands.describe(players="プレイヤー数（4〜7）")
    async def werewolf(interaction: discord.Interaction, players: int):
        try:
            # まず即座に応答を返す
            await interaction.response.defer()

            if not 4 <= players <= 7:
                await interaction.followup.send("⚠️ プレイヤー数は4〜7人で指定してください。", ephemeral=True)
                return

            cid = interaction.channel.id
            if cid in werewolf_rooms:
                await interaction.followup.send("⚠️ このチャンネルではすでにゲームが進行中です。", ephemeral=True)
                return

            role_sets = ROLE_PRESETS.get(players, [])
            if not role_sets:
                await interaction.followup.send("⚠️ 指定されたプレイヤー数の役職セットが見つかりません。", ephemeral=True)
                return

            # 4人ゲームの場合は注意書きを追加
            warning = ""
            if players == 4:
                warning = "\n⚠️ **4人ゲームは役職が限られるため、ゲームバランスが偏る可能性があります。**\n"

            # 役職セットの説明を生成
            set_descriptions = []
            for i, role_set in enumerate(role_sets, 1):
                role_counts = Counter(role_set)
                desc_parts = []
                for role, count in role_counts.items():
                    desc_parts.append(f"{role}×{count}")
                set_descriptions.append(f"セット{i}: {', '.join(desc_parts)}")

            description = "\n".join([
                f"🐺 人狼ゲームを開始します（{players}人）",
                warning,
                "**■ 参加方法**",
                "1. 以下から役職セットを選んでください",
                "2. その後表示される「参加する」ボタンを押してください",
                "3. 募集締切は3分です。時間内に参加者が揃わないとゲームは開始されません",
                "",
                "**■ 選択可能な役職セット**",
                *set_descriptions
            ])

            view = RoleSelectionView(role_sets)
            await interaction.followup.send(description, view=view)

        except Exception as e:
            # エラーハンドリング
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ エラーが発生しました。もう一度お試しください。", ephemeral=True)
            raise e  # エラーを再度発生させてログに記録

    @bot.tree.command(name="じんろう中断", description="進行中の人狼ゲームを中断します")
    async def cancel_game(interaction: discord.Interaction):
        # 進行中のゲームを探す
        channel_rooms = [room for room in werewolf_rooms.values() if room["channel"].id == interaction.channel.id]
        if not channel_rooms:
            await interaction.response.send_message("⚠️ このチャンネルで進行中のゲームはありません。", ephemeral=True)
            return

        room = channel_rooms[0]
        # 参加者かどうかチェック
        if not any(p.user.id == interaction.user.id for p in room["players"]):
            await interaction.response.send_message("⚠️ このゲームの参加者ではありません。", ephemeral=True)
            return

        # ゲームを中断
        room["started"] = False
        
        # アクティブなビューを全て停止
        if hasattr(room, "active_views"):
            for view in room.get("active_views", []):
                if not view.is_finished():
                    view.stop()
        
        # メッセージを送信
        await interaction.response.send_message("🛑 人狼ゲームを中断しました。")
        
        # 部屋情報を削除
        room_id = next(k for k, v in werewolf_rooms.items() if v is room)
        del werewolf_rooms[room_id]

    @bot.tree.command(name="じんろうリセット", description="人狼ゲームを強制終了し、部屋情報をクリアします")
    async def reset_werewolf(interaction: discord.Interaction):
        cid = interaction.channel.id
        if cid in werewolf_rooms:
            del werewolf_rooms[cid]
            await interaction.response.send_message("🔄 部屋をリセットしました。人狼ゲームを強制終了しました。", ephemeral=False)
        else:
            await interaction.response.send_message("❌ このチャンネルでは進行中の人狼ゲームがありません。", ephemeral=True)

    @bot.tree.command(name="じんろうヘルプ", description="人狼ゲームのルールと役職の説明を表示します")
    async def help_werewolf(interaction: discord.Interaction):
        help_text = [
            "🐺 **人狼ゲーム ヘルプ**",
            "",
            "**■ 基本ルール**",
            "1. 参加者にランダムで役職が配られます",
            "2. 昼と夜を繰り返しながらゲームが進行します",
            "3. 昼は全員で話し合い、投票で1人を処刑します",
            "4. 夜は各役職が特殊能力を使用できます",
            "",
            "**■ 勝利条件**",
            "・村人陣営：人狼を全滅させる",
            "・人狼陣営：生存者の半数以上を人狼にする（狂人は人数にカウントされません）",
            "",
            "**■ 役職説明**"
        ]
        
        # 役職説明を追加
        for role, desc in ROLE_DESCRIPTIONS.items():
            help_text.append(f"・**{role}**：{desc}")

        help_text.extend([
            "",
            "**■ コマンド一覧**",
            "・`/じんろう [人数]`：人狼ゲームを開始",
            "・`/じんろう中断`：進行中のゲームを中断",
            "・`/じんろうリセット`：ゲームを強制終了",
            "・`/じんろうヘルプ`：このヘルプを表示"
        ])

        await interaction.response.send_message("\n".join(help_text), ephemeral=True)

    @bot.tree.command(name="じんろう戦績", description="人狼ゲームの戦績を表示します")
    async def werewolf_stats(interaction: discord.Interaction, target: Optional[discord.User] = None):
        """戦績表示コマンド"""
        user = target or interaction.user
        stats = GameStats(user.id)
        await interaction.response.send_message(
            f"🏆 {user.mention} の人狼ゲーム戦績\n\n{stats.get_stats_display()}",
            ephemeral=True
        )

    # === イベントリスナー定義 ===
    @bot.event
    async def on_ready():
        await bot.tree.sync()
        print(f"{bot.user} 起動完了")

    # 既存のコードをsetup_werewolf関数内に移動
    return bot

# =============================
# JoinView の定義
# =============================
class JoinView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=JOIN_TIMEOUT)  # 3分でタイムアウト
        self.channel_id = channel_id

    async def on_timeout(self):
        """タイムアウト時の処理"""
        room = werewolf_rooms.get(self.channel_id)
        if not room:
            return

        channel = werewolf_bot.get_channel(self.channel_id)
        if not channel:
            return

        # 参加者が0人の場合は部屋を削除
        if len(room["players"]) == 0:
            del werewolf_rooms[self.channel_id]
            await channel.send("⏰ 参加者が集まらなかったため、募集を終了します。")
            return

        # 参加者が揃っていない場合は部屋を削除
        if len(room["players"]) < len(room["role_set"]):
            player_count = len(room["players"])
            needed_count = len(room["role_set"])
            del werewolf_rooms[self.channel_id]
            await channel.send(f"⏰ 制限時間（3分）が経過しました。（{player_count}/{needed_count}人）\n募集を終了します。")
            return

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            cid = self.channel_id
            room = werewolf_rooms.get(cid)
            if not room:
                await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
                return

            # 参加済みチェック
            if interaction.user.id in [u.id for u in room["players"]]:
                await interaction.response.send_message("⚠️ すでに参加しています。", ephemeral=True)
                return

            # 定員チェック
            if len(room["players"]) >= len(room["role_set"]):
                await interaction.response.send_message("⚠️ 定員に達しています。", ephemeral=True)
                return

            # 参加者リストに追加
            room["players"].append(interaction.user)
            remaining = len(room["role_set"]) - len(room["players"])
            
            try:
                # 参加メッセージを送信
                if remaining > 0:
                    await interaction.response.send_message(
                        f"✅ {interaction.user.mention} が参加しました！\n"
                        f"あと{remaining}人必要です。（制限時間: 残り約{int(JOIN_TIMEOUT - len(room['players']) * 10)}秒）", 
                        ephemeral=False
                    )
                else:
                    await interaction.response.send_message(
                        f"✅ {interaction.user.mention} が参加しました！\n"
                        "参加者が揃いました！ゲームを開始します。", 
                        ephemeral=False
                    )
            except discord.errors.InteractionResponded:
                # すでに応答済みの場合は、フォローアップメッセージを送信
                await interaction.followup.send(
                    f"✅ {interaction.user.mention} が参加しました！",
                    ephemeral=False
                )

            # 参加者数が役職数と揃ったら、役職配布 → 夜フェーズへ
            if len(room["players"]) == len(room["role_set"]):
                await asyncio.sleep(1)
                await send_roles_and_start(cid)

        except Exception as e:
            # エラーが発生した場合のフォールバック処理
            try:
                error_msg = f"⚠️ エラーが発生しました: {str(e)}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg, ephemeral=True)
                else:
                    await interaction.followup.send(error_msg, ephemeral=True)
            except:
                # 最後の手段として、チャンネルにエラーメッセージを送信
                channel = werewolf_bot.get_channel(self.channel_id)
                if channel:
                    await channel.send(f"⚠️ {interaction.user.mention} の参加処理中にエラーが発生しました。もう一度お試しください。")

# =============================
# フェーズ処理のヘルパー関数群
# =============================
@lru_cache(maxsize=128)
def check_win_condition_cached(alive_players: FrozenSet[int], wolf_players: FrozenSet[int]) -> Tuple[str, str]:
    """勝利条件のチェック（キャッシュ付き）"""
    wolf_count = len(wolf_players & alive_players)
    villager_count = len(alive_players) - wolf_count
    
    if wolf_count == 0:
        return "villagers", "人狼が全滅したため、村人陣営の勝利です！"
    elif wolf_count >= villager_count:
        return "werewolves", "人狼が村人の数以上になったため、人狼陣営の勝利です！"
    return "", ""

def check_win_condition(room: dict) -> Tuple[str, str]:
    """勝利条件のチェック（メインロジック）"""
    # キャッシュ用にFrozenSetに変換
    alive = frozenset(room["alive"])
    wolves = frozenset(uid for uid, role in room["role_map"].items() if role == "人狼")
    return check_win_condition_cached(alive, wolves)

async def process_night_results(cid: int):
    """夜フェーズの結果を処理"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    # アクション履歴をリセット
    room["voted_players"] = set()
    room["attacked_by_wolf"] = set()
    room["used_seer"] = set()
    room["used_knight"] = set()
    room.setdefault("active_views", [])

    # 初日の夜は最低待機時間を設ける
    if room["day_count"] == 1:
        await asyncio.sleep(1)  # 初日は1秒だけ待機

    # 騎士の護衛を処理
    protected_id = room["night_actions"].get("knight_target")
    
    # 襲撃処理（騎士に守られていない場合のみ）
    killed_ids = room["night_actions"]["werewolf_targets"][:]
    unique_killed = set(killed_ids)
    actually_killed = set()
    
    for victim_id in unique_killed:
        if victim_id != protected_id and victim_id in room["alive"]:
            room["alive"].remove(victim_id)
            room["dead"].add(victim_id)
            actually_killed.add(victim_id)

    # 朝の通知
    if room["day_count"] == 1:
        await channel.send("🌅 初日の朝になりました。昨夜は襲撃がありませんでした。")
    else:
        if actually_killed:
            killed_mentions = "、".join(f"{werewolf_bot.get_user(uid).display_name}" for uid in actually_killed)
            await channel.send(f"🌅 朝になりました。昨夜、{killed_mentions} が襲撃されました。")
        else:
            await channel.send("🌅 朝になりました。昨夜の襲撃は失敗したようです。")

    # 次のフェーズへ
    room["phase"] = PHASE_DAY
    room["day_count"] = room.get("day_count", 1) + 1
    
    # 議論フェーズの説明
    await channel.send(
        "💬 **議論の時間です**\n"
        "1. 話し合いで人狼を推理しましょう\n"
        "2. 議論が終わったら、次のフェーズで投票を行います\n"
        "3. 投票で最多票を集めたプレイヤーが処刑されます"
    )

    # 新しいフェーズスキップボタンを表示
    skip_view = PhaseSkipView(cid)
    room["active_views"].append(skip_view)  # アクティブなビューを記録
    await channel.send("⏩ 議論が終わったら、次のフェーズへスキップできます：", view=skip_view)

async def process_day_results(cid: int):
    """昼フェーズの投票結果を集計し、吊るし処理 → 勝敗判定 → 夜へ移行または終了。"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    vote_map = room.get("votes", {})
    target_id, count, vote_details = get_vote_results(vote_map, room)
    
    # 投票結果を表示
    if channel and vote_details:
        await send_vote_results(channel, vote_details)
    
    if target_id is None:
        # 投票なし→ランダム吊り
        if room["alive"]:
            chosen = random.choice(list(room["alive"]))
            room["alive"].remove(chosen)
            room["dead"].add(chosen)
            chosen_name = werewolf_bot.get_user(chosen).display_name
            await channel.send(f"🔨 誰も投票しなかったため、ランダムで {chosen_name} を吊りました。")
    else:
        if target_id in room["alive"]:
            room["alive"].remove(target_id)
            room["dead"].add(target_id)
            target_name = werewolf_bot.get_user(target_id).display_name
            # 同数得票の場合はその旨を表示
            max_voted = [uid for uid, v_count in Counter(vote_map.values()).items() if v_count == count]
            if len(max_voted) > 1:
                await channel.send(f"🔨 同数得票のため、ランダムで {target_name} が選ばれ、{count} 票で吊られました。")
            else:
                await channel.send(f"🔨 投票の結果、{target_name} に {count} 票が入り、吊られました。")

    # 勝敗判定
    winner, message = check_win_condition(room)
    if winner:
        await channel.send(message)
        await show_game_summary(cid)
        del werewolf_rooms[cid]
        return

    # 次の夜へ
    room["phase"] = PHASE_NIGHT
    room["night_actions"] = {
        "werewolf_targets": [],
        "seer_target": None,
        "knight_target": None,
        "medium_result": None,
        "madman_info": None
    }
    await channel.send("🌙 夜になります。各役職は DM を確認してください。")

    # 夜アクションの送信
    await send_night_actions(cid)

    # 新しいフェーズスキップボタンを表示
    view = PhaseSkipView(cid)
    await channel.send("⏩ 全員の準備が整ったら、次のフェーズへスキップできます：", view=view)

async def start_voting_phase(cid: int):
    """投票フェーズを開始する（UI改善版）"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    # フェーズを投票フェーズに変更
    room["phase"] = PHASE_VOTE
    room["votes"] = {}
    room["voted_players"] = set()
    room["vote_start_time"] = datetime.now()

    # 投票フェーズの開始を通知（改善版）
    embed = discord.Embed(
        title="🗳️ 投票フェーズ開始",
        description=(
            "全員で話し合って出た結論を投票に反映させましょう。\n"
            "以下の点に注意して投票してください：\n"
            "・占い結果や霊媒結果を総合的に判断\n"
            "・不自然な行動をしたプレイヤーに注目\n"
            "・投票先を決める際は理由も考える"
        ),
        color=discord.Color.blue()
    )
    embed.add_field(
        name="⏰ 制限時間",
        value=f"{PHASE_TIMERS['vote'] // 60}分",
        inline=True
    )
    embed.add_field(
        name="📊 現在の生存者",
        value=str(len(room["alive"])) + "人",
        inline=True
    )
    
    await channel.send(embed=embed)

    # 生存者のみに投票ボタンを表示（DMで）
    for user_id in room["alive"]:
        user = werewolf_bot.get_user(user_id)
        if user:
            view = VoteView(cid)
            # 生存者のみをボタンとして追加（自分以外）
            for target_id in room["alive"]:
                if target_id != user_id:
                    target_user = werewolf_bot.get_user(target_id)
                    if target_user:
                        view.add_item(VoteButton(target_user))
            try:
                await user.send(
                    "👇 投票する相手を選んでください。\n"
                    "投票は1回限りで変更できません。慎重に選択してください。",
                    view=view
                )
            except discord.Forbidden:
                # DMが送れない場合はチャンネルでメンション付きで表示
                await channel.send(f"<@{user_id}> 投票する相手を選んでください：", view=view)

    # 投票状況の定期更新タスクを開始
    asyncio.create_task(update_vote_status(cid))

    # 新しいフェーズスキップボタンを表示
    skip_view = PhaseSkipView(cid)
    room["active_views"].append(skip_view)
    await channel.send("⏩ 全員の投票が完了したら、次のフェーズへスキップできます：", view=skip_view)

async def update_vote_status(cid: int):
    """投票状況を定期的に更新（30秒ごと）"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    while room["phase"] == PHASE_VOTE:
        # 残り時間を計算
        elapsed = datetime.now() - room["vote_start_time"]
        remaining = PHASE_TIMERS["vote"] - int(elapsed.total_seconds())
        
        if remaining <= 0:
            # タイムアウト処理
            await process_vote_results(cid)
            break
        
        # 投票状況を更新
        status = get_vote_status_display(room)
        status += f"\n\n⏰ 残り時間: {remaining // 60}分{remaining % 60}秒"
        
        await channel.send(status)
        await asyncio.sleep(30)  # 30秒待機

async def process_vote_results(cid: int):
    """投票結果を処理し、次のフェーズへ移行する"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    vote_map = room.get("votes", {})
    target_id, count, vote_details = get_vote_results(vote_map, room)
    
    # 投票結果を表示
    if channel and vote_details:
        await send_vote_results(channel, vote_details)
    
    if target_id is None:
        # 投票なし→ランダム吊り
        if room["alive"]:
            chosen = random.choice(list(room["alive"]))
            room["alive"].remove(chosen)
            room["dead"].add(chosen)
            chosen_name = werewolf_bot.get_user(chosen).display_name
            await channel.send(f"🔨 誰も投票しなかったため、ランダムで {chosen_name} を吊りました。")
    else:
        if target_id in room["alive"]:
            room["alive"].remove(target_id)
            room["dead"].add(target_id)
            target_name = werewolf_bot.get_user(target_id).display_name
            # 同数得票の場合はその旨を表示
            max_voted = [uid for uid, v_count in Counter(vote_map.values()).items() if v_count == count]
            if len(max_voted) > 1:
                await channel.send(f"🔨 同数得票のため、ランダムで {target_name} が選ばれ、{count} 票で吊られました。")
            else:
                await channel.send(f"🔨 投票の結果、{target_name} に {count} 票が入り、吊られました。")

    # 勝敗判定
    winner, message = check_win_condition(room)
    if winner:
        await channel.send(message)
        await show_game_summary(cid)
        del werewolf_rooms[cid]
        return

    # 次の夜へ
    room["phase"] = PHASE_NIGHT
    room["night_actions"] = {
        "werewolf_targets": [],
        "seer_target": None,
        "knight_target": None,
        "medium_result": None,
        "madman_info": None
    }
    await channel.send("🌙 夜になります。各役職は DM を確認してください。")

    # 夜アクションの送信
    await send_night_actions(cid)

    # 新しいフェーズスキップボタンを表示
    view = PhaseSkipView(cid)
    await channel.send("⏩ 全員の準備が整ったら、次のフェーズへスキップできます：", view=view)

async def show_game_summary(cid: int):
    """
    ゲーム終了時に役職一覧と戦績を表示
    """
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    # 勝利陣営を判定
    winner, _ = check_win_condition(room)
    is_werewolf_win = winner == "werewolves"

    # 戦績を更新
    for user in room["players"]:
        uid = user.id
        role = room["role_map"][uid]
        is_werewolf_team = role in ["人狼", "狂人"]
        is_win = (is_werewolf_win and is_werewolf_team) or (not is_werewolf_win and not is_werewolf_team)
        GameStats(uid).add_result(role, is_win)

    # サマリーを生成
    summary = [
        "📊 **ゲーム結果**",
        f"🌅 経過日数: {room['day_count']}日",
        f"⌛ 総プレイ時間: {int((datetime.now() - room['start_time']).total_seconds() // 60)}分\n"
    ]

    # 陣営ごとにプレイヤーを分類
    villagers = []
    wolves = []
    for user in room["players"]:
        uid = user.id
        role = room["role_map"][uid]
        status = "💀" if uid in room["dead"] else "🏃"
        player_info = f"{status} <@{uid}>: {role}"
        if role in ["人狼", "狂人"]:
            wolves.append(player_info)
        else:
            villagers.append(player_info)

    summary.extend([
        "**村人陣営**",
        *villagers,
        "\n**人狼陣営**",
        *wolves
    ])

    # 戦績を追加
    summary.append("\n**📈 プレイヤー戦績**")
    for user in room["players"]:
        uid = user.id
        stats = GameStats(uid)
        summary.append(f"\n<@{uid}> の戦績:\n{stats.get_stats_display()}")

    await channel.send("\n".join(summary))

async def wait_for_votes(cid: int):
    """
    投票の待機処理（1分）
    """
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    await asyncio.sleep(60)  # 1分待機

    if room["phase"] == "day":  # まだ昼フェーズなら
        await process_day_results(cid)

async def wait_for_night_actions(cid: int):
    """
    夜フェーズで人狼・占い師のアクションが揃ったら朝処理を呼び出す
    """
    room = werewolf_rooms.get(cid)
    if not room:
        return

    # 生存している人狼の数を数える
    num_wolves = sum(1 for uid, role in room["role_map"].items() 
                    if role == "人狼" and uid in room["alive"])

    # 初日は人狼の襲撃なし
    is_first_night = room["day_count"] == 1
    if is_first_night:
        room["night_actions"]["werewolf_targets"] = []  # 初日は襲撃なし

    # アクションが揃うまで待機（初日は1分、それ以外は2分）
    wait_time = FIRST_NIGHT_TIME if is_first_night else NIGHT_TIME
    for _ in range(wait_time):
        if room["phase"] != "night":  # 夜フェーズが終了していたら
            return

        w_targets = room["night_actions"]["werewolf_targets"]
        s_target = room["night_actions"]["seer_target"]
        
        # 人狼の投票と占い師の占いが揃ったら（初日は人狼の投票は不要）
        if (is_first_night or len(w_targets) >= num_wolves) and (
            s_target is not None or  # 占い師の占い完了
            not any(uid for uid, role in room["role_map"].items()  # または生存占い師なし
                   if role == "占い師" and uid in room["alive"])
        ):
            await process_night_results(cid)
            return
        
        await asyncio.sleep(1)

    # タイムアウト処理
    if room["phase"] == "night":
        await handle_night_timeout(room, cid)

async def handle_night_timeout(room: dict, cid: int):
    """夜フェーズのタイムアウト処理"""
    channel = werewolf_bot.get_channel(cid)
    await channel.send("⏰ 時間切れです。未投票はランダムに決定されます。")
    
    is_first_night = room["day_count"] == 1
    num_wolves = sum(1 for uid, role in room["role_map"].items() 
                    if role == "人狼" and uid in room["alive"])

    # 人狼の未投票をランダム決定（初日以外）
    if not is_first_night and len(room["night_actions"]["werewolf_targets"]) < num_wolves:
        alive_targets = [uid for uid in room["alive"] 
                       if room["role_map"][uid] != "人狼"]
        if alive_targets:
            room["night_actions"]["werewolf_targets"].append(
                random.choice(alive_targets)
            )
    
    # 占い師の未投票をランダム決定
    if room["night_actions"]["seer_target"] is None:
        for uid, role in room["role_map"].items():
            if role == "占い師" and uid in room["alive"]:
                alive_targets = [tid for tid in room["alive"] if tid != uid]
                if alive_targets:
                    room["night_actions"]["seer_target"] = random.choice(alive_targets)
                break
    
    await process_night_results(cid)

# =============================
# ==== 夜フェーズ用 View / Button クラス ====
# =============================

class WolfNightView(discord.ui.View):
    def __init__(self, cid: int, uid: int):
        super().__init__(timeout=60)
        self.cid = cid
        self.user_id = uid
        room = werewolf_rooms.get(cid)
        if not room:
            return

        # 襲撃済みプレイヤーのセットを初期化
        if "attacked_by_wolf" not in room:
            room["attacked_by_wolf"] = set()

        # 生存プレイヤーのみを表示（自分以外）
        for target_id in room["alive"]:
            if target_id != uid and room["role_map"].get(target_id) != "人狼":
                target_user = werewolf_bot.get_user(target_id)
                if target_user:
                    button = WolfKillButton(cid, target_user)
                    # 既に襲撃済みの場合はボタンを無効化
                    if uid in room.get("attacked_by_wolf", set()):
                        button.disabled = True
                    self.add_item(button)

class SeerNightView(discord.ui.View):
    def __init__(self, cid: int, uid: int):
        super().__init__(timeout=60)
        self.cid = cid
        self.user_id = uid
        room = werewolf_rooms.get(cid)
        if not room:
            return

        # 占い済みプレイヤーのセットを初期化
        if "used_seer" not in room:
            room["used_seer"] = set()

        # 生存プレイヤーのみを表示（自分以外）
        for target_id in room["alive"]:
            if target_id != uid:
                target_user = werewolf_bot.get_user(target_id)
                if target_user:
                    button = SeerCheckButton(cid, target_user)
                    # 既に占い済みの場合はボタンを無効化
                    if uid in room.get("used_seer", set()):
                        button.disabled = True
                    self.add_item(button)

class KnightNightView(discord.ui.View):
    def __init__(self, cid: int, uid: int):
        super().__init__(timeout=60)
        self.cid = cid
        self.user_id = uid
        room = werewolf_rooms.get(cid)
        if not room:
            return

        # 護衛済みプレイヤーのセットを初期化
        if "used_knight" not in room:
            room["used_knight"] = set()

        # 生存プレイヤーのみを表示（自分以外）
        for target_id in room["alive"]:
            if target_id != uid:
                target_user = werewolf_bot.get_user(target_id)
                if target_user:
                    button = KnightProtectButton(cid, target_user)
                    # 既に護衛済みの場合はボタンを無効化
                    if uid in room.get("used_knight", set()):
                        button.disabled = True
                    self.add_item(button)

class WolfKillButton(discord.ui.Button):
    def __init__(self, cid: int, target_user: discord.User):
        super().__init__(
            label=f"襲撃: {target_user.display_name}",
            style=discord.ButtonStyle.danger
        )
        self.cid = cid
        self.target_user = target_user

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return
        if room["role_map"].get(uid) != "人狼":
            await interaction.response.send_message("⚠️ あなたには襲撃権限がありません。", ephemeral=True)
            return

        # 襲撃済みチェック
        if uid in room.get("attacked_by_wolf", set()):
            await interaction.response.send_message("⚠️ あなたは既に襲撃済みです。", ephemeral=True)
            return

        room["night_actions"]["werewolf_targets"].append(self.target_user.id)
        room.setdefault("attacked_by_wolf", set()).add(uid)
        
        # 全てのボタンを無効化
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(view=self.view)
        
        await interaction.followup.send(f"✅ {self.target_user.display_name} を襲撃対象に選択しました。", ephemeral=True)
        self.view.stop()

class SeerCheckButton(discord.ui.Button):
    def __init__(self, cid: int, target_user: discord.User):
        super().__init__(
            label=f"占う: {target_user.display_name}",
            style=discord.ButtonStyle.primary
        )
        self.cid = cid
        self.target_user = target_user

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return
        if room["role_map"].get(uid) != "占い師":
            await interaction.response.send_message("⚠️ あなたには占い権限がありません。", ephemeral=True)
            return

        # 占い済みチェック
        if uid in room.get("used_seer", set()):
            await interaction.response.send_message("⚠️ あなたは既に占い済みです。", ephemeral=True)
            return

        room["night_actions"]["seer_target"] = self.target_user.id
        room.setdefault("used_seer", set()).add(uid)
        
        # 全てのボタンを無効化
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(view=self.view)
        
        # 占い結果をすぐに通知
        target_role = room["role_map"][self.target_user.id]
        is_werewolf = target_role == "人狼"
        result = "人狼" if is_werewolf else "村人陣営"
        await interaction.followup.send(f"🔮 {self.target_user.display_name} を占いました。\n結果：**{result}**", ephemeral=True)
        self.view.stop()

class KnightProtectButton(discord.ui.Button):
    def __init__(self, cid: int, target_user: discord.User):
        super().__init__(
            label=f"護衛: {target_user.display_name}",
            style=discord.ButtonStyle.success
        )
        self.cid = cid
        self.target_user = target_user

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return
        if room["role_map"].get(uid) != "騎士":
            await interaction.response.send_message("⚠️ あなたには護衛権限がありません。", ephemeral=True)
            return

        # 護衛済みチェック
        if uid in room.get("used_knight", set()):
            await interaction.response.send_message("⚠️ あなたは既に護衛済みです。", ephemeral=True)
            return

        room["night_actions"]["knight_target"] = self.target_user.id
        room.setdefault("used_knight", set()).add(uid)
        
        # 全てのボタンを無効化
        for child in self.view.children:
            child.disabled = True
        await interaction.response.edit_message(view=self.view)
        
        await interaction.followup.send(f"🛡️ {self.target_user.display_name} を護衛対象に選択しました。", ephemeral=True)
        self.view.stop()

# =============================
# ==== 昼フェーズ用 View / Button クラス ====
# =============================

class VoteView(discord.ui.View):
    def __init__(self, cid: int):
        super().__init__(timeout=180)  # 3分でタイムアウト
        self.cid = cid
        self.room = werewolf_rooms.get(cid)
        self.button_states = {}  # ユーザーごとのボタン状態を保持
        if not self.room:
            return
        
        # 投票済みプレイヤーのセットを初期化
        if "voted_players" not in self.room:
            self.room["voted_players"] = set()

    async def on_timeout(self):
        """タイムアウト時の処理"""
        room = werewolf_rooms.get(self.cid)
        # 部屋が存在しない、または中断されている場合は何もしない
        if not room or not room.get("started", False):
            return

        channel = werewolf_bot.get_channel(self.cid)
        if channel:
            await channel.send("⏰ 投票時間が終了しました。未投票者は自動的にランダム投票となります。")
            await process_day_results(self.cid)

    def stop(self):
        """ビューを停止する際の処理"""
        self.timeout = None  # タイムアウトを無効化
        super().stop()

class VoteButton(discord.ui.Button):
    def __init__(self, target_player: discord.User):
        super().__init__(
            label=f"{target_player.display_name}",
            style=discord.ButtonStyle.danger,
            custom_id=str(target_player.id)
        )
        self.target_player = target_player

    async def callback(self, interaction: discord.Interaction):
        try:
            cid = interaction.channel.id
            room = werewolf_rooms.get(cid)
            if not room or room["phase"] != PHASE_VOTE:  # フェーズ判定を修正
                await interaction.response.send_message("⚠️ 今は投票フェーズではありません。", ephemeral=True)
                return

            voter_id = interaction.user.id
            
            # 生存者チェック
            if voter_id not in room["alive"]:
                await interaction.response.send_message("⚠️ 死亡したプレイヤーは投票できません。", ephemeral=True)
                return

            # 投票を記録
            room.setdefault("votes", {})[voter_id] = int(self.custom_id)
            room.setdefault("voted_players", set()).add(voter_id)

            # このユーザーのカスタムビューを作成（ボタンの状態を個別に管理）
            custom_view = VoteView(cid)
            for button in custom_view.children:
                if isinstance(button, VoteButton):
                    # 投票済みのユーザーには全ボタンを無効化
                    button.disabled = True
            
            # このユーザーにのみ無効化されたビューを表示
            await interaction.response.edit_message(view=custom_view)
            
            # 投票完了メッセージ
            await interaction.followup.send(
                f"✅ {self.target_player.display_name} に投票しました。",
                ephemeral=True
            )

            # 投票状況を全体に通知
            channel = interaction.channel
            total_voters = len(room["alive"])  # 生存者数
            current_votes = len(room["votes"])
            await channel.send(f"💫 投票状況: {current_votes}/{total_voters} 人が投票済み")

            # 全員が投票したかチェック
            if current_votes == total_voters:
                await process_vote_results(cid)

        except Exception as e:
            try:
                error_msg = f"⚠️ 投票中にエラーが発生しました: {str(e)}"
                if not interaction.response.is_done():
                    await interaction.response.send_message(error_msg, ephemeral=True)
                else:
                    await interaction.followup.send(error_msg, ephemeral=True)
            except:
                channel = interaction.channel
                if channel:
                    await channel.send(f"⚠️ {interaction.user.mention} の投票処理中にエラーが発生しました。")

# =============================
# ==== メインコマンド・役職選択 View ====
# =============================

class RoleSetButton(discord.ui.Button):
    def __init__(self, role_set, index):
        label = f"セット{index+1}: " + "・".join(role_set)
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.role_set = role_set

    async def callback(self, interaction: discord.Interaction):
        cid = interaction.channel.id

        # 部屋オブジェクトを初期化
        werewolf_rooms[cid] = initialize_room(cid, self.role_set)

        # どのセットが選ばれたかをチャンネルに表示
        chosen_text = "・".join(self.role_set)
        await interaction.response.send_message(f"🧩 <@{interaction.user.id}> がセットを選択しました：\n**{chosen_text}**")

        # 参加ボタンを表示
        view = JoinView(cid)
        await interaction.followup.send("参加者は以下のボタンを押して参加してください：", view=view)

class RoleSelectionView(discord.ui.View):
    def __init__(self, role_sets):
        super().__init__(timeout=60)
        for i, rs in enumerate(role_sets):
            self.add_item(RoleSetButton(rs, i))

# =============================
# ==== 役職配布＆夜フェーズ開始処理 ====
# =============================

async def send_roles_and_start(cid: int):
    """役職配布と初日の処理"""
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    players = room["players"]
    roles = room["role_set"][:]
    random.shuffle(roles)
    random.shuffle(players)

    # 役職配布と初期化
    room["role_map"] = {user.id: role for user, role in zip(players, roles)}
    room["alive"] = set(user.id for user in players)
    room["dead"] = set()
    room["phase"] = PHASE_NIGHT
    room["day_count"] = 1
    room["night_actions"] = {
        "werewolf_targets": [],
        "seer_target": None,
        "knight_target": None,
        "medium_result": None,
        "madman_info": None
    }
    room["votes"] = {}
    room["last_executed"] = None

    # 役職通知とアクション要求
    for user in players:
        uid = user.id
        role = room["role_map"][uid]
        
        # 基本の役職説明
        role_desc = ROLE_DESCRIPTIONS.get(role, "役職の説明がありません")
        try:
            await user.send(f"🎭 あなたの役職は **{role}** です。\n{role_desc}")
        except discord.Forbidden:
            await channel.send(f"⚠️ <@{uid}> に DM が送れませんでした。")
            continue

        # 特殊役職の追加情報
        if role == "人狼":
            # 人狼同士を知らせる
            wolves = [uid for uid, r in room["role_map"].items() if r == "人狼"]
            other_wolves = [wid for wid in wolves if wid != uid]
            if other_wolves:
                wolf_info = "、".join(f"{werewolf_bot.get_user(wid).display_name}" for wid in other_wolves)
                await user.send(f"🐺 仲間の人狼は {wolf_info} です。")
            # 初日は襲撃なしを通知
            await user.send("🌙 初日の夜は襲撃できません。")
        elif role == "占い師":
            # 初日は人狼以外（白）のプレイヤーからランダムに占う
            possible_targets = [pid for pid in room["alive"] 
                              if pid != uid and room["role_map"][pid] != "人狼"]
            if possible_targets:
                target = random.choice(possible_targets)
                room["night_actions"]["seer_target"] = target
                target_role = room["role_map"][target]
                is_werewolf = target_role == "人狼"  # 必ずFalseになるはず
                result = "人狼" if is_werewolf else "村人陣営"
                target_name = werewolf_bot.get_user(target).display_name
                await user.send(f"🔮 初日の占い対象は {target_name} にランダムで決定されました。\n結果：**{result}**")

    # 全体通知
    await channel.send("🌙 初日の夜です。各役職は DM を確認してください。")

    # 新しいフェーズスキップボタンを表示
    view = PhaseSkipView(cid)
    await channel.send("⏩ 全員の準備が整ったら、次のフェーズへスキップできます：", view=view)
    
    # 夜アクション待機（初日は1分）
    asyncio.create_task(wait_for_night_actions(cid))

# === 投票処理の改善 ===
def get_vote_results(votes: dict, room: dict) -> tuple[int, int, list]:
    """
    投票結果から最多得票者とその得票数を返す。
    同数の場合はランダムに選択。
    """
    if not votes:
        return None, 0, []
    
    # 投票結果を集計
    counter = Counter(votes.values())
    max_votes = max(counter.values())
    max_voted = [uid for uid, count in counter.items() if count == max_votes]
    
    # 投票状況の詳細を生成
    vote_details = []
    for voter_id, target_id in votes.items():
        voter = werewolf_bot.get_user(voter_id)
        target = werewolf_bot.get_user(target_id)
        if voter and target:
            vote_details.append(f"{voter.display_name} → {target.display_name}")
    
    chosen = random.choice(max_voted)
    return chosen, max_votes, vote_details

async def send_vote_results(channel: discord.TextChannel, vote_details: list):
    """投票結果をチャンネルに表示"""
    vote_summary = "\n".join(vote_details)
    await channel.send(f"📊 **投票結果**\n{vote_summary}")

async def send_dm_or_channel(user: discord.User, channel: discord.TextChannel, message: str, view: discord.ui.View = None) -> bool:
    """
    DMを送信し、失敗した場合はチャンネルにメンションで送信。
    戻り値: DMの送信に成功したかどうか
    """
    try:
        if view:
            await user.send(message, view=view)
        else:
            await user.send(message)
        return True
    except discord.Forbidden:
        mention_msg = f"<@{user.id}> {message}"
        if view:
            await channel.send(mention_msg, view=view)
        else:
            await channel.send(mention_msg)
        return False

class PhaseSkipView(discord.ui.View):
    def __init__(self, cid: int):
        super().__init__(timeout=None)
        self.cid = cid

    def stop(self):
        """ビューを停止する際の処理"""
        super().stop()

    @discord.ui.button(label="次のフェーズへ", style=discord.ButtonStyle.danger)
    async def skip_phase(self, interaction: discord.Interaction, button: discord.ui.Button):
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return

        # 参加者チェック
        if interaction.user.id not in [p.id for p in room["players"]]:
            await interaction.response.send_message("⚠️ このゲームの参加者ではありません。", ephemeral=True)
            return

        # ボタンを無効化して再クリックを防止
        button.disabled = True
        await interaction.response.edit_message(view=self)

        try:
            # アクティブなビューを全て停止
            for view in room.get("active_views", []):
                if not view.is_finished():
                    view.stop()
            room["active_views"] = []  # リセット

            if room["phase"] == "night":
                # 初日の夜は特別処理
                if room["day_count"] == 1:
                    # 初日の夜は襲撃なしで朝に移行
                    room["night_actions"]["werewolf_targets"] = []
                    await process_night_results(self.cid)
                else:
                    await process_night_results(self.cid)
            elif room["phase"] == "day":
                # 議論フェーズから投票フェーズへ
                await start_voting_phase(self.cid)
            elif room["phase"] == "vote":
                # 投票フェーズから結果処理へ
                await process_vote_results(self.cid)

            await interaction.followup.send("⏩ フェーズをスキップしました。", ephemeral=False)
        except Exception as e:
            await interaction.followup.send(f"⚠️ エラーが発生しました: {str(e)}", ephemeral=True)

# =============================
# ==== 夜フェーズでの役職アクション通知を改善 ====
# =============================
async def send_night_actions(cid: int):
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    for user in room["players"]:
        uid = user.id
        if uid not in room["alive"]:
            continue

        role = room["role_map"][uid]
        if role == "人狼":
            if room["day_count"] == 1:
                await send_dm_or_channel(user, channel, "🌙 初日の夜は襲撃できません。")
            else:
                view = WolfNightView(cid, uid)
                await send_dm_or_channel(user, channel, "🌙 襲撃する相手を選んでください：", view)
        elif role == "占い師":
            view = SeerNightView(cid, uid)
            await send_dm_or_channel(user, channel, "🌙 占う相手を選んでください：", view)
        elif role == "騎士":
            view = KnightNightView(cid, uid)
            await send_dm_or_channel(user, channel, "🌙 護衛する相手を選んでください：", view)
        elif role == "狂人":
            await send_dm_or_channel(user, channel, "🌙 あなたは狂人です。人狼陣営の勝利のために行動してください。")
        else:
            await send_dm_or_channel(user, channel, "🌙 あなたは特別な行動はできません。")

# =============================
# ==== 部屋の初期化処理を改善 ====
# =============================
def initialize_room(cid: int, role_set: list):
    """部屋の初期化処理を共通化"""
    return {
        "role_set": role_set,
        "players": [],
        "role_map": {},
        "alive": set(),
        "dead": set(),
        "phase": None,
        "day_count": 1,
        "night_actions": {
            "werewolf_targets": [],
            "seer_target": None,
            "knight_target": None,
            "medium_result": None
        },
        "votes": {},
        "voted_players": set(),
        "attacked_by_wolf": set(),
        "used_seer": set(),
        "used_knight": set(),
        "last_executed": None,
        "channel_id": cid
    }

# ゲーム進行状況の表示を改善
def get_game_status_display(room: dict) -> str:
    """ゲームの現在の状態を表示する文字列を生成"""
    phase_emojis = {
        PHASE_NIGHT: "🌙",
        PHASE_DAY: "☀️",
        PHASE_VOTE: "🗳️"
    }
    
    status = [
        f"{phase_emojis.get(room['phase'], '❓')} **{room['day_count']}日目 {room['phase']}フェーズ**",
        f"👥 生存者: {len(room['alive'])}人",
        f"💀 死亡者: {len(room['dead'])}人",
        f"⏱️ 経過時間: {int((datetime.now() - room['start_time']).total_seconds() // 60)}分"
    ]
    
    # 死亡者一覧（いる場合のみ）
    if room['dead']:
        dead_players = []
        for uid in room['dead']:
            user = werewolf_bot.get_user(uid)
            role = room['role_map'][uid]
            if user:
                dead_players.append(f"{user.display_name}({role})")
        status.append(f"\n☠️ 死亡者一覧: {', '.join(dead_players)}")
    
    return "\n".join(status)

# 投票フェーズの表示を改善
def get_vote_status_display(room: dict) -> str:
    """投票状況の表示を生成"""
    voted = len(room.get('votes', {}))
    total = len(room['alive'])
    remaining = total - voted
    
    status = [
        "🗳️ **投票状況**",
        f"✅ 投票済み: {voted}人",
        f"⏳ 未投票: {remaining}人",
        f"👥 投票権限者: {total}人"
    ]
    
    # 投票済みプレイヤーを表示
    if voted > 0:
        voted_players = []
        for voter_id in room['votes'].keys():
            voter = werewolf_bot.get_user(voter_id)
            if voter:
                voted_players.append(voter.display_name)
        status.append(f"\n投票済みプレイヤー: {', '.join(voted_players)}")
    
    return "\n".join(status)

# エラーハンドリングの改善
class WerewolfGameError(Exception):
    """人狼ゲーム固有のエラー"""
    pass

class GameNotFoundError(WerewolfGameError):
    """ゲームが見つからない場合のエラー"""
    pass

class InvalidPhaseError(WerewolfGameError):
    """不正なフェーズ遷移のエラー"""
    pass

class PlayerNotFoundError(WerewolfGameError):
    """プレイヤーが見つからない場合のエラー"""
    pass

# エラーハンドリング付きの安全なプレイヤー操作
def get_player_safely(user_id: int) -> discord.User:
    """プレイヤーを安全に取得"""
    user = werewolf_bot.get_user(user_id)
    if not user:
        raise PlayerNotFoundError(f"プレイヤー(ID: {user_id})が見つかりません")
    return user

def get_room_safely(channel_id: int) -> dict:
    """ゲームルームを安全に取得"""
    room = werewolf_rooms.get(channel_id)
    if not room:
        raise GameNotFoundError(f"チャンネル(ID: {channel_id})でゲームが見つかりません")
    return room

# 非同期処理の改善
async def safe_dm(user: discord.User, content: str, **kwargs) -> bool:
    """DMを安全に送信（失敗してもエラーにならない）"""
    try:
        await user.send(content, **kwargs)
        return True
    except discord.Forbidden:
        return False
    except Exception as e:
        print(f"DM送信エラー(ユーザー: {user.id}): {e}")
        return False

# ゲーム状態の検証
def validate_game_state(room: dict) -> None:
    """ゲーム状態の整合性を検証"""
    # プレイヤー情報の検証
    for user_id in room["players"]:
        if user_id not in room["role_map"]:
            raise WerewolfGameError(f"プレイヤー(ID: {user_id})の役職が未設定です")
    
    # 生存者と死亡者の重複チェック
    if set(room["alive"]) & set(room["dead"]):
        raise WerewolfGameError("生存者と死亡者が重複しています")
    
    # 全プレイヤーが生存または死亡に含まれているか確認
    all_players = set(room["players"])
    accounted_players = set(room["alive"]) | set(room["dead"])
    if all_players != accounted_players:
        raise WerewolfGameError("プレイヤーの状態が不正です")

# エラーハンドリング付きのコマンド実行
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """コマンドエラーのハンドリング"""
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(
            f"⏳ コマンドのクールダウン中です。{error.retry_after:.1f}秒後に再試行してください。",
            ephemeral=True
        )
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "⚠️ このコマンドを実行する権限がありません。",
            ephemeral=True
        )
    elif isinstance(error, WerewolfGameError):
        await interaction.response.send_message(
            f"🚫 ゲームエラー: {str(error)}",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "❌ 予期せぬエラーが発生しました。しばらく待ってから再試行してください。",
            ephemeral=True
        )
        # エラーログ出力
        print(f"コマンドエラー: {error}")

# パフォーマンス最適化
def cleanup_inactive_games():
    """非アクティブなゲームをクリーンアップ"""
    current_time = datetime.now()
    inactive_channels = []
    
    for channel_id, room in werewolf_rooms.items():
        # 最後のアクティビティから30分以上経過したゲームを終了
        if "last_activity" in room:
            inactive_time = (current_time - room["last_activity"]).total_seconds()
            if inactive_time > 1800:  # 30分
                inactive_channels.append(channel_id)
    
    # 非アクティブなゲームを削除
    for channel_id in inactive_channels:
        del werewolf_rooms[channel_id]

# 定期的なクリーンアップタスク
@tasks.loop(minutes=15)
async def cleanup_task():
    """定期的なクリーンアップを実行"""
    cleanup_inactive_games()

# ゲーム開始時の処理を改善
async def start_game(interaction: discord.Interaction):
    """ゲームを開始する（エラーハンドリング付き）"""
    try:
        channel_id = interaction.channel_id
        room = get_room_safely(channel_id)
        
        # ゲーム開始前の検証
        if len(room["players"]) not in ROLE_PRESETS:
            raise WerewolfGameError(f"プレイヤー数({len(room['players'])})が不正です")
        
        # ゲーム状態の初期化
        room["phase"] = PHASE_NIGHT
        room["day_count"] = 1
        room["start_time"] = datetime.now()
        room["last_activity"] = datetime.now()
        
        # 役職の割り当て
        await assign_roles(channel_id)
        
        # ゲーム状態の検証
        validate_game_state(room)
        
        # ゲーム開始メッセージ
        await interaction.channel.send(
            "🎮 **人狼ゲームを開始します**\n" +
            get_game_status_display(room)
        )
        
        # 各プレイヤーに役職を通知
        for user_id in room["players"]:
            user = get_player_safely(user_id)
            role = room["role_map"][user_id]
            
            # 役職に応じた追加情報を付加
            additional_info = ""
            if role == "人狼":
                # 他の人狼を通知
                other_wolves = [uid for uid, r in room["role_map"].items() if r == "人狼" and uid != user_id]
                if other_wolves:
                    wolf_names = [get_player_safely(uid).display_name for uid in other_wolves]
                    additional_info = f"\n\n🐺 仲間の人狼: {', '.join(wolf_names)}"
            
            await safe_dm(
                user,
                f"あなたの役職は **{role}** です。\n" +
                ROLE_DESCRIPTIONS[role] +
                additional_info
            )
        
        # 初日夜フェーズを開始
        await start_first_night(channel_id)
        
    except WerewolfGameError as e:
        await interaction.channel.send(f"🚫 ゲーム開始エラー: {str(e)}")
    except Exception as e:
        await interaction.channel.send("❌ 予期せぬエラーが発生しました。")
        print(f"ゲーム開始エラー: {e}")
