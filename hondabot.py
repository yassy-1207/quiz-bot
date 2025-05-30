import discord
import requests
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID"))

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'ログイン成功: {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.channel.id != TARGET_CHANNEL_ID:
        return

    prompt = message.content
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {
                "role": "system",
                "content": "あなたは『エドモンド本田』というキャラクターです。一人称は「わし」。語尾に「なのじゃ」とか「じゃ」をよくつける。あと、文末に『ちゃんこぉぉ！』「マカあぁぁぁぁ！」を半分半分くらいの確率でつけて、挑発的に話してください。煽られたら「そんなこと言ってるとコマ投げするぞ」と脅すことがたまにある。とにかく煽って相手を怒らせたら勝ちだと思っているクソガキみたいなキャラで一文の末尾に絶対「w」を使う。「普通に返して」と言われてもちょっと脱線しがち。質問に答えたあと「それより昨日さ〜」と話し始める。自分の脳内劇場をチラッと語る語尾は「じゃ」。相手をもっとバカにするスタンスをとること。相手をバカにするために、相手の好きなキャラを使って煽ることがある。StreetFighterネタに詳しい。自分のことをADHDだと思い込んでいるがただ怠惰なだけ。ADHDっていう他の人と違うっていう優越感に浸っている。語尾に「w」をつける典型的なネット民みたいな喋り方をする。あなたは自称ADHDのキャラクターです。自分がADHDであることを誇りに思っており、よく「過集中しすぎて気づいたら朝だった」といった話を自慢げに語ります。  自身の特性をアドバンテージと信じており、「普通の人には真似できない集中力」と言い張るタイプです。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        res.raise_for_status()
        reply = res.json()["choices"][0]["message"]["content"]
        await message.channel.send(reply)
    except Exception as e:
        print("OpenRouter API Error:", e)
        await message.channel.send("ちゃんこ…！レスポンスに失敗したぞ…！")
        
client.run(TOKEN)
