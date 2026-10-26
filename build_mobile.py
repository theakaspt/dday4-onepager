"""d.day one-pager 모바일 웹 빌드
mobile/template.html + data/data.json (+ kiosk-src 로고·사진·폰트) -> dist/

  python3 -I build_mobile.py

- dist/ 를 지우고 새로 만든다. kiosk-src/ 는 읽기만 한다.
- 원고는 data/data.json (kiosk-src/data.json 사본 + 모바일 워딩 변경). kiosk-src/data.json 은 읽지 않는다.
- 폰트·이미지 파일명에 내용 해시 8자리를 붙인다(immutable 캐시 안전).
- 끝에 금지 문자열 검사와 첫 로드 크기 예산 검사를 하고, 실패하면 종료 코드 1.
필요: python3, pillow, fonttools(+brotli), pyftsubset
"""
import hashlib, io, json, os, re, shutil, subprocess, sys, tempfile
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'kiosk-src')
DATA_JSON = os.path.join(ROOT, 'data', 'data.json')
TPL = os.path.join(ROOT, 'mobile', 'template.html')
DIST = os.path.join(ROOT, 'dist')
ASSETS = os.path.join(DIST, 'assets')

BUDGET = 400 * 1024          # 첫 화면 전송량 예산 (index.html + 폰트 2 + 로고 7)
LOGO_MAX_H = 248             # 로고 높이 상한(2x). 원본이 더 작으면 원본 높이 유지(업스케일 안 함)
MENTOR_Q = 80
FORBIDDEN = ['타겟', 'orbit-04', '—', '디캠프', 'D.CAMP', 'PIONEER', '전담 멘토']
EXTRA_CHARS = '·…“”‘’→←↑↓~–•※₂₃₆°％✓'
DESC = '궤도에 오르기까지, 일곱 개의 기록 / dcamp batch 4 7개사 원페이저'
LOGOS = ['cosmo', 'idea', 'tefa', 'fust', 'space', 'pitin', 'gapt']


def h8(b):
    return hashlib.sha256(b).hexdigest()[:8]


def put(name, ext, data):
    fn = f'{name}.{h8(data)}.{ext}'
    with open(os.path.join(ASSETS, fn), 'wb') as f:
        f.write(data)
    return 'assets/' + fn


def main():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(ASSETS)

    data = json.load(open(DATA_JSON, encoding='utf-8'))
    tpl = open(TPL, encoding='utf-8').read()
    kiosk_tpl = open(os.path.join(SRC, 'template.html'), encoding='utf-8').read()

    # one-pager 워드마크: 키오스크 template의 인라인 SVG를 그대로 가져옴
    m = re.search(r'<svg class="wm".*?</svg>', kiosk_tpl, re.S)
    if not m:
        sys.exit('wordmark svg not found in kiosk template')
    wordmark = m.group(0)

    # 이미지
    images, first_load = {}, []
    used_logos = {c['wlogo'] for c in data}
    for k in LOGOS:
        key = 'w_' + k
        im = Image.open(os.path.join(SRC, 'logos', key + '.png'))
        h = min(LOGO_MAX_H, im.height)
        if h != im.height:
            im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
        b = io.BytesIO(); im.save(b, 'WEBP', lossless=True, method=6)
        p = put(key, 'webp', b.getvalue())
        images[key] = {'s': p, 'w': im.width, 'h': im.height}
        if key in used_logos:
            first_load.append(p)
    photos = sorted({blk['photo'] for c in data for s in c['sections'] for blk in s['blocks'] if blk.get('t') == 'mentor'})
    for key in photos:
        im = Image.open(os.path.join(SRC, 'assets', key + '.png')).convert('RGB')
        b = io.BytesIO(); im.save(b, 'WEBP', quality=MENTOR_Q, method=6)
        images[key] = {'s': put(key, 'webp', b.getvalue()), 'w': im.width, 'h': im.height}

    # 폰트: SUIT 서브셋 (화면에 쓰이는 글자 + ASCII + 기호), Chivo Mono 그대로
    chars = set(tpl) | set(kiosk_tpl) | set(json.dumps(data, ensure_ascii=False)) | set(DESC) | set(EXTRA_CHARS)
    chars |= {chr(i) for i in range(0x20, 0x7f)}
    chars = ''.join(sorted(c for c in chars if ord(c) >= 0x20))
    with tempfile.TemporaryDirectory() as td:
        tf = os.path.join(td, 'chars.txt'); of = os.path.join(td, 'suit.woff2')
        open(tf, 'w', encoding='utf-8').write(chars)
        subprocess.run(['pyftsubset', os.path.join(SRC, 'vendor', 'SUIT-Variable.woff2'), f'--text-file={tf}',
                        '--flavor=woff2', f'--output-file={of}', '--layout-features=*', '--no-hinting'], check=True)
        suit = put('suit', 'woff2', open(of, 'rb').read())
    mono = put('mono', 'woff2', open(os.path.join(SRC, 'vendor', 'chivo-mono-latin-wght-normal.woff2'), 'rb').read())

    # 서브셋에 빠진 글자 확인 (시스템 폰트로 대체됨 -> 경고만)
    from fontTools.ttLib import TTFont
    cmap = TTFont(os.path.join(DIST, suit)).getBestCmap()
    missing = [c for c in chars if ord(c) not in cmap and not c.isspace()]

    out = (tpl.replace('__FONT_SUIT__', suit).replace('__FONT_MONO__', mono)
              .replace('__DESC__', DESC).replace('__WORDMARK__', wordmark)
              .replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')))
              .replace('__IMAGES__', json.dumps(images, separators=(',', ':'))))
    left = re.findall(r'__[A-Z_]+__', out)
    if left:
        sys.exit(f'unreplaced placeholders: {left}')
    open(os.path.join(DIST, 'index.html'), 'w', encoding='utf-8').write(out)

    vercel = {
        'headers': [
            {'source': '/assets/(.*)', 'headers': [{'key': 'Cache-Control', 'value': 'public, max-age=31536000, immutable'}]},
            {'source': '/index.html', 'headers': [{'key': 'Cache-Control', 'value': 'public, max-age=0, must-revalidate'}]},
        ],
        'cleanUrls': True,
    }
    json.dump(vercel, open(os.path.join(DIST, 'vercel.json'), 'w', encoding='utf-8'), indent=2)

    # ---- 리포트 ----
    ok = True
    print('dist files')
    total = 0
    for dp, _, fns in os.walk(DIST):
        for fn in sorted(fns):
            p = os.path.join(dp, fn); sz = os.path.getsize(p); total += sz
            print(f'  {os.path.relpath(p, DIST):40s} {sz/1024:8.1f} KB')
    print(f'  {"(all files)":40s} {total/1024:8.1f} KB')

    fl = ['index.html', suit, mono] + first_load
    fl_size = sum(os.path.getsize(os.path.join(DIST, p)) for p in fl)
    print(f'first load (index + 2 fonts + {len(first_load)} logos): {fl_size/1024:.1f} KB / budget {BUDGET/1024:.0f} KB')
    if fl_size > BUDGET:
        print('FAIL: first-load budget exceeded'); ok = False

    # 금지 문자열 (텍스트 산출물 전부)
    for fn in ['index.html', 'vercel.json']:
        txt = open(os.path.join(DIST, fn), encoding='utf-8').read()
        hits = [w for w in FORBIDDEN if w in txt]
        if hits:
            print(f'FAIL: forbidden strings in {fn}: {hits!r}'); ok = False
    # 외부 요청 유발 패턴 (링크 href·xmlns는 요청이 아니므로 제외)
    ext = re.findall(r'(?:src|srcset)\s*=\s*["\']?\s*(?:https?:)?//|url\(\s*["\']?(?:https?:)?//|@import|<link[^>]+href=["\'](?:https?:)?//', out, re.I)
    if ext:
        print(f'FAIL: external resource references: {ext}'); ok = False
    if missing:
        print(f'WARN: glyphs missing in SUIT subset (system fallback): {"".join(missing)!r}')
    print('forbidden/external check:', 'ok' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
