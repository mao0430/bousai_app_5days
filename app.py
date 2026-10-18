from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = 'your-secret-key-here'

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# JMAの警報・注意報APIでは青森市は「020010」などの市町村コードで表現される
# 既存の 1420500 は地理院/住居表示系のコードであり、警報APIには一致しないため修正する
AREA_CODES = {"020010", "0220100", "1420500"}
AREA_CODE = "020010"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def safe_int(value, default=0):
    """数値文字列を安全に int に変換する"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_bool(value, default=None):
    """フォーム値やJSON値を安全に bool に変換する"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ('true', '1', 'yes', 'on'):
            return True
        if normalized in ('false', '0', 'no', 'off', ''):
            return False
    if isinstance(value, (int, float)):
        return value != 0
    return default


def get_vacancy_status(shelter):
    """収容人数と現在の避難者数から空き状況を判定する"""
    if not isinstance(shelter, dict):
        return {'label': '情報なし', 'class': 'status-unknown', 'remaining': 0}

    capacity = max(0, safe_int(shelter.get('capacity'), 0))
    current_occupants = max(0, safe_int(shelter.get('current_occupants'), 0))

    if capacity <= 0:
        return {'label': '情報なし', 'class': 'status-unknown', 'remaining': 0}

    remaining = capacity - current_occupants

    if remaining > 0:
        return {'label': '空きあり', 'class': 'status-green', 'remaining': remaining}
    if current_occupants >= capacity:
        return {'label': '満員', 'class': 'status-red', 'remaining': 0}
    return {'label': 'ほぼ満員', 'class': 'status-yellow', 'remaining': remaining}


def normalize_shelter(shelter):
    """避難所データに必須項目がない場合でも一覧表示できるよう整形する"""
    if not isinstance(shelter, dict):
        return {
            'id': 0,
            'name': '',
            'address': '',
            'status': '未登録',
            'capacity': 0,
            'current_occupants': 0,
            'pet_allowed': None,
            'barrier_free': None,
            'wheelchair_toilet': None,
            'welfare_space': None,
        }

    return {
        'id': shelter.get('id', 0),
        'name': shelter.get('name', '').strip(),
        'address': shelter.get('address', '').strip(),
        'status': shelter.get('status', '未登録').strip() or '未登録',
        'capacity': max(0, safe_int(shelter.get('capacity'), 0)),
        'current_occupants': max(0, safe_int(shelter.get('current_occupants'), 0)),
        'pet_allowed': safe_bool(shelter.get('pet_allowed')),
        'barrier_free': safe_bool(shelter.get('barrier_free')),
        'wheelchair_toilet': safe_bool(shelter.get('wheelchair_toilet')),
        'welfare_space': safe_bool(shelter.get('welfare_space')),
    }


app.jinja_env.globals['get_vacancy_status'] = get_vacancy_status


shelters = [normalize_shelter(s) for s in load_json(DATA_FILE, [])]
instructions = load_json(INSTRUCTIONS_FILE, [])

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def save_shelters():
    """避難所データをJSONファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None, amenity_filters=None):
    """地区と指定された設備条件に一致する避難所を返す"""
    amenity_filters = amenity_filters or {}
    return [
        shelter for shelter in shelters
        if (not district or shelter.get('district') == district)
        and all(shelter.get(key) is True for key in amenity_filters)
    ]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        for area_group in ("class10Items", "class20Items"):
            items = warning.get(area_group, [])
            if not isinstance(items, list):
                continue

            area = next(
                (
                    item for item in items
                    if isinstance(item, dict)
                    and str(item.get("areaCode", "")) in AREA_CODES
                ),
                None
            )
            if not area:
                continue

            kinds = area.get("kinds", [])
            if not isinstance(kinds, list):
                continue

            for kind in kinds:
                if not isinstance(kind, dict):
                    continue

                status = kind.get("status", "")
                code = kind.get("code", "")
                if status not in ("発表", "継続") or not code or code in seen_codes:
                    continue

                warnings.append({
                    "name": WARNING_CODES.get(
                        code,
                        f"不明な警報・注意報 (コード: {code})"
                    ),
                    "code": code,
                    "status": status
                })
                seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time()
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "error": True
        }


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/')
def index():
    resident_notices = [i for i in instructions if i.get('target') == '住民']
    return render_template('index.html', resident_notices=resident_notices)

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        address = (request.form.get('address') or '').strip()
        status = (request.form.get('status') or '開設中').strip()
        capacity = max(0, safe_int(request.form.get('capacity'), 0))
        current_occupants = max(0, safe_int(request.form.get('current_occupants'), 0))
        pet_allowed = request.form.get('pet_allowed') == 'on'
        barrier_free = request.form.get('barrier_free') == 'on'
        wheelchair_toilet = request.form.get('wheelchair_toilet') == 'on'
        welfare_space = request.form.get('welfare_space') == 'on'

        if not name:
            return render_template('shelter_register.html', error=True, message='避難所名を入力してください。')

        if capacity < 0:
            return render_template('shelter_register.html', error=True, message='収容人数は0以上で入力してください。')

        if current_occupants < 0:
            return render_template('shelter_register.html', error=True, message='現在の避難者数は0以上で入力してください。')

        if any(s.get('name') == name and s.get('address') == address for s in shelters):
            return render_template('shelter_register.html', error=True, message='同じ名前・住所の避難所はすでに登録されています。')

        new_id = max((s.get('id', 0) for s in shelters), default=0) + 1
        shelters.append({
            'id': new_id,
            'name': name,
            'address': address,
            'status': status or '開設中',
            'capacity': capacity,
            'current_occupants': current_occupants,
            'pet_allowed': pet_allowed,
            'barrier_free': barrier_free,
            'wheelchair_toilet': wheelchair_toilet,
            'welfare_space': welfare_space,
        })
        save_shelters()
        return render_template('shelter_register.html', success=True, message='避難所を登録しました。')

    return render_template('shelter_register.html')

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    return render_template('shelter_search.html')

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    return render_template('search_results.html', results=shelters)


# 指示ボード：住民向けの指示を一覧で確認する
@app.route('/board')
@login_required
def board():
    resident_instructions = [i for i in instructions if i.get('target') == '住民']
    return render_template('board.html', instructions=resident_instructions)

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    amenity_keys = (
        'pet_allowed',
        'barrier_free',
    )
    amenity_filters = {
        key: True for key in amenity_keys
        if request.args.get(key) == 'on'
    }
    results = filter_shelters(request.args.get('district'), amenity_filters)
    return render_template('search_results.html', results=results)

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
