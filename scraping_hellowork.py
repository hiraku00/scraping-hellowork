from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
import os
import datetime
import argparse
import traceback

# Selenium関連のインポート
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from shutil import which
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# --- グローバル設定 ---
CONVERT_CSV_TO_EXCEL = True  # 処理完了後にCSVをExcelに変換するかどうか
OUTPUT_DIR_NAME = "output"      # 出力先ディレクトリ名
CSV_FILENAME = "hellowork_jobs_list.csv" # 出力CSVファイル名
EXCEL_FILENAME = "hellowork_jobs_list.xlsx" # 出力Excelファイル名 (CONVERT_CSV_TO_EXCEL=True の場合)
INITIAL_PAGE_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do?action=initDisp&screenId=GECA110010" # 最初に開くURL
PAGE_LOAD_TIMEOUT = 15 # Seleniumの要素待機タイムアウト（秒）
REQUEST_WAIT_TIME = 2  # ページ遷移後などの待機時間（秒）

# --- 出力する列の順番 ---
COLUMNS_ORDER = [
    '求人番号', '職種', '事業所名', '就業場所', '仕事の内容',
    '雇用形態', '正社員以外の名称', '賃金', '求人区分', '受付年月日', '紹介期限日',
    '就業時間', '休日', '年齢',
    '公開範囲', 'こだわり条件', '求人数',
    '求人票リンク', '詳細リンク'
]

# --- データ抽出関数 ---
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

                if header == '賃金':
                    temp_data[header] = value.split()[0] if value else value
                elif header == '就業時間':
                    temp_data[header] = value.replace('（ 1 ）','(1)').replace('（ 2 ）','(2)').replace('（ 3 ）','(3)')
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

        for key in COLUMNS_ORDER:
            if key not in job_data: job_data[key] = None
    except Exception as e:
        print(f"!! データ抽出中にエラー発生: {e}")
        return None
    return job_data

# --- CSV追記関数 ---
def append_page_data_to_csv(page_data, page_num, output_csv_path):
    """1ページ分のデータをCSVファイルに追記する"""
    if not page_data:
        print(f"ページ {page_num}: 書き出すデータがありません。")
        return

    df = pd.DataFrame(page_data)
    df = df.reindex(columns=COLUMNS_ORDER) # 列順序を適用

    try:
        write_header = page_num == 1
        write_mode = 'w' if page_num == 1 else 'a'
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
    # options.add_experimental_option("detach", True) # デバッグ用にブラウザを閉じない場合

    driver = None
    processing_start_time = None # スクレピング処理の実際の開始時間
    try:
        print(f"WebDriverを起動中...")
        # chromedriver が PATH にあるか確認
        chromedriver_path = which("chromedriver")
        if chromedriver_path:
            print(f"PATH に chromedriver が見つかりました: {chromedriver_path}")
            service = ChromeService(executable_path=chromedriver_path)
        else:
            print("chromedriver が PATH に見つからなかったので、webdriver-manager を使用します。")
            service = ChromeService(ChromeDriverManager().install())

        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(10) # 要素が見つかるまでの最大待機時間
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
            current_page_url = driver.current_url # 「次へ」のRefererやリンク生成用

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
                print(f"ページ {page_count} ({current_page_url}): 求人テーブルなし。中断。")
                break

            print(f"ページ {page_count}: {len(job_tables)} 件検出。抽出開始...")
            current_page_extracted_count = 0
            for index, table in enumerate(job_tables):
                job_data = extract_job_data(table, current_page_url)
                if job_data:
                    current_page_data.append(job_data)
                    current_page_extracted_count += 1
            print(f"ページ {page_count}: {current_page_extracted_count} 件抽出完了。")
            all_extracted_jobs_count += current_page_extracted_count

            append_page_data_to_csv(current_page_data, page_count, output_csv_filepath)
            page_loop_end_time = time.time()
            print(f"ページ {page_count} 処理完了 (所要時間: {page_loop_end_time - page_loop_start_time:.2f}秒)")

            # 「次へ」ボタンの処理
            try:
                next_buttons = WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located((By.NAME, "fwListNaviBtnNext"))
                )
                clicked_next = False
                for btn in next_buttons:
                    if btn.is_enabled() and btn.is_displayed():
                        elapsed_time_str_before_click = datetime.timedelta(seconds=int(time.time() - processing_start_time))
                        print(f"[{elapsed_time_str_before_click}] 「次へ」ボタンをクリックします...")
                        try:
                            driver.execute_script("arguments[0].scrollIntoView(true);", btn) # ボタンが見えるようにスクロール
                            time.sleep(0.3) # スクロール安定待ち
                            driver.execute_script("arguments[0].click();", btn)
                            clicked_next = True
                            break # 最初のクリック可能なボタンで十分
                        except Exception as e_click:
                            print(f"「次へ」ボタンクリック中にエラー: {e_click}")
                            # 他の「次へ」ボタンがあるかもしれないので継続
                            continue

                if clicked_next:
                    page_count += 1
                    time.sleep(REQUEST_WAIT_TIME) # 次のページの読み込みとサーバー負荷軽減のための待機
                else:
                    elapsed_time_str_end = datetime.timedelta(seconds=int(time.time() - processing_start_time))
                    print(f"\n[{elapsed_time_str_end}] クリック可能な「次へ」ボタンが見つかりません。全ページ処理完了。")
                    break
            except TimeoutException: # 「次へ」ボタン自体が見つからない
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
            # 処理開始時間 (processing_start_time) がNoneでない（ユーザー操作後まで進んだ）場合
            # それ以外（ブラウザ起動直後など）はスクリプト全体の開始時間を使う
            reference_start_time_for_final_log = processing_start_time if processing_start_time is not None else start_time
            final_elapsed_time_str = datetime.timedelta(seconds=int(time.time() - reference_start_time_for_final_log))
            print(f"[{final_elapsed_time_str}] WebDriverを終了します。")
            driver.quit()

    return all_extracted_jobs_count, output_csv_filepath, processing_start_time

# --- メイン処理のエントリポイント ---
if __name__ == "__main__":
    script_overall_start_time = time.time() # スクリプト全体の実行開始時間

    parser = argparse.ArgumentParser(description='ハローワーク求人情報をSeleniumでスクレイピングします（ユーザー検索後）。')
    parser.add_argument('--debug', type=int, metavar='PAGES', help='デバッグモード。指定ページ数で処理を停止 (例: --debug 3)')
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR_NAME, exist_ok=True)

    print(f"スクレイピングを開始します。出力先: '{OUTPUT_DIR_NAME}'")
    if args.debug:
        print(f"★★★ デバッグモード: 最大 {args.debug} ページまで処理します ★★★")

    total_jobs, final_csv_path, actual_processing_start_time = scrape_after_manual_search(
        INITIAL_PAGE_URL,
        OUTPUT_DIR_NAME,
        max_pages=args.debug
    )

    if total_jobs > 0 and final_csv_path:
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
                df_final = df_final.reindex(columns=COLUMNS_ORDER) # 念のためExcel出力前にも列順序適用
                df_final.to_excel(excel_filepath, index=False, engine='openpyxl')
                print(f"Excelファイルへの変換が完了しました: '{excel_filepath}'")
            except ImportError:
                print("'openpyxl' ライブラリが見つかりません。Excel変換はスキップされました。CSVファイルをご利用ください。")
            except Exception as e_conv:
                print(f"CSVからExcelへの変換中にエラーが発生しました: {e_conv}")
    else:
        print("\n有効なデータを取得・出力できませんでした。")
