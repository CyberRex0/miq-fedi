from misskey import Misskey
import websockets
import asyncio, aiohttp
import json
import datetime
import sys
import traceback
import re
import math
import time

import config

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from io import BytesIO

WS_URL = f'wss://{config.MISSKEY_INSTANCE}/streaming?i={config.MISSKEY_TOKEN}'
msk = Misskey(config.MISSKEY_INSTANCE, i=config.MISSKEY_TOKEN)
i = msk.i()

MY_ID = i['id']
print('Bot user id: ' + MY_ID)

BASE_GRADATION_IMAGE = Image.open('base-gd-2.png')
BASE_WHITE_IMAGE = Image.open('base-w.png')

FONT_FILE = 'MPLUSRounded1c-Regular.ttf'

MPLUS_FONT_TEXT = ImageFont.truetype(FONT_FILE, size=45)
MPLUS_FONT_NAME = ImageFont.truetype(FONT_FILE, size=30)
MPLUS_FONT_16 = ImageFont.truetype('MPLUSRounded1c-Regular.ttf', size=16)

session = aiohttp.ClientSession()

def draw_text(im, ofs, string, font='MPLUSRounded1c-Regular.ttf', size=16, color=(0,0,0,255), split_len=None, padding=4):
    
    draw = ImageDraw.Draw(im)
    fontObj = ImageFont.truetype(font, size=size)

    s = []

    string = string.replace('\n', ' ')
    string = re.sub(r'[\u2700-\u27BF]|[\uE000-\uF8FF]|\uD83C[\uDC00-\uDFFF]|\uD83D[\uDC00-\uDFFF]|[\u2011-\u26FF]|\uD83E[\uDD10-\uDDFF]', '', string)

    if split_len and len(string) > split_len:

        for i in range(0, len(string), split_len):
            s.append(string[i:i+split_len])

        tsize = fontObj.getsize(s[0])

        ofs_y = ofs[1]
        dy = 0
        t_height = tsize[1]

        for t in s:
            sz = fontObj.getsize(t)
            x = ofs[0] - (sz[0]/2)
            draw.text((x, ofs_y), t, font=fontObj, fill=color)
            ofs_y += t_height + padding
            dy += t_height + padding
        
        return (0, dy)

    else:
        tsize_t = fontObj.getsize(string)
        text_x = ofs[0] - (tsize_t[0]/2)
        text_y = ofs[1]
        draw.text((text_x, text_y), string, font=fontObj, fill=color)
        return tsize_t
    

receivedNotes = set()

async def on_post_note(note):

    if note['id'] in receivedNotes:
        return

    receivedNotes.add(note['id'])

    if note.get('mentions'):
        print(note['mentions'])
        if MY_ID in note['mentions']:
            # print(note)

            try:
                note['text'] = re.sub(r'@(?=\w+)(?!' + i['username'] + r')', '', note['text'])
                content = note['text'].strip().split(' ', 1)[1].strip()
            except IndexError:
                # メンションだけされた？
                if note.get('reply'):

                    if config.DEBUG:
                        print(f'Quote: {note["user"]["name"] or note["user"]["username"]} からの実行依頼を受信')

                    # 引用する
                    img = BASE_WHITE_IMAGE.copy()
                    # アイコン画像ダウンロード
                    if not note['user'].get('avatarUrl'):
                        msk.notes_create(text='アイコン画像がないので作れません', reply_id=note['id'])
                        return
                    
                    if config.DEBUG:
                        print('Quote: アイコンダウンロード')

                    async with session.get(note['user']['avatarUrl']) as resp:
                        if resp.status != 200:
                            msk.notes_create(text='アイコン画像ダウンロードに失敗しました', reply_id=note['id'])
                            return
                        avatar = await resp.read()
                    
                    if config.DEBUG:
                        print('Quote: 描画中')
                    icon = Image.open(BytesIO(avatar))
                    icon = icon.resize((720, 720), Image.ANTIALIAS)
                    icon = icon.convert('RGBA')
                    img.paste(icon, (0,0))

                    # 黒グラデ合成
                    img.paste(BASE_GRADATION_IMAGE, (0,0), BASE_GRADATION_IMAGE)

                    # テキスト合成
                    tx = ImageDraw.Draw(img)

                    base_x = 960

                    # 文章描画
                    tsize_t = draw_text(img, (base_x, 210), note['reply']['text'], font=FONT_FILE, size=45, color=(255,255,255,255), split_len=14)

                    # 名前描画
                    uname = note['user']['name'] or note['user']['username']
                    name_y = 210 + tsize_t[1] + 50
                    tsize_name = draw_text(img, (base_x, name_y), uname, font=FONT_FILE, size=25, color=(255,255,255,255), split_len=25)
                    
                    # ID描画
                    id = note['user']['username']
                    id_y = name_y + tsize_name[1] + 4
                    tsize_id = draw_text(img, (base_x, id_y), f'(@{id}@{note["user"]["host"] or config.MISSKEY_INSTANCE})', font=FONT_FILE, size=22, color=(180,180,180,255), split_len=35)

                    # クレジット
                    tx.text((980, 694), '<Make it a quote for Fedi> by CyberRex', font=MPLUS_FONT_16, fill=(120,120,120,255))

                    # print(f'{tsize_t=}')
                    # print(f'{tsize_name=}')


                    # ドライブにアップロード
                    if config.DEBUG:
                        print('Quote: アップロード準備中')
                    try:
                        data = BytesIO()
                        img.save(data, format='JPEG')
                        data.seek(0)
                        if config.DEBUG:
                            print('Quote: アップロード中')
                        f = msk.drive_files_create(file=data, name=f'{datetime.datetime.utcnow().timestamp()}.jpg')
                    except Exception as e:
                        msk.notes_create('ドライブにアップロードに失敗しました\n' + traceback.format_exc(), reply_id=note['id'])
                        return
                    if config.DEBUG:
                        print('Quote: ノート送信中')
                    msk.notes_create(text='.', file_ids=[f['id']], reply_id=note['id'])
                    if config.DEBUG:
                        print('Quote: 完了')

                    return




            if content == 'ping':

                postdate = datetime.datetime.fromisoformat(note['createdAt'][:-1]).timestamp()
                nowdate = datetime.datetime.utcnow().timestamp()
                sa = nowdate - postdate
                text = f'{sa*1000:.2f}ms'
                msk.notes_create(text=text, reply_id=note['id'])

            

async def on_followed(user):
    try:
        msk.following_create(user['id'])
    except:
        pass

async def main():

    print('Connecting to ' + config.MISSKEY_INSTANCE + '...', end='')
    async with websockets.connect(WS_URL) as ws:
        print('OK')
        print('Attemping to watching timeline...', end='')
        p = {
            'type': 'connect',
            'body': {
                'channel': 'globalTimeline',
                'id': 'GTL1'
            }
        }
        await ws.send(json.dumps(p))
        p = {
            'type': 'connect',
            'body': {
                'channel': 'homeTimeline',
                'id': 'HTL1'
            }
        }
        await ws.send(json.dumps(p))
        print('OK')
        p = {
            'type': 'connect',
            'body': {
                'channel': 'main'
            }
        }
        await ws.send(json.dumps(p))
        
        print('Listening ws')
        while True:
            data = await ws.recv()
            j = json.loads(data)
            # print(j)

            if j['type'] == 'channel':
                if j['body']['type'] == 'note':
                    note = j['body']['body']
                    try:
                        await on_post_note(note)
                    except Exception as e:
                        print(traceback.format_exc())
                        continue
                if j['body']['type'] == 'followed':
                    try:
                        await on_followed(j['body']['body'])
                    except Exception as e:
                        print(traceback.format_exc())
                        continue
                

reconnect_counter = 0

while True:
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        break
    except:
        time.sleep(10)
        reconnect_counter += 1
        print('Reconnecting...', end='')
        if reconnect_counter > 10:
            print('Too many reconnects. Exiting.')
            sys.exit(1)
        continue