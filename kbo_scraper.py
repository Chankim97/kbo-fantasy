"""
KBO 판타지 리그 — 자동 스크래퍼 v2
실제 KBO 기록실 HTML 구조에 맞춘 파서

사용법:
  python3 kbo_scraper.py           # 즉시 1회 실행 (테스트)
  python3 kbo_scraper.py --daemon  # 자정마다 자동 실행
"""

import requests
from bs4 import BeautifulSoup
import json, sys, time, re
from datetime import datetime, date, timedelta
from pathlib import Path

# ── 설정 ──────────────────────────────────────────────────────────────────
SAVE_DIR = Path(__file__).parent / "data"
SAVE_DIR.mkdir(exist_ok=True)

BASE = "https://www.koreabaseball.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer":        BASE + "/",
    "Accept-Language":"ko-KR,ko;q=0.9",
    "Accept":         "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ── 유틸 ──────────────────────────────────────────────────────────────────
def _i(v):
    try: return int(str(v).replace(",", "").strip())
    except: return 0

def _f(v):
    try: return float(str(v).replace(",", "").strip())
    except: return 0.0

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def get_page(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=15)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            log(f"  [{attempt+1}/{retries}] 재시도: {e}")
            time.sleep(3 * (attempt + 1))
    log(f"  페이지 로드 실패: {url}")
    return None

def parse_table(html, page_num=1):
    """KBO 기록실 표 공통 파서 — 실제 thead/tbody 구조 대응"""
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # 테이블 여러 후보 시도
    table = (soup.find("table", id="tblRecord")
          or soup.find("table", class_=re.compile(r"tData|record|tbl", re.I))
          or soup.find("div", class_=re.compile(r"record|tbl", re.I))
          and soup.find("div", class_=re.compile(r"record|tbl", re.I)).find("table")
          or soup.find("table"))

    if not table:
        return []

    tbody = table.find("tbody")
    rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

    result = []
    for row in rows:
        cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if cells:
            result.append(cells)
    return result

# ── 타자 기록 ──────────────────────────────────────────────────────────────
def scrape_hitters():
    """KBO 기록실 타자 기본기록 전체 페이지 수집"""
    all_players = {}
    log("📊 타자 기록 수집 시작...")

    # KBO 기록실 컬럼 순서 (2026 기준):
    # 0:순위 1:선수명 2:팀 3:AVG 4:G 5:PA 6:AB 7:R 8:H 9:2B 10:3B
    # 11:HR 12:TB 13:RBI 14:SAC 15:SF 16:BB 17:IBB 18:HBP 19:SO 20:GDP 21:SB 22:CS

    for page in range(1, 20):
        url    = f"{BASE}/Record/Player/HitterBasic/Basic1.aspx"
        params = {"sort": "HRA_RT", "order": "DESC", "pageNo": str(page)}
        html   = get_page(url, params)
        rows   = parse_table(html, page)

        if not rows:
            log(f"  타자 {page}페이지: 0행 → 종료")
            break

        count = 0
        for cells in rows:
            if len(cells) < 10:
                continue
            # 첫 컬럼이 숫자(순위)인지 확인
            try:
                int(cells[0])
            except ValueError:
                continue

            name = cells[1].strip()
            team = cells[2].strip()
            if not name or not team:
                continue

            # 기본 스탯
            ab  = _i(cells[6])
            h   = _i(cells[8])
            h2  = _i(cells[9])
            h3  = _i(cells[10])
            hr  = _i(cells[11])
            tb  = _i(cells[12]) if len(cells) > 12 else (h - h2 - h3 - hr) + h2*2 + h3*3 + hr*4
            rbi = _i(cells[13]) if len(cells) > 13 else 0
            sac = _i(cells[14]) if len(cells) > 14 else 0
            sf  = _i(cells[15]) if len(cells) > 15 else 0
            bb  = _i(cells[16]) if len(cells) > 16 else 0
            ibb = _i(cells[17]) if len(cells) > 17 else 0
            hbp = _i(cells[18]) if len(cells) > 18 else 0
            so  = _i(cells[19]) if len(cells) > 19 else 0
            gdp = _i(cells[20]) if len(cells) > 20 else 0
            sb  = _i(cells[21]) if len(cells) > 21 else 0
            cs  = _i(cells[22]) if len(cells) > 22 else 0
            pa  = _i(cells[5])  if len(cells) > 5  else ab + bb + hbp + sf + sac

            # 비율 스탯 계산
            avg = round(h / ab, 3) if ab > 0 else 0.0
            obp_den = ab + bb + hbp + sf
            obp = round((h + bb + hbp) / obp_den, 3) if obp_den > 0 else 0.0
            slg = round(tb / ab, 3) if ab > 0 else 0.0
            ops = round(obp + slg, 3)

            key = f"{name}_{team}"
            all_players[key] = {
                "name": name, "team": team, "type": "hitter",
                "g":   _i(cells[4]),
                "pa":  pa,  "ab": ab,  "r": _i(cells[7]),
                "h":   h,   "h2": h2,  "h3": h3,  "hr": hr,
                "tb":  tb,  "rbi": rbi,
                "sac": sac, "sf": sf,
                "bb":  bb,  "ibb": ibb, "hbp": hbp,
                "so":  so,  "gdp": gdp,
                "sb":  sb,  "cs": cs,
                "avg": avg, "obp": obp, "slg": slg, "ops": ops,
            }
            count += 1

        log(f"  타자 {page}페이지: {count}명 (누계 {len(all_players)}명)")
        if count < 3:  # 마지막 페이지
            break
        time.sleep(1.0)  # 서버 부하 방지

    log(f"✅ 타자 합계: {len(all_players)}명")
    return all_players

# ── 투수 기록 ──────────────────────────────────────────────────────────────
def scrape_pitchers():
    """KBO 기록실 투수 기본기록 전체 페이지 수집"""
    all_players = {}
    log("📊 투수 기록 수집 시작...")

    # KBO 기록실 투수 컬럼 (2026 기준):
    # 0:순위 1:선수명 2:팀 3:ERA 4:G 5:W 6:L 7:SV 8:HLD 9:IP
    # 10:H(피안타) 11:HR(피홈런) 12:BB 13:HBP 14:SO 15:R 16:ER 17:WP 18:BK 19:WHIP 20:QS 21:CG 22:SHO

    for page in range(1, 20):
        url    = f"{BASE}/Record/Player/PitcherBasic/Basic1.aspx"
        params = {"sort": "ERA", "order": "ASC", "pageNo": str(page)}
        html   = get_page(url, params)
        rows   = parse_table(html, page)

        if not rows:
            log(f"  투수 {page}페이지: 0행 → 종료")
            break

        count = 0
        for cells in rows:
            if len(cells) < 10:
                continue
            try:
                int(cells[0])
            except ValueError:
                continue

            name = cells[1].strip()
            team = cells[2].strip()
            if not name or not team:
                continue

            ip   = _f(cells[9])
            h_a  = _i(cells[10]) if len(cells) > 10 else 0
            hr_a = _i(cells[11]) if len(cells) > 11 else 0
            bb_a = _i(cells[12]) if len(cells) > 12 else 0
            hbp_a= _i(cells[13]) if len(cells) > 13 else 0
            so   = _i(cells[14]) if len(cells) > 14 else 0
            r_a  = _i(cells[15]) if len(cells) > 15 else 0
            er   = _i(cells[16]) if len(cells) > 16 else 0
            era  = _f(cells[3])
            whip = round((bb_a + h_a) / ip, 2) if ip > 0 else 99.99
            qs   = _i(cells[20]) if len(cells) > 20 else 0
            cg   = _i(cells[21]) if len(cells) > 21 else 0
            sho  = _i(cells[22]) if len(cells) > 22 else 0

            key = f"{name}_{team}"
            all_players[key] = {
                "name": name, "team": team, "type": "pitcher",
                "g":   _i(cells[4]),
                "w":   _i(cells[5]),  "l":   _i(cells[6]),
                "sv":  _i(cells[7]),  "hld": _i(cells[8]) if len(cells) > 8 else 0,
                "ip":  ip,
                "h_a": h_a, "hr_a": hr_a,
                "bb_a":bb_a,"hbp_a":hbp_a,
                "so":  so,
                "r_a": r_a, "er":   er,
                "era": era, "whip": whip,
                "qs":  qs,  "cg":   cg,  "sho": sho,
                "gidp": 0,  "bs": 0,     # 별도 페이지에 있음
            }
            count += 1

        log(f"  투수 {page}페이지: {count}명 (누계 {len(all_players)}명)")
        if count < 3:
            break
        time.sleep(1.0)

    log(f"✅ 투수 합계: {len(all_players)}명")
    return all_players

# ── 저장 + 실행 ────────────────────────────────────────────────────────────
def run_once():
    today = date.today().isoformat()
    log(f"{'='*50}")
    log(f"KBO 기록 수집: {today}")
    log(f"{'='*50}")

    t0 = time.time()
    hitters  = scrape_hitters()
    pitchers = scrape_pitchers()

    all_stats = {}
    all_stats.update(hitters)
    all_stats.update(pitchers)

    payload = {
        "date":     today,
        "scraped":  datetime.now().isoformat(),
        "hitters":  len(hitters),
        "pitchers": len(pitchers),
        "total":    len(all_stats),
        "players":  all_stats,
    }

    # 날짜별 파일 + 최신 파일 동시 저장
    dated_file  = SAVE_DIR / f"stats_{today}.json"
    latest_file = SAVE_DIR / "stats_latest.json"

    for f in [dated_file, latest_file]:
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    log(f"{'='*50}")
    log(f"완료: 타자 {len(hitters)}명 + 투수 {len(pitchers)}명")
    log(f"저장: {dated_file}")
    log(f"소요: {elapsed:.1f}초")
    log(f"{'='*50}")
    return payload

def run_daemon():
    """자정마다 자동 실행"""
    log("=== KBO 판타지 자동 스크래퍼 시작 ===")
    log("Ctrl+C 로 종료")

    # 시작 시 최신 파일 없으면 즉시 1회 실행
    if not (SAVE_DIR / "stats_latest.json").exists():
        log("최신 스탯 없음 → 즉시 1회 수집")
        try:
            run_once()
        except Exception as e:
            log(f"초기 수집 오류: {e}")

    while True:
        now  = datetime.now()
        # 다음 자정 00:10 (집계 여유 10분)
        next_run = now.replace(hour=0, minute=10, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)

        wait_sec = (next_run - now).total_seconds()
        h, m = int(wait_sec // 3600), int((wait_sec % 3600) // 60)
        log(f"다음 실행: {next_run:%Y-%m-%d %H:%M} ({h}시간 {m}분 후)")

        try:
            time.sleep(wait_sec)
        except KeyboardInterrupt:
            log("종료")
            break

        try:
            run_once()
        except Exception as e:
            log(f"수집 오류: {e}")

if __name__ == "__main__":
    if "--daemon" in sys.argv:
        run_daemon()
    else:
        run_once()
