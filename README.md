# ハローワーク求人情報 スクレイピングツール (Hellowork Job Scraper)

## 概要 (Overview)

このプロジェクトは、ハローワークインターネットサービスの求人検索結果ページから求人情報を自動で収集（スクレイピング）し、CSVファイルおよびExcelファイルとして出力するPythonスクリプトです。
**ユーザーがブラウザで検索条件を指定した後、スクリプトがその状態を引き継いで処理を開始します。**

This project provides a Python script to automate the process of scraping job listings from the Hellowork (Japanese public employment service) website. **After the user performs an initial search with desired criteria in their browser, the script takes over to scrape the results.** The data is exported into CSV and optionally Excel formats.

## 機能 (Features)

- **ユーザー主導の検索:** ユーザーがWebブラウザ上でハローワークの検索ページを開き、自由に検索条件（就業場所、職種、フリーワード、表示件数など）を指定して最初の検索結果を表示します。
- **Seleniumによるブラウザ操作引継ぎ:** スクリプトはユーザーの操作後、起動したChromeブラウザの表示内容を引き継ぎ、スクレイピングを開始します。
- **複数ページ対応:** 検索結果が複数ページにわたる場合、ページネーションを辿って全ページの情報を取得します。
- **データ抽出:** 各求人から以下の情報を抽出します:
  - 求人番号, 職種, 事業所名, 就業場所, 仕事の内容, 雇用形態, 正社員以外の名称, 賃金, 求人区分, 受付年月日, 紹介期限日, 就業時間, 休日, 年齢, 公開範囲, こだわり条件, 求人数, 求人票リンク, 詳細リンク
- **CSV出力 (追記型):** 取得したデータを `output/hellowork_jobs_all.csv` ファイルに1ページ処理するごとに追記します。これにより、処理が中断された場合でも途中までのデータを保持できます。
- **Excel出力 (任意):** スクリプト完了後、最終的なCSVファイルを `output/hellowork_jobs_all.xlsx` としてExcel形式に変換するオプション機能があります（スクリプト内の `CONVERT_CSV_TO_EXCEL` 定数で制御）。
- **経過時間表示:** スクリプトのスクレイピング処理開始からの経過時間を主要なステップで表示します。
- **デバッグ用ページ数制限:** コマンドライン引数 `--debug COUNT` を使用して、処理する最大ページ数を指定できます。テストや開発時に便利です。

## 必要なもの (Prerequisites)

- Python 3.7 以上
- pip (Python package installer)
- Google Chrome ブラウザ

## セットアップ (Setup)

1.  **リポジトリをクローン:**
    ```bash
    git clone https://github.com/hiraku00/scraping-hellowork.git
    cd scraping-hellowork
    ```

2.  **必要なライブラリをインストール:**
    プロジェクトルートに `requirements.txt` を作成し、以下の内容を記述してください。

    ```txt
    # requirements.txt
    beautifulsoup4
    pandas
    selenium
    webdriver-manager
    openpyxl
    ```
    その後、以下のコマンドでインストールします。
    ```bash
    pip install -r requirements.txt
    ```
    (`openpyxl` はExcel出力オプションを使用する場合に必要です。ChromeDriverは `webdriver-manager` によって自動的にダウンロード・管理されます。)

## 使い方 (Usage)

スクリプトはコマンドラインから実行します。

1.  **スクリプトを実行:**
    ```bash
    python scraping_hellowork.py
    ```
    または、デバッグモードで最初の3ページのみ取得する場合:
    ```bash
    python scraping_hellowork.py --debug 3
    ```

2.  **ブラウザ操作:**
    *   スクリプトを実行すると、Chromeブラウザが起動し、ハローワークの求人検索初期ページが表示されます。
    *   コンソールに「ブラウザが起動しました。ハローワークのサイトで求人を検索してください。...準備ができたらEnterキーを押してください...」というメッセージが表示されます。
    *   **起動したChromeブラウザのウィンドウで、**希望の検索条件（就業場所、職種、フリーワード、求人区分など）を手動で入力・選択します。
    *   **（推奨）** 表示件数を「50件」に変更します。
    *   「検索」ボタンを押し、最初の検索結果一覧を表示させます。

3.  **スクレイピング開始:**
    *   ブラウザに最初の検索結果が表示されたら、ターミナルのコンソールに戻り、**Enterキー**を押します。
    *   スクリプトが処理を引き継ぎ、表示されているページからデータの抽出とページネーションを開始します。

スクリプトが完了すると、カレントディレクトリに `output` フォルダが作成され、その中に結果が出力されます。処理終了後、ブラウザは自動で閉じられます。

## 出力 (Output)

- `output/hellowork_jobs_all.csv`: スクレイピングされた全求人データを含むCSVファイル (UTF-8 with BOM)。
- `output/hellowork_jobs_all.xlsx`: 上記CSVファイルをExcel形式に変換したファイル（スクリプト内の `CONVERT_CSV_TO_EXCEL` が `True` の場合のみ）。

## 設定 (Configuration)

スクリプト内の以下の定数を変更することで、一部の挙動を調整できます。

- `CONVERT_CSV_TO_EXCEL` (`scraping_hellowork.py` 内):
  - `True` (デフォルト): 処理完了後にCSVファイルをExcelファイルに変換します。
  - `False`: Excelファイルへの変換を行いません。
- `INITIAL_PAGE_URL`: スクリプトが最初に開くハローワークのURL。
- `PAGE_LOAD_TIMEOUT`: Seleniumがページの要素が表示されるのを待つ最大時間（秒）。
- `REQUEST_WAIT_TIME`: ページ遷移後など、サーバーへの負荷軽減と安定化のための待機時間（秒）。

## 注意事項 (Disclaimer)

- **利用規約の遵守:** ハローワークインターネットサービスの利用規約を必ず確認し、遵守してください。Webサイトへの過度な負荷を避けるため、スクリプト内の `time.sleep()` は適切に設定してください。
- **サイト構造の変更:** WebサイトのHTML構造は予告なく変更される可能性があります。構造が変更された場合、このスクリプトは正常に動作しなくなることがあります。その場合は、スクリプトの修正が必要になります。
- **自己責任:** このスクリプトの使用によって生じたいかなる損害についても、作成者は責任を負いません。自己の責任において使用してください。

## ライセンス (License)

このプロジェクトは [MIT License](LICENSE) の下で公開されています。
