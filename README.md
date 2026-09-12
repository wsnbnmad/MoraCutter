# MoraCutter

人力ボーカロイド用音声切り出し支援ツールです。手入力による素早い切り出しに専念し、音声処理はPC内で完結します。

## ダウンロード

[GitHub Releases](https://github.com/wsnbnmad/MoraCutter/releases)からZIPをダウンロードしてください。


Windows 10 / 11のx64版に対応しています。

## はじめ方

1. ダウンロードしたZIPを任意のフォルダーへ展開します。
2. 展開先の`MoraCutter.exe`を起動します。
3. 音声ファイルをドラッグ＆ドロップ、または「音声を追加」から読み込みます。
4. 波形を右ドラッグして範囲を選び、発音を入力してEnterでリストへ追加します。
5. 必要な項目にチェックを付け、保存先と音声形式を選んで書き出します。

詳しい操作方法は、配布ZIPに入っている`お読みください.txt`を参照してください。

## 主な機能

- WAV / MP3などの音声を読み込み
- 波形のズーム、スクロール、範囲選択、cue調整、ループ再生
- 複数素材をまとめたリスト表示、検索、並べ替え、選択書き出し
- 収集用リストと五十音表による不足音の確認
- `.moracutter`形式でプロジェクトを保存
- サンプリング周波数とビット深度を選んで個別WAVを書き出し
- 復旧データの自動保存

音声やプロジェクトの内容を外部へ自動送信することはありません。

## プロジェクトファイル

標準形式は`.moracutter`です。旧`.mcp.json`と`.json`も読み書きできます。

プロジェクトファイルには元音声そのものではなく、元音声の保存場所が記録されます。元音声を移動した場合は、プロジェクトを開いた際の案内から再リンクしてください。

## データの保存場所

設定、履歴、復旧データ、ログは`%LOCALAPPDATA%\MoraCutter`に保存されます。

## Windowsの警告について

MoraCutterは自己署名されているため、Windows Defender SmartScreenが警告を表示する場合があります。公式の[GitHub Releases](https://github.com/wsnbnmad/MoraCutter/releases)からダウンロードしたファイルを使用してください。詳しくは[Windowsで表示される署名警告について](CODE_SIGNING.md)を参照してください。

## 不具合報告

[GitHub Issues](https://github.com/wsnbnmad/MoraCutter/issues)から報告できます。エラーが発生した場合、ログは`%LOCALAPPDATA%\MoraCutter\logs`に保存されます。内容を確認してから添付してください。

## ライセンス

MoraCutterは[MIT License](LICENSE.txt)です。同梱される第三者ソフトウェアについては[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)を参照してください。
