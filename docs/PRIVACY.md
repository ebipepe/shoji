# Privacy policy

*Last updated: 2026-10-28* — [日本語は下にあります](#プライバシーポリシー日本語)

Shoji is a filter that runs entirely on your own PC. It has no accounts, no telemetry, no analytics, no crash
reporting and no update checks. There is no Shoji server, so nothing about you or your browsing is sent to the
Shoji project.

## What Shoji keeps on your PC

All of this stays on your PC, in `data\` (source version) or `%LOCALAPPDATA%\Shoji` (Windows app):

| Data | Contents | How to remove it |
|---|---|---|
| Statistics (`stats.db`) | Counts of blocked ads, trackers and so on per day and hour, the blocked domains, and the last ~1,000 blocked items | Dashboard → *Reset statistics*, or delete the folder |
| Settings (`config.json`), your rules (`user_rules.txt`) | Your choices and the rules you added | Delete the folder |
| Log (`shoji.log`) | Start/stop messages and errors | Delete the file |
| Filter lists (`lists\`) | Copies of the public filter lists | Delete the folder |
| Certificate (`certs\`) | The root certificate and **private key** created for HTTPS filtering on this PC only | See [Uninstall](../README.md#uninstall) |
| Filtering log | Recent requests and what Shoji did with them | Kept **in memory only**; cleared when Shoji quits or with *Clear* |

## Connections Shoji itself makes

Besides passing your own traffic on to the sites you visit, Shoji connects only to:

- **Filter list sources**, to download the lists you have turned on (about once a day): `easylist.to`,
  `filters.adtidy.org`, `ublockorigin.github.io`, `adguardteam.github.io`, `malware-filter.gitlab.io`,
  `raw.githubusercontent.com` / `cdn.jsdelivr.net` and `pgl.yoyo.org`. These servers see an ordinary download
  request from your IP address with the user agent `Shoji/<version>`.
- **A DNS resolver**, only if you use Shoji's DNS filter (`set_dns.bat`, or phones on your network): DNS questions
  that are not blocked are forwarded over DNS-over-HTTPS to Cloudflare (`cloudflare-dns.com`), with Google DNS
  (`8.8.8.8`) as a fallback. You can change the resolver in `config.json` (`dns.upstream`).
- **Browser vendors' public version information**, only for the browsers you use (about once a day), to tell you
  when your browser is out of date: `versionhistory.googleapis.com` (Chrome), `edgeupdates.microsoft.com` (Edge) and
  `product-details.mozilla.org` (Firefox). Nothing about you or your browsing is sent; these servers see an ordinary
  request from your IP address with the user agent `Shoji/<version>`. Turn it off with *Features → Browser update
  check*. To know which browser you use, Shoji reads the browser name and major version from your own requests,
  on your PC only.

## HTTPS filtering

To filter HTTPS pages, Shoji creates a root certificate that is unique to your PC and asks you before adding it to
Windows. The private key is generated on your PC and never leaves it. Pages are decrypted **only inside Shoji on
your PC** to remove ads; nothing is recorded or sent anywhere. Banks, payment sites, sign-in pages and apps that pin
certificates are passed through without decryption.

## Changes to your system

When it starts, Shoji points the Windows **system proxy** at itself (restored when Shoji quits) and turns on one
**Firefox** setting (`security.enterprise_roots.enabled`) so Firefox trusts Windows certificates. It adds the
**root certificate** only after Windows asks you. **Start with Windows** stays off until you turn it on, and **DNS**
is changed only if you run `set_dns.bat` as administrator. *Setup → Remove Shoji from this PC* undoes all of them.

## Contact

Questions about privacy: [open an issue](https://github.com/ebipepe/shoji/issues).

---

# プライバシーポリシー（日本語）

*最終更新: 2026-10-28*

Shoji は、あなたの PC の中だけで動くフィルタです。アカウント、利用状況の送信（テレメトリー）、アクセス解析、
クラッシュの報告、更新の確認は、どれもありません。Shoji 用のサーバーもないので、あなたやあなたの閲覧についての
情報が Shoji のプロジェクトに送られることはありません。

## PC の中に保存するもの

すべて PC の中の `data\`（ソース版）または `%LOCALAPPDATA%\Shoji`（アプリ版）に保存します。

| データ | 内容 | 消し方 |
|---|---|---|
| 統計（`stats.db`） | 日・時間ごとのブロック数、ブロックしたドメイン、直近約 1,000 件のブロックの記録 | ダッシュボード →「統計をリセット」、またはフォルダごと削除 |
| 設定（`config.json`）・ユーザールール（`user_rules.txt`） | 設定と、あなたが追加したルール | フォルダごと削除 |
| ログ（`shoji.log`） | 起動・終了やエラーの記録 | ファイルを削除 |
| フィルタリスト（`lists\`） | 公開されているフィルタリストの写し | フォルダごと削除 |
| 証明書（`certs\`） | HTTPS フィルタ用に、この PC のためだけに作ったルート証明書と**秘密鍵** | [アンインストール](../README.ja.md#アンインストール)を参照 |
| フィルタリングログ | 直近の通信と、Shoji がそれぞれをどう扱ったか | **メモリ上だけ**。Shoji の終了時か「クリア」で消えます |

## Shoji 自身が行う通信

あなた自身の通信を、見ようとしているサイトへ中継するほかに、Shoji が自分から接続するのは次の 3 つだけです。

- **フィルタリストの配布元**: 有効にしたリストを、1 日に 1 回ほどダウンロードします。接続先は
  `easylist.to`、`filters.adtidy.org`、`ublockorigin.github.io`、`adguardteam.github.io`、`malware-filter.gitlab.io`、
  `raw.githubusercontent.com` / `cdn.jsdelivr.net`、`pgl.yoyo.org` です。配布元のサーバーには、あなたの IP アドレスからの
  普通のダウンロードとして見えます（ユーザーエージェントは `Shoji/<バージョン>`）。
- **DNS の問い合わせ先**: Shoji の DNS フィルタを使う場合だけです（`set_dns.bat` を使ったとき、または同じネットワークの
  スマホなどから使うとき）。ブロックしなかった DNS の問い合わせを、DNS-over-HTTPS で Cloudflare（`cloudflare-dns.com`）に
  転送します。つながらないときは Google の DNS（`8.8.8.8`）を使います。問い合わせ先は `config.json` の `dns.upstream` で変えられます。
- **ブラウザの各社の公開情報**: 使っているブラウザが古いままなら知らせるために、使っているブラウザの分だけ、1 日に 1 回ほど
  最新の版を確かめます。接続先は `versionhistory.googleapis.com`（Chrome）、`edgeupdates.microsoft.com`（Edge）、
  `product-details.mozilla.org`（Firefox）です。あなたや閲覧についての情報は送りません。配布元のサーバーには、あなたの IP アドレスからの
  普通の問い合わせとして見えます（ユーザーエージェントは `Shoji/<バージョン>`）。「機能設定」→「ブラウザの更新の確認」でオフにできます。
  どのブラウザを使っているかは、あなた自身の通信に含まれるブラウザの名前と大きい版から、PC の中だけで読み取ります。

## HTTPS フィルタについて

HTTPS のページから広告を取り除くために、Shoji はこの PC 専用のルート証明書を作り、あなたに確認してから Windows に登録します。
秘密鍵はこの PC の中で作られ、外に出ることはありません。ページの中身を見るのは、**この PC の中の Shoji だけ**です。
記録も送信もしません。銀行・決済・ログインのページや、証明書を固定しているアプリは、中身を見ずにそのまま通します。

## システムの設定の変更

Shoji は起動すると、Windows の**システムのプロキシ設定**を自分に向け（終了時に元に戻します）、Windows の証明書を
信頼させるために **Firefox の設定**を 1 つ（`security.enterprise_roots.enabled`）オンにします。**ルート証明書**は、
Windows があなたに確認してから登録します。**Windows の起動時に自動で起動**は、あなたがオンにするまで無効のままです。
**DNS** は、管理者として `set_dns.bat` を実行したときだけ変えます。「セットアップ」→「Shoji を PC から取り除く」で、
これらをすべて元に戻せます。

## 問い合わせ

プライバシーについての質問は、[Issue](https://github.com/ebipepe/shoji/issues) でお寄せください。
