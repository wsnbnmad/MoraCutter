MoraCutter v1.0.1 ソース版
============================

このZIPにはMoraCutterのソースコードが入っています。
すぐに使えるWindows版は、公式のGitHub Releasesからダウンロードできます。
https://github.com/wsnbnmad/MoraCutter/releases

必要なもの
------------
- Python 3.10以上
- FFmpeg / FFprobe / FFplay

起動方法
--------
1. このフォルダーでコマンドプロンプトまたはPowerShellを開きます。
2. 必要なパッケージをインストールします。

   python -m pip install -r requirements.txt

3. MoraCutterを起動します。

   python main.py

macOS / Linux
-------------
macOSとLinux向けの完成版は配布していません。環境に合わせてPythonとFFmpegを準備し、次のコマンドで起動してください。

   python3 -m pip install -r requirements.txt
   python3 main.py

動作環境によっては追加の設定が必要になる場合があります。

データの取り扱い
----------------
音声処理はPC内で行われます。音声やプロジェクトの内容を外部へ自動送信することはありません。

ライセンス
----------
MoraCutter本体はMIT Licenseです。第三者ソフトウェアには、それぞれのライセンスが適用されます。
