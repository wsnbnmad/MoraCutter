# Windowsで表示される署名警告について

配布版の`MoraCutter.exe`は、`sgnl88.com`名義の自己署名証明書で署名されています。

自己署名は、公開認証局が発行する証明書とは異なります。そのため、公式配布ファイルでもWindows Defender SmartScreenが「不明な発行元」などの警告を表示する場合があります。

安全のため、MoraCutterは必ず公式の[GitHub Releases](https://github.com/wsnbnmad/MoraCutter/releases)からダウンロードしてください。必要に応じて、GitHubに表示されるダイジェストと配布ZIP内の`SHA256SUMS.txt`を照合できます。

署名情報は、`MoraCutter.exe`のプロパティにある「デジタル署名」タブから確認できます。証明書ファイルを別途インストールする必要はありません。
