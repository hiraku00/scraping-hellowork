import pandas as pd
import time
import os
import datetime
import traceback
from shutil import which

# Selenium関連のインポート
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException

# --- グローバル設定 (汎用的なもの) ---
DEFAULT_PAGE_LOAD_TIMEOUT = 15 # Seleniumの要素待機タイムアウト（秒）
DEFAULT_REQUEST_WAIT_TIME = 2  # ページ遷移後などの待機時間（秒）
DEFAULT_OUTPUT_DIR_NAME = "output_generic" # 出力先ディレクトリ名 (デフォルト)

# --- WebDriver関連 ---
def setup_webdriver(headless=False, window_size='1200,900', lang='ja-JP', detach=False):
    """
    Chrome WebDriverをセットアップして返す。
    """
    options = webdriver.ChromeOptions()
    options.add_argument(f'--window-size={window_size}')
    options.add_argument(f'--lang={lang}')
    if headless:
        options.add_argument('--headless')
        options.add_argument('--disable-gpu') # headlessモードで推奨
    if detach:
        options.add_experimental_option("detach", True)

    driver = None
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
                return None
        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(10) # 暗黙的な待機
        print(f"WebDriver起動完了。")
        return driver
    except Exception as e:
        print(f"WebDriverのセットアップ中にエラーが発生しました: {e}")
        traceback.print_exc()
        if driver:
            driver.quit()
        return None

def close_webdriver(driver):
    """
    WebDriverを安全に終了する。
    """
    if driver:
        print("WebDriverを終了します。")
        driver.quit()

# --- データ出力関連 ---
def append_data_to_csv(data_list, csv_filepath, columns_order=None, page_num=None):
    """
    リスト形式のデータをCSVファイルに追記する。
    data_list: 辞書のリスト
    csv_filepath: 出力CSVファイルパス
    columns_order: CSVに出力する列の順番を指定するリスト (任意)
    page_num: ログ表示用のページ番号 (任意)
    """
    if not data_list:
        log_prefix = f"ページ {page_num}: " if page_num else ""
        print(f"{log_prefix}書き出すデータがありません。")
        return

    df = pd.DataFrame(data_list)
    if columns_order:
        # DataFrameに存在しない列が指定されてもエラーにならないようにする
        existing_cols_in_df = [col for col in columns_order if col in df.columns]
        # columns_order に含まれていないが df には存在する列も保持する
        additional_cols_in_df = [col for col in df.columns if col not in columns_order]
        final_columns = existing_cols_in_df + additional_cols_in_df
        df = df.reindex(columns=final_columns)
    else:
        pass # 列順序の指定がない場合はDataFrameのデフォルト順

    try:
        is_new_file = not os.path.exists(csv_filepath)
        write_mode = 'a' if not is_new_file else 'w'
        df.to_csv(csv_filepath, mode=write_mode, header=is_new_file, index=False, encoding='utf-8-sig')
        log_prefix = f"ページ {page_num}: " if page_num else ""
        action = "新規書き込み" if is_new_file else "追記"
        print(f"{log_prefix}'{csv_filepath}' に{action}完了。 ({len(data_list)}件)")
    except Exception as e:
        log_prefix = f"ページ {page_num}: " if page_num else ""
        print(f"{log_prefix}CSV書き込み/追記エラー: {e}")
        traceback.print_exc()

def convert_csv_to_excel(csv_filepath, excel_filepath, columns_order=None):
    """
    CSVファイルをExcelファイルに変換する。
    columns_order: Excelに出力する列の順番を指定するリスト (任意)
    """
    if not os.path.exists(csv_filepath):
        print(f"エラー: CSVファイルが見つかりません。'{csv_filepath}'")
        return False

    try:
        print(f"\nCSVファイル '{csv_filepath}' をExcelファイル '{excel_filepath}' に変換中...")
        df = pd.read_csv(csv_filepath)
        if columns_order:
            existing_columns = [col for col in columns_order if col in df.columns]
            df = df[existing_columns]
        df.to_excel(excel_filepath, index=False, engine='openpyxl')
        print(f"Excelファイルへの変換が完了しました: '{excel_filepath}'")
        return True
    except ImportError:
        print("'openpyxl' ライブラリが見つかりません。Excel変換はスキップされました。CSVファイルをご利用ください。")
    except FileNotFoundError:
        print(f"エラー: CSVファイルが見つかりません。'{csv_filepath}'")
    except Exception as e:
        print(f"CSVからExcelへの変換中にエラーが発生しました: {e}")
        traceback.print_exc()
    return False

# --- ファイル・ディレクトリ操作 ---
def ensure_output_dir(dir_name):
    """
    出力ディレクトリが存在しない場合は作成する。
    """
    os.makedirs(dir_name, exist_ok=True)
    return os.path.abspath(dir_name)

def delete_file_if_exists(filepath):
    """
    指定されたファイルが存在すれば削除する。
    """
    if os.path.exists(filepath):
        print(f"既存ファイル削除: '{filepath}'")
        try:
            os.remove(filepath)
            return True
        except OSError as e:
            print(f"エラー: 既存ファイル削除失敗 - {e}")
            return False
    return True

# --- Seleniumユーティリティ ---
def wait_for_element_presence(driver, by, value, timeout=DEFAULT_PAGE_LOAD_TIMEOUT):
    """指定された要素がDOM上に現れるまで待機する"""
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_element_located((by, value)))
    except TimeoutException:
        print(f"要素 ({by}, {value}) がタイムアウト ({timeout}秒) までにDOM上に見つかりませんでした。")
        return None

def wait_for_elements_presence(driver, by, value, timeout=DEFAULT_PAGE_LOAD_TIMEOUT):
    """指定された要素群がDOM上に現れるまで待機する"""
    try:
        return WebDriverWait(driver, timeout).until(EC.presence_of_all_elements_located((by, value)))
    except TimeoutException:
        print(f"要素群 ({by}, {value}) がタイムアウト ({timeout}秒) までにDOM上に見つかりませんでした。")
        return []

def click_element(driver, element, scroll_to_center=True):
    """要素をクリックする。必要に応じてスクロールも行う。"""
    try:
        if scroll_to_center:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5) # スクロール後の描画待ち
        # JavaScriptクリックを試みる (要素が隠れている場合などに有効)
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception: # JavaScriptクリックが失敗した場合、通常のクリックを試す
        try:
            element.click()
            return True
        except Exception as e_click:
            print(f"要素クリック中にエラー: {e_click}")
            return False

def find_clickable_element(driver, by, value):
    """表示されていてクリック可能な（disabledでない）要素を探す"""
    try:
        elements = driver.find_elements(by, value)
        for el in elements:
            if el.is_displayed() and el.is_enabled() and "disabled" not in el.get_attribute("class"):
                return el
    except NoSuchElementException:
        pass
    return None
