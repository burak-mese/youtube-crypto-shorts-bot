import os, asyncio, requests, subprocess, json, feedparser, tempfile, random, base64, hashlib
import edge_tts
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GROQ_API_KEY          = os.environ['GROQ_API_KEY']
PEXELS_API_KEY        = os.environ['PEXELS_API_KEY']
YOUTUBE_CLIENT_ID     = os.environ['YOUTUBE_CLIENT_ID']
YOUTUBE_CLIENT_SECRET = os.environ['YOUTUBE_CLIENT_SECRET']
YOUTUBE_REFRESH_TOKEN = os.environ['YOUTUBE_REFRESH_TOKEN']
VIDEOS_PER_RUN = 6

RSS_FEEDS = [
    'https://cointelegraph.com/rss',
    'https://coindesk.com/arc/outboundfeeds/rss/',
    'https://cryptonews.com/news/feed/',
    'https://decrypt.co/feed',
    'https://bitcoinmagazine.com/.rss/full/',
    'https://www.coindesk.com/arc/outboundfeeds/rss/?category=markets',
    'https://cryptoslate.com/feed/',
    'https://beincrypto.com/feed/',
]

PEXELS_QUERIES = ['cryptocurrency bitcoin', 'blockchain technology', 'crypto trading', 'digital currency', 'bitcoin ethereum', 'crypto market']

def title_hash(title):
    return hashlib.md5(title.lower().strip()[:50].encode()).hexdigest()

def load_seen_titles():
    github_token = os.environ.get('GITHUB_TOKEN')
    if github_token:
        try:
            resp = requests.get('https://api.github.com/gists', headers={'Authorization': f'token {github_token}'}, params={'per_page': 10})
            for gist in resp.json():
                if gist.get('description') == 'youtube-crypto-bot-seen-titles':
                    content = requests.get(list(gist['files'].values())[0]['raw_url']).json()
                    return set(content.get('titles', []))
        except: pass
    return set()

def save_seen_titles(titles):
    github_token = os.environ.get('GITHUB_TOKEN')
    if not github_token: return
    try:
        data = {'titles': list(titles)[-200:]}
        resp = requests.get('https://api.github.com/gists', headers={'Authorization': f'token {github_token}'}, params={'per_page': 10})
        existing = next((g['id'] for g in resp.json() if g.get('description') == 'youtube-crypto-bot-seen-titles'), None)
        gist_data = {'description': 'youtube-crypto-bot-seen-titles', 'public': False, 'files': {'seen.json': {'content': json.dumps(data)}}}
        if existing:
            requests.patch(f'https://api.github.com/gists/{existing}', headers={'Authorization': f'token {github_token}'}, json=gist_data)
        else:
            requests.post('https://api.github.com/gists', headers={'Authorization': f'token {github_token}'}, json=gist_data)
    except: pass

def fetch_news(seen_titles):
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:8]:
                title = entry.get('title', '')
                h = title_hash(title)
                if h not in seen_titles:
                    articles.append({'title': title, 'summary': entry.get('summary', '')[:300], 'hash': h})
        except Exception as e:
            print(f'RSS error: {e}')
    random.shuffle(articles)
    return articles[:25]

def generate_scripts(articles):
    articles_text = '\n'.join([f"{i+1}. {a['title']}: {a['summary']}" for i, a in enumerate(articles[:20])])
    prompt = f"""You are a viral YouTube Shorts script writer for a CRYPTO news channel with 2M+ subscribers.

Today's crypto headlines:
{articles_text}

Pick the {VIDEOS_PER_RUN} most shocking, bullish/bearish, or viral-worthy stories.
Write a YouTube Shorts script for each (max 150 words, ~55 seconds spoken).

Rules:
- Start with SHOCKING hook: price, %, or "Nobody is talking about THIS"
- Use "YOUR crypto", "YOUR portfolio" — make it personal
- Include specific prices, % changes, market cap when available  
- Create extreme FOMO or FEAR
- Mention specific coins (BTC, ETH, etc.)
- End exactly: "Follow for daily crypto news!"
- High energy, almost breathless tone

Return ONLY valid JSON array:
[{{"title":"viral title max 60 chars","script":"full script","tags":["crypto","bitcoin","ethereum","blockchain"],"search_query":"pexels search 2-3 words","emoji":"🚀"}}]"""

    headers = {'Authorization': f'Bearer {GROQ_API_KEY}', 'Content-Type': 'application/json'}
    payload = json.dumps({"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "temperature": 0.9})
    resp = requests.post('https://api.groq.com/openai/v1/chat/completions', headers=headers, data=payload)
    if resp.status_code != 200: raise Exception(f'Groq error: {resp.text}')
    text = resp.json()['choices'][0]['message']['content'].strip()
    if '```' in text:
        parts = text.split('```')
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith('json'): text = text[4:]
    return json.loads(text.strip())

async def generate_audio(script, output_path):
    communicate = edge_tts.Communicate(script, voice='en-US-GuyNeural', rate='+15%')
    await communicate.save(output_path)

def download_pexels_video(query, output_path):
    headers = {'Authorization': PEXELS_API_KEY}
    resp = requests.get(f'https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=15&size=medium', headers=headers)
    videos = resp.json().get('videos', [])
    if not videos:
        resp = requests.get('https://api.pexels.com/videos/search?query=cryptocurrency&orientation=portrait&per_page=15&size=medium', headers=headers)
        videos = resp.json().get('videos', [])
    if not videos: raise Exception(f'No Pexels videos for: {query}')
    video = random.choice(videos[:5])
    good_files = [f for f in video['video_files'] if f.get('width', 9999) <= 1080]
    video_files = sorted(good_files or video['video_files'], key=lambda x: x.get('width', 0), reverse=True)
    r = requests.get(video_files[0]['link'], stream=True)
    with open(output_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=8192): f.write(chunk)

def create_shorts_video(video_path, audio_path, output_path, title='', emoji='🚀'):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', audio_path], capture_output=True, text=True)
    duration = float(result.stdout.strip())
    safe_title = title.replace("'", "").replace('"', '').replace(':', ' ').replace('%', 'pct')[:35]
    words = safe_title.upper().split()
    mid = len(words) // 2
    line1 = ' '.join(words[:mid]) if len(words) > 3 else safe_title.upper()
    line2 = ' '.join(words[mid:]) if len(words) > 3 else ''
    vf = (
        'scale=1080:1920,'
        'drawbox=x=0:y=0:w=iw:h=300:color=black@0.8:t=fill,'
        'drawbox=x<0:y=1620:w=iw:h=300:color=black@0.8:t=fill,'
        'drawbox=x=0:y=295:w=iw:h=8:color=0xf7931a@0.9:t=fill,'
        "drawtext=text='CRYPTO NEWS':fontcolor=0xf7931a:fontsize=36:x=(w-text_w)/2:y=30:box=0,"
        f"drawtext=text='{line1}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=100:box=0,"
    )
    if line2:
        vf += f"drawtext=text='{line2}':fontcolor=white:fontsize=58:x=(w-text_w)/2:y=170:box=0,"
    vf += "drawtext=text='Follow for daily crypto news!':fontcolor=0xf7931a:fontsize=36:x=(w-text_w)/2:y=1650:box=0"
    cmd = ['ffmpeg', '-y', '-stream_loop', '-1', '-i', video_path, '-i', audio_path, '-map', '0:v:0', '-map', '1:a:0', '-vf', vf, '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-t', str(duration), output_path]
    subprocess.run(cmd, check=True)

def get_youtube_service():
    creds = Credentials(token=None, refresh_token=YOUTUBE_REFRESH_TOKEN, client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET, token_uri='https://oauth2.googleapis.com/token')
    try: creds.refresh(Request())
    except Exception as e: print(f'Token note: {e}')
    return build('youtube', 'v3', credentials=creds)

def upload_to_youtube(youtube, video_path, title, tags):
    description = f"{title}\n\nThe biggest crypto moves explained in 60 seconds. Every day.\n\n🚀 Subscribe for daily crypto updates!\n₿ Bitcoin & Ethereum news\n📊 Market analysis\n🔥 Altcoin alerts\n\n#Shorts #Crypto #Bitcoin #Ethereum #Blockchain #CryptoNews #DeFi #Web3"
    body = {'snippet': {'title': title, 'description': description, 'tags': tags + ['shorts', 'crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi'], 'categoryId': '25', 'defaultLanguage': 'en'}, 'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False}}
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True, chunksize=1024*1024)
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status: print(f'  Upload {int(status.progress() * 100)}%')
    print(f'✅ Uploaded: https://youtube.com/shorts/{response["id"]}')
    return response['id']

async def main():
    print('🚀 Crypto Shorts Bot starting...')
    seen_titles = load_seen_titles()
    articles = fetch_news(seen_titles)
    print(f'Found {len(articles)} fresh articles')
    scripts = generate_scripts(articles)
    print(f'Generated {len(scripts)} scripts')
    youtube = get_youtube_service()
    success = 0
    used_hashes = set()
    for i, item in enumerate(scripts):
        print(f'\n--- Video {i+1}/{len(scripts)}: {item["title"]} ---')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                audio_path = os.path.join(tmpdir, 'audio.mp3')
                video_raw = os.path.join(tmpdir, 'raw.mp4')
                video_out = os.path.join(tmpdir, 'output.mp4')
                await generate_audio(item['script'], audio_path)
                download_pexels_video(item.get('search_query', random.choice(PEXELS_QUERIES)), video_raw)
                create_shorts_video(video_raw, audio_path, video_out, title=item['title'], emoji=item.get('emoji', '🚀'))
                upload_to_youtube(youtube, video_out, item['title'], item['tags'])
                success += 1
                seen_titles.add(title_hash(item['title']))
                used_hashes.add(title_hash(item['title']))
        except Exception as e:
            print(f'  ❌ ERROR: {e} — skipping!')
    if used_hashes: save_seen_titles(seen_titles)
    print(f'\n🎉 Done! {success}/{len(scripts)} videos uploaded.')

if __name__ == '__main__':
    asyncio.run(main())
