import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from urllib.parse import urljoin
import os # ★ osモジュールをインポート

def scrape_hellowork_with_search(init_url, search_post_url):
    """
    初期ページアクセスと検索実行後に求人情報をスクレイピングする関数
    """
    all_jobs_data = []
    base_url = "https://www.hellowork.mhlw.go.jp/kensaku/"

    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Referer': 'https://www.hellowork.mhlw.go.jp/'
    }

    try:
        # 1. 初期表示ページにアクセス
        print(f"初期ページにアクセス中: {init_url}")
        init_response = session.get(init_url, headers=headers, timeout=45)
        init_response.raise_for_status()
        init_response.encoding = init_response.apparent_encoding
        print("初期ページアクセス完了。フォーム情報を取得中...")

        init_soup = BeautifulSoup(init_response.text, 'html.parser')

        # フォーム特定
        search_button_element = init_soup.find('input', {'id': 'ID_searchBtn', 'name': 'searchBtn'})
        form = None
        if search_button_element:
            form = search_button_element.find_parent('form')
            # (フォーム特定ロジックは変更なし)
            if form: print("検索ボタンの親要素からフォームを見つけました。")
            else: print("検索ボタンの親formが見つかりません。"); return []
        else: # ボタンが見つからない場合の代替策
            print("検索ボタンが見つかりません。代替手段でフォームを探します...")
            form = init_soup.find('form', {'action': './GECA110010.do'}) or init_soup.find('form', id='ID_form_1')

        if not form:
            print("エラー: 検索フォームが見つかりませんでした。")
            # (デバッグHTML出力は省略)
            return []

        # フォームデータ準備
        payload = {}
        hidden_inputs = form.find_all('input', type='hidden')
        for input_tag in hidden_inputs:
            name = input_tag.get('name')
            value = input_tag.get('value', '')
            if name:
                if name in payload:
                    if isinstance(payload[name], list): payload[name].append(value)
                    else: payload[name] = [payload[name], value]
                else: payload[name] = value

        # 必須項目と検索ボタン情報追加
        payload['kjKbnRadioBtn'] = '1' # 一般求人
        search_button_value = '検索'
        if search_button_element: search_button_value = search_button_element.get('value', '検索')
        payload['searchBtn'] = search_button_value

        # 2. 検索実行 (POST)
        print(f"検索を実行中 (POST to: {search_post_url})")
        headers['Referer'] = init_url
        post_target_url = urljoin(init_url, form.get('action', search_post_url))
        print(f"実際のPOST先URL: {post_target_url}")

        search_response = session.post(post_target_url, data=payload, headers=headers, timeout=60)
        search_response.raise_for_status()
        search_response.encoding = search_response.apparent_encoding
        print("検索実行完了。検索結果を解析中...")

        # (デバッグHTML出力は省略)
        # try:
        #     with open("debug_hellowork_search_result.html", "w", encoding=search_response.encoding or 'utf-8') as f:
        #         f.write(search_response.text)
        #     print("デバッグ用に検索結果HTMLを debug_hellowork_search_result.html に保存しました。")
        # except Exception as e_write: print(f"デバッグ用HTML保存エラー: {e_write}")


        # 3. 結果解析
        soup = BeautifulSoup(search_response.text, 'html.parser')
        job_tables = soup.find_all('table', class_='kyujin mt1 noborder')

        if not job_tables:
            # (エラーハンドリングは変更なし)
            no_result_msg = soup.find(lambda tag: tag.name and "ご指定の条件に該当する求人はありませんでした" in tag.get_text())
            # ... (他のエラーチェック) ...
            if no_result_msg: print("検索結果が0件でした。")
            else: print("求人情報テーブルが見つかりませんでした。")
            return []

        print(f"{len(job_tables)} 件の求人情報を検出しました。")

        # データ抽出ループ
        for index, table in enumerate(job_tables):
            # (データ抽出のコアロジックは変更なし)
            print(f"{index + 1} 件目のデータを処理中...")
            job_data = {}
            try:
                # 職種
                shokushu_tag = table.select_one('tr.kyujin_head td.m13 div')
                job_data['職種'] = shokushu_tag.get_text(strip=True) if shokushu_tag else None

                # 日付
                date_info_div = table.select_one('tr:not(.kyujin_head):not(.kyujin_body):not(.kyujin_foot) div.flex.fs13')
                if date_info_div:
                    dates_text = date_info_div.get_text(separator=' ', strip=True)
                    parts = dates_text.split()
                    job_data['受付年月日'] = parts[parts.index('受付年月日：') + 1] if '受付年月日：' in parts else None
                    job_data['紹介期限日'] = parts[parts.index('紹介期限日：') + 1] if '紹介期限日：' in parts else None
                else:
                    job_data['受付年月日'], job_data['紹介期限日'] = None, None


                # Body情報
                body_rows = table.select('tr.kyujin_body tr.border_new')
                temp_data = {}
                for row in body_rows:
                    header_tag = row.find('td', class_='fb')
                    value_tag = header_tag.find_next_sibling('td') if header_tag else None
                    if header_tag and value_tag:
                        header = ' '.join(header_tag.get_text(strip=True).split()).replace('（手当等を含む）', '').strip()
                        if not header: continue
                        value_raw_text = value_tag.get_text(separator=' ', strip=True)
                        value = ' '.join(value_raw_text.split())

                        # 各項目の整形
                        if header == '賃金':
                            temp_data[header] = value.split()[0] if value else value
                        elif header == '就業時間':
                            temp_data[header] = value.replace('（ 1 ）','(1)').replace('（ 2 ）','(2)').replace('（ 3 ）','(3)')
                        elif header == '仕事の内容':
                            value_div = value_tag.find('div')
                            temp_data[header] = '\n'.join(line.strip() for line in value_div.get_text(separator='\n').splitlines() if line.strip()) if value_div else value
                        elif header == '求人番号':
                            num_div = value_tag.find('div')
                            temp_data[header] = num_div.get_text(strip=True) if num_div else value_tag.get_text(strip=True)
                        else:
                            temp_data[header] = value
                job_data.update(temp_data)

                # こだわり条件
                kodawari_tags = table.select('div.kodawari span.nes_label')
                job_data['こだわり条件'] = ', '.join([tag.get_text(strip=True) for tag in kodawari_tags]) if kodawari_tags else None

                # 求人数
                kyujin_num_text = None
                kyujinsu_marker = table.find(string=lambda t: t and '求人数：' in t.strip())
                if kyujinsu_marker:
                    num_div = kyujinsu_marker.find_next('div', class_='ml01')
                    if num_div: kyujin_num_text = num_div.get_text(strip=True)
                job_data['求人数'] = kyujin_num_text

                # リンク
                kyujinhyo_link_tag = table.select_one('a#ID_kyujinhyoBtn')
                job_data['求人票リンク'] = urljoin(post_target_url, kyujinhyo_link_tag['href']) if kyujinhyo_link_tag and 'href' in kyujinhyo_link_tag.attrs else None
                detail_link_tag = table.select_one('a#ID_dispDetailBtn')
                job_data['詳細リンク'] = urljoin(post_target_url, detail_link_tag['href']) if detail_link_tag and 'href' in detail_link_tag.attrs else None

                # 求人番号 (最終確認)
                if '求人番号' not in job_data or not job_data['求人番号']:
                    kyujin_bango_header = table.find('td', class_='fb', string=lambda t: t and '求人番号' in t.strip())
                    if kyujin_bango_header:
                        bango_val_td = kyujin_bango_header.find_next_sibling('td')
                        if bango_val_td:
                            bango_div = bango_val_td.find('div')
                            if bango_div: job_data['求人番号'] = bango_div.get_text(strip=True)


                # 不足項目をNoneで初期化
                for key in ['事業所名', '就業場所', '雇用形態', '正社員以外の名称', '求人区分', '休日', '年齢', '公開範囲']:
                    if key not in job_data: job_data[key] = None

                all_jobs_data.append(job_data)
                print(f" -> 求人番号: {job_data.get('求人番号', 'N/A')} の情報を取得完了")

            except Exception as e:
                print(f"{index + 1} 件目のデータ処理中に予期せぬエラーが発生しました: {e}")
                if job_data: all_jobs_data.append(job_data) # 部分データでも追加

            time.sleep(1.5) # 待機

    # (エラーハンドリングは変更なし)
    except requests.exceptions.Timeout: print("エラー: リクエストがタイムアウトしました。")
    except requests.exceptions.HTTPError as e: print(f"HTTPエラー: {e.response.status_code} - {e.response.reason}")
    except requests.exceptions.RequestException as e: print(f"リクエストエラー: {e}")
    except Exception as e: print(f"予期せぬエラー: {e}")

    return all_jobs_data

# --- メイン処理 ---
initial_url = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do?action=initDisp&screenId=GECA110010"
search_post_url = "https://www.hellowork.mhlw.go.jp/kensaku/GECA110010.do"

# 出力ディレクトリ名を指定
output_dir = "output"
# 出力ディレクトリが存在しない場合は作成
os.makedirs(output_dir, exist_ok=True)

print(f"スクレイピングを開始します。")
scraped_data = scrape_hellowork_with_search(initial_url, search_post_url)

if scraped_data:
    print(f"\n合計 {len(scraped_data)} 件のデータを取得しました。")
    df = pd.DataFrame(scraped_data)

    # 列の順番定義 (変更なし)
    columns_order = [
        '求人番号', '職種', '事業所名', '就業場所', '仕事の内容',
        '雇用形態', '正社員以外の名称', '賃金', '求人区分', '受付年月日', '紹介期限日',
        '就業時間', '休日', '年齢',
        '公開範囲', 'こだわり条件', '求人数',
        '求人票リンク', '詳細リンク'
    ]
    existing_columns = [col for col in columns_order if col in df.columns]
    other_columns = [col for col in df.columns if col not in existing_columns]
    final_columns = existing_columns + other_columns
    df = df[final_columns]

    # Excelファイル名をディレクトリパスと結合
    excel_filename = "hellowork_jobs.xlsx"
    output_excel_path = os.path.join(output_dir, excel_filename)

    # CSVファイル名をディレクトリパスと結合
    csv_filename = "hellowork_jobs.csv"
    output_csv_path = os.path.join(output_dir, csv_filename)

    try:
        df.to_excel(output_excel_path, index=False, engine='openpyxl')
        print(f"\nデータをExcelファイル '{output_excel_path}' に出力しました。")
    except ImportError:
        print("\n'openpyxl' ライブラリが見つかりません。CSVで出力します。")
        try:
            df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
            print(f"データをCSVファイル '{output_csv_path}' に出力しました。")
        except Exception as e_csv: print(f"CSV出力エラー: {e_csv}")
    except Exception as e:
        print(f"Excel出力エラー: {e}")
        try:
            df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
            print(f"データをCSVファイル '{output_csv_path}' に出力しました。")
        except Exception as e_csv: print(f"CSV出力エラー: {e_csv}")
else:
    print("データを取得できませんでした。")
