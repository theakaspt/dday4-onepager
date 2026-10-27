"""d.day one-pager 모바일 웹 빌드
mobile/template.html + data/data.json (+ kiosk-src 로고·사진·폰트) -> dist/

  python3 -I build_mobile.py

- dist/ 를 지우고 새로 만든다. kiosk-src/ 는 읽기만 한다.
- 원고는 data/data.json (kiosk-src/data.json 사본 + 모바일 워딩 변경). kiosk-src/data.json 은 읽지 않는다.
- 폰트·이미지 파일명에 내용 해시 8자리를 붙인다(immutable 캐시 안전).
- 줄바꿈 보조: 원고는 그대로 두고 화면용 DATA에만 U+2060(단어결합자)·U+2011(비분리 하이픈)·묶음 표시(U+E000/U+E001 -> 화면에서
  <span class="nw">)를 넣는다. B1은 B1_RE 정규식(원고 전체), B2·B3는 mobile/linebreak_rules.json.
  보조 문자를 걷어내고 U+2011을 '-'로 되돌리면 data/data.json 원문과 완전히 같아야 한다(아니면 실패).
- 공유 미리보기 이미지: mobile/og.html을 playwright(chromium)로 1200x630 스크린샷 -> assets/og.<hash>.png (200KB 이하)
- 끝에 금지 문자열 검사와 첫 로드 크기 예산 검사를 하고, 실패하면 종료 코드 1.
필요: python3, pillow, fonttools(+brotli), pyftsubset, playwright(chromium)
"""
import hashlib, io, json, os, re, shutil, subprocess, sys, tempfile
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'kiosk-src')
DATA_JSON = os.path.join(ROOT, 'data', 'data.json')
TPL = os.path.join(ROOT, 'mobile', 'template.html')
RULES = os.path.join(ROOT, 'mobile', 'linebreak_rules.json')
OG_TPL = os.path.join(ROOT, 'mobile', 'og.html')
DIST = os.path.join(ROOT, 'dist')
ASSETS = os.path.join(DIST, 'assets')

BUDGET = 400 * 1024          # 첫 화면 전송량 예산 (index.html + 폰트 2 + 로고 7)
LOGO_MAX_H = 248             # 로고 높이 상한(2x). 원본이 더 작으면 원본 높이 유지(업스케일 안 함)
MENTOR_Q = 80
FORBIDDEN = ['타겟', 'orbit-04', '—', '디캠프', 'D.CAMP', 'PIONEER', '전담 멘토']
EXTRA_CHARS = '·…“”‘’→←↑↓~–•※₂₃₆°％✓'
DESC = '궤도에 오르기까지, 일곱 개의 기록 / dcamp batch 4 7개사 원페이저'
LOGOS = ['cosmo', 'idea', 'tefa', 'fust', 'space', 'pitin', 'gapt']
SITE = 'https://dday-onepager.vercel.app/'
OG_MAX = 200 * 1024

# ---- 줄바꿈 보조 ----
WJ, NBH, NWO, NWC = '\u2060', '\u2011', '\ue000', '\ue001'
# B1: 닫는 괄호·따옴표 바로 뒤에 조사가 오면 사이에 단어결합자 (조사가 다음 줄로 떨어지지 않게)
# 묶음 규칙을 먼저 적용하므로 괄호와 조사 사이에 묶음 표시(U+E000/E001)가 끼어 있을 수 있음 -> 표시 뒤에 단어결합자
B1_RE = re.compile(r'([)’”])([\ue000\ue001]*)(?=으로|[을를이가은는의로와과에도만])')
B1_SKIP = {'id', 'home', 'homeLabel', 'email', 'logo', 'wlogo', 'photo', 'accent', 'key'}   # 화면 글이 아닌 값
TAG_RE = re.compile(r'(<[^>]*>)')


def text_parts(s, fn):
    """HTML 태그 밖의 글자에만 fn 적용"""
    return ''.join(p if p.startswith('<') else fn(p) for p in TAG_RE.split(s))


def restore(o):
    """화면용 DATA -> 원문 (보조 문자 제거, U+2011 -> '-')"""
    if isinstance(o, dict):
        return {k: restore(v) for k, v in o.items()}
    if isinstance(o, list):
        return [restore(v) for v in o]
    if isinstance(o, str):
        return o.replace(WJ, '').replace(NWO, '').replace(NWC, '').replace(NBH, '-')
    return o


def apply_b1(o, key=None, hits=None):
    if isinstance(o, dict):
        return {k: apply_b1(v, k, hits) for k, v in o.items()}
    if isinstance(o, list):
        return [apply_b1(v, key, hits) for v in o]
    if isinstance(o, str) and key not in B1_SKIP:
        def f(t):
            n = len(B1_RE.findall(t))
            if n: hits.append(n)
            return B1_RE.sub(lambda m: m.group(1) + m.group(2) + WJ, t)
        return text_parts(o, f)
    return o


def apply_rules(data, rules):
    """B2·B3: 지정 위치의 구절을 묶음 표시로 감쌈. 반환: [(id, 기대 개수, 실제 개수)]"""
    res = []
    by_qn = {c['qn']: c for c in data}
    for r in rules:
        c = by_qn[r['qn']]
        phrase = r['text']
        rep_ = NWO + (phrase.replace('-', NBH) if r.get('nbhyphen') else phrase) + NWC
        cnt = [0]

        def sub(s):
            def f(t):
                cnt[0] += t.count(phrase)
                return t.replace(phrase, rep_)
            return text_parts(s, f)

        def walk(o):
            if isinstance(o, dict):
                return {k: walk(v) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v) for v in o]
            return sub(o) if isinstance(o, str) else o

        w = r['where']
        if w == 'intro':
            c['intro'] = sub(c['intro'])
        else:
            key, part = w.split('.')
            sec = next(x for x in c['sections'] if x['key'] == key)
            if part == 'title':
                sec['title'] = sub(sec['title'])
            else:
                sec['blocks'] = walk(sec['blocks'])
        res.append((r['id'], r.get('count', 1), cnt[0]))
    return res


def markers_ok(o):
    """묶음 표시가 문자열마다 열고 닫힘이 짝이 맞고 중첩되지 않는지"""
    bad = []

    def chk(s):
        d = 0
        for ch in s:
            if ch == NWO:
                d += 1
                if d > 1: return False
            elif ch == NWC:
                d -= 1
                if d < 0: return False
        return d == 0

    def walk(o):
        if isinstance(o, dict):
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
        elif isinstance(o, str) and not chk(o):
            bad.append(o[:40])
    walk(o)
    return bad


def render_og(data, tpl):
    """mobile/og.html -> 1200x630 PNG bytes (CONFIG.event 문구 사용, 폰트는 kiosk-src/vendor, 흰 로고 7개)"""
    import html as _html
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    ev = {}
    blk = re.search(r'event:\s*\{(.*?)\}', tpl, re.S).group(1)
    for k in ('kicker', 'lead', 'footL', 'footR'):
        ev[k] = json.loads(re.search(k + r':\s*("(?:[^"\\]|\\.)*")', blk).group(1))
    lines = ev['lead'].split('\n')
    lead = '<br>'.join(('<span class="hl">%s</span>' if i == len(lines) - 1 else '%s') % _html.escape(x) for i, x in enumerate(lines))
    logos = ''
    for c in data:
        f = Path(SRC, 'logos', c['wlogo'] + '.png')
        h = round(30 * (c.get('wlogoScale') or 1))
        logos += f'<img src="{f.as_uri()}" style="height:{h}px" alt="">'
    og = (open(OG_TPL, encoding='utf-8').read()
          .replace('__FONT_SUIT__', Path(SRC, 'vendor', 'SUIT-Variable.woff2').as_uri())
          .replace('__FONT_MONO__', Path(SRC, 'vendor', 'chivo-mono-latin-wght-normal.woff2').as_uri())
          .replace('__KICKER__', _html.escape(ev['kicker'])).replace('__LEAD__', lead).replace('__LOGOS__', logos)
          .replace('__FOOTL__', _html.escape(ev['footL'] + ' · one-pager')).replace('__FOOTR__', _html.escape(ev['footR'])))
    left = re.findall(r'__[A-Z_]+__', og)
    if left:
        sys.exit(f'og.html unreplaced placeholders: {left}')
    with tempfile.TemporaryDirectory() as td:
        hp = os.path.join(td, 'og.html'); open(hp, 'w', encoding='utf-8').write(og)
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={'width': 1200, 'height': 630}, device_scale_factor=1, offline=True)
            ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith(('file://', 'data:')) else r.abort())
            pg = ctx.new_page()
            pg.goto(Path(hp).as_uri())
            pg.wait_for_function("document.documentElement.dataset.ready === '1' && document.fonts.status === 'loaded'")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)")
            png = pg.screenshot(type='png')
            b.close()
    im = Image.open(io.BytesIO(png)).convert('RGB')
    for colors in (None, 256, 128, 64):
        q = im if colors is None else im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        bb = io.BytesIO(); q.save(bb, 'PNG', optimize=True)
        if bb.tell() <= OG_MAX:
            break
    return bb.getvalue(), im.size


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
    rules = json.load(open(RULES, encoding='utf-8'))['nw']

    # 줄바꿈 보조를 넣은 화면용 DATA (원고 data는 그대로). 묶음 규칙(원문 구절로 찾음) -> B1 단어결합자 순서
    disp = json.loads(json.dumps(data, ensure_ascii=False))
    rule_res = apply_rules(disp, rules)
    b1_hits = []
    disp = apply_b1(disp, None, b1_hits)
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
    chars = set(tpl) | set(kiosk_tpl) | set(json.dumps(disp, ensure_ascii=False)) | set(DESC) | set(EXTRA_CHARS)
    chars |= {chr(i) for i in range(0x20, 0x7f)}
    chars -= {WJ, NWO, NWC, NBH}   # 보이지 않는 보조 문자, U+2011은 아래에서 '-' 글리프로 연결
    chars = ''.join(sorted(c for c in chars if ord(c) >= 0x20))
    with tempfile.TemporaryDirectory() as td:
        tf = os.path.join(td, 'chars.txt'); of = os.path.join(td, 'suit.woff2')
        open(tf, 'w', encoding='utf-8').write(chars)
        subprocess.run(['pyftsubset', os.path.join(SRC, 'vendor', 'SUIT-Variable.woff2'), f'--text-file={tf}',
                        '--flavor=woff2', f'--output-file={of}', '--layout-features=*', '--no-hinting'], check=True)
        # SUIT에는 U+2011(비분리 하이픈) 글리프가 없어 시스템 폰트로 대체되면 모양이 달라짐 -> '-' 글리프를 그대로 연결
        from fontTools.ttLib import TTFont
        ft = TTFont(of)
        for t in ft['cmap'].tables:
            if t.isUnicode() and 0x2d in t.cmap:
                t.cmap[0x2011] = t.cmap[0x2d]
        ft.flavor = 'woff2'; ft.save(of)
        suit = put('suit', 'woff2', open(of, 'rb').read())
    mono = put('mono', 'woff2', open(os.path.join(SRC, 'vendor', 'chivo-mono-latin-wght-normal.woff2'), 'rb').read())

    # 서브셋에 빠진 글자 확인 (시스템 폰트로 대체됨 -> 경고만)
    from fontTools.ttLib import TTFont
    cmap = TTFont(os.path.join(DIST, suit)).getBestCmap()
    missing = [c for c in chars if ord(c) not in cmap and not c.isspace()]

    # 공유 미리보기 이미지 (첫 로드에는 포함되지 않음)
    og_png, og_size = render_og(data, tpl)
    og = put('og', 'png', og_png)

    out = (tpl.replace('__FONT_SUIT__', suit).replace('__FONT_MONO__', mono)
              .replace('__DESC__', DESC).replace('__WORDMARK__', wordmark)
              .replace('__OG_URL__', SITE).replace('__OG_IMAGE__', SITE + og)
              .replace('__DATA__', json.dumps(disp, ensure_ascii=False, separators=(',', ':')))
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
    # 줄바꿈 보조: 원문 대조 (index.html에 실제로 들어간 DATA를 다시 읽어서 비교)
    emitted = json.loads(re.search(r'var DATA = (.*?);\nvar IMAGES', out, re.S).group(1))
    same = restore(emitted) == data
    print(f'linebreak: B1 word-joiner {sum(b1_hits)} places; rules ' + ', '.join(f'{i}:{n}/{e}' for i, e, n in rule_res))
    print('linebreak restore == data/data.json:', 'ok' if same else 'FAILED')
    if not same:
        ok = False
    bad_rules = [(i, e, n) for i, e, n in rule_res if e != n]
    if bad_rules:
        print(f'FAIL: linebreak rule count mismatch (id, expected, found): {bad_rules}'); ok = False
    bm = markers_ok(emitted)
    if bm:
        print(f'FAIL: unbalanced nw markers: {bm}'); ok = False
    # og 이미지
    og_sz = os.path.getsize(os.path.join(DIST, og))
    print(f'og image: {og} {og_size[0]}x{og_size[1]} {og_sz/1024:.1f} KB (limit {OG_MAX/1024:.0f} KB, not in first load)')
    if og_size != (1200, 630) or og_sz > OG_MAX:
        print('FAIL: og image size'); ok = False
    if f'content="{SITE}{og}"' not in out:
        print('FAIL: og:image absolute url missing'); ok = False
    if missing:
        print(f'WARN: glyphs missing in SUIT subset (system fallback): {"".join(missing)!r}')
    print('forbidden/external check:', 'ok' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
