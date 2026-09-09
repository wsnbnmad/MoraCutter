# Windows署名と誤検知対策

## 重要

`signal88.com`というWebサイトを所有しているだけでは、Windowsの発行元確認には使われません。警告画面へ確認済み発行元を表示するには、公開信頼された認証局またはMicrosoft Trusted Signingから取得したコード署名証明書で、配布するEXEへAuthenticode署名を付ける必要があります。

自己署名証明書は開発中の改ざん検査には使えますが、不特定多数のPCでSmartScreenの信頼を得る方法にはなりません。

## このプロジェクトで行っていること

- `CompanyName`、著作権、製品名へ `signal88.com` を設定
- アプリ識別子を `signal88.MoraCutter` に固定
- 管理者権限を要求しない `asInvoker` マニフェスト
- PyInstallerのUPX圧縮を明示的に無効化
- 一時展開型のone-fileではなく、挙動が確認しやすいone-folder形式
- SHA-256ファイルハッシュの同梱
- SHA-256ダイジェストとRFC 3161タイムスタンプを使う署名スクリプト
- 署名直後のSignToolおよびAuthenticode検証

これらは誤検知の可能性を下げ、利用者が配布元と改ざん有無を確認しやすくしますが、DefenderやSmartScreenで警告されないことを保証するものではありません。

## 正式署名までの手順

1. Microsoft Trusted Signingまたは公開信頼された認証局から、組織・個人向けコード署名証明書を取得します。
2. 証明書を秘密鍵付きで、ビルド用PCの `CurrentUser\\My` 証明書ストアへ安全に登録します。
3. PowerShellでコード署名用証明書を確認します。

   ```powershell
   Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert |
     Select-Object Subject, Issuer, NotAfter, Thumbprint
   ```

4. 表示された拇印を使ってビルドします。

   ```powershell
   .\\build_windows.ps1 -CertificateThumbprint "40文字の拇印"
   ```

5. `release\\dist\\MoraCutter\\MoraCutter.exe` のプロパティに「デジタル署名」タブがあり、署名状態が有効であることを確認します。

## 配布時

- HTTPSの `https://signal88.com/` から配布してください。
- 配布ページにバージョン、SHA-256、署名者名、変更履歴を掲載してください。
- ZIPを差し替えるときはバージョンも更新し、古いハッシュを再利用しないでください。
- Virustotalなど第三者サービスへ未公開素材入りのファイルを送信しないでください。確認する場合は、配布予定のアプリ本体だけを対象にします。
- FFmpeg等の第三者バイナリへ自分の証明書で署名し直さないでください。署名対象は自分が作成した `MoraCutter.exe` です。

