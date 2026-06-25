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
DIST_DIR        = 'dist/sikoku-kaisen'
INDEX_HTML      = 'index.html'
DATA_JSON       = 'data.json'
MASTER_CSV      = 'master.csv'
CHANGE_LOG_MAX  = 30          # change_log の最大保持件数
SP_TIMEOUT      = 12          # SP リクエストのタイムアウト秒数
SP_USER_AGENT   = 'Mozilla/5.0 (compatible; SikokuKaisenBot/1.0)'
JST             = timezone(timedelta(hours=9))

# 👑 CF Workers の公開URL（data.json の差分比較に使用）
#    wrangler deploy 後の実際の URL に書き換えてください
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
    """
    master.csv を読み込んで companies リストを返す。
    ファイルが存在しない場合はハードコードしたフォールバックデータを返す。
    """
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
                'is_manual_required':        False,   # SP監視後に更新
                'notes':                     row.get('notes', '').strip(),
            })

    print(f'[build] {MASTER_CSV} 読み込み完了: {len(companies)} 社')
    return companies


def _fallback_companies() -> list[dict]:
    """master.csv 不在時のフォールバックデータ"""
    return [
        {
            'id': 'docomo', 'name': 'ドコモ光',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 5720, 'initial_fee': 3300, 'construction_fee': 0,
            'contract_term_months': 24, 'cancellation_fee': 0,
            'docomo_discount_per_person': 1100, 'campaign_cashback': 0,
            'speed_mbps': 1000, 'discount_type': 'family',
            'sp_url': '', 'is_manual': True, 'is_manual_required': False,
            'notes': '光コラボ。解約金なし。',
        },
        {
            'id': 'picara', 'name': 'ピカラ光（STNet）',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 5280, 'initial_fee': 3300, 'construction_fee': 19800,
            'contract_term_months': 24, 'cancellation_fee': 10000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 20000,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://www.stnet.co.jp/personal/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '四国全域対応。高速光回線。',
        },
        {
            'id': 'flets', 'name': 'NTTフレッツ光',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 6050, 'initial_fee': 3300, 'construction_fee': 19800,
            'contract_term_months': 24, 'cancellation_fee': 5000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://flets-w.com/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '全国対応。',
        },
        {
            'id': 'au', 'name': 'auひかり',
            'area_pref': ['徳島','香川','愛媛','高知'], 'type': '光回線',
            'monthly_fee': 5610, 'initial_fee': 3300, 'construction_fee': 24200,
            'contract_term_months': 24, 'cancellation_fee': 15000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 30000,
            'speed_mbps': 1000, 'discount_type': 'none',
            'sp_url': 'https://www.au.com/internet/',
            'is_manual': False, 'is_manual_required': False,
            'notes': 'auスマホ割あり。',
        },
        {
            'id': 'catv_kagawa', 'name': 'ケーブルメディア四国',
            'area_pref': ['香川'], 'type': 'CATV',
            'monthly_fee': 4950, 'initial_fee': 5500, 'construction_fee': 11000,
            'contract_term_months': 12, 'cancellation_fee': 5000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 320, 'discount_type': 'none',
            'sp_url': 'https://www.cavy.co.jp/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '香川限定。最大320Mbps。',
        },
        {
            'id': 'catv_kochi', 'name': '高知ケーブルテレビ（KCB）',
            'area_pref': ['高知'], 'type': 'CATV',
            'monthly_fee': 4620, 'initial_fee': 5500, 'construction_fee': 11000,
            'contract_term_months': 12, 'cancellation_fee': 5000,
            'docomo_discount_per_person': 0, 'campaign_cashback': 0,
            'speed_mbps': 200, 'discount_type': 'none',
            'sp_url': 'https://www.kcb.co.jp/',
            'is_manual': False, 'is_manual_required': False,
            'notes': '高知限定。最大200Mbps。',
        },
    ]

# ============================================================
# ② CF上の現行 data.json を取得（前回ハッシュ・change_log 引き継ぎ）
# ============================================================

def fetch_prev_data() -> dict:
    """
    CF Workers 上の現行 data.json を取得して返す。
    取得失敗時は空の初期構造を返す（新規ビルドとして扱う）。
    """
    try:
        resp = requests.get(CF_DATA_JSON_URL, timeout=10)
        if resp.status_code == 200:
            prev = resp.json()
            print(f'[build] CF上の data.json 取得成功（built_at: {prev.get("built_at","不明")}）')
            return prev
        else:
            print(f'[build] CF上の data.json 取得失敗（HTTP {resp.status_code}）。新規ビルドとして扱います。')
    except Exception as e:
        print(f'[build] CF上の data.json 取得例外: {e}。新規ビルドとして扱います。')

    return {'change_log': [], 'page_hashes': {}}

# ============================================================
# ③ robots.txt チェック
# ============================================================

def can_scrape(base_url: str, target_url: str) -> bool:
    """
    robots.txt を確認し、SP 可否を返す。
    取得失敗時は安全側（禁止）として False を返す。
    """
    robots_url = base_url.rstrip('/') + '/robots.txt'
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        result = rp.can_fetch('*', target_url)
        status = '可' if result else '不可'
        print(f'[build]   robots.txt チェック → SP {status} ({robots_url})')
        return result
    except Exception as e:
        print(f'[build]   robots.txt 取得失敗: {e} → 安全側（SP禁止）として扱います')
        return False

# ============================================================
# ④ SP補助監視（ハッシュ比較）
# ============================================================

def scrape_hash(url: str) -> str | None:
    """
    URL のページテキストを取得して MD5 ハッシュを返す。
    失敗時は None を返す。
    """
    try:
        headers = {'User-Agent': SP_USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=SP_TIMEOUT)
        resp.raise_for_status()
        return page_hash(resp.text)
    except requests.exceptions.Timeout:
        print(f'[build]   SP タイムアウト: {url}')
    except requests.exceptions.RequestException as e:
        print(f'[build]   SP エラー: {e}')
    return None

# ============================================================
# ⑤ メイン処理
# ============================================================

def build():
    print('=' * 60)
    print(f'[build] 四国回線シミュレーター ビルド開始: {now_jst()}')
    print('=' * 60)

    # --- dist/ 準備 ---
    os.makedirs(DIST_DIR, exist_ok=True)

    # --- index.html コピー ---
    if os.path.exists(INDEX_HTML):
        shutil.copy(INDEX_HTML, os.path.join(DIST_DIR, INDEX_HTML))
        print(f'[build] {INDEX_HTML} → {DIST_DIR}/ にコピー完了')
    else:
        print(f'[build] 警告: {INDEX_HTML} が見つかりません')

    # --- ① master.csv 読み込み ---
    companies = load_master_csv()

    # --- ② CF上の前回データ取得 ---
    prev_data    = fetch_prev_data()
    prev_hashes  = prev_data.get('page_hashes', {})
    change_log   = list(prev_data.get('change_log', []))

    # --- ③ 各社 SP監視ループ ---
    page_hashes = {}   # 今回のハッシュを記録（次回比較用）

    for c in companies:
        sp_url = c.get('sp_url', '').strip()
        cid    = c['id']
        cname  = c['name']

        print(f'[build] チェック中: {cname}')

        # sp_url が未設定 or is_manual=True → 監視スキップ
        if not sp_url or c.get('is_manual', False):
            print(f'[build]   → SP監視スキップ（手動管理）')
            c['is_manual_required'] = c.get('is_manual', False)
            continue

        # robots.txt チェック
        from urllib.parse import urlparse
        parsed   = urlparse(sp_url)
        base_url = f'{parsed.scheme}://{parsed.netloc}'

        if not can_scrape(base_url, sp_url):
            print(f'[build]   → SP不可。手動確認フラグを立てます。')
            c['is_manual_required'] = True
            change_log.append({
                'date':               today_jst(),
                'company':            cname,
                'message':            'robots.txt によりSP不可。手動での料金確認を推奨します。',
                'is_manual_required': True,
            })
            continue

        # ハッシュ取得
        current_hash = scrape_hash(sp_url)

        if current_hash is None:
            # SP失敗 → 手動フラグ
            print(f'[build]   → SP失敗。手動確認フラグを立てます。')
            c['is_manual_required'] = True
            change_log.append({
                'date':               today_jst(),
                'company':            cname,
                'message':            'SPに失敗しました。手動での料金確認を推奨します。',
                'is_manual_required': True,
            })
            continue

        # ハッシュ保存
        page_hashes[cid] = current_hash

        # 前回ハッシュと比較
        prev_hash = prev_hashes.get(cid)
        if prev_hash and prev_hash != current_hash:
            print(f'[build]   ⚠ ページ変化を検知！ change_log にアラート追記します。')
            c['is_manual_required'] = True
            change_log.append({
                'date':               today_jst(),
                'company':            cname,
                'message':            'キャンペーンページに変化を検知しました。master.csv の確認・更新を推奨します。',
                'is_manual_required': True,
            })
        elif not prev_hash:
            print(f'[build]   → 初回ハッシュを記録しました。')
        else:
            print(f'[build]   → 変化なし。')

    # change_log を最新 CHANGE_LOG_MAX 件に制限
    change_log = change_log[-CHANGE_LOG_MAX:]

    # --- ④ data.json 生成 ---
    data = {
        'built_at':    now_jst(),
        'companies':   companies,
        'change_log':  change_log,
        'page_hashes': page_hashes,   # 次回比較用（内部管理フィールド）
    }

    data_json_path = os.path.join(DIST_DIR, DATA_JSON)
    with open(data_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'[build] {DATA_JSON} → {DIST_DIR}/ に出力完了')

    # --- 完了サマリー ---
    manual_required = [c['name'] for c in companies if c.get('is_manual_required')]
    print('=' * 60)
    print(f'[build] ビルド完了: {now_jst()}')
    if manual_required:
        print(f'[build] ⚠ 手動確認が必要な会社: {", ".join(manual_required)}')
    else:
        print(f'[build] ✅ 全社 SP監視正常。手動確認は不要です。')
    print('=' * 60)


# ============================================================
# エントリーポイント
# ============================================================
if __name__ == '__main__':
    build()
