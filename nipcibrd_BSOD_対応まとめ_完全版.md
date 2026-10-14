# LabVIEW 2021 SP1 導入後の起動不能（nipcibrd.sys／0x1EA）対応まとめ【完全版】

作成日：2026-10-15
作業申請書（情シス向け）：https://claude.ai/code/artifact/97b8e035-e9fb-4651-8f44-dc62b6b343b8

---

## 目次

0. [結論](#0-結論)
1. [現象](#1-現象)
2. [原因と仕組み](#2-原因と仕組み)
3. [「去年までは問題なかった」理由](#3-去年までは問題なかった理由)
4. [ドライバ関連の情報](#4-ドライバ関連の情報)
5. [復旧方法の比較と推奨](#5-復旧方法の比較と推奨)
6. [推奨手順（案1＋MSI削除）](#6-推奨手順案1msi削除)
7. [予備手順（案2：レジストリで無効化）](#7-予備手順案2レジストリで無効化)
8. [回復環境での注意点](#8-回復環境での注意点)
9. [再現環境について](#9-再現環境について)
10. [根拠の検証状況と訂正履歴](#10-根拠の検証状況と訂正履歴)
11. [次のアクション](#11-次のアクション)
12. [参考リンク一覧](#12-参考リンク一覧)

---

## 0. 結論

- LabVIEW 2021 SP1 と一緒に入った NI のドライバ **nipcibrd.sys** が、Windows のセキュリティ機能（VBS 上のセキュアPCI）に遮断されて BSOD → 起動不能になっている。**PC の故障やマルウェアではない**
- NI の既知の不具合で、**PXI Platform Services 2023 Q3 で修正済み**。LabVIEW 2021 SP1 に付属するのは修正前の 21.5
- 推奨は **案1：ハイパーバイザを一時停止して起動 → MSI で nipcibrd だけ削除 → VBS を戻す**。VBS の一時停止が認められなければ **案2：回復環境でレジストリから無効化**
- **USB は使えない前提**。どの手順も USB 不要で組んである
- 別件で **NI-PAL のセキュリティ更新（早ければ 2026-11-10 から影響）** が全社の NI 導入 PC で必要

---

## 1. 現象

| 項目 | 内容 |
| --- | --- |
| 対象PC | （機種・BIOS バージョンを記入。Dell Latitude かどうかも記入） |
| 環境 | Windows（AD 参加・BitLocker 有効） |
| きっかけ | LabVIEW 2021 SP1 のインストール後の再起動 |
| 症状 | 起動のたびに BSOD → 自動修復（回復環境）に戻る |
| 停止コード | SECURE_PCI_CONFIG_SPACE_ACCESS_VIOLATION（**0x000001EA**） |
| 原因ドライバ | nipcibrd.sys（National Instruments PCI Bridge Driver） |

> ⚠ 当初「0xEA」とメモしていた。**0xEA は THREAD_STUCK_IN_DEVICE_DRIVER（主に GPU ドライバ）で別物**。表記は `0x000001EA` でゼロが並ぶため「1」を見落としやすい。**画面写真で停止コード名を再確認すること**。

---

## 2. 原因と仕組み

### 2.1 何が起きているか

1. LabVIEW 2021 SP1 Platform には **PXI Platform Services 21.5** が同梱されており、インストール時に導入された
2. その中の **nipcibrd.sys** が、Windows の正規の API を通さずに **PCI コンフィグ空間を直接読み書き**しようとする
3. **VBS（仮想化ベースのセキュリティ）** 上で動く「セキュアPCI」がこれを遮断し、BSOD（0x1EA）になる

Microsoft の説明では、0x1EA は「セキュアPCI が有効なとき、VTL0 から PCI MCFG 範囲を直接マッピングしてコンフィグ空間にアクセスすることは禁止されている」ことを示す。

### 2.2 用語

| 用語 | 意味 |
| --- | --- |
| **VBS** | Virtualization-Based Security（仮想化ベースのセキュリティ）。VBScript とは無関係。ハイパーバイザを起動して PC を **VTL1（保護された領域）** と **VTL0（普段の Windows：カーネル・ドライバ・アプリ）** に分け、カーネル権限のドライバでも VTL1 が禁止する操作はできなくする |
| VBS の上の主な機能 | **メモリ整合性（HVCI）**、**Credential Guard**（AD 環境でよく使われる）、**セキュアPCI**（今回の BSOD の原因） |
| **PCI** | PC の汎用拡張バス規格（現在の主流は PCIe） |
| **PXI** | PCI eXtensions for Instrumentation。NI 主導の計測向け規格。電気的には PCI／PCIe と同じバスで、CompactPCI ベースのシャーシに計測モジュールを挿す。モジュール間の同期クロック（10MHz 基準）やトリガ線を持つ |
| **PCI ブリッジ** | バスとバスをつなぐ中継器。ホストブリッジ（CPU⇔PCI）、PCI-PCI ブリッジ（バス同士）などがあり、ツリー状にバスを広げる。nipcibrd.sys の「pcibrd」は PCI bridge の意味で、PXI シャーシ内のブリッジ構成を調べて管理するドライバ |
| PCI コンフィグ空間 | 各 PCI デバイスの設定用レジスタ。Microsoft の立場では、PCI リソースはそのデバイスのバスドライバだけが扱うもので、正規の手段（BUS_INTERFACE_STANDARD 等）以外のアクセスはセキュアPCI で BSOD にされる |

### 2.3 セキュアPCI が働く 3 条件

OSR（Windows ドライバ開発者コミュニティ）の解説によれば、以下が**全部そろったときだけ**発動する。

1. Windows 10 以降
2. BIOS が **SDEV ACPI テーブル**に対応（Microsoft の要件だが、最近までは TPM 2.0 のように強制が緩かった）
3. **VBS が有効**（Windows 11 新規インストールでは既定オン、Windows 10 では既定オフ）

→ **今 0x1EA が出ているなら、その PC は 3 条件を満たしていることが確定**している。

---

## 3. 「去年までは問題なかった」理由

nipcibrd.sys 自体は去年も同じ。**PC 側で 3 条件がそろった**と考えられる（推定・未確認）。

| 変化 | 該当条件 | 確認先 |
| --- | --- | --- |
| GPO／Intune で VBS・メモリ整合性・Credential Guard を全社展開 | 3 | 情シス |
| Windows 10 → 11 移行、または PC 入れ替え | 3 | 情シス |
| BIOS／ファームウェア更新で SDEV 対応 | 2 | 情シス・メーカー更新履歴 |
| Windows Update 経由の Intel ファームウェア更新（この直後に同エラーが出始めた報告あり） | 2 | 更新履歴 |
| BIOS のセキュリティ機能（例：Lenovo「Enhanced Windows Biometric Security」は VBS を有効にする） | 3 | BIOS 設定 |
| 去年は PXI Platform Services を入れずに導入していた | — | 去年の導入手順 |

参考：NI フォーラムに「新しい ThinkPad P1 Gen 6 では起きたが、1 年前の X1 Extreme Gen 5 では起きなかった」という報告あり。**新しい PC ほど起きやすい**。

報告がある機種：ThinkPad L13 Gen3（AMD）、ThinkPad P1 Gen 6、Surface 5、Framework 13、Dell Alienware。**普通の業務用ノートでも起きる**。Latitude での具体的な報告は見つからなかった。

→ **全社施策が原因なら、同じ構成の他の PC でも同じことが起きうる。**

---

## 4. ドライバ関連の情報

### 4.1 nipcibrd.sys

| 項目 | 内容 |
| --- | --- |
| 正体 | NI の PCI Bridge Driver。PXI Platform Services の一部 |
| NI ハードがなくても入るか | **入る**（LabVIEW・VISA などの依存で自動的に入る） |
| 起動種別 | **ブート時に読み込み（Start=0）**。他 PC のドライバ一覧ログで `R0 nipcibrd` と記録されていた |
| 業務で必要か | NI の PXI／PCI ボードを使わないなら**不要** |

### 4.2 フィルタ登録（UpperFilters／LowerFilters）

- Windows の正式な仕組み。デバイスの通信経路に別のドライバを「経由地」として挟む登録で、`UpperFilters`／`LowerFilters` という REG_MULTI_SZ（複数行文字列）の値に**ドライバ名だけ**が書かれる
- たとえ：ショートカットのように「名前で本体を指しているだけ」だが、**リンク切れが致命的**。起動時に「このドライバたちを順番に積んで動かす」リストとして読まれるので、載っている名前が見つからない／無効だと**そのデバイス自体が動かない** → ストレージにつながる PCI 機器なら INACCESSIBLE_BOOT_DEVICE（0x7B）。「全員そろわないと出発できないバスの乗車名簿」に近い
- **nipcibrd がフィルタとして登録されているかは未確定**（NI の資料で明記されたものは見つからず）。ただし「サービスだけ無効化すると 0x7B」という実例があり、可能性は高い
- **値ごと消すのも危険**：ディスクのクラスキーで `UpperFilters` を値ごと削除したら起動しなくなり、`partmgr` を書き戻して直した事例あり → 消すのは **nipcibrd の行だけ**

### 4.3 やってはいけないこと（実例あり）

| 操作 | 結果 |
| --- | --- |
| nipcibrd.sys のファイルをリネーム | **起動しなくなった** |
| サービスの起動種別だけ「無効」（Autoruns 等） | **0x7B で起動不能**。回復環境でレジストリを「ブート」に戻すまで直らなかった |
| DISM でオフライン削除 | Microsoft の説明はドライバストアからの削除まで。本体・サービス・フィルタ登録が消える保証がなく、ブート必須ドライバの削除はイメージを起動不能にしうると警告あり。レジストリのバックアップでは切り戻せない → **不採用** |
| セーフモードから NI-VISA をアンインストール | 復旧しなかった |
| `UpperFilters` 値ごと削除 | 他のフィルタも外れて起動不能 |

### 4.4 削除方法

| 方法 | 内容 | 注意 |
| --- | --- | --- |
| **MSI で個別削除（推奨）** | nipcibrd の MSI（`pcibrdi64.msi`／`pcibrdi32.msi` など）をアンインストール。詳細は 6 章 | **依存パッケージを巻き込まず** nipcibrd だけ消せる。NI ハードがなければ DAQmx・VISA・Vision に影響しなかった報告あり。公式手順ではない。NI Package Manager 上は「インストール済み」のまま残るため、今後の NI ソフトの修復・更新で**修正前の版が復活する可能性** |
| NI Package Manager（NI 公式） | 「インストール済み」で「製品のみ」のチェックを外し「PXI Platform Services Runtime」を削除 | **VISA・DAQmx・Vision 等も巻き添えで消える**ことがある。nipcibrd だけを単独では消せない |

### 4.5 PXI Platform Services のバージョン

| バージョン | 状況 |
| --- | --- |
| 21.5 | LabVIEW 2021 SP1 Platform に同梱。**今回の原因** |
| 2023 Q2 | 直らなかった報告あり |
| **2023 Q3** | Readme に「Windows のブルースクリーンにつながるドライバ非互換を修正」と明記。対応 LabVIEW は **2020 以降** → LabVIEW 2021 SP1 は公式サポート内。Windows 10／11 対応 |
| 2023 Q4 | 更新で直った報告あり |
| 2024〜2026 Q3（最新） | LabVIEW 2021 対応かは**未確認**。入れる前に Readme の Application Software Support 表を確認 |

**方針**：PXI 製品を使わない → **削除**（バージョン選び不要）。使う必要がある → **2023 Q3**。
なお新形式の LabVIEW サポートパッケージ（LVAddons に入るもの）は LabVIEW 2022 Q3 以降向けなので、2021 では無関係。

### 4.6 【別件・期限あり】NI-PAL のセキュリティ更新

| 項目 | 内容 |
| --- | --- |
| 内容 | 多くの NI ドライバが使う **NI-PAL（nipalk.sys）** が脆弱性 **CVE-2026-18485** で Microsoft の**脆弱ドライバ ブロックリスト**に登録された |
| 影響時期 | **早ければ 2026-11-10 から** Windows が読み込みをブロックする可能性 |
| 影響 | NI MAX・Hardware Manager・各デバイスドライバでエラー → NI のソフト・ハードが動かなくなるおそれ |
| 対象 | NI-PAL **26.3.1 以前**。ブロックリストは **Windows 11 で既定オン**（Windows 10 は既定オフ） |
| 確認 | `C:\Windows\System32\drivers\nipalk.sys` → プロパティ → 詳細 → 製品バージョン |
| 対処 | NI Update Service か NI-PAL ダウンロードページのオフラインインストーラーで **NI-PAL 2026 Q3 以降**を入れて再起動（約 1 分）→ NI MAX でデバイス確認・セルフテスト |
| LabVIEW 2021 への影響 | NI-PAL の 1 部品だけの更新で、ドライバ全体のバージョンアップ不要。NI-PAL 17.0 まで後方互換 |
| NI の見解 | ブロックリストの無効化は推奨しない |

→ nipcibrd を片付けても、NI-PAL を更新しないと **11 月以降に別の理由で NI ソフトが止まる**可能性。**全社の NI 導入 PC が対象**。

---

## 5. 復旧方法の比較と推奨

| 案 | 方法 | 回復キー | セキュリティ影響 | 見込み | 主なリスク・根拠 |
| --- | --- | --- | --- | --- | --- |
| **1（推奨）** | `hypervisorlaunchtype off` で起動 → **MSI** で nipcibrd 削除 → `auto` に戻す | 不要な場合あり（BCD 変更で求められることも） | 作業中の約 30 分だけ VBS 停止 | 高め | 同じ状態になる BIOS の VT-x 無効化で起動できた実例あり。「保護を外して起動 → MSI で削除 → 戻す」はコミュニティで最も実績のある流れ。**反例**：AMD の ThinkPad で仮想化を切っても直らず再インストールしかなかった。GPO・UEFI ロックで VBS 強制の環境では効かない可能性 |
| 2 | 回復環境でオフラインレジストリ編集（フィルタ登録除去＋`Start=4`）→ 起動後に削除 | 必要 | なし | 中〜高 | Microsoft 公式 KB に同じ組み合わせ（Start=4＋UpperFilters の参照削除）の手順あり（別ドライバ）。nipcibrd での成功実例は見つからず。見落としで 0x7B（SYSTEM ハイブのバックアップで完全に戻せる） |
| 3 | システムの復元 | 必要 | なし | 復元ポイント次第 | ドメイン PC では無効化されていることが多い |
| 4 | BIOS で VT-d・SR-IOV（または VT-x）を一時無効化（NI 公式 KB 記載） | 求められる可能性大 | 作業中のみ低下 | 中〜高（成功報告が最多） | BIOS パスワード管理下では不可。項目がない機種あり（Surface）。NI KB 自体が「環境により効かない」と記載 |
| 5 | OS 再セットアップ | 不要 | なし | 確実 | 時間・データ移行 |
| 不採用 | DISM でオフライン削除 | — | — | — | 4.3 参照 |

**判断**：案1 → （VBS 停止が不可なら）案2 → 案4 → 案5。

---

## 6. 推奨手順（案1＋MSI削除）

所要 30 分程度。VBS が止まるのは手順 3〜6 の間だけ。

| # | 手順 | なぜ必要か |
| --- | --- | --- |
| 1 | 自動修復 →「詳細オプション」→「トラブルシューティング」→「詳細オプション」→「コマンドプロンプト」。回復キーを求められたら入力か「このドライブをスキップ」 | 起動しないので回復環境でしか作業できない。BCD は BitLocker で暗号化されていない領域にあるのでスキップでも可 |
| 2 | `bcdedit /enum {default}` で `hypervisorlaunchtype` の値（通常 `Auto`）を写真で記録 | 戻す値を確実にし、作業前と同じ状態に戻したことを証明するため |
| 3 | `bcdedit /set {default} hypervisorlaunchtype off` | VBS の土台のハイパーバイザを止めると遮断が起きず、ドライバが残ったままでも起動できる |
| 4 | コマンドプロンプトを閉じ「続行」で起動（回復キーを求められたら入力） | 削除作業は Windows 起動状態で行う前提。BCD 変更を BitLocker が検知すると回復キーを求められる |
| 5 | **MSI で nipcibrd を削除**（下記 6.1） | 原因そのものを取り除く。ここを飛ばして VBS を戻すと再び BSOD |
| 6 | 管理者のコマンドプロンプトで `bcdedit /set {default} hypervisorlaunchtype auto`（手順 2 で行がなかった場合は `bcdedit /deletevalue {default} hypervisorlaunchtype`） | VBS を止めたままだとメモリ整合性などの保護が全部無効で、社内基準を満たさない |
| 7 | 再起動 → `msinfo32` で「仮想化ベースのセキュリティ：実行中」、コア分離のメモリ整合性オン、LabVIEW 起動を確認 | 設定を戻したことと、保護が実際に動いていることは別 |

> ⚠ **手順 5 の削除と確認が終わる前に手順 6 をやると再び BSOD**。手順 4 で起動しない／同じ BSOD が出る場合は、手順 2 の値に戻して案2へ。

### 6.1 MSI での削除（USB 不要）

前提：MSI は回復環境では実行できないので、**案1 で通常起動した後**に行う。**管理者権限が必要**（なければ情シスに依頼）。

#### 方法A：製品コードで削除（第一候補・ファイル不要）

Windows Installer は、インストールした MSI のコピーを `C:\Windows\Installer` に保存しており、削除時はまずそれを使う。そのため製品コードだけで削除できる。

1. 製品コードを探す
   ```
   reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall /s /f "PCI Bridge" /d
   reg query HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall /s /f "PCI Bridge" /d
   ```
   見つかったキーの末尾の `{…}` が製品コード（64bit 版と 32bit 版で別々にある想定）。表示名・バージョンとともに写真で記録。
   見つからない場合は PowerShell で Windows Installer 登録製品を一覧化：
   ```
   $i = New-Object -ComObject WindowsInstaller.Installer
   $i.ProductsEx("", "", 7) | ForEach-Object { [pscustomobject]@{Name=$_.InstallProperty("ProductName"); Code=$_.ProductCode(); Cache=$_.InstallProperty("LocalPackage")} } | Where-Object Name -like "*PCI*"
   ```
2. （任意・自分で確かめたい場合）Windows が「アプリと機能」から削除するときに使うコマンドを表示
   ```
   reg query "見つかったキー" /v UninstallString
   ```
   MSI 製品なら通常 `MsiExec.exe /X{…}` の形。
3. 削除（製品コードごとに実行。ログは報告資料にもなる）
   ```
   msiexec /x {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX} /norestart /l*v C:\pcibrd_uninstall_1.log
   ```
4. 確認
   ```
   sc query nipcibrd
   dir C:\Windows\System32\drivers\nipcibrd.sys
   ```
   「指定されたサービスはインストールされたサービスとして存在しません。」「ファイルが見つかりません」なら OK。
5. **VBS は止めたまま一度再起動**して、削除後の状態で通常起動できることを確認 → 案1 の手順 6 へ

#### 方法B：PC 内に残っている MSI ファイルで削除

```
where /r "C:\ProgramData\National Instruments" *pcibrd*
```
報告によりファイル名が `pcibrd64.msi` だったり `pcibrdi64.msi` だったりするのでワイルドカードで探す（報告例の場所：`C:\ProgramData\National Instruments\MDF\ProductCache\NI-PCI Bridge Driver [バージョン]`）。
```
msiexec /x "見つかったパス\pcibrdi64.msi" /norestart /l*v C:\pcibrd_uninstall_64.log
msiexec /x "見つかったパス\pcibrdi32.msi" /norestart /l*v C:\pcibrd_uninstall_32.log
```
以降は方法A の 4〜5 と同じ。

#### 方法C：インストーラーをダウンロードして取り出す（最終手段）

ネットワーク経由なので USB 不要。**ni.com からのダウンロードが許可されているか事前に情シスに確認**。

1. PXI Platform Services のダウンロードページから**今入っているのと同じバージョン（21.5）**のオフラインインストーラー（ISO）を取得（MSI の削除はインストール済み製品と同じ製品コードでないと動かないため）
2. ISO を右クリック →「マウント」し、`\pool\` 内の `ni-pcibrd_～.nipkg` を探す
3. 展開（`.nipkg` は Debian パッケージ同様の ar 形式で、中に `data.tar.gz` → `data.tar` がある。**Windows 標準 `tar` で ar を展開できるかは未検証**。再現環境で確認）
   ```
   mkdir C:\temp\pcibrd
   tar -xf "D:\pool\ni-pcibrd_～.nipkg" -C C:\temp\pcibrd
   tar -xf C:\temp\pcibrd\data.tar.gz -C C:\temp\pcibrd
   ```
4. 出てきた `pcibrdi64.msi`／`pcibrdi32.msi` を方法B と同様に `msiexec /x`

#### 参考：セーフモード＋MSI の報告

セーフモード（ネットワーク付き）で起動し、レジストリで Windows Installer をセーフモードでも動くようにしてから `net start MSIServer`、`ProductCache` 内の MSI を実行 → 再起動で通常起動できた、という報告あり。ただし今回の PC でセーフモードが起動するかは不明（ブート時に nipcibrd が読み込まれるため）。

---

## 7. 予備手順（案2：レジストリで無効化）

セキュリティ設定に触れずに、nipcibrd を「眠らせて」起動させる。ファイルは消さないので、SYSTEM ハイブのバックアップを戻せば完全に元通り。手順 1〜8 は回復環境、手順 9 は起動後。所要 30〜45 分。

| # | 手順・コマンド | なぜ必要か／注意 |
| --- | --- | --- |
| 1 | 回復環境でコマンドプロンプト。回復キーを入力（**案2 ではスキップ不可**） | OS ドライブ内のファイルを読み書きするため |
| 2 | OS ドライブの確認：`for %d in (C D E F G) do @if exist %d:\Windows\System32\config\SYSTEM echo %d:`。表示がなければ `manage-bde -status` → `manage-bde -unlock D: -RecoveryPassword <回復キー>` | 回復環境はドライブ文字を振り直す（8 章）。以下 `D:` として記載 |
| 3 | `copy D:\Windows\System32\config\SYSTEM D:\SYSTEM.bak` | SYSTEM はドライバ・サービス設定のレジストリ実体。これを戻せば完全に元通り |
| 4 | `reg load HKLM\OFF D:\Windows\System32\config\SYSTEM` → `reg query HKLM\OFF\Select /v Current`（`0x1` なら ControlSet001） | 起動していない Windows のレジストリを仮名「OFF」で開く。オフラインには `CurrentControlSet` が存在しない。**回復環境の `HKLM\SYSTEM` は回復環境自身の設定なので触らない** |
| 5 | `reg query HKLM\OFF\ControlSet001 /s /f nipcibrd > X:\hit.txt` → `notepad X:\hit.txt`（記録として残すなら `D:\hit.txt`） | 登録箇所は PC ごとに違う。X: は回復環境の RAM ディスクで再起動で消える |
| 6 | フィルタ登録を外す（下記 7.2） | 経由地の登録を残したまま本体を止めると 0x7B |
| 7 | `reg query HKLM\OFF\ControlSet001\Services\nipcibrd /v Start`（元の値を記録）→ `reg add HKLM\OFF\ControlSet001\Services\nipcibrd /v Start /t REG_DWORD /d 4 /f` → 再度 query で `0x4` を確認 | Start：0=ブート、1=システム、2=自動、3=手動、4=無効。サービス登録が残るとフィルタから外しても読み込まれる。**フィルタ登録が見つかった場合、手順 6 と 7 は必ずセット**（6 だけ→BSOD 残存の可能性、7 だけ→0x7B） |
| 8 | regedit を閉じてから `reg unload HKLM\OFF` →「続行」で起動 | `reg load` は本体ファイルを直接開いている状態。unload で残りの変更を書き切って閉じる。この時点で NI の一部機能が動かないのは想定どおり |
| 9 | 起動後、6.1 の MSI 削除（または NI Package Manager で PXI Platform Services Runtime 削除）→ `nipcibrd.sys` がないことを確認 → 再起動 | 手順 7 までは眠らせただけ。正式に削除して管理情報と実態を一致させる |

### 7.1 検索結果（hit.txt）の読み方

```
HKEY_LOCAL_MACHINE\OFF\ControlSet001\Control\Class\{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
    UpperFilters    REG_MULTI_SZ    nipcibrd\0partmgr

HKEY_LOCAL_MACHINE\OFF\ControlSet001\Enum\PCI\VEN_xxxx&DEV_xxxx&...\x&xxxxxxxx&0&xx
    LowerFilters    REG_MULTI_SZ    nipcibrd

HKEY_LOCAL_MACHINE\OFF\ControlSet001\Services\nipcibrd

検索の結果: 3 件の一致が見つかりました。
```
（形の例。実際のパス・GUID は PC ごとに異なる。nipcibrd がフィルタ登録されているかは未確定）

- 字下げのない `HKEY_LOCAL_MACHINE\…` の行が**キー**（手順の `<キー>`）
- 字下げされた行が**値**：「値の名前」「種類」「データ」の順
- `\0` は複数行の区切り（例 1 は `nipcibrd` と `partmgr` の 2 つ）
- 値の行がなくキーだけの行は、キー名そのものに nipcibrd が含まれていたという意味

| 見つかった場所 | 意味 | 対応 |
| --- | --- | --- |
| 値の名前が `UpperFilters`／`LowerFilters` | フィルタ登録 | 手順 6 で **nipcibrd の行だけ**外す |
| キーが `Services\nipcibrd` | サービス登録 | 手順 7 で無効化（**キーごと削除はしない**） |
| それ以外（`Enum` 配下の `Service` 値など） | NI デバイス自体の情報 | 触らず記録のみ |

### 7.2 フィルタ登録の外し方

**方法1：regedit（推奨・打ち間違いリスクが小さい）**

1. コマンドプロンプトで `regedit`
2. `HKEY_LOCAL_MACHINE` → `OFF` を展開（同じ階層の `SYSTEM` などは回復環境自身のものなので開かない）
3. hit.txt のキーの行を順にたどる（アドレス欄があれば、コピーしたキーを貼り付けて Enter で直接移動）
4. 右側で `UpperFilters`（または `LowerFilters`）のデータが hit.txt と一致することを確認
5. 左側のキーを右クリック →「エクスポート」で `D:\filter_backup1.reg`（2 件目以降は数字を変える）
6. 値をダブルクリック →「複数行文字列の編集」
7. `nipcibrd` の 1 行だけなら → キャンセルして値を右クリック →「削除」。他の行もあるなら → **nipcibrd の行だけ**消して OK（空行の警告が出たら OK で自動除去。他の行の文字・順番は変えない）
8. データから nipcibrd が消え、他が残っていることを確認
9. 次の対象があれば 3 に戻る
10. 全部終わったら regedit を閉じる（開いたままだと `reg unload` が失敗）

**方法2：コマンドのみ**

- 長いパスは手で打たず、メモ帳でキーの行をコピー → `Ctrl+V`（または右クリック）で貼り付け
- **キーは必ず `"` で囲む**（`Enum` 配下のパスには `&` が含まれ、囲まないとコマンドの区切りと解釈される）

```
reg query "<キー>" /v <値の名前>
reg export "<キー>" D:\filter_backup1.reg
```
- ケースA（データが `nipcibrd` だけ）：`reg delete "<キー>" /v <値の名前> /f`
- ケースB（他もある）：nipcibrd を除いた残りを**元の順番のまま** `\0` でつないで上書き
  `reg add "<キー>" /v <値の名前> /t REG_MULTI_SZ /d "<残り>" /f`
  例：`nipcibrd\0partmgr` → `partmgr`、`aaa\0nipcibrd\0bbb` → `aaa\0bbb`
- 確認：再度 `reg query`。ケースA は「指定されたレジストリ キーまたは値が見つかりませんでした。」、ケースB は nipcibrd だけが消えて残りが元の順番なら OK

具体例（7.1 の例の場合）：
```
reg query "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Control\Class\{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}" /v UpperFilters
reg export "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Control\Class\{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}" D:\filter_backup1.reg
reg add "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Control\Class\{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}" /v UpperFilters /t REG_MULTI_SZ /d "partmgr" /f

reg query "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Enum\PCI\VEN_xxxx&DEV_xxxx&...\x&xxxxxxxx&0&xx" /v LowerFilters
reg export "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Enum\PCI\VEN_xxxx&DEV_xxxx&...\x&xxxxxxxx&0&xx" D:\filter_backup2.reg
reg delete "HKEY_LOCAL_MACHINE\OFF\ControlSet001\Enum\PCI\VEN_xxxx&DEV_xxxx&...\x&xxxxxxxx&0&xx" /v LowerFilters /f
```

> ⚠ 他のフィルタ名を消す・打ち間違えると、それ自体が起動不能の原因になる。`Enum` 配下で「アクセスが拒否されました」と出たら、**権限を変えずに作業を止めて情シスに相談**。想定外の場所に大量にヒットした場合も同様。

### 7.3 切り戻し

回復環境で `reg unload` 済みの状態で：
```
copy D:\SYSTEM.bak D:\Windows\System32\config\SYSTEM
```
上書き確認に `Y`。ファイルは削除していないので完全に元通り。

---

## 8. 回復環境での注意点

| 項目 | 内容 |
| --- | --- |
| 入り方 | 起動失敗が続くと自動修復 →「詳細オプション」。出なければ電源長押しの強制終了を 2〜3 回 |
| ドライブ文字 | 回復環境は独自に振り直すため、**C: が D: や E: になることがある**（「システムで予約済み」等が先に C を取る）。回復環境自身は **X:** |
| ドライブ確認 | `for %d in (C D E F G) do @if exist %d:\Windows\System32\config\SYSTEM echo %d:`、または `bcdedit /enum {default}` の `osdevice`、または `diskpart` → `list volume` |
| BitLocker | ロック中のドライブは中身が見えない。`manage-bde -status` で確認し解除。**AD 環境では回復キーは情シス経由**（画面の回復キー ID 先頭 8 桁を伝える） |
| X: の使い分け | X: は RAM ディスクで**再起動で消える**。見るだけのメモ → X:、切り戻しに使うバックアップ → D: |
| セーフモード | PIN サインインがループした報告あり。使うならパスワードでサインインできるようにしておく |

---

## 9. 再現環境について

- **仮想マシンでは再現できない可能性が高い**（SDEV テーブルと VBS の条件が仮想 BIOS でそろうか怪しい。BSOD が出なくても「問題なし」とは言えない）
- 現実的な作り方：
  1. **同じ機種（型番）・同じ BIOS バージョン**の予備機を、**同じ社内イメージ・ポリシー**で用意してもらう
  2. `msinfo32` で「仮想化ベースのセキュリティ：実行中」を確認
  3. ディスク全体のバックアップを取る（試行ごとに戻せるように）
  4. LabVIEW 2021 SP1 を PXI Platform Services 込みで入れ、**同じ BSOD が出ることを確認**（原因の確定にもなる）
  5. 案1（＋MSI 方法A）→ 戻す → 案2 の順で検証。方法C の `tar` 展開もここで確認
- 予備機がなければ、去年まで問題なかった同僚 PC の `msinfo32` で VBS 状態を見るだけでも仮説の確認材料になる

---

## 10. 根拠の検証状況と訂正履歴

### 10.1 確認済み

| 内容 | 根拠 |
| --- | --- |
| 0x1EA の意味 | Microsoft Bug Check 0x1EA |
| 3 条件 | OSR の解説 |
| nipcibrd による 0x1EA、NI 公式の対処（BIOS／PXI Platform Services 削除） | NI KB |
| 2023 Q3 で修正、LabVIEW 2020 以降対応 | PXI Platform Services 2023 Q3 Readme |
| LabVIEW 2021 SP1 Platform に PXI Platform Services 21.5 同梱 | LabVIEW 2021 SP1 Platform Readme |
| サービス無効化だけで 0x7B、MSI で個別削除可能 | NI Community |
| リネームで起動不能 | NI Community（FRC） |
| Start=4 と UpperFilters 参照削除の組み合わせ手順 | Microsoft KB「カーネルモードのフィルタドライバを一時的に無効化する方法」（別ドライバ） |
| `msiexec /x` は製品コードを受け付ける、`/l*v` でログ | Microsoft msiexec コマンドライン |
| Uninstall のサブキー名は製品コード | Microsoft Uninstall Registry Key |
| 削除時は `C:\Windows\Installer` のキャッシュ MSI を使う | Patch My PC、woshub |
| NI-PAL の脆弱性・ブロックリスト・11/10 | NI「Required NI-PAL Security Update」 |

### 10.2 未確認（再現環境で確認すべきもの）

- nipcibrd が UpperFilters／LowerFilters に登録されているか
- NI のドライバの Uninstall 表示名に「PCI Bridge」が含まれるか
- Windows 標準 `tar` で `.nipkg` を展開できるか
- 案1 が GPO／UEFI ロック環境で効くか
- PXI Platform Services 2024 以降の LabVIEW 2021 対応
- 「違う版の MSI では削除できない」ときのエラー文（一般的挙動として記載、出典未確認）

### 10.3 訂正履歴

| 当初の説明 | 訂正 |
| --- | --- |
| DISM でオフライン削除 | 停止の保証なし・切り戻し不可 → 不採用 |
| フィルタ登録の検索は `Control\Class` のみ | `Enum` 配下のデバイス単位フィルタもあるので ControlSet 全体を検索 |
| nipcibrd は 2 つの形で登録されている（断定） | 「可能性がある」に修正。手順 5 で確認 |
| Microsoft の起動トラブル記事に「フィルタ除去＋Start を 1→4」が一連の手順として載っている | 誤り。0x7B セクションの番号付き手順はフィルタ除去のみ。「Start 1→4」は同セクション内の別小見出し（Windows Update 後の問題）で **TrustedInstaller** の手順。ドライバ無効化は同セクション後半の指針として別に記載。組み合わせ手順の直接の根拠は Microsoft KB 816071 |
| 手順 6（フィルタ除去）の説明が粗かった | regedit 10 ステップ／コマンド版を具体例つきで書き直し |

---

## 11. 次のアクション

| # | やること | 誰に／どこで |
| --- | --- | --- |
| 1 | BSOD 画面の写真（停止コード名・原因ドライバ名） | 本番 PC |
| 2 | 回復キーの開示と作業承認（案1 の VBS 一時停止可否） | 情シス |
| 3 | この 1 年の VBS・Credential Guard・Win11 移行・BIOS 一括更新の有無 | 情シス |
| 4 | ローカル管理者権限の有無（MSI 削除に必要） | 情シス |
| 5 | 同機種・同 BIOS の予備機で再現環境 | 情シス |
| 6 | 再現環境で案1（＋方法A）→ 案2 を検証 | 予備機 |
| 7 | 本番 PC の復旧 | 本番 PC |
| 8 | NI-PAL の版を確認し 26.3.1 以前なら更新（**11/10 までに**、全 NI 導入 PC） | 全 NI 導入 PC |
| 9 | LabVIEW 導入手順に「PXI Platform Services を外す（または 2023 Q3 以降）」を反映 | 情シス・導入手順書 |
| 10 | 作業申請書に未反映事項を反映：MSI 削除（6.1）、NI-PAL、Microsoft KB 816071、リネーム・サービス単独無効化の失敗実例 | 申請書 |

---

## 12. 参考リンク一覧

### NI（公式）
- [Blue Screen of Death After Installing NI Software（NI KB）](https://digital.ni.com/public.nsf/allkb/4FDBD20184E5534686257496006C3EA5)
- [同 KB 日本語ページ](https://knowledge.ni.com/KnowledgeArticleDetails?id=kA03q0000019l42CAA&l=ja-JP)
- [PXI Platform Services 2023 Q3 Readme](https://www.ni.com/pdf/manuals/pxi-platformservices-2023-q3.html)
- [PXI Platform Services 21.5 Readme](https://ni.com/pdf/manuals/374995y.html)
- [PXI Platform Services Download](https://www.ni.com/en/support/downloads/drivers/download.pxi-platform-services.html)
- [PXI Platform Services Release Notes（全バージョン）](https://www.ni.com/en/support/documentation/release-notes/product.pxi-platform-services.html)
- [Required NI-PAL Security Update](https://www.ni.com/en/support/documentation/supplemental/26/required-ni-pal-security-update.html)
- [LabVIEW 2021 SP1 Platform Readme](https://www.ni.com/pdf/manuals/377933f.html)
- [LabVIEW 2021 SP1 Readme](https://www.ni.com/pdf/manuals/374715t.html)

### Microsoft（公式）
- [Bug Check 0x1EA: SECURE_PCI_CONFIG_SPACE_ACCESS_VIOLATION](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/bug-check-0x1ea--secure-pci-config-space-access-violation)
- [Advanced troubleshooting for Windows startup issues – 0x7B セクション](https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/windows-boot-issues-troubleshooting#error-code-inaccessible_boot_device-stop-0x7b)
- [How to temporarily deactivate the kernel-mode filter driver（KB 816071）](https://support.microsoft.com/en-us/help/816071/how-to-temporarily-deactivate-the-kernel-mode-filter-driver-in-windows)
- [Install a Filter Driver（UpperFilters／LowerFilters の仕組み）](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/installing-a-filter-driver)
- [msiexec Command-Line Options](https://learn.microsoft.com/en-us/windows/win32/msi/command-line-options)
- [Uninstall Registry Key](https://learn.microsoft.com/fi-fi/windows/win32/msi/uninstall-registry-key)
- [Driver Servicing Command-Line Options（DISM）](https://technet.microsoft.com/ja-jp/library/dd799258)
- [Add and Remove Drivers to an Offline Windows Image（DISM）](https://technet.microsoft.com/library/hh825070.aspx)
- [Recovering from HVCI Boot Loop（Microsoft Q&A）](https://learn.microsoft.com/en-my/answers/questions/5936780/recovering-from-hvci-boot-loop-after-enabling-memo)

### コミュニティ・技術解説
- [FYI ... PCI device space configuration accesses（OSR）](https://community.osr.com/t/fyi-pci-device-space-configuration-accesses/57997)
- [BSOD: nipcibrd.sys SECURE_PCI_CONFIG_SPACE_ACCESS_VIOLATION（NI Community）](https://forums.ni.com/t5/LabVIEW/BSOD-nipcibrd-sys-SECURE-PCI-CONFIG-SPACE-ACCESS-VIOLATION/td-p/4284462)
- [How to disable the nipcibrd.sys driver（NI Community）](https://forums.ni.com/t5/LabVIEW/How-to-disable-the-nipcibrd-sys-driver-to-prevent-hibernation/td-p/4296535)
- [Nipcibrd.sys / LabVIEW 2019（NI Community）](https://forums.ni.com/t5/LabVIEW/Nipcibrd-sys-Labview-2019/td-p/3985464)
- [Nipcibrd.sys / LabVIEW 2019 Page 2（NI Community）](https://forums.ni.com/t5/LabVIEW/Nipcibrd-sys-Labview-2019/td-p/3985464/page/2?profile.language=en)
- [NIPCIBRD.SYS causes Windows 10 BSOD（NI Community・FRC）](https://decibel.ni.com/t5/FIRST-Robotics-Competition/NIPCIBRD-SYS-causes-Windows-10-Blue-Screen-of-Death/m-p/4030287)
- [Why does Game Tools require PXI?（NI Community）](https://decibel.ni.com/t5/General/Why-does-Game-Tools-require-PXI/m-p/4346253)
- [Blue Screen in nipcibrd.sys on boot after installing game tools（GitHub）](https://github.com/wpilibsuite/2024Beta/issues/7)
- [Nipcibrd.sys Causing BSOD Best Solution（Chief Delphi）](https://www.chiefdelphi.com/t/nipcibrd-sys-causing-bsod-best-solution/467741)
- [Nipcibrd.sys: SYSTEM THREAD EXCEPTION NOT HANDLED（Chief Delphi）](https://www.chiefdelphi.com/t/nipcibrd-sys-system-thread-exception-not-handled/398103)
- [Dell - laptop repair almost none（Dell Community・Alienware）](https://www.dell.com/community/en/conversations/alienware/dell-laptop-repair-almost-none/68b1e163a86bb633c6a01a38)
- [New GSOD Implicates Intel Firmware（Ed Tittel）](https://edtittel.com/?p=6101)
- [Windows 10 cannot boot after registry file deleted（Tom's Hardware）](https://forums.tomshardware.com/threads/windows-10-cannot-boot-after-registry-file-deleted.3482426/)
- [FRST ログ（nipcibrd が R0）（BleepingComputer）](https://www.bleepingcomputer.com/forums/t/751305/proxy-script-address-http12700186-doesnt-get-away-at-all-need-help/)
- [Fix System Error 1612（Patch My PC：Windows Installer キャッシュ）](https://patchmypc.com/kb/system-error-1612-installation-source/)
- [How to Force Uninstall ANY Stubborn Program（woshub）](https://woshub.com/force-unistall-windows-app-that-wont-delete/)
