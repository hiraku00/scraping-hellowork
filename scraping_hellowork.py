from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
import os
import datetime
import argparse
import traceback
from shutil import which
import re # 正規表現のインポート

# Selenium関連のインポート
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# --- グローバル設定 ---
CONVERT_CSV_TO_EXCEL = True  # 処理完了後にCSVをExcelに変換するかどうか
ENABLE_CLEANSING = True     # データクレンジングを実行するかどうか ★追加★
OUTPUT_DIR_NAME = "output"      # 出力先ディレクトリ名
CSV_FILENAME = "hellowork_jobs_list.csv" # 出力CSVファイル名
EXCEL_FILENAME = "hellowork_jobs_list.xlsx" # 出力Excelファイル名 (CONVERT_CSV_TO_EXCEL=True の場合)
INITIAL_PAGE_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do?action=initDisp&screenId=GECA110010" # 最初に開くURL
PAGE_LOAD_TIMEOUT = 15 # Seleniumの要素待機タイムアウト（秒）
REQUEST_WAIT_TIME = 2  # ページ遷移後などの待機時間（秒）

# --- 出力する列の順番 ---
# 元の列 + クレンジング列を含むリスト (クレンジング有効時用)
COLUMNS_ORDER_CLEANSED = [
    '求人番号', '職種', '事業所名',
    '就業場所', '就業場所_都道府県', '就業場所_市区町村', # ★変更★
    '仕事の内容',
    '雇用形態', '正社員以外の名称',
    '賃金', '賃金_下限', '賃金_上限', '賃金_単位', # ★変更★
    '求人区分',
    '受付年月日', '受付年月日_YYYYMMDD', # ★変更★
    '紹介期限日','紹介期限日_YYYYMMDD', # ★変更★
    '就業時間',
    '休日', '休日_曜日等', '休日_週休二日制', '休日_年間休日数', # ★変更★
    '年齢', '年齢制限_有無', '年齢制限_下限', '年齢制限_上限', # ★変更★
    '公開範囲',
    'こだわり条件', 'こだわり条件_リスト', # ★変更★
    '求人数', '求人数_数値', # ★変更★
    '求人票リンク', '詳細リンク'
]
# クレンジング無効時用の元の列リスト
COLUMNS_ORDER_ORIGINAL = [
    '求人番号', '職種', '事業所名', '就業場所', '仕事の内容',
    '雇用形態', '正社員以外の名称', '賃金', '求人区分', '受付年月日', '紹介期限日',
    '就業時間', '休日', '年齢',
    '公開範囲', 'こだわり条件', '求人数',
    '求人票リンク', '詳細リンク'
]


# --- ★修正★ データクレンジング関数 ---
def clean_job_data(job_data):
    """
    抽出した求人データに対してデータクレンジングを行い、新しい列を追加する。
    """
    if not job_data:
        return job_data

    cleaned_data = job_data.copy()

    # --- 賃金 ---
    cleaned_data['賃金_下限'] = None
    cleaned_data['賃金_上限'] = None
    cleaned_data['賃金_単位'] = None
    wage_str = cleaned_data.get('賃金')
    if wage_str:
        wage_str = str(wage_str).replace(',', '') # カンマ除去
        # 月給の範囲 (例: 199800円〜281650円)
        match_range_month = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str)
        # 時給の範囲 (例: 1250円〜1500円) - /時間給パターンは無視
        match_range_hour = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str) if '時間給' in str(wage_str) else None
         # 日給の範囲 (例: 8000円〜10000円) - /日給パターンは無視
        match_range_day = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str) if '日給' in str(wage_str) else None
        # 固定額 (例: 176000円)
        match_fixed = re.search(r'^([\d\.]+)円$', wage_str)
        # 固定時給 (例: 1050円, 1200円／ 時間給) - 単位含む
        match_fixed_hour_unit = re.search(r'^([\d\.]+)円(?:／|／ )時間給$', wage_str)
        # 固定日給 (例: 9000円／日給) - 単位含む
        match_fixed_day_unit = re.search(r'^([\d\.]+)円(?:／|／ )日給$', wage_str)

        # 優先度をつけて判定
        if match_range_hour:
            try:
                cleaned_data['賃金_下限'] = int(float(match_range_hour.group(1)))
                cleaned_data['賃金_上限'] = int(float(match_range_hour.group(2)))
                cleaned_data['賃金_単位'] = '円/時'
            except ValueError: pass
        elif match_range_day:
             try:
                cleaned_data['賃金_下限'] = int(float(match_range_day.group(1)))
                cleaned_data['賃金_上限'] = int(float(match_range_day.group(2)))
                cleaned_data['賃金_単位'] = '円/日'
             except ValueError: pass
        elif match_range_month: # 時給/日給範囲でなければ月給範囲
            try:
                cleaned_data['賃金_下限'] = int(float(match_range_month.group(1)))
                cleaned_data['賃金_上限'] = int(float(match_range_month.group(2)))
                cleaned_data['賃金_単位'] = '円' # 月給と推定
            except ValueError: pass
        elif match_fixed_hour_unit:
            try:
                 val = int(float(match_fixed_hour_unit.group(1)))
                 cleaned_data['賃金_下限'] = val
                 cleaned_data['賃金_上限'] = val
                 cleaned_data['賃金_単位'] = '円/時'
            except ValueError: pass
        elif match_fixed_day_unit:
             try:
                 val = int(float(match_fixed_day_unit.group(1)))
                 cleaned_data['賃金_下限'] = val
                 cleaned_data['賃金_上限'] = val
                 cleaned_data['賃金_単位'] = '円/日'
             except ValueError: pass
        elif match_fixed: # 固定額で単位がない場合 -> 文脈で判断が必要だが、ここでは月給と推定
            # パート求人などの場合、ここが時給の可能性もあるため、雇用形態や求人区分と合わせて判断するとより精度が上がる
            # 今回はシンプルに月給と推定
             try:
                 val = int(float(match_fixed.group(1)))
                 cleaned_data['賃金_下限'] = val
                 cleaned_data['賃金_上限'] = val
                 # 雇用形態がパートなどであれば時給の可能性が高い
                 if cleaned_data.get('雇用形態') == 'パート労働者':
                      cleaned_data['賃金_単位'] = '円/時' # パートなら時給と推定
                 else:
                      cleaned_data['賃金_単位'] = '円' # それ以外は月給と推定
             except ValueError:
                 pass

    # --- 就業場所 ---
    cleaned_data['就業場所_都道府県'] = None
    cleaned_data['就業場所_市区町村'] = None
    location_str = cleaned_data.get('就業場所')
    if location_str:
        prefectures = [
            "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
            "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
            "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
            "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
            "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
            "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
            "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"
        ]
        found_pref = None
        rest_of_location = location_str

        # 複数の地名がスペース区切りで入っている場合、最初の地名で判断
        first_location_part = location_str.split()[0] if location_str else ""

        for pref in prefectures:
            if first_location_part.startswith(pref):
                found_pref = pref
                # 都道府県名を除いた部分 + 残りの部分
                city_part = first_location_part[len(pref):].strip()
                other_parts = ' '.join(location_str.split()[1:])
                rest_of_location = f"{city_part} {other_parts}".strip() if city_part or other_parts else None
                break

        cleaned_data['就業場所_都道府県'] = found_pref
        cleaned_data['就業場所_市区町村'] = rest_of_location if rest_of_location else None # 残りがない場合はNone

        # 都道府県が見つからず、スペース区切りで複数要素がある場合（例: 埼玉県 さいたま市）
        if not found_pref and len(location_str.split()) > 1:
            parts = location_str.split()
            if parts[0] in prefectures:
                cleaned_data['就業場所_都道府県'] = parts[0]
                cleaned_data['就業場所_市区町村'] = ' '.join(parts[1:])


    # --- 休日 ---
    cleaned_data['休日_曜日等'] = None
    cleaned_data['休日_週休二日制'] = None
    cleaned_data['休日_年間休日数'] = None
    holiday_str = cleaned_data.get('休日')
    if holiday_str:
        match_days = re.search(r'年間休日数：\s*(\d+)\s*日', holiday_str)
        if match_days:
            try:
                cleaned_data['休日_年間休日数'] = int(match_days.group(1))
            except ValueError: pass

        match_weekly = re.search(r'週休二日制：\s*(\S+)', holiday_str)
        if match_weekly:
            # 「毎週」や「その他」などを取得
            cleaned_data['休日_週休二日制'] = match_weekly.group(1).strip()

        # 曜日等の抽出改善
        holiday_str_cleaned = re.sub(r'年間休日数：\s*\d+\s*日', '', holiday_str).strip()
        holiday_str_cleaned = re.sub(r'週休二日制：\s*\S+', '', holiday_str_cleaned).strip()
        # 先頭・末尾の「他」や不要な空白を除去
        holiday_str_cleaned = re.sub(r'^\s*他\s*|\s*他\s*$', '', holiday_str_cleaned).strip()
        cleaned_data['休日_曜日等'] = holiday_str_cleaned if holiday_str_cleaned else None


    # --- 年齢 ---
    cleaned_data['年齢制限_有無'] = None
    cleaned_data['年齢制限_下限'] = None
    cleaned_data['年齢制限_上限'] = None
    age_str = cleaned_data.get('年齢')
    if age_str:
        if age_str == '不問':
            cleaned_data['年齢制限_有無'] = False
        else:
            cleaned_data['年齢制限_有無'] = True
            match_upper = re.search(r'〜(\d+)歳以下', age_str)
            if match_upper:
                try: cleaned_data['年齢制限_上限'] = int(match_upper.group(1))
                except ValueError: pass
            match_lower = re.search(r'(\d+)歳以上〜?', age_str) # 〜があってもなくてもOK
            if match_lower:
                try: cleaned_data['年齢制限_下限'] = int(match_lower.group(1))
                except ValueError: pass
            # "XX歳〜XX歳" のパターンにも対応できるように修正（上記でカバーされる場合もあるが一応）
            match_range = re.search(r'(\d+)歳〜(\d+)歳', age_str)
            if match_range:
                 try:
                     if cleaned_data['年齢制限_下限'] is None: # 上のlowerで取れていない場合
                         cleaned_data['年齢制限_下限'] = int(match_range.group(1))
                     if cleaned_data['年齢制限_上限'] is None: # 上のupperで取れていない場合
                        cleaned_data['年齢制限_上限'] = int(match_range.group(2))
                 except ValueError: pass
            # "XX歳以上" のみの場合
            match_lower_only = re.search(r'^(\d+)歳以上$', age_str)
            if match_lower_only and cleaned_data['年齢制限_下限'] is None:
                try: cleaned_data['年齢制限_下限'] = int(match_lower_only.group(1))
                except ValueError: pass


    # --- こだわり条件 ---
    cleaned_data['こだわり条件_リスト'] = None
    kodawari_str = cleaned_data.get('こだわり条件')
    if kodawari_str:
        cleaned_data['こだわり条件_リスト'] = [item.strip() for item in kodawari_str.split(',') if item.strip()]

    # --- 求人数 ---
    cleaned_data['求人数_数値'] = None
    kyujinsu_str = cleaned_data.get('求人数')
    if kyujinsu_str:
        try:
            cleaned_data['求人数_数値'] = int(kyujinsu_str)
        except (ValueError, TypeError): pass

    # --- 受付年月日, 紹介期限日 ---
    cleaned_data['受付年月日_YYYYMMDD'] = None
    cleaned_data['紹介期限日_YYYYMMDD'] = None
    def format_date_jp_to_iso(date_jp_str):
        if not date_jp_str or not isinstance(date_jp_str, str): return None
        match = re.match(r'(\d+)年(\d+)月(\d+)日', date_jp_str)
        if match:
            try:
                year, month, day = map(int, match.groups())
                # 西暦を2000年代に補正 (必要であれば)
                if year < 100: year += 2000 # 例: 25年 -> 2025年
                dt_obj = datetime.date(year, month, day)
                return dt_obj.strftime('%Y-%m-%d')
            except ValueError: return None
        return None

    cleaned_data['受付年月日_YYYYMMDD'] = format_date_jp_to_iso(cleaned_data.get('受付年月日'))
    cleaned_data['紹介期限日_YYYYMMDD'] = format_date_jp_to_iso(cleaned_data.get('紹介期限日'))


    return cleaned_data

# --- データ抽出関数 ---
# (extract_job_data 関数は変更なし、ただし賃金等の取得方法を確認)
def extract_job_data(table_soup, base_url_for_links):
    """個別の求人情報テーブルからデータを抽出する"""
    job_data = {}
    try:
        shokushu_tag = table_soup.select_one('tr.kyujin_head td.m13 div')
        job_data['職種'] = shokushu_tag.get_text(strip=True) if shokushu_tag else None

        date_info_div = table_soup.select_one('tr:not(.kyujin_head):not(.kyujin_body):not(.kyujin_foot) div.flex.fs13')
        if date_info_div:
            dates_text = date_info_div.get_text(separator=' ', strip=True)
            parts = dates_text.split()
            uketsuke_date = parts[parts.index('受付年月日：') + 1] if '受付年月日：' in parts and parts.index('受付年月日：') + 1 < len(parts) else None
            shokai_date = parts[parts.index('紹介期限日：') + 1] if '紹介期限日：' in parts and parts.index('紹介期限日：') + 1 < len(parts) else None
            job_data['受付年月日'] = uketsuke_date
            job_data['紹介期限日'] = shokai_date
        else:
            job_data['受付年月日'], job_data['紹介期限日'] = None, None

        body_rows = table_soup.select('tr.kyujin_body tr.border_new')
        temp_data = {}
        for row in body_rows:
            header_tag = row.find('td', class_='fb')
            value_tag = header_tag.find_next_sibling('td') if header_tag else None
            if header_tag and value_tag:
                header = ' '.join(header_tag.get_text(strip=True).split()).replace('（手当等を含む）', '').strip()
                if not header: continue
                value_raw_text = value_tag.get_text(separator=' ', strip=True)
                value = ' '.join(value_raw_text.split())

                # オリジナルの賃金情報をそのまま保持（クレンジング関数で処理）
                if header == '賃金':
                    # 単位情報（時間給など）が含まれている場合もそのまま取得
                    wage_text_parts = value_tag.get_text(separator='\n').splitlines()
                    temp_data[header] = ' '.join(part.strip() for part in wage_text_parts if part.strip())
                elif header == '就業時間':
                    temp_data[header] = ' '.join(value.split()) # 余分なスペース調整
                elif header == '仕事の内容':
                    value_div = value_tag.find('div')
                    temp_data[header] = '\n'.join(l.strip() for l in value_div.get_text(separator='\n').splitlines() if l.strip()) if value_div else value
                elif header == '求人番号':
                    num_div = value_tag.find('div')
                    temp_data[header] = num_div.get_text(strip=True) if num_div else value_tag.get_text(strip=True)
                else:
                    temp_data[header] = value
        job_data.update(temp_data)

        kodawari_tags = table_soup.select('div.kodawari span.nes_label')
        job_data['こだわり条件'] = ', '.join([tag.get_text(strip=True) for tag in kodawari_tags]) if kodawari_tags else None

        kyujin_num_text = None
        kyujinsu_marker = table_soup.find(string=lambda t: t and '求人数：' in t.strip())
        if kyujinsu_marker:
            num_div = kyujinsu_marker.find_next('div', class_='ml01')
            kyujin_num_text = num_div.get_text(strip=True) if num_div else None
        job_data['求人数'] = kyujin_num_text

        kyujinhyo_link_tag = table_soup.select_one('a#ID_kyujinhyoBtn')
        job_data['求人票リンク'] = urljoin(base_url_for_links, kyujinhyo_link_tag['href']) if kyujinhyo_link_tag and 'href' in kyujinhyo_link_tag.attrs else None
        detail_link_tag = table_soup.select_one('a#ID_dispDetailBtn')
        job_data['詳細リンク'] = urljoin(base_url_for_links, detail_link_tag['href']) if detail_link_tag and 'href' in detail_link_tag.attrs else None

        if '求人番号' not in job_data or not job_data.get('求人番号'):
            bango_header_td = table_soup.find('td', class_='fb', string=lambda t: t and '求人番号' in t.strip())
            if bango_header_td:
                bango_val_td = bango_header_td.find_next_sibling('td')
                if bango_val_td:
                    bango_div = bango_val_td.find('div')
                    if bango_div: job_data['求人番号'] = bango_div.get_text(strip=True)

        # 元の列リストに含まれるキーがなければNoneで埋める (クレンジング前の列のみ)
        for key in COLUMNS_ORDER_ORIGINAL:
            if key not in job_data: job_data[key] = None

    except Exception as e:
        print(f"!! データ抽出中にエラー発生: {e}")
        traceback.print_exc() # 詳細なトレースバックを表示
        return None
    return job_data


# --- CSV追記関数 ---
def append_page_data_to_csv(page_data, page_num, output_csv_path):
    """1ページ分のデータをCSVファイルに追記する"""
    if not page_data:
        print(f"ページ {page_num}: 書き出すデータがありません。")
        return

    df = pd.DataFrame(page_data)
    columns_to_use = COLUMNS_ORDER_CLEANSED if ENABLE_CLEANSING else COLUMNS_ORDER_ORIGINAL
    df = df.reindex(columns=columns_to_use)

    try:
        write_header = not os.path.exists(output_csv_path)
        write_mode = 'a' if os.path.exists(output_csv_path) else 'w'
        df.to_csv(output_csv_path, mode=write_mode, header=write_header, index=False, encoding='utf-8-sig')
        print(f"ページ {page_num}: '{output_csv_path}' に{'書き込み' if write_mode == 'w' else '追記'}完了。")
    except Exception as e:
        print(f"ページ {page_num}: CSV書き込み/追記エラー: {e}")

# --- Seleniumを使ったメインスクレイピング関数 ---
def scrape_after_manual_search(initial_page_url, output_dir, max_pages=None):
    """
    ユーザーがブラウザで検索操作を行った後、その状態を引き継いでスクレイピングを開始する。
    """
    all_extracted_jobs_count = 0
    output_csv_filepath = os.path.join(output_dir, CSV_FILENAME)

    if os.path.exists(output_csv_filepath):
        print(f"既存ファイル削除: '{output_csv_filepath}'")
        try:
            os.remove(output_csv_filepath)
        except OSError as e:
            print(f"エラー: 既存ファイル削除失敗 - {e}")
            return 0, None, None

    options = webdriver.ChromeOptions()
    options.add_argument('--window-size=1200,900')
    options.add_argument('--lang=ja-JP')
    # options.add_experimental_option("detach", True)

    driver = None
    processing_start_time = None
    try:
        print(f"WebDriverを起動中...")
        chromedriver_path = which("chromedriver")
        if chromedriver_path:
            print(f"PATH に chromedriver が見つかりました: {chromedriver_path}")
            service = ChromeService(executable_path=chromedriver_path)
        else:
            print("chromedriver が PATH に見つからなかったので、webdriver-manager を使用します。")
            try:
                service = ChromeService(ChromeDriverManager().install())
            except Exception as e_manager:
                 print(f"webdriver-managerでのドライバー取得に失敗しました: {e_manager}")
                 print("chromedriverを手動でダウンロードし、PATHを通すか、スクリプトと同じディレクトリに配置してください。")
                 return 0, None, None


        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(10)
        print(f"WebDriver起動完了。")

        driver.get(initial_page_url)
        print("\n" + "="*50)
        print("ブラウザが起動しました。ハローワークのサイトで求人を検索してください。")
        print("1. 検索条件を指定します。")
        print("2. 「検索」ボタンを押して最初の結果一覧を表示させます。")
        print("3. (推奨) 表示件数を「50件」に変更します。")
        print("4. 全ての操作が完了したら、このコンソールに戻りEnterキーを押してください。")
        print("="*50)
        input("準備ができたらEnterキーを押してください...")

        processing_start_time = time.time()
        print(f"[{datetime.timedelta(seconds=0)}] ユーザー操作完了、スクレイピングを開始します。")

        page_count = 1
        while True:
            if max_pages is not None and page_count > max_pages:
                print(f"\n指定された最大ページ数 ({max_pages}) に達したため、処理を終了します。")
                break

            page_loop_start_time = time.time()
            elapsed_time_from_processing_start = datetime.timedelta(seconds=int(page_loop_start_time - processing_start_time))
            print(f"\n--- ページ {page_count} ({elapsed_time_from_processing_start}経過){' [最大: '+str(max_pages)+']' if max_pages else ''} ---")

            try:
                WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table.kyujin, div.msg_disp_info"))
                )
            except TimeoutException:
                if page_count == 1:
                    print(f"ページ1 ({driver.current_url}) で求人テーブルまたは情報メッセージが見つかりませんでした。")
                    print("ブラウザで検索結果が正しく表示されているか確認してください。")
                else:
                    print(f"ページ{page_count} ({driver.current_url}) で求人テーブルまたは情報メッセージが見つかりません。")
                break

            current_html_content = driver.page_source
            soup = BeautifulSoup(current_html_content, 'html.parser')
            current_page_url = driver.current_url

            no_data_message = soup.find("div", class_="msg_disp_info", string=lambda t: t and "ご指定の条件に該当する求人はありませんでした" in t)
            if no_data_message and page_count == 1 :
                print("検索結果0件でした。")
                break

            job_tables = soup.find_all('table', class_='kyujin mt1 noborder')
            current_page_data = []

            if not job_tables and page_count == 1:
                print(f"ページ1 ({current_page_url}) で求人情報テーブルが見つかりませんでした。")
                break
            elif not job_tables:
                # 最後のページに到達した可能性
                print(f"ページ {page_count} ({current_page_url}): 求人テーブルなし。処理終了。")
                break

            print(f"ページ {page_count}: {len(job_tables)} 件検出。抽出開始...")
            current_page_extracted_count = 0
            for index, table in enumerate(job_tables):
                job_data = extract_job_data(table, current_page_url)
                if job_data:
                    if ENABLE_CLEANSING:
                        try:
                           job_data = clean_job_data(job_data)
                        except Exception as e_clean:
                           print(f"!! 求人番号 {job_data.get('求人番号', '不明')} のクレンジング中にエラー: {e_clean}")
                           traceback.print_exc()
                    current_page_data.append(job_data)
                    current_page_extracted_count += 1
            print(f"ページ {page_count}: {current_page_extracted_count} 件抽出完了。")
            all_extracted_jobs_count += current_page_extracted_count

            append_page_data_to_csv(current_page_data, page_count, output_csv_filepath)
            page_loop_end_time = time.time()
            print(f"ページ {page_count} 処理完了 (所要時間: {page_loop_end_time - page_loop_start_time:.2f}秒)")

            # 「次へ」ボタンの処理
            try:
                # 「次へ」ボタンの存在をまず確認
                next_button_elements = driver.find_elements(By.NAME, "fwListNaviBtnNext")

                # クリック可能な（非表示やdisabledでない）「次へ」ボタンを探す
                clickable_next_button = None
                for btn in next_button_elements:
                     if btn.is_displayed() and "disabled" not in btn.get_attribute("class"):
                         clickable_next_button = btn
                         break # 最初に見つかったものを採用

                if clickable_next_button:
                    elapsed_time_str_before_click = datetime.timedelta(seconds=int(time.time() - processing_start_time))
                    print(f"[{elapsed_time_str_before_click}] 「次へ」ボタンをクリックします...")
                    try:
                        # スクロールしてクリックを試みる
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", clickable_next_button)
                        time.sleep(0.5)
                        # JavaScriptクリックを優先
                        driver.execute_script("arguments[0].click();", clickable_next_button)
                        clicked_next = True
                    except Exception as e_click:
                        print(f"「次へ」ボタンクリック中にエラー: {e_click}")
                        clicked_next = False # クリック失敗

                    if clicked_next:
                        page_count += 1
                        time.sleep(REQUEST_WAIT_TIME)
                    else:
                         print("「次へ」ボタンのクリックに失敗しました。処理を終了します。")
                         break

                else:
                    # クリック可能な「次へ」ボタンがない場合、ループ終了
                    elapsed_time_str_end = datetime.timedelta(seconds=int(time.time() - processing_start_time))
                    print(f"\n[{elapsed_time_str_end}] クリック可能な「次へ」ボタンが見つかりません。全ページ処理完了。")
                    break

            except NoSuchElementException: # 「次へ」ボタン自体が存在しない
                elapsed_time_str_end = datetime.timedelta(seconds=int(time.time() - processing_start_time))
                print(f"\n[{elapsed_time_str_end}] 「次へ」ボタンが見つかりません。全ページ処理完了。")
                break
            except Exception as e_next:
                print(f"「次へ」ボタン処理中に予期せぬエラー: {e_next}")
                traceback.print_exc()
                break
        # --- ループ終了 ---

    except TimeoutException as e_sel:
        print(f"Seleniumタイムアウトエラー: {e_sel}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
    finally:
        if driver:
            reference_start_time_for_final_log = processing_start_time if processing_start_time is not None else script_overall_start_time
            final_elapsed_time_str = datetime.timedelta(seconds=int(time.time() - reference_start_time_for_final_log))
            print(f"[{final_elapsed_time_str}] WebDriverを終了します。")
            driver.quit()

    return all_extracted_jobs_count, output_csv_filepath, processing_start_time


# --- メイン処理のエントリポイント ---
if __name__ == "__main__":
    script_overall_start_time = time.time()

    parser = argparse.ArgumentParser(description='ハローワーク求人情報をSeleniumでスクレイピングします（ユーザー検索後）。')
    parser.add_argument('--debug', type=int, metavar='PAGES', help='デバッグモード。指定ページ数で処理を停止 (例: --debug 3)')
    parser.add_argument('--no-clean', action='store_true', help='データクレンジングを実行しない場合に指定します。')
    args = parser.parse_args()

    if args.no_clean:
        ENABLE_CLEANSING = False
        print("★★★ データクレンジングは実行されません ★★★")
    elif ENABLE_CLEANSING:
         print("★★★ データクレンジングを実行します ★★★")

    os.makedirs(OUTPUT_DIR_NAME, exist_ok=True)

    print(f"スクレイピングを開始します。出力先: '{OUTPUT_DIR_NAME}'")
    if args.debug:
        print(f"★★★ デバッグモード: 最大 {args.debug} ページまで処理します ★★★")

    total_jobs, final_csv_path, actual_processing_start_time = scrape_after_manual_search(
        INITIAL_PAGE_URL,
        OUTPUT_DIR_NAME,
        max_pages=args.debug
    )

    if total_jobs > 0 and final_csv_path and os.path.exists(final_csv_path): # ファイル存在確認を追加
        if actual_processing_start_time:
            processing_duration = time.time() - actual_processing_start_time
            print(f"\n--- 処理完了 (スクレイピング所要時間: {datetime.timedelta(seconds=int(processing_duration))}) ---")
        else:
            print(f"\n--- 処理完了 ---")

        print(f"合計 {total_jobs} 件の求人データをCSV '{final_csv_path}' に出力しました。")
        print(f"ファイルパス: '{os.path.abspath(final_csv_path)}'")

        if CONVERT_CSV_TO_EXCEL:
            excel_filepath = os.path.join(OUTPUT_DIR_NAME, EXCEL_FILENAME)
            try:
                print(f"\nCSVファイルをExcelファイル '{excel_filepath}' に変換中...")
                df_final = pd.read_csv(final_csv_path)
                columns_to_use_excel = COLUMNS_ORDER_CLEANSED if ENABLE_CLEANSING else COLUMNS_ORDER_ORIGINAL
                # DataFrameに存在しない列が指定されるのを防ぐ
                existing_columns = [col for col in columns_to_use_excel if col in df_final.columns]
                df_final = df_final[existing_columns] # 存在する列のみで再構成
                df_final.to_excel(excel_filepath, index=False, engine='openpyxl')
                print(f"Excelファイルへの変換が完了しました: '{excel_filepath}'")
            except ImportError:
                print("'openpyxl' ライブラリが見つかりません。Excel変換はスキップされました。CSVファイルをご利用ください。")
            except FileNotFoundError:
                 print(f"エラー: CSVファイルが見つかりません。'{final_csv_path}'")
            except Exception as e_conv:
                print(f"CSVからExcelへの変換中にエラーが発生しました: {e_conv}")
                traceback.print_exc()
    elif total_jobs == 0:
         print("\n検索結果が0件だったか、求人情報の抽出ができませんでした。")
    else:
        print("\n有効なデータを取得・出力できませんでした。CSVファイルが作成されていない可能性があります。")
