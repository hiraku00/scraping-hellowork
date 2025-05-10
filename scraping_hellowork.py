from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import datetime
import argparse
import traceback
import time
import re # 正規表現のインポート

# 汎用ユーティリティのインポート
import generic_scraper_utils as gsu
from selenium.webdriver.common.by import By # Byは特化スクリプトでも直接使うことが多い

# --- ハローワーク特有の設定 ---
CONVERT_CSV_TO_EXCEL = True
ENABLE_CLEANSING = True
OUTPUT_DIR_NAME = "output"  # ハローワーク専用の出力ディレクトリ名
CSV_FILENAME = "hellowork_jobs_list.csv"
EXCEL_FILENAME = "hellowork_jobs_list.xlsx"
INITIAL_PAGE_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do?action=initDisp&screenId=GECA110010"
PAGE_LOAD_TIMEOUT = gsu.DEFAULT_PAGE_LOAD_TIMEOUT # 汎用ユーティリティのデフォルト値を使用
REQUEST_WAIT_TIME = gsu.DEFAULT_REQUEST_WAIT_TIME # 汎用ユーティリティのデフォルト値を使用

# --- 出力する列の順番 (ハローワーク特有) ---
COLUMNS_ORDER_CLEANSED = [
    '求人番号', '職種', '事業所名',
    '就業場所', '就業場所_都道府県', '就業場所_市区町村',
    '仕事の内容',
    '雇用形態', '正社員以外の名称',
    '賃金', '賃金_下限', '賃金_上限', '賃金_単位',
    '求人区分',
    '受付年月日', '受付年月日_YYYYMMDD',
    '紹介期限日','紹介期限日_YYYYMMDD',
    '就業時間',
    '休日', '休日_曜日等', '休日_週休二日制', '休日_年間休日数',
    '年齢', '年齢制限_有無', '年齢制限_下限', '年齢制限_上限',
    '公開範囲',
    'こだわり条件', 'こだわり条件_リスト',
    '求人数', '求人数_数値',
    '求人票リンク', '詳細リンク'
]
COLUMNS_ORDER_ORIGINAL = [
    '求人番号', '職種', '事業所名', '就業場所', '仕事の内容',
    '雇用形態', '正社員以外の名称', '賃金', '求人区分', '受付年月日', '紹介期限日',
    '就業時間', '休日', '年齢',
    '公開範囲', 'こだわり条件', '求人数',
    '求人票リンク', '詳細リンク'
]

# --- データクレンジング関数 (ハローワーク特有) ---
def clean_job_data_for_hellowork(job_data):
    """
    抽出したハローワークの求人データに対してデータクレンジングを行い、新しい列を追加する。
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
        wage_str = str(wage_str).replace(',', '')
        match_range_month = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str)
        match_range_hour = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str) if '時間給' in str(wage_str) else None
        match_range_day = re.search(r'([\d\.]+)円〜([\d\.]+)円', wage_str) if '日給' in str(wage_str) else None
        match_fixed = re.search(r'^([\d\.]+)円$', wage_str)
        match_fixed_hour_unit = re.search(r'^([\d\.]+)円(?:／|／ )時間給$', wage_str)
        match_fixed_day_unit = re.search(r'^([\d\.]+)円(?:／|／ )日給$', wage_str)

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
        elif match_range_month:
            try:
                cleaned_data['賃金_下限'] = int(float(match_range_month.group(1)))
                cleaned_data['賃金_上限'] = int(float(match_range_month.group(2)))
                cleaned_data['賃金_単位'] = '円'
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
        elif match_fixed:
            try:
                val = int(float(match_fixed.group(1)))
                cleaned_data['賃金_下限'] = val
                cleaned_data['賃金_上限'] = val
                if cleaned_data.get('雇用形態') == 'パート労働者':
                    cleaned_data['賃金_単位'] = '円/時'
                else:
                    cleaned_data['賃金_単位'] = '円'
            except ValueError: pass

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
        first_location_part = location_str.split()[0] if location_str else ""
        for pref in prefectures:
            if first_location_part.startswith(pref):
                found_pref = pref
                city_part = first_location_part[len(pref):].strip()
                other_parts = ' '.join(location_str.split()[1:])
                rest_of_location = f"{city_part} {other_parts}".strip() if city_part or other_parts else None
                break
        cleaned_data['就業場所_都道府県'] = found_pref
        cleaned_data['就業場所_市区町村'] = rest_of_location if rest_of_location else None
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
            try: cleaned_data['休日_年間休日数'] = int(match_days.group(1))
            except ValueError: pass
        match_weekly = re.search(r'週休二日制：\s*(\S+)', holiday_str)
        if match_weekly:
            cleaned_data['休日_週休二日制'] = match_weekly.group(1).strip()
        holiday_str_cleaned = re.sub(r'年間休日数：\s*\d+\s*日', '', holiday_str).strip()
        holiday_str_cleaned = re.sub(r'週休二日制：\s*\S+', '', holiday_str_cleaned).strip()
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
            match_lower = re.search(r'(\d+)歳以上〜?', age_str)
            if match_lower:
                try: cleaned_data['年齢制限_下限'] = int(match_lower.group(1))
                except ValueError: pass
            match_range = re.search(r'(\d+)歳〜(\d+)歳', age_str)
            if match_range:
                try:
                    if cleaned_data['年齢制限_下限'] is None:
                        cleaned_data['年齢制限_下限'] = int(match_range.group(1))
                    if cleaned_data['年齢制限_上限'] is None:
                        cleaned_data['年齢制限_上限'] = int(match_range.group(2))
                except ValueError: pass
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
        try: cleaned_data['求人数_数値'] = int(kyujinsu_str)
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
                if year < 100: year += 2000
                dt_obj = datetime.date(year, month, day)
                return dt_obj.strftime('%Y-%m-%d')
            except ValueError: return None
        return None
    cleaned_data['受付年月日_YYYYMMDD'] = format_date_jp_to_iso(cleaned_data.get('受付年月日'))
    cleaned_data['紹介期限日_YYYYMMDD'] = format_date_jp_to_iso(cleaned_data.get('紹介期限日'))

    return cleaned_data

# --- データ抽出関数 (ハローワーク特有) ---
def extract_job_data_from_hellowork_table(table_soup, base_url_for_links):
    """個別のハローワーク求人情報テーブルからデータを抽出する"""
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

                if header == '賃金':
                    wage_text_parts = value_tag.get_text(separator='\n').splitlines()
                    temp_data[header] = ' '.join(part.strip() for part in wage_text_parts if part.strip())
                elif header == '就業時間':
                    temp_data[header] = ' '.join(value.split())
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

        for key in COLUMNS_ORDER_ORIGINAL:
            if key not in job_data: job_data[key] = None

    except Exception as e:
        print(f"!! データ抽出中にエラー発生: {e}")
        traceback.print_exc()
        return None
    return job_data


# --- Seleniumを使ったメインスクレイピング関数 (ハローワーク特有) ---
def scrape_hellowork_after_manual_search(initial_page_url, output_dir, max_pages=None):
    """
    ユーザーがハローワークサイトで検索操作を行った後、その状態を引き継いでスクレイピングを開始する。
    """
    all_extracted_jobs_count = 0
    output_csv_filepath = os.path.join(output_dir, CSV_FILENAME)

    gsu.delete_file_if_exists(output_csv_filepath)

    driver = gsu.setup_webdriver(detach=False) # ユーザー操作後、スクリプトが終了するまでブラウザを開いておく場合はTrue
    if not driver:
        return 0, None, None

    processing_start_time = None
    script_overall_start_time_ref = time.time() # ドライバー起動前の時刻を記録

    try:
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
            elapsed_from_processing_start = int(page_loop_start_time - processing_start_time)
            print(f"\n--- ページ {page_count} ({datetime.timedelta(seconds=elapsed_from_processing_start)}経過){' [最大: '+str(max_pages)+']' if max_pages else ''} ---")

            # ハローワークの求人テーブルまたは情報メッセージの存在を確認
            try:
                gsu.WebDriverWait(driver, PAGE_LOAD_TIMEOUT).until(
                    lambda d: d.find_elements(By.CSS_SELECTOR, "table.kyujin") or \
                              d.find_elements(By.CSS_SELECTOR, "div.msg_disp_info")
                )
            except gsu.TimeoutException:
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

            job_tables = soup.find_all('table', class_='kyujin mt1 noborder') # ハローワーク特有のセレクタ
            current_page_data = []

            if not job_tables and page_count == 1:
                print(f"ページ1 ({current_page_url}) で求人情報テーブルが見つかりませんでした。")
                break
            elif not job_tables:
                print(f"ページ {page_count} ({current_page_url}): 求人テーブルなし。処理終了。")
                break

            print(f"ページ {page_count}: {len(job_tables)} 件検出。抽出開始...")
            current_page_extracted_count = 0
            for table in job_tables:
                job_data = extract_job_data_from_hellowork_table(table, current_page_url)
                if job_data:
                    if ENABLE_CLEANSING:
                        try:
                            job_data = clean_job_data_for_hellowork(job_data)
                        except Exception as e_clean:
                            print(f"!! 求人番号 {job_data.get('求人番号', '不明')} のクレンジング中にエラー: {e_clean}")
                            traceback.print_exc()
                    current_page_data.append(job_data)
                    current_page_extracted_count += 1
            print(f"ページ {page_count}: {current_page_extracted_count} 件抽出完了。")
            all_extracted_jobs_count += current_page_extracted_count

            cols_order = COLUMNS_ORDER_CLEANSED if ENABLE_CLEANSING else COLUMNS_ORDER_ORIGINAL
            gsu.append_data_to_csv(current_page_data, output_csv_filepath, columns_order=cols_order, page_num=page_count)

            page_loop_end_time = time.time()
            print(f"ページ {page_count} 処理完了 (所要時間: {page_loop_end_time - page_loop_start_time:.2f}秒)")

            # 「次へ」ボタンの処理 (ハローワーク特有の要素名)
            try:
                # ハローワークの「次へ」ボタンは name="fwListNaviBtnNext"
                clickable_next_button = gsu.find_clickable_element(driver, By.NAME, "fwListNaviBtnNext")

                if clickable_next_button:
                    elapsed_before_click = int(time.time() - processing_start_time)
                    print(f"[{datetime.timedelta(seconds=elapsed_before_click)}] 「次へ」ボタンをクリックします...")

                    if gsu.click_element(driver, clickable_next_button):
                        page_count += 1
                        time.sleep(REQUEST_WAIT_TIME) # ページ遷移後の待機
                    else:
                        print("「次へ」ボタンのクリックに失敗しました。処理を終了します。")
                        break
                else:
                    elapsed_at_end = int(time.time() - processing_start_time)
                    print(f"\n[{datetime.timedelta(seconds=elapsed_at_end)}] クリック可能な「次へ」ボタンが見つかりません。全ページ処理完了。")
                    break
            except Exception as e_next:
                print(f"「次へ」ボタン処理中に予期せぬエラー: {e_next}")
                traceback.print_exc()
                break
        # --- ループ終了 ---

    except gsu.TimeoutException as e_sel:
        print(f"Seleniumタイムアウトエラー (メイン処理中): {e_sel}")
    except Exception as e:
        print(f"予期せぬエラーが発生しました (メイン処理中): {e}")
        traceback.print_exc()
    finally:
        # ログ出力のための基準時刻を設定
        final_log_start_time = processing_start_time if processing_start_time is not None else script_overall_start_time_ref
        elapsed_total = int(time.time() - final_log_start_time)
        print(f"[{datetime.timedelta(seconds=elapsed_total)}] 処理終了シーケンス開始。")
        gsu.close_webdriver(driver)

    return all_extracted_jobs_count, output_csv_filepath, processing_start_time


# --- メイン処理のエントリポイント ---
if __name__ == "__main__":
    script_overall_start_time = time.time() # スクリプト全体の開始時刻

    parser = argparse.ArgumentParser(description='ハローワーク求人情報をSeleniumでスクレイピングします（ユーザー検索後）。')
    parser.add_argument('--debug', type=int, metavar='PAGES', help='デバッグモード。指定ページ数で処理を停止 (例: --debug 3)')
    parser.add_argument('--no-clean', action='store_true', help='データクレンジングを実行しない場合に指定します。')
    args = parser.parse_args()

    # グローバル変数 ENABLE_CLEANSING をargsに基づいて更新
    if args.no_clean:
        ENABLE_CLEANSING = False # グローバル変数を直接変更
        print("★★★ データクレンジングは実行されません ★★★")
    elif ENABLE_CLEANSING: # グローバル変数の現在の状態（Trueのはず）
        print("★★★ データクレンジングを実行します ★★★")

    output_abs_dir = gsu.ensure_output_dir(OUTPUT_DIR_NAME)

    print(f"スクレイピングを開始します。出力先: '{output_abs_dir}'")
    if args.debug:
        print(f"★★★ デバッグモード: 最大 {args.debug} ページまで処理します ★★★")

    total_jobs, final_csv_path, actual_processing_start_time = scrape_hellowork_after_manual_search(
        INITIAL_PAGE_URL,
        output_abs_dir,
        max_pages=args.debug
    )

    if total_jobs > 0 and final_csv_path and os.path.exists(final_csv_path):
        if actual_processing_start_time: # スクレイピング処理が実際に開始された場合
            processing_duration = time.time() - actual_processing_start_time
            print(f"\n--- 処理完了 (スクレイピング所要時間: {datetime.timedelta(seconds=int(processing_duration))}) ---")
        else: # WebDriver起動失敗などでスクレイピングが開始されなかった場合
            print(f"\n--- 処理は終了しましたが、スクレイピングは実行されませんでした ---")

        print(f"合計 {total_jobs} 件の求人データをCSV '{final_csv_path}' に出力しました。")
        print(f"ファイルパス: '{os.path.abspath(final_csv_path)}'")

        if CONVERT_CSV_TO_EXCEL:
            excel_filepath = os.path.join(output_abs_dir, EXCEL_FILENAME)
            cols_order_excel = COLUMNS_ORDER_CLEANSED if ENABLE_CLEANSING else COLUMNS_ORDER_ORIGINAL
            gsu.convert_csv_to_excel(final_csv_path, excel_filepath, columns_order=cols_order_excel)

    elif total_jobs == 0 and actual_processing_start_time is not None: # スクレイピングは実行されたが結果0件
        print("\n検索結果が0件だったか、求人情報の抽出ができませんでした。")
    else: # それ以外のケース（WebDriver起動失敗など）
        print("\n有効なデータを取得・出力できませんでした。CSVファイルが作成されていない可能性があります。")

    overall_duration = time.time() - script_overall_start_time
    print(f"スクリプト全体の実行時間: {datetime.timedelta(seconds=int(overall_duration))}")
