"""占いの画像カードを作る(使い方: このファイルの card(名前, 題字の行, 本文の行, 一言) を呼ぶ。出力は out/)。"""
from PIL import Image, ImageDraw, ImageFont
import random
F="/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"
GOLD=(236,200,120); CREAM=(250,244,232)
def card(name,title,lines,foot=""):
    W=H=1200
    im=Image.new("RGB",(W,H)); px=im.load()
    for y in range(H):
        t=y/H; c=(int(30+34*t),int(22+8*t),int(62+36*t))
        for x in range(W): px[x,y]=c
    d=ImageDraw.Draw(im); random.seed(name)
    for _ in range(60):
        x,y,r=random.randint(0,W),random.randint(0,H),random.choice([1,1,2,3]); d.ellipse([x-r,y-r,x+r,y+r],fill=(240,230,255))
    d.rounded_rectangle([60,60,W-60,H-60],radius=24,outline=GOLD,width=4)
    d.rounded_rectangle([82,82,W-82,H-82],radius=16,outline=(150,125,80),width=1)
    ft=ImageFont.truetype(F,92); fb=ImageFont.truetype(F,54); fs=ImageFont.truetype(F,36)
    th=len(title)*120; bh=len(lines)*92; fh=70 if foot else 0
    total=th+60+bh+fh; y=(H-total)/2
    for t in title:
        w=d.textlength(t,font=ft); d.text(((W-w)/2,y),t,font=ft,fill=GOLD); y+=120
    y+=10; d.line([(W/2-90,y),(W/2+90,y)],fill=GOLD,width=3); y+=50
    for l in lines:
        w=d.textlength(l,font=fb); d.text(((W-w)/2,y),l,font=fb,fill=CREAM); y+=92
    if foot:
        y+=30; w=d.textlength(foot,font=fs); d.text(((W-w)/2,y),foot,font=fs,fill=(200,185,235))
    im.save(f"out/{name}.png")
if __name__=="__main__":
    import os; os.makedirs("out",exist_ok=True)
    card("n1",["返信を待つ夜の","過ごし方"],["スマホを別の部屋に置く","温かい飲み物を入れる","今の気持ちを一行だけ書く","先のことは、明日考える"],"保存して、つらい夜に見返してね")
    card("n2",["好きな人の気持ちを","知りたいとき"],["まず、自分に聞いてみる","・どんな返事なら安心する?","・どうなったら嬉しい?","・何がいちばん不安?"])
    card("n3",["友達に言えない","恋の悩み"],["一人で抱えなくていい","言葉にして話すだけで","整理されることがあります"],"誰かに聞いてもらう夜があってもいい")
    card("n4",["復縁を考える前に"],["「会いたい」と","「やり直したい」は","似ているけれど、別の気持ち"],"あなたは、どちらに近い?")
