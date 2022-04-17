import logging
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
import textwrap

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

BASE_GRADATION_IMAGE = Image.open('base-gd-5.png')
BASE_WHITE_IMAGE = Image.open('base-w.png')

FONT_FILE = 'fonts/MPLUSRounded1c-Regular.ttf'
FONT_FILE_SERIF = 'fonts/NotoSerifJP-Regular.otf'
FONT_FILE_OLD_JAPANESE = 'fonts/YujiSyuku-Regular.ttf'
FONT_FILE_POP = 'fonts/MochiyPopPOne-Regular.ttf'

#MPLUS_FONT_TEXT = ImageFont.truetype(FONT_FILE, size=45)
#MPLUS_FONT_NAME = ImageFont.truetype(FONT_FILE, size=30)
MPLUS_FONT_16 = ImageFont.truetype('fonts/MPLUSRounded1c-Regular.ttf', size=16)

session = aiohttp.ClientSession()

# logging.basicConfig(level=logging.DEBUG)

def draw_text(im, ofs, string, font='fonts/MPLUSRounded1c-Regular.ttf', size=16, color=(0,0,0,255), split_len=None, padding=4, auto_expand=False, emojis: list = []):
    
    draw = ImageDraw.Draw(im)
    fontObj = ImageFont.truetype(font, size=size)

    # 改行、句読点(。、.,)で分割した後にさらにワードラップを行う
    pure_lines = []
    pos = 0
    l = ''

    for char in string:
        if char == '\n':
            pure_lines.append(l)
            l = ''
            pos += 1
        elif char == '、' or char == ',':
            pure_lines.append(l + ('、' if char == '、' else ','))
            l = ''
            pos += 1
        elif char == '。' or char == '.':
            pure_lines.append(l + ('。' if char == '。' else '.'))
            l = ''
            pos += 1
        else:
            l += char
            pos += 1

    if l:
        pure_lines.append(l)

    lines = []

    for line in pure_lines:
        lines.extend(textwrap.wrap(line, width=split_len))
    
    dy = 0

    draw_lines = []


    # 計算
    for line in lines:
        tsize = fontObj.getsize(line)

        ofs_y = ofs[1] + dy
        t_height = tsize[1]

        x = int(ofs[0] - (tsize[0]/2))
        #draw.text((x, ofs_y), t, font=fontObj, fill=color)
        draw_lines.append((x, ofs_y, line))
        ofs_y += t_height + padding
        dy += t_height + padding
    
    # 描画
    adj_y = -30 * (len(draw_lines)-1)
    for dl in draw_lines:
        with Pilmoji(im) as p:
            p.text((dl[0], (adj_y + dl[1])), dl[2], font=fontObj, fill=color, emojis=emojis, emoji_position_offset=(-4, 4))

    real_y = ofs[1] + adj_y + dy

    return (0, dy, real_y)
    

receivedNotes = set()

async def on_post_note(note):
    pass

async def on_mention(note):
    # HTLとGTLを監視している都合上重複する恐れがあるため
    if note['id'] in receivedNotes:
        return

    receivedNotes.add(note['id'])

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

        reply_note = note['reply']

        # ボットの投稿へのメンションの場合は応答しない
        if reply_note['user']['id'] == MY_ID:
            return

        if reply_note['cw']:
            reply_note['text'] = reply_note['cw'] + '\n' + reply_note['text']

        if config.DEBUG:
            print(f'Quote: {note["user"]["name"] or note["user"]["username"]} からの実行依頼を受信')

        # 引用する
        img = BASE_WHITE_IMAGE.copy()
        # アイコン画像ダウンロード
        if not reply_note['user'].get('avatarUrl'):
            msk.notes_create(text='アイコン画像がないので作れません', reply_id=note['id'])
            return
        
        if config.DEBUG:
            print('Quote: アイコンダウンロード')

        async with session.get(reply_note['user']['avatarUrl']) as resp:
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

        base_x = 890

        font_path = FONT_FILE

        if '%serif' in note['text']:
            font_path = FONT_FILE_SERIF
        elif '%pop' in note['text']:
            font_path = FONT_FILE_POP
        elif '%oldjp' in note['text']:
            font_path = FONT_FILE_OLD_JAPANESE

        # 文章描画
        tsize_t = draw_text(img, (base_x, 270), note['reply']['text'], font=font_path, size=45, color=(255,255,255,255), split_len=16, auto_expand=True, emojis=reply_note['emojis'])

        # 名前描画
        uname = reply_note['user']['name'] or reply_note['user']['username']
        name_y = tsize_t[2] + 40
        tsize_name = draw_text(img, (base_x, name_y), uname, font=font_path, size=25, color=(255,255,255,255), split_len=25, emojis=reply_note['user']['emojis'])
        
        # ID描画
        id = reply_note['user']['username']
        id_y = name_y + tsize_name[1] + 4
        tsize_id = draw_text(img, (base_x, id_y), f'(@{id}@{reply_note["user"]["host"] or config.MISSKEY_INSTANCE})', font=font_path, size=26, color=(180,180,180,255), split_len=32)

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
            msk.drive_files_update(file_id=f['id'], comment=f'"{reply_note["text"]}" —{reply_note["user"]["name"]}')
        except Exception as e:
            if 'INTERNAL_ERROR' in str(e):
                msk.notes_create('Internal Error occured in Misskey!', reply_id=note['id'])
                return
            if 'RATE_LIMIT_EXCEEDED' in str(e):
                msk.notes_create('利用殺到による一時的なAPI制限が発生しました。しばらく時間を置いてから再度お試しください。\nA temporary API restriction has occurred due to overwhelming usage. Please wait for a while and try again.', reply_id=note['id'])
                return
            msk.notes_create('画像アップロードに失敗しました\n```plaintext\n' + traceback.format_exc() + '\n```', reply_id=note['id'])
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

                if j['body']['type'] == 'mention':
                    note = j['body']['body']
                    try:
                        await on_mention(note)
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