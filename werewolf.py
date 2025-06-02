# werewolf.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import random
from dotenv import load_dotenv
from collections import Counter

# グローバル変数の定義
werewolf_bot = None
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# =============================
# 役職プリセット
# =============================
# {プレイヤー人数: [役職セット1, 役職セット2, ...]}
ROLE_PRESETS = {
    3: [
        ["村人", "村人", "人狼"],  # 基本セット
        ["村人", "占い師", "人狼"],  # 占い師セット
        ["村人", "狂人", "人狼"],  # 狂人セット
    ],
    4: [
        ["村人", "村人", "村人", "人狼"],  # 基本セット
        ["村人", "占い師", "村人", "人狼"],  # 占い師セット
        ["村人", "村人", "狂人", "人狼"],  # 狂人セット
        ["村人", "占い師", "狂人", "人狼"],  # バランスセット
    ],
    5: [
        ["村人", "村人", "占い師", "狂人", "人狼"],  # 基本セット
        ["村人", "村人", "村人", "人狼", "人狼"],  # 人狼2セット
        ["村人", "村人", "占い師", "人狼", "人狼"],  # 占い師・人狼2セット
        ["村人", "占い師", "狂人", "人狼", "人狼"],  # フルバリエーションセット
    ],
    6: [
        ["村人", "村人", "村人", "占い師", "狂人", "人狼"],  # 基本セット
        ["村人", "村人", "占い師", "狂人", "人狼", "人狼"],  # 人狼2セット
        ["村人", "村人", "村人", "占い師", "人狼", "人狼"],  # 占い師・人狼2セット
        ["村人", "村人", "占い師", "狂人", "狂人", "人狼"],  # 狂人2セット
    ],
    7: [
        ["村人", "村人", "村人", "占い師", "狂人", "人狼", "人狼"],  # 基本セット
        ["村人", "村人", "村人", "占い師", "占い師", "人狼", "人狼"],  # 占い師2セット
        ["村人", "村人", "村人", "占い師", "狂人", "狂人", "人狼"],  # 狂人2セット
        ["村人", "村人", "占い師", "狂人", "狂人", "人狼", "人狼"],  # フルバリエーションセット
    ],
}

# 役職の説明文
ROLE_DESCRIPTIONS = {
    "村人": "特別な能力は持ちませんが、話し合いで人狼を見つけ出しましょう。",
    "人狼": "夜フェーズで村人を襲撃できます。村人に悟られないように立ち回りましょう。",
    "占い師": "夜フェーズで1人を占い、人狼かどうかを知ることができます。",
    "狂人": "人狼陣営の村人です。人狼のことを知っていますが、村人のふりをして人狼を勝利に導きましょう。"
}

# =============================
# 部屋（ルーム）データ構造
# =============================
# werewolf_rooms[channel_id] = {
#   "role_set": [...],        # 選択された役職リスト（例：["村人","占い師","人狼"]）
#   "players": [...],         # 参加者の discord.User オブジェクトリスト
#   "role_map": {user_id: role},  # 役職割当てマップ
#   "alive": set(user_id, ...),   # 生存者の ID 集合
#   "dead": set(),                # 死亡者の ID 集合
#   "phase": str,                 # "night" / "day" / "vote"
#   "night_actions": {
#       "werewolf_targets": [user_id, ...],  # 人狼が襲撃した ID リスト
#       "seer_target": Optional[user_id],    # 占い師が占った ID
#       "madman_info": Optional[str],        # 狂人が得た情報
#   },
#   "votes": {voter_id: target_id, ...},     # 昼フェーズの投票マップ
#   "last_vote_time": datetime,              # 最後の投票時刻
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
    @app_commands.describe(players="プレイヤー数（3〜7）")
    async def werewolf(interaction: discord.Interaction, players: int):
        if not 3 <= players <= 7:
            await interaction.response.send_message("⚠️ プレイヤー数は3〜7人で指定してください。", ephemeral=True)
            return

        cid = interaction.channel.id
        if cid in werewolf_rooms:
            await interaction.response.send_message("⚠️ このチャンネルではすでにゲームが進行中です。", ephemeral=True)
            return

        role_sets = ROLE_PRESETS.get(players, [])
        if not role_sets:
            await interaction.response.send_message("⚠️ 指定されたプレイヤー数の役職セットが見つかりません。", ephemeral=True)
            return

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
            "以下から役職セットを選んでください：",
            "",  # 空行を追加
            *set_descriptions
        ])

        view = RoleSelectionView(role_sets)
        await interaction.response.send_message(description, view=view)

    @bot.tree.command(name="じんろう中断", description="進行中の人狼ゲームを中断します")
    async def cancel_game(interaction: discord.Interaction):
        cid = interaction.channel.id
        if cid not in werewolf_rooms:
            await interaction.response.send_message("⚠️ このチャンネルでは人狼ゲームが進行していません。", ephemeral=True)
            return

        room = werewolf_rooms[cid]
        # 参加者チェック
        if interaction.user.id not in [p.id for p in room["players"]]:
            await interaction.response.send_message("⚠️ このゲームの参加者ではありません。", ephemeral=True)
            return

        # ゲーム中断
        del werewolf_rooms[cid]
        await interaction.response.send_message("🛑 人狼ゲームを中断しました。", ephemeral=False)

    @bot.tree.command(name="じんろうリセット", description="人狼ゲームを強制終了し、部屋情報をクリアします")
    async def reset_werewolf(interaction: discord.Interaction):
        cid = interaction.channel.id
        if cid in werewolf_rooms:
            del werewolf_rooms[cid]
            await interaction.response.send_message("🔄 部屋をリセットしました。人狼ゲームを強制終了しました。", ephemeral=False)
        else:
            await interaction.response.send_message("❌ このチャンネルでは進行中の人狼ゲームがありません。", ephemeral=True)

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
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
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
        await interaction.response.send_message(f"✅ {interaction.user.mention} が参加しました！", ephemeral=False)

        # 参加者数が役職数と揃ったら、役職配布 → 夜フェーズへ
        if len(room["players"]) == len(room["role_set"]):
            await asyncio.sleep(1)
            await send_roles_and_start(cid)

# =============================
# フェーズ処理のヘルパー関数群
# =============================
def check_win_condition(room: dict) -> str | None:
    """
    勝敗判定を行い、勝利チームを返す。
    - 村人勝利: "villagers"
    - 人狼勝利: "werewolves"
    - 継続: None
    """
    alive_ids = list(room["alive"])
    roles_alive = [room["role_map"][uid] for uid in alive_ids]
    num_wolves = roles_alive.count("人狼")
    num_villagers = len(alive_ids) - num_wolves

    if num_wolves == 0:
        return "villagers"
    if num_wolves >= num_villagers:
        return "werewolves"
    return None

async def process_night_results(cid: int):
    """
    夜フェーズのアクションを集計し、朝フェーズへ移行。
    """
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    # --- 襲撃処理 ---
    killed_ids = room["night_actions"]["werewolf_targets"][:]
    unique_killed = set(killed_ids)
    for victim_id in unique_killed:
        if victim_id in room["alive"]:
            room["alive"].remove(victim_id)
            room["dead"].add(victim_id)

    if unique_killed:
        killed_mentions = "、".join(f"<@{uid}>" for uid in unique_killed)
        await channel.send(f"🌅 朝です。昨夜、{killed_mentions} が襲撃されました。")
    else:
        await channel.send("🌅 朝です。昨夜の襲撃はありませんでした。")

    # --- 占い師処理 ---
    seer_target = room["night_actions"]["seer_target"]
    if seer_target is not None:
        seer_id = None
        for uid, role in room["role_map"].items():
            if role == "占い師" and uid in room["alive"]:
                seer_id = uid
                break
        if seer_id:
            seer_user = await werewolf_bot.fetch_user(seer_id)
            result_role = room["role_map"].get(seer_target, None)
            if result_role == "人狼":
                msg = f"🔮 あなたが占った <@{seer_target}> は **人狼** でした。"
            else:
                msg = f"🔮 あなたが占った <@{seer_target}> は **村人陣営** でした。"
            try:
                await seer_user.send(msg)
            except discord.Forbidden:
                await channel.send(f"⚠️ 占い師 <@{seer_id}> に DM 送信できません。DM を有効にしてください。")

    # --- 昼フェーズの開始 ---
    room["phase"] = "day"
    room["votes"] = {}
    await channel.send("💬 昼の議論を開始します。1分以内に投票を行ってください。以下のボタンから投票できます。")

    vote_view = VoteView(cid)
    await channel.send("🔻 投票する人を選択してください：", view=vote_view)

    # 投票待機
    asyncio.create_task(wait_for_votes(cid))

async def process_day_results(cid: int):
    """
    昼フェーズの投票結果を集計し、吊るし処理 → 勝敗判定 → 夜へ移行または終了。
    """
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    vote_map = room.get("votes", {})
    target_id, count = get_vote_results(vote_map)
    
    if target_id is None:
        # 投票なし→ランダム吊り
        if room["alive"]:
            chosen = random.choice(list(room["alive"]))
            room["alive"].remove(chosen)
            room["dead"].add(chosen)
            await channel.send(f"🔨 誰も投票しなかったため、ランダムで <@{chosen}> を吊りました。")
    else:
        if target_id in room["alive"]:
            room["alive"].remove(target_id)
            room["dead"].add(target_id)
            # 同数得票の場合はその旨を表示
            max_voted = [uid for uid, v_count in Counter(vote_map.values()).items() if v_count == count]
            if len(max_voted) > 1:
                await channel.send(f"🔨 同数得票のため、ランダムで <@{target_id}> が選ばれ、{count} 票で吊られました。")
            else:
                await channel.send(f"🔨 投票の結果、<@{target_id}> に {count} 票が入り、吊られました。")

    # 勝敗判定
    winner = check_win_condition(room)
    if winner == "villagers":
        await channel.send("🎉 村人陣営の勝利です！")
        await show_game_summary(cid)
        del werewolf_rooms[cid]
        return
    if winner == "werewolves":
        await channel.send("🐺 人狼陣営の勝利です！")
        await show_game_summary(cid)
        del werewolf_rooms[cid]
        return

    # 次の夜へ
    room["phase"] = "night"
    room["night_actions"] = {
        "werewolf_targets": [], 
        "seer_target": None,
        "madman_info": None
    }
    await channel.send("🌙 夜になります。各役職は DM を確認してください。")

    for user in room["players"]:
        uid = user.id
        if uid not in room["alive"]:
            continue
            
        role = room["role_map"][uid]
        if role == "人狼":
            view = WolfNightView(cid, uid)
            success = await send_dm_or_channel(
                user, channel,
                "🌙 【夜フェーズ】 襲撃する相手を選んでください：",
                view
            )
        elif role == "占い師":
            view = SeerNightView(cid, uid)
            success = await send_dm_or_channel(
                user, channel,
                "🌙 【夜フェーズ】 占う相手を選んでください：",
                view
            )
        elif role == "狂人":
            # 狂人に人狼を教える
            wolves = [uid for uid, r in room["role_map"].items() if r == "人狼"]
            wolf_info = "、".join(f"<@{wid}>" for wid in wolves)
            success = await send_dm_or_channel(
                user, channel,
                f"🌙 【夜フェーズ】 あなたは狂人です。人狼は {wolf_info} です。"
            )
            room["night_actions"]["madman_info"] = "informed"
        else:
            success = await send_dm_or_channel(
                user, channel,
                "🌙 【夜フェーズ】 あなたは村人です。お休みしてください。"
            )

    asyncio.create_task(wait_for_night_actions(cid))

async def show_game_summary(cid: int):
    """
    ゲーム終了時に役職一覧を表示
    """
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    summary = ["📊 **ゲーム結果**"]
    for user in room["players"]:
        uid = user.id
        role = room["role_map"][uid]
        status = "💀" if uid in room["dead"] else "🏃"
        summary.append(f"{status} <@{uid}>: {role}")
    
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

    # アクションが揃うまで待機（最大2分）
    for _ in range(120):  # 2分 = 120秒
        if room["phase"] != "night":  # 夜フェーズが終了していたら
            return

        w_targets = room["night_actions"]["werewolf_targets"]
        s_target = room["night_actions"]["seer_target"]
        
        # 人狼の投票と占い師の占いが揃ったら
        if len(w_targets) >= num_wolves and (
            s_target is not None or  # 占い師の占い完了
            not any(uid for uid, role in room["role_map"].items()  # または生存占い師なし
                   if role == "占い師" and uid in room["alive"])
        ):
            await process_night_results(cid)
            return
        
        await asyncio.sleep(1)

    # タイムアウト処理
    if room["phase"] == "night":
        channel = werewolf_bot.get_channel(cid)
        await channel.send("⏰ 時間切れです。未投票はランダムに決定されます。")
        
        # 人狼の未投票をランダム決定
        if len(room["night_actions"]["werewolf_targets"]) < num_wolves:
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
        for target_id in room["alive"]:
            if target_id != uid:
                self.add_item(WolfKillButton(cid, target_id))

class WolfKillButton(discord.ui.Button):
    def __init__(self, cid: int, target_id: int):
        label = f"襲撃: <@{target_id}>"
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.cid = cid
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return
        if room["role_map"].get(uid) != "人狼":
            await interaction.response.send_message("⚠️ あなたには襲撃権限がありません。", ephemeral=True)
            return
        room["night_actions"]["werewolf_targets"].append(self.target_id)
        await interaction.response.send_message(f"✅ <@{self.target_id}> を襲撃対象に選択しました。", ephemeral=True)
        self.stop()

class SeerNightView(discord.ui.View):
    def __init__(self, cid: int, uid: int):
        super().__init__(timeout=60)
        self.cid = cid
        self.user_id = uid
        room = werewolf_rooms.get(cid)
        if not room:
            return
        for target_id in room["alive"]:
            if target_id != uid:
                self.add_item(SeerCheckButton(cid, target_id))

class SeerCheckButton(discord.ui.Button):
    def __init__(self, cid: int, target_id: int):
        label = f"占う: <@{target_id}>"
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.cid = cid
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        uid = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room:
            await interaction.response.send_message("❌ この部屋は存在しません。", ephemeral=True)
            return
        if room["role_map"].get(uid) != "占い師":
            await interaction.response.send_message("⚠️ あなたには占い権限がありません。", ephemeral=True)
            return
        room["night_actions"]["seer_target"] = self.target_id
        await interaction.response.send_message(f"🔮 <@{self.target_id}> を占い対象に選択しました。", ephemeral=True)
        self.stop()

# =============================
# ==== 昼フェーズ用 View / Button クラス ====
# =============================

class VoteView(discord.ui.View):
    def __init__(self, cid: int):
        super().__init__(timeout=60)
        self.cid = cid
        room = werewolf_rooms.get(cid)
        if not room:
            return
        for target_id in room["alive"]:
            self.add_item(VoteButton(cid, target_id))

class VoteButton(discord.ui.Button):
    def __init__(self, cid: int, target_id: int):
        label = f"投票: <@{target_id}>"
        super().__init__(label=label, style=discord.ButtonStyle.danger)
        self.cid = cid
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        voter_id = interaction.user.id
        room = werewolf_rooms.get(self.cid)
        if not room or room["phase"] != "day":
            await interaction.response.send_message("⚠️ 今は投票フェーズではありません。", ephemeral=True)
            return
        room.setdefault("votes", {})[voter_id] = self.target_id
        await interaction.response.send_message(f"✅ 投票完了: <@{self.target_id}> に投票しました。", ephemeral=True)
        self.stop()

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
        werewolf_rooms[cid] = {
            "role_set": self.role_set,
            "players": [],
            "role_map": {},
            "alive": set(),
            "dead": set(),
            "phase": None,
            "night_actions": {"werewolf_targets": [], "seer_target": None},
            "votes": {},
        }

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
    room = werewolf_rooms.get(cid)
    channel = werewolf_bot.get_channel(cid)
    if not room:
        return

    players = room["players"]
    roles = room["role_set"][:]
    random.shuffle(roles)
    random.shuffle(players)

    # 【1】 役職を DM で配布し、role_map, alive, dead, phase, night_actions を初期化
    room["role_map"] = {user.id: role for user, role in zip(players, roles)}
    room["alive"] = set(user.id for user in players)
    room["dead"] = set()
    room["phase"] = "night"
    room["night_actions"] = {"werewolf_targets": [], "seer_target": None}
    room["votes"] = {}

    for user, role in zip(players, roles):
        try:
            await user.send(f"🎭 あなたの役職は **{role}** です。内緒にしてね！")
        except discord.Forbidden:
            await channel.send(f"⚠️ <@{user.id}> に DM が送れませんでした。DM を有効にしてください。")

    # 【2】 チャンネルに夜開始通知
    await channel.send("🌙 夜が始まります。人狼と占い師は DM を確認してください。")

    # 【3】 夜フェーズ用 DM を全員に送信
    for user in players:
        uid = user.id
        if uid not in room["alive"]:
            continue
        role = room["role_map"][uid]
        if role == "人狼":
            view = WolfNightView(cid, uid)
            try:
                await user.send("🌙 【夜フェーズ】 襲撃する相手を選んでください：", view=view)
            except discord.Forbidden:
                await channel.send(f"⚠️ <@{uid}> に DM 送信できません。")
        elif role == "占い師":
            view = SeerNightView(cid, uid)
            try:
                await user.send("🌙 【夜フェーズ】 占う相手を選んでください：", view=view)
            except discord.Forbidden:
                await channel.send(f"⚠️ <@{uid}> に DM 送信できません。")
        else:
            try:
                await user.send("🌙 【夜フェーズ】 あなたは村人です。お休みしてください。")
            except discord.Forbidden:
                await channel.send(f"⚠️ <@{uid}> に DM 送信できません。")

    # 【4】 夜アクション待機タスクを起動
    asyncio.create_task(wait_for_night_actions(cid))

# === 投票処理の改善 ===
def get_vote_results(votes: dict) -> tuple[int, int]:
    """
    投票結果から最多得票者とその得票数を返す。
    同数の場合はランダムに選択。
    """
    if not votes:
        return None, 0
    
    counter = Counter(votes.values())
    max_votes = max(counter.values())
    max_voted = [uid for uid, count in counter.items() if count == max_votes]
    chosen = random.choice(max_voted)
    return chosen, max_votes

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
