import logging
from cv2 import split
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

try:
    import config_my as config
except ImportError:
    import config

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pilmoji import Pilmoji
from io import BytesIO

WS_URL = f'wss://{config.MISSKEY_INSTANCE}/streaming?i={config.MISSKEY_TOKEN}'
msk = Misskey(config.MISSKEY_INSTANCE, i=config.MISSKEY_TOKEN)
i = msk.i()

MY_ID = i['id']
print('Bot user id: ' + MY_ID)

BASE_GRADATION_IMAGE = Image.open('base-gd-4.png')
BASE_WHITE_IMAGE = Image.open('base-w.png')

FONT_FILE = 'MPLUSRounded1c-Regular.ttf'

MPLUS_FONT_TEXT = ImageFont.truetype(FONT_FILE, size=45)
MPLUS_FONT_NAME = ImageFont.truetype(FONT_FILE, size=30)
MPLUS_FONT_16 = ImageFont.truetype('MPLUSRounded1c-Regular.ttf', size=16)

session = aiohttp.ClientSession()

# logging.basicConfig(level=logging.DEBUG)

def draw_text(im, ofs, string, font='MPLUSRounded1c-Regular.ttf', size=16, color=(0,0,0,255), split_len=None, padding=4):
    
    draw = ImageDraw.Draw(im)
    fontObj = ImageFont.truetype(font, size=size)

    lines = string.split('\n')
    dy = 0

    draw_lines = []


    # 計算
    for line in lines:

        if split_len and len(line) > split_len:

            l = []

            for i in range(0, len(line), split_len):
                l.append(line[i:i+split_len])

            tsize = fontObj.getsize(l[0])

            ofs_y = ofs[1] + dy
            t_height = tsize[1]

            for t in l:
                sz = fontObj.getsize(t)
                x = int(ofs[0] - (sz[0]/2))
                #draw.text((x, ofs_y), t, font=fontObj, fill=color)
                draw_lines.append((x, ofs_y, t))
                ofs_y += t_height + padding
                dy += t_height + padding

        else:
            tsize_t = fontObj.getsize(line)
            text_x = int(ofs[0] - (tsize_t[0]/2))
            text_y = ofs[1] + dy
            #draw.text((text_x, text_y), line, font=fontObj, fill=color)
            draw_lines.append((text_x, text_y, line))
            dy += tsize_t[1] + padding
    
    # 描画
    adj_y = -30 * (len(draw_lines)-1)
    for dl in draw_lines:
        with Pilmoji(im) as p:
            p.text((dl[0], (adj_y + dl[1])), dl[2], font=fontObj, fill=color, emoji_position_offset=(-8, 4))

    real_y = ofs[1] + adj_y + dy

    return (0, dy, real_y)
    

receivedNotes = set()

async def on_post_note(note):

    # HTLとGTLを監視している都合上重複する恐れがあるため
    if note['id'] in receivedNotes:
        return

    receivedNotes.add(note['id'])

    if note.get('mentions'):
        print(note['mentions'])
        if MY_ID in note['mentions']:
            command = False

            # 他のメンション取り除く
            split_text = note['text'].split(' ')
            new_st = []

            for t in split_text:
                if t.startswith('@'):
                    if (not t==f'@{i["username"]}') and (not t==f'@{i["username"]}@{config.MISSKEY_INSTANCE}'):
                        pass
                    else:
                        new_st.append(t)
                else:
                    new_st.append(t)

            note['text'] = ' '.join(new_st)

            try:
                content = note['text'].strip().split(' ', 1)[1].strip()
                command = True
            except IndexError:
                pass
            
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
                icon = icon.convert('L') # グレースケール変換
                icon_filtered = ImageEnhance.Brightness(icon)

                img.paste(icon_filtered.enhance(0.7), (0,0))

                # 黒グラデ合成
                img.paste(BASE_GRADATION_IMAGE, (0,0), BASE_GRADATION_IMAGE)

                # テキスト合成
                tx = ImageDraw.Draw(img)

                base_x = 960

                # 文章描画
                tsize_t = draw_text(img, (base_x, 270), note['reply']['text'], font=FONT_FILE, size=45, color=(255,255,255,255), split_len=14)

                # 名前描画
                uname = note['user']['name'] or note['user']['username']
                name_y = tsize_t[2] + 90
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


            if command:

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