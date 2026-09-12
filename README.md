# MoraCutter

音MAD・YTPMV向けの、人力ボーカロイド用音声切り出し支援ツールです。v1.0.0は手入力による高速な切り出しに専念し、音声処理はローカルで完結します。

## 配布版

- Windows 10 / 11
- x64およびネイティブARM64
- インストール、Python、管理者権限は不要
- WAV / MP3などFFmpeg対応音声
- `.moracutter`（UTF-8 JSON）と旧`.mcp.json`をサポート
- 利用者データは`%LOCALAPPDATA%\MoraCutter`へ保存
- 自動音声認識はUIから無効化し、配布EXEにもモデルを含めない

利用方法は配布物の`お読みください.txt`を参照してください。

## ソースから起動

Python 3.10以上とFFmpegが必要です。

```powershell
python -m pip install -r requirements.txt
python main.py
```

## テスト

```powershell
python -m unittest discover -s tests -v
```

## Windowsビルド

FFmpegの`bin`フォルダを明示し、実行中のPythonと同じCPUアーキテクチャを指定します。

```powershell
./build_windows.ps1 -Architecture x64 -FFmpegBin C:\path\to\ffmpeg\bin
```

ARM64版はWindows ARM64上のネイティブPythonで実行します。

```powershell
./build_windows.ps1 -Architecture ARM64 -FFmpegBin C:\path\to\ffmpeg\bin
```

自己署名証明書を作る場合:

```powershell
./create_self_signed_certificate.ps1
./build_windows.ps1 -Architecture x64 -FFmpegBin C:\path\to\ffmpeg\bin -CertificateThumbprint 40文字の拇印
```

GitHub Actionsはx64とARM64の未署名候補を別々に生成します。候補を確認後、秘密鍵を保持するローカル環境で`finalize_windows_package.ps1`を使って署名・ハッシュ作成・ZIP化します。秘密鍵やPFXはリポジトリへ保存しません。

## プロジェクト互換性

`.moracutter`の中身はバージョン番号を持つJSONです。旧形式を読み書きでき、未知の新しい形式は破損を避けるため明示的に拒否します。元音声は埋め込まず絶対パスで参照し、見つからない場合は選択フォルダから同名ファイルを一括再リンクできます。

## ライセンス

MoraCutterは[MIT License](LICENSE.txt)です。同梱される第三者コンポーネントは[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)および配布物の`THIRD_PARTY_LICENSES`を参照してください。
