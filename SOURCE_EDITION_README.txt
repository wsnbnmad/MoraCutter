Mora Cutter MVP - ソース公開版
================================

この配布物にはEXEファイルを含めていません。
すべてのプログラムをテキストエディターで確認できます。

必要なもの
------------
- Python 3.10以上
- NumPy
- FFmpeg / FFprobe / FFplay

Windowsでの準備
---------------
1. Python公式配布版をインストールします。
2. コマンドプロンプトまたはPowerShellで次を実行します。

   python -m pip install numpy

3. FFmpeg、FFprobe、FFplayへPATHを通します。
4. MoraCutter.pywをダブルクリックします。

コンソールで起動する場合
------------------------
このフォルダーで次を実行します。

   python main.py

macOS / Linux
-------------

   python3 -m pip install numpy
   python3 main.py

安全性を確認する場合
--------------------
- MoraCutter.pyw、main.py、mora_cutterフォルダー内はすべて通常のテキストです。
- 音声処理はローカルのFFmpegを呼び出します。
- ネットワークへ音声を送信するコードはありません。
- modelsフォルダーへ外部モデルを追加した場合は、そのモデルを別途確認してください。
