"""모바일 웹 회귀 검사 (playwright, chromium)

  python3 -I tests/check_mobile.py            # dist/ 를 먼저 빌드해 둘 것 (build_mobile.py)

- 오프라인 컨텍스트(offline=True) + file:// 로 dist/index.html 을 연다. file:// 이 아닌 요청은 전부 차단·기록.
- 뷰포트 4종 x 7개사: 목록 > 행 터치 > 진입 연출 종료 대기 > 다음 질문(인라인 카드 또는 고정 바)으로 MENTOR까지 > 다른 기업 이야기 보기 > 목록
  답변마다 (a) 가로 스크롤 없음 (b) 다음 질문 어포던스 보임 (c) 보이는 글자 12px 이상, 본문 p 16px 이상 (d) 콘솔 에러·요청 실패 0
- 키워드 탭(MARKET), 뒤로가기(go_back), 링크 href, 키워드 탭바 한 줄 수용, 스크린샷(shots/)
- 전체화면: 첫 터치에서 1회 요청(행 열기는 그대로), 해제 후 재시도 없음, 거부·미지원(아이폰 사파리 모사)에서 에러 0,
  전체화면 진입·해제로 뷰포트 높이가 바뀌어도(헤드리스는 실제 창 크기가 안 바뀌어 set_viewport_size로 모사) 진입 연출·답변 위치가 튀지 않음
- (v1.2 추가) A1 연출 중 터치 즉시 처리·중복 없음, A3 상단 메뉴 버튼, A4 280px 탭바, A5 주소(#c{기업}a{섹션}) 갱신·복원,
  A7 본 기업 표시(localStorage, 예외 환경 포함), B1~B4 줄바꿈(구절이 한 줄 안에 있는지, .nw 가로 넘침, core_field 마지막 줄)
통과 기준: 모든 뷰포트에서 "screens N no-next []" 와 errors [] 출력, 마지막 줄 RESULT PASS
"""
import asyncio, glob, json, os, shutil, sys
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
URL = 'file://' + os.path.join(ROOT, 'dist', 'index.html')
SHOTS = os.path.join(ROOT, 'shots')
DATA = json.load(open(os.path.join(ROOT, 'data', 'data.json'), encoding='utf-8'))
# Galaxy S24 / iPhone SE / iPhone 16 / iPhone Pro Max
VIEWPORTS = [('360x780', 360, 780), ('375x667', 375, 667), ('393x852', 393, 852), ('430x932', 430, 932)]
NARROW = ('280x700', 280, 700)   # A4·B 가로 넘침 검증용 (큰 글씨 설정 모사)
norm = lambda t: t.replace('\u2060', '').replace('\u2011', '-')
EXPECT_HOME = {i: c['home'] for i, c in enumerate(DATA)}

JS_STATE = """() => {
  const bar = document.querySelector('#dHead').getBoundingClientRect();
  const chips = document.querySelector('#chips').getBoundingClientRect();
  const g = document.querySelector('#next .ghost button');
  let card = false, home = false, label = '';
  if (g) { const r = g.getBoundingClientRect(); card = r.height > 0 && r.top >= bar.bottom - 1 && r.bottom <= chips.top + 1; home = !!g.dataset.home; label = g.textContent; }
  const nb = document.querySelector('#nbar');
  return { card, nbar: nb.classList.contains('on'), home, label,
           sw: document.documentElement.scrollWidth, iw: innerWidth,
           turns: [...document.querySelectorAll('#thread .turn')].map(t => t.id) };
}"""

# requestFullscreen 호출 횟수·결과 기록 (원래 함수는 그대로 호출)
FS_SPY = """(()=>{const o=Element.prototype.requestFullscreen; window.__fs={calls:0,ok:0,err:null};
  if(o) Element.prototype.requestFullscreen=function(a){window.__fs.calls++; const r=o.call(this,a); r.then(()=>{window.__fs.ok++},e=>{window.__fs.err=String(e)}); return r;};})()"""
FS_REJECT = "Element.prototype.requestFullscreen=function(){window.__fsReq=(window.__fsReq||0)+1;return Promise.reject(new TypeError('Permissions check failed'))}"
FS_THROW = "Element.prototype.requestFullscreen=function(){window.__fsReq=(window.__fsReq||0)+1;throw new TypeError('not allowed')}"
FS_IPHONE = """Object.defineProperty(Document.prototype,'fullscreenEnabled',{get(){return undefined}});
  Object.defineProperty(Document.prototype,'webkitFullscreenEnabled',{get(){return undefined}});
  delete Element.prototype.requestFullscreen; delete Element.prototype.webkitRequestFullscreen;"""
FS_STUB = "Element.prototype.requestFullscreen=function(){window.__fsReq=(window.__fsReq||0)+1;return Promise.resolve()}"
JS_POS = """() => { const t=[...document.querySelectorAll('#thread .turn')].pop(); const bar=document.querySelector('#dHead').getBoundingClientRect().bottom;
  return { y: scrollY, rel: t ? Math.round(t.getBoundingClientRect().top - bar) : null, dq: Math.round(document.querySelector('#dQ').getBoundingClientRect().top),
           logo: Math.round(document.querySelector('#intro img').getBoundingClientRect().top), pad: document.querySelector('#pad').style.height }; }"""

JS_FONTS = """() => {
  const scr = document.querySelector('.screen.on');
  let min = 1e9, minEl = '', pmin = 1e9, pEl = '';
  const walker = document.createTreeWalker(scr, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue;
    const el = n.parentElement; if (seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el);
    if (cs.visibility !== 'visible' || el.getClientRects().length === 0) continue;
    let a = el, hidden = false; while (a && a !== document.body) { const s = getComputedStyle(a); if (s.opacity === '0' || s.display === 'none' || s.visibility === 'hidden') { hidden = true; break; } a = a.parentElement; }
    if (hidden) continue;
    const r = el.getBoundingClientRect(); if (r.bottom < 0 || r.top > innerHeight) continue;
    const fs = parseFloat(cs.fontSize);
    if (fs < min) { min = fs; minEl = el.className + ':' + n.textContent.trim().slice(0, 16); }
    const p = el.closest('p'); if (p) { const pf = parseFloat(getComputedStyle(p).fontSize); if (pf < pmin) { pmin = pf; pEl = p.className; } }
  }
  return { min, minEl, pmin: pmin === 1e9 ? null : pmin, pEl };
}"""


async def wait_reveal_done(pg):
    if os.environ.get('DEBUG'):
        print('  state', await pg.evaluate("[location.hash, document.querySelector('.screen.on').id, document.querySelector('#next').className]"))
    await pg.wait_for_function("document.querySelector('#next').classList.contains('on') || !document.querySelector('#next').classList.contains('rv')", timeout=15000)
    await pg.wait_for_timeout(800)   # 카드 등장 후 연출 종료(busy 해제)까지 약 0.5초


async def wait_answer(pg, n_before):
    await pg.wait_for_function(f"(()=>{{const t=document.querySelectorAll('#thread .turn');return t.length>0 && t[t.length-1].querySelector('.ans') && document.querySelector('#next .ghost button')}})()", timeout=10000)
    await pg.wait_for_timeout(1300)


async def check_screen(pg, vp, tag, bad, issues):
    s = await pg.evaluate(JS_STATE)
    if not (s['card'] or s['nbar']):
        bad.append((vp, tag))
    if s['sw'] > s['iw']:
        issues.append(f'{vp} {tag}: horizontal scroll {s["sw"]}>{s["iw"]}')
    f = await pg.evaluate(JS_FONTS)
    if f['min'] < 12:
        issues.append(f'{vp} {tag}: font {f["min"]}px at {f["minEl"]}')
    if f['pmin'] is not None and f['pmin'] < 16:
        issues.append(f'{vp} {tag}: p font {f["pmin"]}px at {f["pEl"]}')
    return s


async def tap_next(pg):
    s = await pg.evaluate(JS_STATE)
    if s['card']:
        await pg.locator('#next .ghost button').tap()
        return 'card'
    await pg.locator('#nbar').tap()
    return 'nbar'


async def run_viewport(b, vp, w, h):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=True, has_touch=True, device_scale_factor=3, offline=True)
    external, errors = [], []

    async def router(route):
        if route.request.url.startswith(('file://', 'data:')):
            await route.continue_()
        else:
            external.append(route.request.url); await route.abort()
    await ctx.route('**/*', router)
    pg = await ctx.new_page()
    pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.on('requestfailed', lambda r: errors.append(f'requestfailed: {r.url} {r.failure}'))
    await pg.add_init_script(FS_SPY)
    await pg.goto(URL)
    await pg.wait_for_timeout(600)
    shot = lambda name: pg.screenshot(path=os.path.join(SHOTS, f'{vp}_{name}.png'))

    bad, issues, screens, via = [], [], 0, {'card': 0, 'nbar': 0}
    fs_first = None
    # 첫 화면
    if await pg.evaluate("document.documentElement.scrollWidth > innerWidth"):
        issues.append(f'{vp} home: horizontal scroll')
    f = await pg.evaluate(JS_FONTS)
    if f['min'] < 12: issues.append(f'{vp} home: font {f["min"]}px at {f["minEl"]}')
    if vp in ('393x852', '360x780'):
        await shot('01_home')
        await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_01_home_full.png'), full_page=True)
    # 키워드 탭바 한 줄 수용
    chip_fit = None

    for i, c in enumerate(DATA):
        await pg.locator(f'.row[data-i="{i}"]').tap()
        await wait_reveal_done(pg)
        if i == 0:
            # 첫 터치: 전체화면 1회 요청 + 행 열기는 정상
            fs_first = await pg.evaluate("({fsEl: !!document.fullscreenElement, spy: window.__fs, detail: document.querySelector('#detail').classList.contains('on'), hash: location.hash, intro: document.querySelector('#dQ').textContent})")
            if not fs_first['detail'] or fs_first['hash'] != '#c0' or norm(fs_first['intro']) != c['intro']:
                issues.append(f'{vp} first tap did not open row: {fs_first}')
            if fs_first['spy']['calls'] != 1:
                issues.append(f'{vp} first tap fullscreen calls {fs_first["spy"]}')
            # 전체화면에서 빠져나와도 다시 시도하지 않아야 함
            await pg.evaluate("document.fullscreenElement ? document.exitFullscreen().catch(()=>{}) : null")
            await pg.wait_for_timeout(300)
        if chip_fit is None:
            chip_fit = await pg.evaluate("""(()=>{const C=document.querySelector('#chips');const r=C.getBoundingClientRect();
              const over=[...C.children].filter(x=>x.scrollWidth>x.clientWidth+0.5||x.getBoundingClientRect().right>r.right+0.5).map(x=>x.textContent);
              const tops=new Set([...C.children].map(x=>Math.round(x.getBoundingClientRect().top)));
              return {fs:getComputedStyle(C.children[0]).fontSize, w:C.clientWidth, sw:C.scrollWidth, rows:tops.size, over}})()""")
            if vp == '360x780':
                await pg.locator('#dock').screenshot(path=os.path.join(SHOTS, f'{vp}_02_keyword_tabbar.png'))
        if vp == '393x852' and i == 1:
            await shot('02_ideaocean_after_reveal')
        # 링크
        href = await pg.evaluate("[document.querySelector('#bWeb').getAttribute('href'), document.querySelector('#bMail').getAttribute('href'), document.querySelector('#bWeb').target]")
        from urllib.parse import quote
        exp_mail = 'mailto:' + c['email'] + '?subject=' + quote('[d.day founders summit] 부스 문의드립니다', safe="-_.!~*'()")
        if href[0] != c['home'] or href[1] != exp_mail or href[2] != '_blank':
            issues.append(f'{vp} {c["ko"]}: link mismatch {href} vs {c["home"]} {exp_mail}')
        # 진입 직후에도 다음 질문이 보여야 함
        await check_screen(pg, vp, f'{c["ko"]}/intro', bad, issues)
        if (await pg.evaluate('location.hash')) != f'#c{i}':
            issues.append(f'{vp} {c["ko"]}: hash after reveal {await pg.evaluate("location.hash")}')
        steps = 0
        while True:
            s = await pg.evaluate(JS_STATE)
            if s['home']:
                break
            n0 = len(s['turns'])
            via[await tap_next(pg)] += 1
            await wait_answer(pg, n0)
            steps += 1; screens += 1
            s = await check_screen(pg, vp, f'{c["ko"]}/{s["turns"][-1] if s["turns"] else ""}+{steps}', bad, issues)
            key = DATA[i]['sections'][steps - 1]['key']
            hh = await pg.evaluate('location.hash')
            if hh != f'#c{i}a{steps - 1}':
                issues.append(f'{vp} {c["ko"]}: hash {hh} != #c{i}a{steps - 1}')
            if vp == '393x852' and i == 1:
                if key == 'problem': await shot('03_ideaocean_problem')
                if key == 'market': await shot('04_ideaocean_market')
                if key == 'mentor':
                    await shot('05_ideaocean_mentor')
            if steps > 10:
                issues.append(f'{vp} {c["ko"]}: did not reach end'); break
        if steps != len(c['sections']):
            issues.append(f'{vp} {c["ko"]}: steps {steps} != sections {len(c["sections"])}')
        # 마지막 카드
        s = await pg.evaluate(JS_STATE)
        if not (s['card'] or s['nbar']): bad.append((vp, f'{c["ko"]}/end'))
        if vp == '393x852' and i == 1:
            await pg.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            await pg.wait_for_timeout(700)
            await shot('06_ideaocean_last_card')
        await tap_next(pg)
        await pg.wait_for_function("document.querySelector('#home').classList.contains('on')", timeout=5000)
        await pg.wait_for_timeout(350)
        if '#c' in pg.url:
            issues.append(f'{vp} {c["ko"]}: url still {pg.url} after home')

    # 키워드 탭: 코스모비에서 2개 답변 후 MARKET 탭 -> 스레드가 MARKET 하나로 새로 시작
    await pg.locator('.row[data-i="0"]').tap(); await wait_reveal_done(pg)
    for _ in range(2):
        await tap_next(pg); await wait_answer(pg, 0)
    before = (await pg.evaluate(JS_STATE))['turns']
    await pg.locator('.chip', has_text='MARKET').tap(); await wait_answer(pg, 0)
    after = await pg.evaluate(JS_STATE)
    on = await pg.evaluate("[...document.querySelectorAll('.chip.on')].map(x=>x.textContent)")
    kw = f'before={before} after={after["turns"]} on={on}'
    if after['turns'] != ['turn-3'] or on != ['MARKET']:
        issues.append(f'{vp} keyword tab: {kw}')
    # 진입 연출 중 키워드 탭
    await pg.locator('#bAll').tap(); await pg.wait_for_function("document.querySelector('#home').classList.contains('on')")
    await pg.locator('.row[data-i="2"]').tap(); await pg.wait_for_timeout(500)
    await pg.locator('.chip', has_text='MARKET').tap(); await wait_answer(pg, 0)
    rv = await pg.evaluate("[[...document.querySelectorAll('#thread .turn')].map(t=>t.id).join(), document.querySelector('#dQ').textContent, document.querySelectorAll('#panel .rv:not(.on)').length]")
    if rv[0] != 'turn-3' or norm(rv[1]) != DATA[2]['intro'] or rv[2] != 0:
        issues.append(f'{vp} chip during reveal: {rv}')
    fs_calls = await pg.evaluate("window.__fs.calls")
    if fs_calls != 1:
        issues.append(f'{vp} fullscreen requested {fs_calls} times (expected once)')
    # 뒤로가기
    await pg.go_back(); await pg.wait_for_timeout(500)
    back_ok = await pg.evaluate("document.querySelector('#home').classList.contains('on') && !document.querySelector('#detail').classList.contains('on')")
    if not back_ok: issues.append(f'{vp} go_back did not return to list')
    # 딥링크
    await pg.goto('about:blank'); await pg.goto(URL + '#c4'); await pg.wait_for_timeout(600)
    dl = await pg.evaluate("[document.querySelector('#detail').classList.contains('on'), document.querySelector('#dBar').textContent]")
    await pg.go_back(); await pg.wait_for_timeout(500)
    dl_back = await pg.evaluate("document.querySelector('#home').classList.contains('on')")
    if not dl[0] or DATA[4]['ko'] not in dl[1] or not dl_back:
        issues.append(f'{vp} deeplink #c4: {dl} back_to_home={dl_back}')
    await ctx.close()
    fs_info = {'first': fs_first and {k: fs_first[k] for k in ('fsEl', 'spy')}, 'calls_total': fs_calls}
    return screens, bad, issues, errors, external, via, chip_fit, kw, fs_info


async def run_fullscreen_variants(b, vp, w, h):
    """전체화면 거부·예외·미지원(아이폰 사파리 모사): 첫 터치가 행을 정상으로 열고 에러 0.
    stub: 전체화면 진입/해제로 뷰포트 높이가 바뀌는 상황을 모사해 진입 연출·답변 위치가 튀지 않는지."""
    issues, errors, external, info = [], [], [], {}
    for mode, script in (('reject', FS_REJECT), ('throw', FS_THROW), ('iphone', FS_IPHONE), ('stub', FS_STUB)):
        H0 = h - 110 if mode == 'stub' else h   # stub: 주소창·상태바가 있는 높이에서 시작해 전체화면 높이(h)로 커짐
        ctx = await b.new_context(viewport={'width': w, 'height': H0}, is_mobile=True, has_touch=True, device_scale_factor=3, offline=True)

        async def router(route):
            if route.request.url.startswith(('file://', 'data:')):
                await route.continue_()
            else:
                external.append(route.request.url); await route.abort()
        await ctx.route('**/*', router)
        pg = await ctx.new_page()
        pg.on('console', lambda m, mode=mode: errors.append(f'{mode} console: ' + m.text) if m.type == 'error' else None)
        pg.on('pageerror', lambda e, mode=mode: errors.append(f'{mode} pageerror: ' + str(e)))
        await pg.add_init_script(script)
        await pg.goto(URL); await pg.wait_for_timeout(500)
        ci = 2
        await pg.locator(f'.row[data-i="{ci}"]').tap()
        if mode != 'stub':
            await wait_reveal_done(pg)
            r = await pg.evaluate("[document.querySelector('#detail').classList.contains('on'), location.hash, document.querySelector('#dQ').textContent, window.__fsReq || 0, !!document.fullscreenElement]")
            info[mode] = {'opened': r[0] and r[1] == f'#c{ci}' and norm(r[2]) == DATA[ci]['intro'], 'requests': r[3]}
            if not info[mode]['opened']:
                issues.append(f'{vp} fs-{mode}: row not opened {r}')
            if mode == 'iphone' and r[3] != 0:
                issues.append(f'{vp} fs-iphone: requested {r[3]}')
            if mode in ('reject', 'throw'):
                await pg.locator('.chip', has_text='MARKET').tap(); await wait_answer(pg, 0)
                n = await pg.evaluate("window.__fsReq || 0")
                if n != 1: issues.append(f'{vp} fs-{mode}: requested {n} times (expected once)')
        else:
            # 진입 연출 중 높이 변화: 로고·회사 소개 위치와 스크롤 위치가 그대로여야 함
            await pg.wait_for_timeout(600)
            a = await pg.evaluate(JS_POS)
            await pg.set_viewport_size({'width': w, 'height': h}); await pg.wait_for_timeout(300)
            bb = await pg.evaluate(JS_POS)
            if (a['dq'], a['logo'], a['y']) != (bb['dq'], bb['logo'], bb['y']):
                issues.append(f'{vp} fs-stub reveal jumped {a} -> {bb}')
            await wait_reveal_done(pg)
            jumps = []
            for step in range(4):
                # 해제(작아짐) 상태에서 질문 > 다시 진입(커짐): 직전 질문 말풍선 위치 유지
                await pg.evaluate("document.dispatchEvent(new Event('fullscreenchange'))")
                await pg.set_viewport_size({'width': w, 'height': H0}); await pg.wait_for_timeout(250)
                await tap_next(pg); await wait_answer(pg, 0)
                s0 = await pg.evaluate(JS_POS)
                await pg.evaluate("document.dispatchEvent(new Event('fullscreenchange'))")
                await pg.set_viewport_size({'width': w, 'height': h}); await pg.wait_for_timeout(300)
                s1 = await pg.evaluate(JS_POS)
                jumps.append((s0['rel'], s1['rel'], s0['pad'], s1['pad']))
                if abs(s0['rel'] - s1['rel']) > 1:
                    issues.append(f'{vp} fs-stub answer {step + 1} moved {s0} -> {s1}')
                st = await pg.evaluate(JS_STATE)
                if not (st['card'] or st['nbar']):
                    issues.append(f'{vp} fs-stub answer {step + 1}: no next affordance after resize')
            info['stub'] = {'reveal_same': (a['dq'], a['y']) == (bb['dq'], bb['y']), 'rel/pad (before->after grow)': jumps}
        await ctx.close()
    return issues, errors, external, info



# ======================= v1.2 추가 검사 =======================
ASKS = {'why': '왜 지금 이 사업인가요?', 'problem': '어떤 문제를 해결하나요?', 'who': '가장 먼저 공략할 고객은 누구인가요?',
        'market': '시장은 얼마나 커질 수 있나요?', 'goal': '어떤 회사로 성장하고 싶나요?', 'mentor': '함께한 멘토는 누구인가요?'}
ANS_SEL = '.h, .p, .note, .subh, .tgt, .lst li, .stat, .step, .mentor'


def expect_count(ci, k):
    """답변 하나가 완성됐을 때 있어야 하는 요소 수 (제목 + 블록)"""
    s = DATA[ci]['sections'][k]
    n = 1 if s.get('title') else 0
    for b in s['blocks']:
        n += len(b['items']) if b['t'] in ('targets', 'list', 'stats', 'steps') else 1
    return n


def sec_index(ci, key):
    return [x['key'] for x in DATA[ci]['sections']].index(key)


async def new_page(b, w, h, init=None):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=True, has_touch=True, device_scale_factor=3, offline=True)
    errors, external = [], []

    async def router(route):
        if route.request.url.startswith(('file://', 'data:')):
            await route.continue_()
        else:
            external.append(route.request.url); await route.abort()
    await ctx.route('**/*', router)
    pg = await ctx.new_page()
    pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.on('requestfailed', lambda r: errors.append(f'requestfailed: {r.url} {r.failure}'))
    if init:
        await pg.add_init_script(init)
    return ctx, pg, errors, external


async def open_hash(pg, h):
    await pg.goto('about:blank'); await pg.goto(URL + h)
    await pg.evaluate('document.fonts.ready.then(()=>0)')
    await pg.wait_for_timeout(350)


JS_TURNS = """() => [...document.querySelectorAll('#thread .turn')].map(t => ({id: t.id, ans: t.querySelectorAll('.ans').length, typing: !!t.querySelector('.typing')}))"""


async def run_a1(b, vp, w, h):
    """A1: 연출 중 터치 즉시 처리. A5: 진행 상태 hash로 새로 열어 복원"""
    issues, info = [], {}
    ctx, pg, errors, external = await new_page(b, w, h)
    await pg.goto(URL); await pg.wait_for_timeout(500)
    await pg.locator('.row[data-i="0"]').tap(); await wait_reveal_done(pg)
    # (1) 답변 연출(카운트업·등장 애니메이션) 300ms 시점에 다음 질문 카드 -> 직전 답변 완성 + 새 질문 즉시
    await pg.locator('.chip', has_text='MARKET').tap()
    await pg.wait_for_function("!!document.querySelector('#turn-3 .ans')", timeout=5000)
    await pg.wait_for_timeout(300)
    r1 = await pg.evaluate("""(SEL) => { const a = document.querySelector('#turn-3 .ans');
      const before = [...a.querySelectorAll('.num[data-n]')].map(e => e.textContent === e.dataset.n);
      const busyCard = !!document.querySelector('#next .ghost button');
      document.querySelector('#next .ghost button').click();
      const cs = getComputedStyle(a);
      return { midBefore: before.some(x => !x), busyCard, turns: [...document.querySelectorAll('#thread .turn')].map(t => t.id),
               nums: [...a.querySelectorAll('.num[data-n]')].every(e => e.textContent === e.dataset.n), op: cs.opacity, anim: cs.animationName,
               cnt: a.querySelectorAll(SEL).length, newAsk: !!document.querySelector('#turn-4 .ask'), hash: location.hash }; }""", ANS_SEL)
    info['card_during_answer'] = r1
    if not (r1['turns'] == ['turn-3', 'turn-4'] and r1['nums'] and r1['op'] == '1' and r1['anim'] == 'none'
            and r1['cnt'] == expect_count(0, 3) and r1['newAsk'] and r1['hash'] == '#c0a4'):
        issues.append(f'{vp} A1 card during answer: {r1} expect cnt {expect_count(0, 3)}')
    # (2) 생각 모션(0.3초) 중 다른 탭 -> 진행 중 답변 정리, 새 섹션 즉시 시작, 늦게 도착하는 옛 답변 없음
    await pg.wait_for_timeout(300)
    await pg.locator('.chip', has_text='WHY NOW').tap()
    r2a = await pg.evaluate("[[...document.querySelectorAll('#thread .turn')].map(t=>t.id), !!document.querySelector('#turn-0 .ask')]")
    await pg.wait_for_timeout(1500)
    r2b = await pg.evaluate(JS_TURNS)
    on = await pg.evaluate("[...document.querySelectorAll('.chip.on')].map(x=>x.textContent)")
    info['tab_during_thinking'] = {'immediate': r2a, 'after': r2b, 'on': on}
    if r2a != [['turn-0'], True] or r2b != [{'id': 'turn-0', 'ans': 1, 'typing': False}] or on != ['WHY NOW']:
        issues.append(f'{vp} A1 tab during thinking: {info["tab_during_thinking"]}')
    # (3) 같은 탭 연타(생각 모션 중) -> 답변이 그 자리에서 완성, 하나만
    await pg.locator('.chip', has_text='PROBLEM').tap(); await pg.wait_for_timeout(300)
    await pg.locator('.chip', has_text='PROBLEM').tap()
    r3 = await pg.evaluate("""(SEL) => ({ turns: [...document.querySelectorAll('#thread .turn')].map(t => t.id + ':' + t.querySelectorAll('.ans').length),
      cnt: (document.querySelector('#turn-1 .ans') || document.body).querySelectorAll(SEL).length, typing: !!document.querySelector('.typing') })""", ANS_SEL)
    info['same_tab_twice'] = r3
    if r3['turns'] != ['turn-1:1'] or r3['cnt'] != expect_count(0, 1) or r3['typing']:
        issues.append(f'{vp} A1 same tab twice: {r3}')
    await pg.wait_for_timeout(1200)
    # (4) 다음 질문 카드/고정 바 연타 5회(0.26초 간격) -> 순서대로, 중복 없음
    clicks = await pg.evaluate("""async () => { const log = [];
      for (let n = 0; n < 5; n++) { const g = document.querySelector('#next .ghost button'), nb = document.querySelector('#nbar');
        if (g && !g.dataset.home) { g.click(); log.push('card'); } else if (nb.classList.contains('on')) { nb.click(); log.push('nbar'); } else log.push('-');
        await new Promise(r => setTimeout(r, 260)); }
      return log; }""")
    await pg.wait_for_timeout(1500)
    r4 = await pg.evaluate(JS_TURNS)
    ids = [int(t['id'].split('-')[1]) for t in r4]
    nxt = await pg.evaluate("(document.querySelector('#next .ghost em')||{}).textContent")
    exp_next = ASKS[DATA[0]['sections'][ids[-1] + 1]['key']] if ids[-1] + 1 < len(DATA[0]['sections']) else '다른 기업 이야기 보기'
    info['rapid_5'] = {'clicks': clicks, 'turns': [t['id'] for t in r4]}
    if (ids != list(range(1, 1 + len(ids))) or any(t['ans'] != 1 or t['typing'] for t in r4) or len(ids) < 2 or nxt != exp_next):
        issues.append(f'{vp} A1 rapid clicks: {r4} next={nxt!r} expected {exp_next!r} clicks={clicks}')
    # A5: 지금 주소로 새로 열면 같은 섹션까지 복원
    hh = await pg.evaluate('location.hash')
    info['hash'] = hh
    if hh != f'#c0a{ids[-1]}':
        issues.append(f'{vp} A5 hash {hh} != #c0a{ids[-1]}')
    await open_hash(pg, hh)
    rr = await pg.evaluate(JS_TURNS)
    if [t['id'] for t in rr] != [f'turn-{j}' for j in range(ids[-1] + 1)] or any(t['ans'] != 1 for t in rr):
        issues.append(f'{vp} A5 restore {hh}: {rr}')
    await ctx.close()
    return issues, errors, external, info


async def run_restore(b, vp, w, h):
    """A5: 딥링크 #c2a3 -> 0~3번 섹션까지, 마지막 질문 말풍선이 상단 바 아래. 뒤로가기는 목록"""
    issues = []
    ctx, pg, errors, external = await new_page(b, w, h)
    await open_hash(pg, '#c2a3')
    r = await pg.evaluate("""() => { const t = document.querySelector('#turn-3'), bar = document.querySelector('#dHead').getBoundingClientRect().bottom;
      return { turns: [...document.querySelectorAll('#thread .turn')].map(x => x.id), rel: t ? Math.round(t.getBoundingClientRect().top - bar) : null,
               on: [...document.querySelectorAll('.chip.on')].map(x => x.textContent), next: (document.querySelector('#next .ghost em')||{}).textContent,
               hash: location.hash, sw: document.documentElement.scrollWidth, iw: innerWidth }; }""")
    if r['turns'] != ['turn-0', 'turn-1', 'turn-2', 'turn-3'] or abs(r['rel'] - 12) > 3 or r['on'] != ['MARKET'] or r['next'] != ASKS['goal'] or r['hash'] != '#c2a3' or r['sw'] > r['iw']:
        issues.append(f'{vp} A5 deeplink #c2a3: {r}')
    await pg.go_back(); await pg.wait_for_timeout(500)
    if not await pg.evaluate("document.querySelector('#home').classList.contains('on')"):
        issues.append(f'{vp} A5 deeplink #c2a3 back did not return to list')
    await ctx.close()
    return issues, errors, external, r


JS_FIND = r"""([sel, phrase]) => {
  for (const root of document.querySelectorAll(sel)) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); const map = []; let s = '';
    while (w.nextNode()) { const n = w.currentNode, v = n.nodeValue;
      for (let i = 0; i < v.length; i++) { if (v[i] === '⁠') continue; s += v[i] === '‑' ? '-' : v[i]; map.push([n, i]); } }
    const at = s.indexOf(phrase); if (at < 0) continue;
    const r = document.createRange(); const a = map[at], z = map[at + phrase.length - 1];
    r.setStart(a[0], a[1]); r.setEnd(z[0], z[1] + 1);
    const rects = [...r.getClientRects()].filter(x => x.width > 0.5 && x.height > 0.5);
    const tops = rects.map(x => x.top), lh = Math.min(...rects.map(x => x.height));
    const anc = r.commonAncestorContainer, el = anc.nodeType === 1 ? anc : anc.parentElement;
    return { found: true, oneLine: Math.max(...tops) - Math.min(...tops) < lh * 0.5, rects: rects.length,
             nw: !!el.closest('.nw'), wj: r.toString().includes('⁠'), right: Math.round(Math.max(...rects.map(x => x.right))) };
  }
  return { found: false };
}"""

JS_NWFIT = """() => ({ sw: document.documentElement.scrollWidth, iw: innerWidth,
  over: [...document.querySelectorAll('.nw')].filter(e => e.getClientRects().length && e.getBoundingClientRect().right > innerWidth + 0.5).map(e => e.textContent + ':' + Math.round(e.getBoundingClientRect().right)),
  overCol: [...document.querySelectorAll('.nw')].filter(e => { const p = e.closest('.h,.p,.note,.lst li,.step .sb,.d-q,.mentor li,.stat .l'); return p && e.getClientRects().length && e.getBoundingClientRect().right > p.getBoundingClientRect().right + 0.5; }).map(e => e.textContent),
  multi: [...document.querySelectorAll('.nw')].filter(e => { const rs = [...e.getClientRects()].filter(x => x.width > 0.5); return rs.length && Math.max(...rs.map(x => x.top)) - Math.min(...rs.map(x => x.top)) > 2; }).map(e => e.textContent),
  markers: /[\\uE000\\uE001]/.test(document.querySelector('#app').textContent + document.title) })"""

JS_CORE = """() => { const sp = document.querySelector('#intro .d-core > span:last-child'); if (!sp) return null;
  const w = document.createTreeWalker(sp, NodeFilter.SHOW_TEXT), lines = new Map();
  while (w.nextNode()) { const n = w.currentNode;
    for (let i = 0; i < n.nodeValue.length; i++) { const ch = n.nodeValue[i]; if (/\\s|\\u2060/.test(ch)) continue;
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); const rc = r.getClientRects()[0]; if (!rc) continue;
      const k = Math.round(rc.top / 4); lines.set(k, (lines.get(k) || '') + ch); } }
  const L = [...lines.entries()].sort((a, b) => a[0] - b[0]).map(x => x[1]);
  return { lines: L.length, last: L[L.length - 1], lastCount: L[L.length - 1].length }; }"""

# (그룹, qn 인덱스, 섹션 key 또는 'intro', 위치 title/body/intro, 구절)
BREAKS = [
    # B1: 괄호 앞 단어까지 한 덩어리(.nw) + 괄호·조사 사이 단어결합자 (v1.2.1)
    ('B1', 4, 'goal', 'title', '서비스(CRO)를'), ('B1', 4, 'goal', 'body', '위탁(CRO)으로'), ('B1', 4, 'goal', 'body', '위탁생산(CDMO)으로'),
    ('B1', 0, 'goal', 'body', '‘허니비’를'), ('B1', 2, 'problem', 'body', '빈피킹(Bin-picking)이라고'), ('B1', 3, 'goal', 'body', '장비(DEBREX)를'),
    ('B1w', 4, 'goal', 'title', '(CDMO)으로'),   # 제목 끝: 묶음 없이 단어결합자만
    ('B2', 3, 'market', 'body', '(연구소·데모룸)'), ('B2', 0, 'problem', 'body', '(KAIST·KAI·한화시스템 등)'),
    ('B2', 5, 'goal', 'body', 'S2G(Station to Grid)'), ('B2', 1, 'goal', 'body', 'Agent–METHEUS–CAD'), ('B2', 1, 'goal', 'body', 'Human-in-the-Loop'),
    ('B3', 0, 'why', 'title', '부품 공급은'), ('B3', 1, 'intro', 'intro', '기계·제품 설계를'), ('B3', 1, 'market', 'title', '기계·제조 설계'),
    ('B3', 1, 'goal', 'title', '제작 가능한'), ('B3', 4, 'why', 'title', '신약 개발은'), ('B3', 5, 'why', 'title', '가장 큰데'),
    ('B3', 5, 'problem', 'title', '충전 하나가'),
]


async def run_breaks(b, vp, w, h):
    """B1~B4 + A3(상세 바 메뉴 버튼·기업명). 딥링크로 섹션을 열어 확인"""
    issues, table = [], {}
    ctx, pg, errors, external = await new_page(b, w, h)
    # 기업별 진입 화면: A3 + B4 + 가로 넘침
    a3 = {}
    for ci, c in enumerate(DATA):
        await open_hash(pg, f'#c{ci}')
        r = await pg.evaluate("""() => { const m = document.querySelector('#bMenu'), r = m.getBoundingClientRect(), ko = document.querySelector('#dBar .ko');
          return { w: Math.round(r.width), h: Math.round(r.height), vis: getComputedStyle(m).display !== 'none' && r.right <= innerWidth,
                   label: m.getAttribute('aria-label'), koFull: ko.scrollWidth <= ko.clientWidth + 1, side: document.querySelectorAll('use[href="#i-side"], #i-side').length,
                   homeBtn: document.querySelectorAll('#home .bar button').length }; }""")
        a3[c['qn']] = r
        if r['w'] < 44 or r['h'] < 44 or not r['vis'] or r['label'] != '목록으로 돌아가기' or not r['koFull'] or r['side'] or r['homeBtn']:
            issues.append(f'{vp} A3 {c["qn"]}: {r}')
        if ci in (0, 2, 3):
            cr = await pg.evaluate(JS_CORE)
            table[f'B4 {c["qn"]} core'] = cr
            if not (cr['lines'] == 1 or cr['lastCount'] >= 4):
                issues.append(f'{vp} B4 {c["qn"]} core last line {cr}')
        f = await pg.evaluate(JS_NWFIT)
        if f['sw'] > f['iw'] or f['over'] or f['markers'] or f['multi']:
            issues.append(f'{vp} intro {c["qn"]} overflow {f}')
    # v1.2.1 Q-05 VISION 스크린샷 (393x852)
    if vp == '393x852':
        await open_hash(pg, f'#c4a{sec_index(4, "goal")}')
        await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_11_q05_vision_v2.png'))
        await open_hash(pg, f'#c{DATA.index(DATA[0])}')
    # 메뉴 버튼 -> 목록
    await pg.locator('#bMenu').tap(); await pg.wait_for_timeout(500)
    if not await pg.evaluate("document.querySelector('#home').classList.contains('on')"):
        issues.append(f'{vp} A3 menu button did not return to list')
    # 구절별
    groups = {}
    for g, ci, key, where, phrase in BREAKS:
        groups.setdefault((ci, key), []).append((g, where, phrase))
    for (ci, key), items in groups.items():
        if key == 'intro':
            await open_hash(pg, f'#c{ci}')
        else:
            k = sec_index(ci, key)
            await open_hash(pg, f'#c{ci}a{k}')
        for g, where, phrase in items:
            sel = '#dQ' if where == 'intro' else (f'#turn-{k} .ans > .h:not(.s)' if where == 'title' else f'#turn-{k} .ans > :not(.who):not(.h)')
            r = await pg.evaluate(JS_FIND, [sel, phrase])
            need = {'B1': ('wj', 'nw'), 'B1w': ('wj',)}.get(g, ('nw',))
            ok = r.get('found') and r['oneLine'] and all(r[x] for x in need) and r['right'] <= w
            table[f'{g} {DATA[ci]["qn"]} {key}.{where} {phrase}'] = 'ok' if ok else r
            if not ok:
                issues.append(f'{vp} {g} {DATA[ci]["qn"]} {key} {phrase}: {r}')
        f = await pg.evaluate(JS_NWFIT)
        if f['sw'] > f['iw'] or f['over'] or f['markers'] or f['multi']:
            issues.append(f'{vp} {DATA[ci]["qn"]} {key} overflow {f}')
        if f['overCol']:
            table.setdefault('nw beyond column (warn)', []).extend(f['overCol'])
    await ctx.close()
    return issues, errors, external, table, a3


async def run_narrow(b):
    """A4: 280x700에서 탭바(11px, 넘치면 가로 스크롤), MENTOR 탭 터치 가능, 활성 탭이 보이게 이동"""
    vp, w, h = NARROW
    issues = []
    ctx, pg, errors, external = await new_page(b, w, h)
    await pg.goto(URL); await pg.wait_for_timeout(500)
    if await pg.evaluate("document.documentElement.scrollWidth > innerWidth"):
        issues.append(f'{vp} home: horizontal scroll')
    await pg.locator('.row[data-i="1"]').tap(); await wait_reveal_done(pg)
    tb = await pg.evaluate("""() => { const C = document.querySelector('#chips');
      return { fs: getComputedStyle(C.children[0]).fontSize, w: C.clientWidth, sw: C.scrollWidth, ox: getComputedStyle(C).overflowX }; }""")
    await pg.locator('#dock').screenshot(path=os.path.join(SHOTS, f'{vp}_01_tabbar_start.png'))
    await pg.locator('.chip', has_text='MENTOR').tap(); await wait_answer(pg, 0)
    m = await pg.evaluate("""() => { const C = document.querySelector('#chips').getBoundingClientRect(), on = document.querySelector('.chip.on');
      const r = on ? on.getBoundingClientRect() : null;
      return { turns: [...document.querySelectorAll('#thread .turn')].map(t => t.id), on: on && on.textContent,
               inView: !!r && r.left >= C.left - 0.5 && r.right <= C.right + 0.5, sw: document.documentElement.scrollWidth, iw: innerWidth,
               hit: !!r && document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2) === on }; }""")
    await pg.locator('#dock').screenshot(path=os.path.join(SHOTS, f'{vp}_02_tabbar_mentor.png'))
    # 다시 왼쪽 탭(WHY NOW)도 터치 가능
    await pg.locator('.chip', has_text='WHY NOW').tap(); await wait_answer(pg, 0)
    back = await pg.evaluate("[[...document.querySelectorAll('#thread .turn')].map(t=>t.id), [...document.querySelectorAll('.chip.on')].map(x=>x.textContent)]")
    info = {'tabbar': tb, 'mentor': m, 'why_after': back}
    if tb['fs'] != '11px' or (tb['sw'] > tb['w'] and tb['ox'] not in ('auto', 'scroll')):
        issues.append(f'{vp} A4 tabbar {tb}')
    if m['turns'] != ['turn-5'] or m['on'] != 'MENTOR' or not m['inView'] or not m['hit'] or m['sw'] > m['iw']:
        issues.append(f'{vp} A4 mentor {m}')
    if back != [['turn-0'], ['WHY NOW']]:
        issues.append(f'{vp} A4 why after mentor {back}')
    await ctx.close()
    return issues, errors, external, info


LS_THROW = """Object.defineProperty(window, 'localStorage', { configurable: true, get() { throw new DOMException('denied', 'SecurityError'); } });"""


async def run_seen(b):
    """A7: 본 기업 표시(새로고침 후 유지, localStorage 예외 환경), 스크린샷(393x852)"""
    vp, w, h = '393x852', 393, 852
    issues, info = [], {}
    ctx, pg, errors, external = await new_page(b, w, h)
    await pg.goto(URL); await pg.wait_for_timeout(500)
    await pg.locator('.row[data-i="1"]').tap(); await pg.wait_for_timeout(700)
    await pg.locator('#bAll').tap(); await pg.wait_for_function("document.querySelector('#home').classList.contains('on')")
    await pg.wait_for_timeout(300)
    await pg.locator('.row[data-i="3"]').tap(); await pg.wait_for_timeout(700)
    await pg.locator('#bMenu').tap(); await pg.wait_for_function("document.querySelector('#home').classList.contains('on')")
    await pg.wait_for_timeout(500)
    JS = """() => [...document.querySelectorAll('.row')].filter(r => r.classList.contains('seen')).map(r => ({ i: +r.dataset.i,
      ck: getComputedStyle(r.querySelector('.ck')).display, ar: getComputedStyle(r.querySelector('.ar')).display, op: getComputedStyle(r.querySelector('.qq')).opacity }))"""
    s1 = await pg.evaluate(JS)
    await pg.evaluate('window.scrollTo(0, 0)'); await pg.wait_for_timeout(300)
    await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_07_home_seen2.png'))
    await pg.reload(); await pg.wait_for_timeout(600)
    s2 = await pg.evaluate(JS)
    info['seen'] = s1; info['after_reload'] = [x['i'] for x in s2]
    exp = [{'i': 1, 'ck': 'block', 'ar': 'none', 'op': '0.72'}, {'i': 3, 'ck': 'block', 'ar': 'none', 'op': '0.72'}]
    if s1 != exp or s2 != exp:
        issues.append(f'A7 seen {s1} / reload {s2}')
    # 스크린샷: Q-05 VISION, Q-03 PROBLEM, Q-01 진입 연출(core_field)
    await open_hash(pg, f'#c4a{sec_index(4, "goal")}'); await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_08_q05_vision.png'))
    await open_hash(pg, f'#c2a{sec_index(2, "problem")}'); await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_09_q03_problem.png'))
    await pg.goto('about:blank'); await pg.goto(URL); await pg.wait_for_timeout(500)
    await pg.locator('.row[data-i="0"]').tap(); await wait_reveal_done(pg)
    core = await pg.evaluate("(()=>{const r=document.querySelector('.d-core').getBoundingClientRect();return {top:Math.round(r.top),bottom:Math.round(r.bottom),ih:innerHeight}})()")
    info['q01_core_visible'] = core['bottom'] <= core['ih'] - 50
    await pg.screenshot(path=os.path.join(SHOTS, f'{vp}_10_q01_reveal.png'))
    await ctx.close()
    # localStorage 예외 환경: 에러 없이 열리고 목록 표시는 이번 방문 동안만
    ctx, pg, e2, x2 = await new_page(b, w, h, LS_THROW)
    await pg.goto(URL); await pg.wait_for_timeout(500)
    await pg.locator('.row[data-i="0"]').tap(); await pg.wait_for_timeout(700)
    await pg.locator('#bAll').tap(); await pg.wait_for_function("document.querySelector('#home').classList.contains('on')")
    await pg.wait_for_timeout(300)
    s3 = [x['i'] for x in await pg.evaluate(JS)]
    info['ls_throw'] = s3
    if s3 != [0]:
        issues.append(f'A7 localStorage throw: {s3}')
    await ctx.close()
    return issues, errors + e2, external + x2, info


async def main():
    os.makedirs(SHOTS, exist_ok=True)
    allok = True
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for vp, w, h in VIEWPORTS:
            screens, bad, issues, errors, external, via, chip_fit, kw, fs_info = await run_viewport(b, vp, w, h)
            fi, fe, fx, fv = await run_fullscreen_variants(b, vp, w, h)
            issues += fi; errors += fe; external += fx
            ai, ae, ax, a1 = await run_a1(b, vp, w, h)
            ri, re_, rx, rs = await run_restore(b, vp, w, h)
            bi, be, bx, btab, a3 = await run_breaks(b, vp, w, h)
            issues += ai + ri + bi; errors += ae + re_ + be; external += ax + rx + bx
            print(f'[{vp}] screens {screens} no-next {bad}')
            print(f'[{vp}] advance via {via}; keyword-tab {kw}')
            print(f'[{vp}] tabbar {chip_fit}')
            print(f'[{vp}] fullscreen {fs_info}; variants {fv}')
            print(f'[{vp}] A1 {a1}')
            print(f'[{vp}] A3 menu {a3["Q-02"]}')
            print(f'[{vp}] A5 deeplink #c2a3 {rs}')
            print(f'[{vp}] B ' + json.dumps(btab, ensure_ascii=False))
            print(f'[{vp}] issues {issues}')
            print(f'[{vp}] external {external}')
            print(f'[{vp}] errors {errors}')
            if bad or issues or errors or external or (chip_fit and (chip_fit['rows'] != 1 or chip_fit['over'] or chip_fit['sw'] > chip_fit['w'])):
                allok = False
        # 280px: A4 + B 가로 넘침·한 줄
        vp, w, h = NARROW
        ni, ne, nx, ninfo = await run_narrow(b)
        bi, be, bx, btab, a3 = await run_breaks(b, vp, w, h)
        print(f'[{vp}] A4 {ninfo}')
        print(f'[{vp}] A3 menu {a3["Q-02"]}')
        print(f'[{vp}] B ' + json.dumps(btab, ensure_ascii=False))
        print(f'[{vp}] issues {ni + bi}')
        print(f'[{vp}] external {nx + bx}')
        print(f'[{vp}] errors {ne + be}')
        if ni or bi or ne or be or nx or bx:
            allok = False
        # A7 + 스크린샷
        si, se, sx, sinfo = await run_seen(b)
        print(f'[A7] {sinfo}')
        print(f'[A7] issues {si} external {sx} errors {se}')
        if si or se or sx:
            allok = False
        await b.close()
    og = glob.glob(os.path.join(ROOT, 'dist', 'assets', 'og.*.png'))
    if len(og) == 1:
        shutil.copyfile(og[0], os.path.join(SHOTS, 'og.png'))
    else:
        print('og image missing in dist'); allok = False
    print('RESULT', 'PASS' if allok else 'FAIL')
    sys.exit(0 if allok else 1)


asyncio.run(main())
