# ハローワーク求人情報 スクレイピングツール (Hellowork Job Scraper)

## 概要 (Overview)

このプロジェクトは、ハローワークインターネットサービスの求人検索結果ページから求人情報を自動で収集（スクレイピング）し、CSV ファイルおよび Excel ファイルとして出力する Python スクリプトです。

This project provides a Python script to automate the process of scraping job listings from the Hellowork (Japanese public employment service) website's search results page and exporting the data into CSV and optionally Excel formats.

## 機能 (Features)

- **求人情報取得:** ハローワークの求人検索ページにアクセスし、デフォルト条件で検索を実行します。
- **複数ページ対応:** 検索結果が複数ページにわたる場合、ページネーションを辿って全ページの情報を取得します。
- **データ抽出:** 各求人から以下の情報を抽出します:
  - 求人番号, 職種, 事業所名, 就業場所, 仕事の内容, 雇用形態, 正社員以外の名称, 賃金, 求人区分, 受付年月日, 紹介期限日, 就業時間, 休日, 年齢, 公開範囲, こだわり条件, 求人数, 求人票リンク, 詳細リンク
- **CSV 出力 (追記型):** 取得したデータを `output/hellowork_jobs_all.csv` ファイルに 1 ページ処理するごとに追記します。これにより、処理が中断された場合でも途中までのデータを保持できます。
- **Excel 出力 (任意):** スクリプト完了後、最終的な CSV ファイルを `output/hellowork_jobs_all.xlsx` として Excel 形式に変換するオプション機能があります（デフォルト: ON）。
- **経過時間表示:** スクリプトの実行開始からの経過時間を主要なステップで表示します。
- **デバッグ用ページ数制限:** コマンドライン引数 `--debug COUNT` を使用して、処理する最大ページ数を指定できます。テストや開発時に便利です。

## 必要なもの (Prerequisites)

- Python 3.7 以上 (Python 3.x should work)
- pip (Python package installer)

## セットアップ (Setup)

1.  **リポジトリをクローン:**

    ```bash
    git clone https://github.com/hiraku00/scraping-hellowork.git
    cd scraping-hellowork
    ```

2.  **必要なライブラリをインストール:**
    ```bash
    pip install -r requirements.txt
    ```
    (注: `requirements.txt` がまだない場合は、以下のコマンドで直接インストールしてください)
    ```bash
    pip install requests beautifulsoup4 pandas openpyxl
    ```
    (`openpyxl` は Excel 出力オプションを使用する場合に必要です)

## 使い方 (Usage)

スクリプトはコマンドラインから実行します。

- **通常実行 (全ページ取得):**

  ```bash
  python scraping_hellowork.py
  ```

- **デバッグ実行 (例: 最初の 3 ページのみ取得):**
  ```bash
  python scraping_hellowork.py --debug 3
  ```

スクリプトを実行すると、カレントディレクトリに `output` フォルダが作成され、その中に結果が出力されます。

## 出力 (Output)

- `output/hellowork_jobs_all.csv`: スクレイピングされた全求人データを含む CSV ファイル (UTF-8 with BOM)。
- `output/hellowork_jobs_all.xlsx`: 上記 CSV ファイルを Excel 形式に変換したファイル（スクリプト内の `CONVERT_CSV_TO_EXCEL` が `True` の場合のみ）。

## 設定 (Configuration)

スクリプト内の以下の定数を変更することで、一部の挙動を調整できます。

- `CONVERT_CSV_TO_EXCEL` (`scraping_hellowork.py` 内):
  - `True` (デフォルト): 処理完了後に CSV ファイルを Excel ファイルに変換します。
  - `False`: Excel ファイルへの変換を行いません。

## 注意事項 (Disclaimer)

- **利用規約の遵守:** ハローワークインターネットサービスの利用規約を必ず確認し、遵守してください。Web サイトへの過度な負荷を避けるため、短時間での連続実行や高頻度のアクセスは控えてください。スクリプト内の `time.sleep()` は適切に設定してください。
- **サイト構造の変更:** Web サイトの HTML 構造は予告なく変更される可能性があります。構造が変更された場合、このスクリプトは正常に動作しなくなることがあります。その場合は、スクリプトの修正が必要になります。
- **自己責任:** このスクリプトの使用によって生じたいかなる損害についても、作成者は責任を負いません。自己の責任において使用してください。

## ライセンス (License)

このプロジェクトは [MIT License](LICENSE) の下で公開されています。
(注: リポジトリに `LICENSE` ファイルを設置してください)
