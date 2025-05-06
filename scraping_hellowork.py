import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
import os
import datetime
import argparse
import traceback

# --- 最後にCSVをExcelに変換する場合 ---
CONVERT_CSV_TO_EXCEL = True # TrueにするとExcel変換を実行

# --- 列の順番を定義 (グローバル定数) ---
COLUMNS_ORDER = [
    '求人番号', '職種', '事業所名', '就業場所', '仕事の内容',
    '雇用形態', '正社員以外の名称', '賃金', '求人区分', '受付年月日', '紹介期限日',
    '就業時間', '休日', '年齢',
    '公開範囲', 'こだわり条件', '求人数',
    '求人票リンク', '詳細リンク'
]

# --- データ抽出関数 (変更なし) ---
def extract_job_data(table_soup, base_url_for_links):
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
        else: job_data['受付年月日'], job_data['紹介期限日'] = None, None
        body_rows = table_soup.select('tr.kyujin_body tr.border_new')
        temp_data = {}
        for row in body_rows:
            header_tag = row.find('td', class_='fb')
            value_tag = header_tag.find_next_sibling('td') if header_tag else None
            if header_tag and value_tag:
                header = ' '.join(header_tag.get_text(strip=True).split()).replace('（手当等を含む）', '').strip()
                if not header: continue
                value_raw_text = value_tag.get_text(separator=' ', strip=True); value = ' '.join(value_raw_text.split())
                if header == '賃金': temp_data[header] = value.split()[0] if value else value
                elif header == '就業時間': temp_data[header] = value.replace('（ 1 ）','(1)').replace('（ 2 ）','(2)').replace('（ 3 ）','(3)')
                elif header == '仕事の内容':
                    value_div = value_tag.find('div')
                    temp_data[header] = '\n'.join(l.strip() for l in value_div.get_text(separator='\n').splitlines() if l.strip()) if value_div else value
                elif header == '求人番号':
                    num_div = value_tag.find('div'); temp_data[header] = num_div.get_text(strip=True) if num_div else value_tag.get_text(strip=True)
                else: temp_data[header] = value
        job_data.update(temp_data)
        kodawari_tags = table_soup.select('div.kodawari span.nes_label')
        job_data['こだわり条件'] = ', '.join([tag.get_text(strip=True) for tag in kodawari_tags]) if kodawari_tags else None
        kyujin_num_text = None
        kyujinsu_marker = table_soup.find(string=lambda t: t and '求人数：' in t.strip())
        if kyujinsu_marker: num_div = kyujinsu_marker.find_next('div', class_='ml01'); kyujin_num_text = num_div.get_text(strip=True) if num_div else None
        job_data['求人数'] = kyujin_num_text
        kyujinhyo_link_tag = table_soup.select_one('a#ID_kyujinhyoBtn')
        job_data['求人票リンク'] = urljoin(base_url_for_links, kyujinhyo_link_tag['href']) if kyujinhyo_link_tag and 'href' in kyujinhyo_link_tag.attrs else None
        detail_link_tag = table_soup.select_one('a#ID_dispDetailBtn')
        job_data['詳細リンク'] = urljoin(base_url_for_links, detail_link_tag['href']) if detail_link_tag and 'href' in detail_link_tag.attrs else None
        if '求人番号' not in job_data or not job_data.get('求人番号'):
            bango_header_td = table_soup.find('td', class_='fb', string=lambda t: t and '求人番号' in t.strip())
            if bango_header_td: bango_val_td = bango_header_td.find_next_sibling('td')
            if bango_val_td: bango_div = bango_val_td.find('div')
            if bango_div: job_data['求人番号'] = bango_div.get_text(strip=True)
        for key in COLUMNS_ORDER:
            if key not in job_data: job_data[key] = None
    except Exception as e: print(f"!! データ抽出エラー: {e}"); return None
    return job_data

# --- CSV追記関数 (変更なし) ---
def append_page_data_to_csv(page_data, page_num, output_csv_path):
    if not page_data: print(f"ページ {page_num}: 書き出すデータなし。"); return
    df = pd.DataFrame(page_data)
    df = df.reindex(columns=COLUMNS_ORDER)
    try:
        write_header = page_num == 1
        write_mode = 'w' if page_num == 1 else 'a'
        df.to_csv(output_csv_path, mode=write_mode, header=write_header, index=False, encoding='utf-8-sig')
        print(f"ページ {page_num}: '{output_csv_path}' に{'書き込み' if write_mode == 'w' else '追記'}完了。")
    except Exception as e: print(f"ページ {page_num}: CSV書き込み/追記エラー: {e}")


# --- メインスクレイピング関数 ---
def scrape_hellowork_with_search(init_url, search_post_url, output_dir, max_pages=None):
    start_time = time.time()
    all_extracted_jobs_count = 0
    output_csv_filename = "hellowork_jobs_all.csv"
    output_csv_path = os.path.join(output_dir, output_csv_filename)

    if os.path.exists(output_csv_path):
        print(f"既存ファイル削除: '{output_csv_path}'")
        try: os.remove(output_csv_path)
        except OSError as e: print(f"エラー: 既存ファイル削除失敗 - {e}")

    base_url = "https://www.hellowork.mhlw.go.jp/kensaku/"
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': init_url
    }
    current_post_url = search_post_url

    try:
        # 1. 初期アクセスとフォーム特定
        print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 初期ページアクセス中...")
        init_response = session.get(init_url, headers=headers, timeout=45); init_response.raise_for_status()
        init_response.encoding = init_response.apparent_encoding
        print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] フォーム情報取得中...")
        init_soup = BeautifulSoup(init_response.text, 'html.parser')
        search_button_element = init_soup.find('input', {'id': 'ID_searchBtn', 'name': 'searchBtn'})
        form = search_button_element.find_parent('form') if search_button_element else None
        if not form: form = init_soup.find('form', {'action': './GECA110010.do'}) or init_soup.find('form', id='ID_form_1')
        if not form: print("エラー: 検索フォームが見つかりません。"); return 0, None
        print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] フォーム特定完了。")
        current_post_url = urljoin(init_url, form.get('action', search_post_url))

        # 初回検索ペイロード作成
        initial_payload = {}
        hidden_inputs = form.find_all('input', type='hidden')
        for input_tag in hidden_inputs:
            name = input_tag.get('name'); value = input_tag.get('value', '')
            if name:
                if name in initial_payload:
                    if isinstance(initial_payload[name], list): initial_payload[name].append(value)
                    else: initial_payload[name] = [initial_payload[name], value]
                else: initial_payload[name] = value
        initial_payload['kjKbnRadioBtn'] = '1'
        initial_payload['searchBtn'] = search_button_element.get('value', '検索') if search_button_element else '検索'

        # 2. 最初の検索実行
        print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 最初の検索実行中 (デフォルト表示件数)...")
        current_response = session.post(current_post_url, data=initial_payload, headers=headers, timeout=60)
        current_response.raise_for_status()
        current_response.encoding = current_response.apparent_encoding
        print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 最初の検索完了。")

        # ★★★ 3. 表示件数を50件に変更 ★★★
        soup_for_disp_change = BeautifulSoup(current_response.text, 'html.parser')
        form_for_disp_change = soup_for_disp_change.find('form', id='ID_form_1')

        # 表示件数select要素のname属性を探す
        display_count_select_name_top = None
        display_count_select_name_btm = None
        select_top = soup_for_disp_change.find('select', id='ID_fwListNaviDispTop')
        select_btm = soup_for_disp_change.find('select', id='ID_fwListNaviDispBtm')
        if select_top and select_top.has_attr('name'): display_count_select_name_top = select_top['name']
        if select_btm and select_btm.has_attr('name'): display_count_select_name_btm = select_btm['name']

        # 並び順select要素の情報を取得
        sort_select_name_top = None
        sort_select_name_btm = None
        sort_value_top = '1' # デフォルト値
        sort_value_btm = '1' # デフォルト値
        sort_select_top = soup_for_disp_change.find('select', id='ID_fwListNaviSortTop')
        sort_select_btm = soup_for_disp_change.find('select', id='ID_fwListNaviSortBtm')
        if sort_select_top and sort_select_top.has_attr('name'):
            sort_select_name_top = sort_select_top['name']
            selected_option = sort_select_top.find('option', selected=True)
            if selected_option: sort_value_top = selected_option.get('value', '1')
        if sort_select_btm and sort_select_btm.has_attr('name'):
            sort_select_name_btm = sort_select_btm['name']
            selected_option = sort_select_btm.find('option', selected=True)
            if selected_option: sort_value_btm = selected_option.get('value', '1')


        if form_for_disp_change and (display_count_select_name_top or display_count_select_name_btm):
            print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 表示件数を50件に変更し、リストを更新します...")
            disp_change_payload = {}

            # --- すべての input type="hidden" の現在の値をコピー ---
            hidden_inputs = form_for_disp_change.find_all('input', type='hidden')
            for input_tag in hidden_inputs:
                name = input_tag.get('name')
                value = input_tag.get('value', '')
                if name:
                    if name in disp_change_payload:
                        if isinstance(disp_change_payload[name], list): disp_change_payload[name].append(value)
                        else: disp_change_payload[name] = [disp_change_payload[name], value]
                    else: disp_change_payload[name] = value

            # --- 表示件数と並び順パラメータを設定/上書き ---
            if display_count_select_name_top: disp_change_payload[display_count_select_name_top] = '50'
            if display_count_select_name_btm: disp_change_payload[display_count_select_name_btm] = '50'
            # 表示件数用の隠しフィールドも設定
            disp_change_payload['fwListNaviDisp'] = '50'

            if sort_select_name_top: disp_change_payload[sort_select_name_top] = sort_value_top
            if sort_select_name_btm: disp_change_payload[sort_select_name_btm] = sort_value_btm
            # 並び順用の隠しフィールドも設定 (現在の値を取得して設定)
            sort_hidden = form_for_disp_change.find('input', {'name': 'fwListNaviSort'})
            disp_change_payload['fwListNaviSort'] = sort_hidden['value'] if sort_hidden else '1' # なければデフォルト1

            # --- ★★★ actionパラメータを追加 ★★★ ---
            disp_change_payload['action'] = 'listCmbChange'

            # ページ関連の隠しフィールドは、表示件数変更時は1ページ目に戻るので初期値(HTMLから取得した値)を使う
            # fwListNowPage, fwListLeftPage などは hidden_inputs のループで取得されているはず

            # 不要な可能性のあるパラメータを念のため削除 (ボタン系)
            disp_change_payload.pop('searchBtn', None)
            for i in range(1, 7): # fwListNaviBtn1 ～ 6
                disp_change_payload.pop(f'fwListNaviBtn{i}', None)
            disp_change_payload.pop('fwListNaviBtnNext', None)
            disp_change_payload.pop('fwListNaviBtnPrev', None)

            # print("表示件数変更 送信ペイロード:", disp_change_payload) # デバッグ用

            try:
                headers['Referer'] = current_response.url
                current_response = session.post(current_post_url, data=disp_change_payload, headers=headers, timeout=60)
                current_response.raise_for_status()
                current_response.encoding = current_response.apparent_encoding
                print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 表示件数変更リクエスト完了。")

                time.sleep(1)

            except requests.exceptions.RequestException as e:
                print(f"エラー: 表示件数変更リクエスト失敗 - {e}")
                print("デフォルト表示件数で続行します。")
            except Exception as e_disp:
                 print(f"エラー: 表示件数変更中エラー - {e_disp}")
                 print("デフォルト表示件数で続行します。")
        else:
            print("警告: 表示件数変更用の要素が見つからず。デフォルト件数で続行。")
        # ★★★ ここまで表示件数変更処理 ★★★

        page_count = 1
        # --- 4. ページネーションループ ---
        while True:
            if max_pages is not None and page_count > max_pages:
                print(f"\n最大ページ数 ({max_pages}) 到達。終了。")
                break

            page_start_time = time.time()
            print(f"\n--- ページ {page_count} ({datetime.timedelta(seconds=int(page_start_time - start_time))}経過){' [最大: '+str(max_pages)+']' if max_pages else ''} ---")
            soup = BeautifulSoup(current_response.text, 'html.parser')
            current_page_url = current_response.url

            job_tables = soup.find_all('table', class_='kyujin mt1 noborder')
            current_page_data = []
            if not job_tables and page_count == 1: print("検索結果0件。"); break
            elif not job_tables: print(f"ページ {page_count}: 求人テーブルなし。中断。"); break

            print(f"ページ {page_count}: {len(job_tables)} 件検出。抽出開始...")
            current_page_extracted_count = 0
            for index, table in enumerate(job_tables):
                job_data = extract_job_data(table, current_post_url)
                if job_data:
                    current_page_data.append(job_data)
                    current_page_extracted_count += 1
            print(f"ページ {page_count}: {current_page_extracted_count} 件抽出完了。")
            all_extracted_jobs_count += current_page_extracted_count

            append_page_data_to_csv(current_page_data, page_count, output_csv_path)
            page_end_time = time.time()
            print(f"ページ {page_count} 処理完了 (所要時間: {page_end_time - page_start_time:.2f}秒)")

            next_button = soup.find('input', {'name': 'fwListNaviBtnNext'})
            if next_button and not next_button.has_attr('disabled'):
                print(f"[{datetime.timedelta(seconds=int(time.time() - start_time))}] 次のページへ...")
                current_form = soup.find('form', id='ID_form_1')
                if not current_form: print("エラー: 次ページ用フォームなし。"); break
                next_payload = {}
                hidden_inputs = current_form.find_all('input', type='hidden')
                for input_tag in hidden_inputs:
                    name = input_tag.get('name'); value = input_tag.get('value', '')
                    if name:
                         if name in next_payload:
                             if isinstance(next_payload[name], list): next_payload[name].append(value)
                             else: next_payload[name] = [next_payload[name], value]
                         else: next_payload[name] = value
                next_payload[next_button['name']] = next_button.get('value', '')
                try:
                    headers['Referer'] = current_page_url
                    next_response = session.post(current_post_url, data=next_payload, headers=headers, timeout=60)
                    next_response.raise_for_status(); next_response.encoding = next_response.apparent_encoding
                    current_response = next_response; page_count += 1; time.sleep(2)
                except requests.exceptions.RequestException as e: print(f"リクエストエラー: {e}"); break
                except Exception as e_inner: print(f"次ページ処理エラー: {e_inner}"); traceback.print_exc(); break
            else:
                print(f"\n[{datetime.timedelta(seconds=int(time.time() - start_time))}] 全ページ処理完了。")
                break
        # --- ループ終了 ---
    except requests.exceptions.Timeout: print("エラー: タイムアウト")
    except requests.exceptions.HTTPError as e: print(f"HTTPエラー: {e.response.status_code} - {e.response.reason}")
    except requests.exceptions.RequestException as e: print(f"リクエストエラー: {e}")
    except Exception as e: print(f"予期せぬエラー: {e}"); traceback.print_exc()

    return all_extracted_jobs_count, output_csv_path

# --- メイン処理のエントリポイント ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='ハローワーク求人情報をスクレイピングします。')
    parser.add_argument('--debug', type=int, metavar='COUNT', help='デバッグモード。指定ページ数で停止 (例: --debug 5)')
    args = parser.parse_args()

    INITIAL_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do?action=initDisp&screenId=GECA110010"
    SEARCH_POST_URL = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do"
    OUTPUT_DIR = "output"
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"スクレイピングを開始します。出力先: '{OUTPUT_DIR}'")
    if args.debug: print(f"★★★ デバッグモード: 最大 {args.debug} ページまで処理 ★★★")

    total_jobs, final_csv_path = scrape_hellowork_with_search(
        INITIAL_URL, SEARCH_POST_URL, OUTPUT_DIR, max_pages=args.debug
    )

    if total_jobs > 0 and final_csv_path:
        print(f"\n--- 処理完了 ---")
        print(f"合計 {total_jobs} 件の求人データをCSV '{final_csv_path}' に出力しました。")
        print(f"ファイルパス: '{os.path.abspath(final_csv_path)}'")
        if CONVERT_CSV_TO_EXCEL:
            excel_filename = os.path.splitext(final_csv_path)[0] + ".xlsx"
            try:
                print(f"\nCSV -> Excel 変換中 ('{excel_filename}')..."); df_final = pd.read_csv(final_csv_path)
                df_final = df_final.reindex(columns=COLUMNS_ORDER)
                df_final.to_excel(excel_filename, index=False, engine='openpyxl'); print("変換完了。")
            except ImportError: print("'openpyxl' がないためExcel変換スキップ。")
            except Exception as e_conv: print(f"CSV->Excel変換エラー: {e_conv}")
    else:
        print("\n有効なデータを取得・出力できませんでした。")
