"""
build.py ― 四国回線提案シミュレーター ビルドスクリプト
===========================================================
【現在】ダミー版
  - dist/ フォルダを作成し、index.html をコピーするだけ
  - Step 4 で SP監視・差分検知の本番コードに差し替え予定

【Step 4 実装予定の内容】
  1. robots.txt チェック（SP可否の自動判定）
  2. SP可 → キャンペーン数値・日付の変化のみ検知（CSV書換なし）
     SP不可 → 監視スキップ・is_manual_required フラグ立て
  3. CF上の現行 data.json を取得して差分比較
  4. 変化があれば change_log にアラート追記
  5. dist/ に data.json + index.html を出力
===========================================================
"""

import os
import shutil
import json
from datetime import datetime, timezone, timedelta

# ============================================================
# 定数
# ============================================================
DIST_DIR   = 'dist'
INDEX_HTML = 'index.html'
DATA_JSON  = 'data.json'

JST = timezone(timedelta(hours=9))

# ============================================================
# ① dist/ フォルダを準備
# ============================================================
print('[build] dist/ フォルダを準備中...')
os.makedirs(DIST_DIR, exist_ok=True)

# ============================================================
# ② index.html を dist/ にコピー
# ============================================================
if os.path.exists(INDEX_HTML):
    shutil.copy(INDEX_HTML, os.path.join(DIST_DIR, INDEX_HTML))
    print(f'[build] {INDEX_HTML} → {DIST_DIR}/ にコピー完了')
else:
    print(f'[build] 警告: {INDEX_HTML} が見つかりません')

# ============================================================
# ③ ダミー data.json を生成して dist/ に出力
#    （Step 4 で master.csv から生成する本番処理に差し替え）
# ============================================================
built_at = datetime.now(JST).strftime('%Y-%m-%d %H:%M')

dummy_data = {
    "built_at": built_at,
    "companies": [
        {
            "id": "docomo",
            "name": "ドコモ光",
            "area_pref": ["徳島", "香川", "愛媛", "高知"],
            "monthly_fee": 5720,
            "initial_fee": 3300,
            "construction_fee": 0,
            "contract_term_months": 24,
            "cancellation_fee": 0,
            "docomo_discount_per_person": 1100,
            "campaign_cashback": 0,
            "speed_mbps": 1000,
            "discount_type": "family",
            "is_manual": True,
            "notes": "光コラボ。解約金なし。"
        },
        {
            "id": "picara",
            "name": "ピカラ光（STNet）",
            "area_pref": ["徳島", "香川", "愛媛", "高知"],
            "monthly_fee": 5280,
            "initial_fee": 3300,
            "construction_fee": 19800,
            "contract_term_months": 24,
            "cancellation_fee": 10000,
            "docomo_discount_per_person": 0,
            "campaign_cashback": 20000,
            "speed_mbps": 1000,
            "discount_type": "none",
            "is_manual": False,
            "notes": "四国全域対応。高速光回線。"
        },
        {
            "id": "flets",
            "name": "NTTフレッツ光",
            "area_pref": ["徳島", "香川", "愛媛", "高知"],
            "monthly_fee": 6050,
            "initial_fee": 3300,
            "construction_fee": 19800,
            "contract_term_months": 24,
            "cancellation_fee": 5000,
            "docomo_discount_per_person": 0,
            "campaign_cashback": 0,
            "speed_mbps": 1000,
            "discount_type": "none",
            "is_manual": True,
            "notes": "全国対応。robots.txt によりSP監視不可。手動確認が必要です。"
        },
        {
            "id": "au",
            "name": "auひかり",
            "area_pref": ["徳島", "香川", "愛媛", "高知"],
            "monthly_fee": 5610,
            "initial_fee": 3300,
            "construction_fee": 24200,
            "contract_term_months": 24,
            "cancellation_fee": 15000,
            "docomo_discount_per_person": 0,
            "campaign_cashback": 30000,
            "speed_mbps": 1000,
            "discount_type": "none",
            "is_manual": False,
            "notes": "auスマホ割あり。"
        },
        {
            "id": "catv_kagawa",
            "name": "ケーブルメディア四国",
            "area_pref": ["香川"],
            "monthly_fee": 4950,
            "initial_fee": 5500,
            "construction_fee": 11000,
            "contract_term_months": 12,
            "cancellation_fee": 5000,
            "docomo_discount_per_person": 0,
            "campaign_cashback": 0,
            "speed_mbps": 320,
            "discount_type": "none",
            "is_manual": False,
            "notes": "香川限定。最大320Mbps。"
        },
        {
            "id": "catv_kochi",
            "name": "高知ケーブルテレビ（KCB）",
            "area_pref": ["高知"],
            "monthly_fee": 4620,
            "initial_fee": 5500,
            "construction_fee": 11000,
            "contract_term_months": 12,
            "cancellation_fee": 5000,
            "docomo_discount_per_person": 0,
            "campaign_cashback": 0,
            "speed_mbps": 200,
            "discount_type": "none",
            "is_manual": False,
            "notes": "高知限定。最大200Mbps。"
        }
    ],
    "change_log": []
}

data_json_path = os.path.join(DIST_DIR, DATA_JSON)
with open(data_json_path, 'w', encoding='utf-8') as f:
    json.dump(dummy_data, f, ensure_ascii=False, indent=2)

print(f'[build] {DATA_JSON} → {DIST_DIR}/ に出力完了')
print(f'[build] ビルド完了: {built_at}')
print(f'[build] ※ このbuild.pyはダミー版です。Step 4 で本番版に差し替えてください。')
