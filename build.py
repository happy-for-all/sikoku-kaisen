"""
build.py ― 四国回線提案シミュレーター ビルドスクリプト【本番版】
===========================================================
処理フロー：
  1. master.csv 読み込み → companies リスト生成
  2. CF上の現行 data.json を取得（前回ハッシュ・change_log 引き継ぎ）
  3. 各社ループ：
       - robots.txt チェック（SP可否の自動判定）
       - SP可 → ページ取得 → ハッシュ比較 → 変化あれば change_log 追記
       - SP不可 → スキップ・is_manual_required フラグ
  4. dist/ に data.json + index.html を出力 → wrangler deploy へ
===========================================================
"""

import os
import io
import csv
import json
import shutil
import hashlib
import requests
import urllib.robotparser
from datetime import datetime, timezone, timedelta

# ============================================================
# 定数
# ============================================================
DIST_DIR        = "dist"
INDEX_HTML      = 'index.html'
DATA_JSON       = 'data.json'
MASTER_CSV      = 'master.csv'
CHANGE_LOG_MAX  = 30          # change_log の最大保持件数
SP_TIMEOUT      = 12          # SP リクエストのタイムアウト秒数
SP_USER_AGENT   = 'Mozilla/5.0 (compatible; SikokuKaisenBot/1.0)'
JST             = timezone(timedelta(hours=9))

# 👑 CF Workers の公開URL（data.json の差分比較に使用）
CF_DATA_JSON_URL = 'https://sikoku-kaisen.cocoro.workers.dev/data.json'

# ============================================================
# ユーティリティ
# ============================================================

def now_jst() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d %H:%M')

def today_jst() -> str:
    return datetime.now(JST).strftime('%Y-%m-%d')

def page_hash(text: str) -> str:
    """ページテキストの MD5 ハッシュを返す"""
    return hashlib.md5(text.encode('utf-8', errors='replace')).hexdigest()

def safe_int(val, default=0) -> int:
    try:
        return int(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return default

# ============================================================
# ① master.csv 読み込み
# ============================================================

def load_master_csv() -> list[dict]:
    if not os.path.exists(MASTER_CSV):
        print(f'[build] 警告: {MASTER_CSV} が見つかりません。フォールバックデータを使用します。')
        return _fallback_companies()

    companies = []
    with open(MASTER_CSV, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            area_raw = row.get('area_pref', '')
            area_list = [a.strip() for a in area_raw.split('|') if a.strip()]

            companies.append({
                'id':                        row.get('company_id', '').strip(),
                'name':                      row.get('company_name', '').strip(),
                'area_pref':                 area_list,
                'type':                      row.get('type', '').strip(),
                'monthly_fee':               safe_int(row.get('monthly_fee_base', 0)),
                # 👑 マンション料金列がない・空欄の場合は戸建て料金をフォールバック
                'monthly_mansion':           safe_int(row.get('monthly_mansion', row.get('monthly_fee_base', 0))),
                'initial_fee':               safe_int(row.get('initial_fee', 0)),
                'construction_fee':          safe_int(row.get('construction_fee', 0)),
                'contract_term_months':      safe_int(row.get('contract_term_months', 24)),
                'cancellation_fee':          safe_int(row.get('cancellation_fee', 0)),
                'docomo_discount_per_person':safe_int(row.get('docomo_discount_per_person', 0)),
                'campaign_cashback':         safe_int(row.get('campaign_cashback', 0)),
                'speed_mbps':                safe_int(row.get('speed_mbps', 0)),
                'discount_type':             row.get('discount_type', 'none').strip(),
                'sp_url':                    row.get('sp_url', '').strip(),
                'is_manual':                 row.get('is_manual', 'true').strip().lower() == 'true',
                'is_manual_required':        False,
                'notes':                     row.get('notes', '').strip(),
            })

    print(f'[build] {MASTER_CSV} 読み込み完了: {len(companies)} 社')
    return companies


def _fallback_companies() -> list[dict]:
    """master.csv 不在時のフォールバックデータ（最新の数値に統一）"""
    return [
        {
            'id': 'docomo', 'name': 'ドコモ光',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 5720, 'monthly_mansion': 4400,
            'initial_fee': 4950, 'construction_fee': 28600,
            'contract_term_months': 24, 'cancellation_fee': 5500,
            'docomo_discount_per_person': 1210, 'campaign_cashback': 48600,
            'speed_mbps': 1000, 'discount_type': 'family',
            'sp_url': 'https://www.nttdocomo.co.jp/internet/hikari/charge/', 
            'is_manual': True, 'is_manual_required': False,
            'notes': '光コラボ。工事費28,600円はdポイント還元で実質無料。さらに20,000ポイント還元中（キャンペーン）。ドコモMAX等は1210円割引。',
        },
        {
            'id': 'picara', 'name': 'ピカラ光（STNet）',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 4950, 'monthly_mansion': 3740,
            'initial_fee': 0, 'construction_fee': 0,
            'contract_term_months': 24, 'cancellation_fee': 4950,
            'docomo_discount_per_person': 0, 'campaign_cashback': 30000,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://www.pikara.jp/hikari/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '初期費用・工事費0円(公式)。ステップ2コース。',
        },
        {
            'id': 'flets', 'name': 'NTTフレッツ光',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 6050, 'monthly_mansion': 4730,
            'initial_fee': 3300, 'construction_fee': 22000,
            'contract_term_months': 24, 'cancellation_fee': 5000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://flets-w.com/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '全国対応。プロバイダ料金別途。マンション料金は目安。',
        },
        {
            'id': 'au', 'name': 'auひかり',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 5610, 'monthly_mansion': 4180,
            'initial_fee': 3300, 'construction_fee': 48950,
            'contract_term_months': 36, 'cancellation_fee': 4730,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://www.au.com/internet/',
            'is_manual': False, 'is_manual_required': False,
            'notes': 'auスマホ割あり。マンション料金は目安。',
        },
        {
            'id': 'catv_kagawa', 'name': 'ケーブルメディア四国',
            'area_pref': ['香川'], 'type': 'CATV',
            'monthly_fee': 4950, 'monthly_mansion': 4950,
            'initial_fee': 5500, 'construction_fee': 11000,
            'contract_term_months': 12, 'cancellation_fee': 11000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 320, 'discount_type': 'none',
            'sp_url': 'https://www.cavy.co.jp/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '香川限定。',
        },
        {
            'id': 'catv_kochi', 'name': '高知ケーブルテレビ（KCB）',
            'area_pref': ['高知'], 'type': 'CATV',
            'monthly_fee': 4620, 'monthly_mansion': 4620,
            'initial_fee': 5500, 'construction_fee': 11000,
            'contract_term_months': 12, 'cancellation_fee': 5000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 200, 'discount_type': 'none',
            'sp_url': 'https://www.kcb.co.jp/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '高知限定。',
        },
    ]

# ============================================================
# 以下、以前と同じ通信・ビルド処理
# ============================================================
def fetch_prev_data() -> dict:
    try:
        resp = requests.get(CF_DATA_JSON_URL, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {'change_log': [], 'page_hashes': {}}

def can_scrape(base_url: str, target_url: str) -> bool:
    robots_url = base_url.rstrip('/') + '/robots.txt'
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch('*', target_url)
    except:
        return False

def scrape_hash(url: str) -> str | None:
    try:
        headers = {'User-Agent': SP_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=SP_TIMEOUT)
        resp.raise_for_status()
        return page_hash(resp.text)
    except:
        return None

def build():
    print('=' * 50)
    print(f'[build] ビルド開始: {now_jst()}')
    print('=' * 50)
    os.makedirs(DIST_DIR, exist_ok=True)
    if os.path.exists(INDEX_HTML):
        shutil.copy(INDEX_HTML, os.path.join(DIST_DIR, INDEX_HTML))
        print(f'[build] {INDEX_HTML} コピー完了')

    companies = load_master_csv()
    prev_data = fetch_prev_data()
    prev_hashes = prev_data.get('page_hashes', {})
    change_log = list(prev_data.get('change_log', []))
    page_hashes = {}

    for c in companies:
        sp_url = c.get('sp_url', '').strip()
        cid = c['id']
        if not sp_url or c.get('is_manual', False):
            c['is_manual_required'] = c.get('is_manual', False)
            continue

        from urllib.parse import urlparse
        parsed = urlparse(sp_url)
        base_url = f'{parsed.scheme}://{parsed.netloc}'

        if not can_scrape(base_url, sp_url):
            c['is_manual_required'] = True
            change_log.append({'date': today_jst(), 'company': c['name'], 'message': 'robots.txt によりSP不可', 'is_manual_required': True})
            continue

        current_hash = scrape_hash(sp_url)
        if current_hash is None:
            c['is_manual_required'] = True
            change_log.append({'date': today_jst(), 'company': c['name'], 'message': 'SPエラー（タイムアウト等）', 'is_manual_required': True})
            continue

        page_hashes[cid] = current_hash
        prev_hash = prev_hashes.get(cid)
        if prev_hash and prev_hash != current_hash:
            c['is_manual_required'] = True
            change_log.append({'date': today_jst(), 'company': c['name'], 'message': 'キャンペーンページ変化検知', 'is_manual_required': True})

    change_log = change_log[-CHANGE_LOG_MAX:]
    data = {'built_at': now_jst(), 'companies': companies, 'change_log': change_log, 'page_hashes': page_hashes}

    with open(os.path.join(DIST_DIR, DATA_JSON), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'[build] {DATA_JSON} 出力完了')
    manual_required = [c['name'] for c in companies if c.get('is_manual_required')]
    if manual_required:
        print(f'[build] ⚠ 手動確認推奨: {", ".join(manual_required)}')
    else:
        print(f'[build] ✅ 全社正常')
    print(f'[build] ビルド完了: {now_jst()}')

if __name__ == '__main__':
    build()
