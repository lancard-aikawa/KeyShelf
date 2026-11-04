# KeyShelf

Google Cloud / Firebase からダウンロードした鍵や設定のファイル（サービスアカウントの鍵、OAuth の
`client_secret_*.json`、`google-services.json`、`GoogleService-Info.plist` など）を、中身で見分けて一覧にする。

フォルダは 2 種類あり、どちらも複数持てる。

| | 保管庫 | リポジトリ |
|---|---|---|
| 意味 | ダウンロードした鍵をしまっておく所（正本） | 鍵が使われている所（写し） |
| 読むもの | `.json` と `.plist` をすべて（サブフォルダも） | 鍵の形をしたものだけ（`package.json` などは出さない） |
| 付けるもの | 重複・同じ登録・写しの数 | どのリポジトリか・git の管理下か・保管庫にもあるか（「保管済み / 未保管」） |

- 種類・プロジェクト・パッケージ名・鍵 ID・戻り先から、**何に使うものか**を文で出す
- 中身が同じファイル、同じ登録を指すファイル、同じアカウントに鍵が複数あることを知らせる
- git に入っている管理鍵と、未保管の管理鍵（リポジトリにだけある）を「注意」に出す
- フォルダは画面右上の「フォルダ」で追加・削除できる（削除しても中のファイルは消さない）。
  入れ子（保管庫とリポジトリの間も）と重複は断る。保管庫は 1 つ以上要る
- 「場所」で、保管庫 / リポジトリ / フォルダ 1 つずつに絞れる
- 「その他」「読めない」（鍵の形でない JSON）は「すべて」から外し、種類のボタンを押したときだけ出す
- 「カード」と「表」で表示を切り替えられる。表は 1 ファイル 1 行で、列の見出しで並べ替え、行の「詳細」でその場にカードを開く（選んだ表示はブラウザが覚える）
- メモと「不要」の印を付けられる（`%USERPROFILE%\.keyshelf\notes.json`）。印はファイルごと（場所で覚える）なので、
  中身が同じ 2 つのファイルの片方だけに「不要」を付けられる

## 守っていること

- **読むだけ。**ファイルを消したり動かしたりしない
- **秘密の値（秘密鍵・client_secret・API キー・トークン）は画面にも JSON にも出さない。**鍵 ID は先頭 8 文字だけ
- 外に何も送らない。サーバは `127.0.0.1` だけで待ち、`Host` を確かめ、POST は JSON だけ受け付ける
- 鍵のファイルはこのリポジトリに入れない（`.gitignore` と `tests/test_repo_clean.py`）

## 使い方

`run-keyshelf.cmd` をダブルクリックすると、サーバを起動してブラウザで開く（既に動いていればブラウザだけ開く）。
窓を閉じるか Ctrl+C で止まる。

```powershell
uv run keyshelf serve            # http://127.0.0.1:20002/ を開く
uv run keyshelf list             # ターミナルに一覧
uv run keyshelf list --json      # JSON（秘密の値は入らない）
uv run keyshelf list --no-copies # リポジトリを探さない
uv run keyshelf list --shelf D:\keys --root D:\Repos   # 設定の代わりにフォルダを指定（くり返し可）
```

設定は `%USERPROFILE%\.keyshelf\config.json`（画面の「フォルダ」で変えるとここに書く）。
無ければ既定値で動く。保管庫は `%USERPROFILE%\KeyShelf`（初回に空のフォルダを作る）、リポジトリは
`%USERPROFILE%\source\repos`・`%USERPROFILE%\repos`・`%USERPROFILE%\src`・`C:\Repos` のうち在るもの。

```json
{ "shelves": ["D:\\keys"], "roots": ["D:\\Repos"], "port": 20002 }
```

前の版の `"folder"`（保管庫 1 つ）は、読むときに `"shelves"` に読み替える。

Windows 向け（起動は `.cmd`、「開く」はエクスプローラ）。Python 3.11 以上と [uv](https://docs.astral.sh/uv/) が要る。
依存は Python の標準ライブラリだけ（試験に pytest）。

## ライセンス

MIT（[LICENSE](LICENSE)）
