# Windows自己署名と配布

## 制限

自己署名はファイルが署名後に改変されていないことの確認には使えますが、不特定多数のPCでSmartScreenの信頼を得るものではありません。Windowsが「不明な発行元」などの警告を出す可能性は配布版の既知の制限です。

## 証明書

`create_self_signed_certificate.ps1`は現在のWindowsユーザーの証明書ストアに、10年間有効なRSA 3072-bit / SHA-256コード署名証明書を作ります。秘密鍵はエクスポート不可です。

```powershell
./create_self_signed_certificate.ps1
```

表示された拇印をビルド時に渡します。

```powershell
./build_windows.ps1 -Architecture x64 -FFmpegBin C:\ffmpeg\bin -CertificateThumbprint 40文字の拇印
```

公開証明書`MoraCutter-public.cer`だけが配布物に書き出されます。秘密鍵、PFX、証明書ストアのバックアップをリポジトリや配布物へ含めてはいけません。公開証明書は自動インストールせず、利用者にもインストールを必須としません。

## ARM64候補への署名

GitHub ActionsのARM64候補を展開した後、秘密鍵があるx64ビルドPCから署名できます。Authenticode署名自体は対象EXEと同じCPUで行う必要はありません。

```powershell
./finalize_windows_package.ps1 -PackageFolder C:\path\MoraCutter-v1.0.0-Windows-ARM64 -CertificateThumbprint 40文字の拇印
```

この工程はEXEへの署名、公開証明書、ファイル別SHA-256、ZIP、ZIPのSHA-256を生成します。

## 公開

GitHub Releasesへx64 ZIP、ARM64 ZIP、Source ZIP、それぞれの`.sha256.txt`、更新履歴、既知の制限を掲載します。DiscordにはGitHub Releasesへのリンクだけを掲載します。
