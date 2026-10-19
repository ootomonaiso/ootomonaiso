"""
SPIKE Prime × Raspberry Pi テンプレート: Pi 側コマンド送信
=================================================

※ このファイルは SPIKE Prime ハブ上ではなく、Raspberry Pi（または
   その他の Linux/Windows/Mac PC）上で実行する「ホスト側」のスクリプトです。
   pybricks ライブラリではなく、汎用 BLE ライブラリ bleak を使用します。

【役割】
  ハブ側で 01_hub_command_listener.py を実行しておくと、このスクリプトから
  "RUN" / "PAUSE" / "STOP" コマンドを BLE 経由で送信し、モーターの動作を
  ハブ側プログラムを止めずに随時制御できます。
  画像認識などの結果に応じて send_command() を呼ぶ想定です。

【事前準備】
  pip install bleak

【接続の仕組み】
  Pybricks ファームウェアが提供する「Pybricks Command/Event Characteristic」
  （UUID: c5f50002-8280-46da-89f4-6d8051e4aeef）を使い、
  0x06（write stdin コマンド）+ 文字列データ を書き込むことで、
  ハブ側の stdin にテキストを送り込みます。
  参考: https://pybricks.com/projects/tutorials/wireless/hub-to-device/pc-communication/

【注意】
  - ハブに Pybricks Code など他のアプリが接続されていると、このスクリプトは
    ハブを見つけられません。他のアプリは切断しておいてください。
  - HUB_NAME は自分のハブの Bluetooth 名に合わせて変更してください
    （Pybricks Code の設定画面で確認・変更できます）。
  - 接続後、ハブ側のボタンでプログラムを起動する必要があります
    （プログラムの自動起動まで自動化したい場合は pybricksdev ライブラリを検討してください）。

====================================================================
【トラブルシューティング全部メモ】
"スキャンでは見つかるのに connect がタイムアウトする／繋がらない" 症状について
考えられる原因と確認コマンドを全部ここに書いておく。上から疑わしい順。
====================================================================

□ 1. BlueZ の experimental 機能が無効（最有力候補）
    Pybricks の BLE 通信（notify を使う stdin/stdout 中継）は BlueZ の
    experimental 機能が無効だと dbus 層でサイレントに固まりタイムアウトする。
    このスクリプト実行時に自動で print_bluez_debug_info() が表示する
    「bluetoothd 起動コマンド」に --experimental (または -E) が無ければこれが原因。
    確認:
      systemctl status bluetooth
      ps -C bluetoothd -o args=
    対処:
      sudo systemctl edit bluetooth
      → 以下を書いて保存
        [Service]
        ExecStart=
        ExecStart=/usr/lib/bluetooth/bluetoothd --experimental
      （bluetoothd の実パスが違う環境もある。`which bluetoothd` や
        `systemctl cat bluetooth` の ExecStart 行で元のパスを確認してから書く）
      sudo systemctl daemon-reload
      sudo systemctl restart bluetooth

□ 2. ハブに他のアプリ（Pybricks Code / LEGO アプリ / 別の bleak プロセス）が
    まだ接続中になっている
    BLE は基本1対1接続。スマホ・PC の Pybricks Code アプリ、ブラウザタブ、
    前回クラッシュして残ったこのスクリプトのプロセスなどが掴んだままだと
    新規接続はタイムアウトする。
    確認:
      ps aux | grep python   （古いプロセスが残ってないか）
      bluetoothctl info <MAC>   （Connected: yes になっていないか）
    対処:
      他アプリを全部切る / 古い python プロセスを kill
      bluetoothctl disconnect <MAC>

□ 3. 権限不足
    rootなしで実行すると GATT 接続まわりで Permission denied 系になることがある。
    対処:
      sudo python3 02_raspi_ble_controller.py
      または
      sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))

□ 4. ペアリング情報が壊れている / 古いボンディングが残っている
    一度ペアリングに失敗した履歴が BlueZ 側に残っていると再接続がタイムアウトする
    ことがある。
    確認・対処:
      bluetoothctl
        remove <MAC>
        scan on
        （ハブが出てくるのを確認したら scan off）
      その後もう一度このスクリプトを実行

□ 5. アダプタ自体がおかしい（Pi 内蔵 BT チップの既知の不安定さ）
    Raspberry Pi 内蔵 Bluetooth (BCM/CYW43455 系) は BLE の同時接続や
    connection interval 周りで不安定になることがあると報告されている。
    対処:
      sudo hciconfig hci0 down && sudo hciconfig hci0 up
      （それでも駄目なら）本体再起動: sudo reboot
      （さらに駄目なら）$5-10 の USB BLE ドングルに挿し替えて
        hci1 を使うようにすると解決することがある
        （bleak 側は特定アダプタを指定できる: BleakScanner(adapter="hci1")）

□ 6. dmesg / journalctl にエラーが出ていないか確認
      dmesg | grep -i blue
      sudo journalctl -u bluetooth -n 100 --no-pager
    "le-connection-abort-by-local" や "Connection timeout" などの行があれば
    それがヒント。

□ 7. ハブ側の電池残量 / スリープ
    PrimeHub はバッテリー低下や一定時間の未操作でスリープ・電源断する。
    ハブの画面・LED が点いているか確認し、点いていなければボタンを押して起こす。

□ 8. ハブ側のファームウェアが古い
    古い Pybricks ファームウェアだと Command/Event Characteristic の挙動が
    違う・無い場合がある。Pybricks Code でファームウェアを最新に更新し直す。

□ 9. 接続は成立しているが start_notify 以降で固まっている可能性
    「connect 自体は通っているが、その後の notify 購読で止まっている」
    パターンもありうる。ログで「接続試行」の後に何も出ずに固まる場合は
    client.connect() 自体ではなく start_notify() を疑う。
    （このスクリプトは connect と start_notify を別ブロックにしてあるので
      どちらで止まっているかログ上で区別できる）

□ 10. 複数の Bluetooth アダプタ/他プロセスが同時にスキャンしている
    別ターミナルで bluetoothctl の scan on を立てたままにしていると
    アダプタの奪い合いで bleak 側の discover/connect が不安定になることがある。
    bluetoothctl 側は scan off してから python スクリプトを実行する。

上から順に 1 → 2 → 5 → 4 の順で疑うのが経験上効率が良い。
1 (experimental) で直るケースが最も多い。
"""

import asyncio
import logging
import subprocess
import traceback
from contextlib import suppress
from bleak import BleakScanner, BleakClient

PYBRICKS_COMMAND_EVENT_CHAR_UUID = "c5f50002-8280-46da-89f4-6d8051e4aeef"

# 自分のハブの Bluetooth 名に合わせて変更する
HUB_NAME = "Pybricks Hub"

# --- デバッグ用: bleak / BlueZ(dbus) 層の詳細ログを標準出力に出す ---
# 「bluetoothctl では見える・connect できるのに bleak だとタイムアウトする」場合、
# ここで dbus のエラー内容（timeout の実際の理由）が見える
logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
logging.getLogger("bleak").setLevel(logging.DEBUG)


def print_bluez_debug_info():
    """BlueZ の experimental フラグが有効かどうかを確認する

    Pybricks ハブの BLE notify（stdin/stdout 通信）は、BlueZ の
    experimental 機能が有効でないと接続後に応答が来ず固まる/タイムアウトする
    ことが多い。bluetoothd の起動オプションに --experimental が付いているか確認する。
    """
    print("--- BlueZ デバッグ情報 ---")
    try:
        out = subprocess.run(
            ["bluetoothctl", "--version"], capture_output=True, text=True, timeout=5
        )
        print(f"  bluetoothctl version: {out.stdout.strip() or out.stderr.strip()}")
    except Exception as e:
        print(f"  bluetoothctl --version 取得失敗: {e}")

    try:
        out = subprocess.run(
            ["ps", "-C", "bluetoothd", "-o", "args="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        args = out.stdout.strip()
        if args:
            print(f"  bluetoothd 起動コマンド: {args}")
            if "--experimental" not in args and "-E" not in args.split():
                print(
                    "  ⚠ bluetoothd に --experimental が付いていません。\n"
                    "    Pybricks の BLE notify が機能しない可能性が高いです。\n"
                    "    sudo systemctl edit bluetooth で \n"
                    "      [Service]\n"
                    "      ExecStart=\n"
                    "      ExecStart=/usr/lib/bluetooth/bluetoothd --experimental\n"
                    "    を設定し、sudo systemctl daemon-reload && sudo systemctl restart bluetooth"
                    " を実行してください。"
                )
        else:
            print("  bluetoothd プロセスが見つかりませんでした（ps 非対応環境？）")
    except Exception as e:
        print(f"  bluetoothd プロセス確認失敗: {e}")
    print("--------------------------")


async def main():
    main_task = asyncio.current_task()
    ready_event = asyncio.Event()

    def handle_disconnect(_):
        print("ハブが切断されました")
        if not main_task.done():
            main_task.cancel()

    def handle_rx(_, data: bytearray):
        # data[0] == 0x01 は「write stdout」イベント（ハブからの出力）
        if data[0] == 0x01:
            payload = data[1:]
            if payload == b"rdy":
                ready_event.set()
            else:
                print("ハブからの応答:", payload)

    print_bluez_debug_info()

    # --- 1. ハブをスキャンして発見 ---
    print("ハブをスキャン中...")

    # デバッグ: 見つかった全デバイスを名前付きで列挙する
    # （bluetoothctl では見えるのに find_device_by_name で見つからない場合、
    #   ここで一覧に出るかどうかで bleak 側の問題かを切り分けられる）
    found = await BleakScanner.discover(timeout=15.0, return_adv=True)
    print(f"--- スキャン結果 {len(found)} 件 ---")
    device = None
    for address, (dev, adv) in found.items():
        name = dev.name or adv.local_name
        print(f"  {address}  name={name!r}  rssi={adv.rssi}")
        if name == HUB_NAME:
            device = dev

    if device is None:
        print(f"ハブが見つかりませんでした（名前: {HUB_NAME}）")
        return

    # --- 2. 接続して通知を購読 ---
    # Raspberry Pi (BlueZ) は1回目の接続要求が
    # "org.bluez.Error.Failed" 等で失敗しやすいため、数回リトライする
    client = BleakClient(device, disconnected_callback=handle_disconnect)
    last_error = None
    for attempt in range(1, 4):
        try:
            print(f"接続試行 {attempt}/3 ...")
            await client.connect(timeout=15.0)
            last_error = None
            break
        except asyncio.TimeoutError:
            last_error = "timeout"
            print(
                "接続失敗: タイムアウト（connect 要求に対して応答が返っていない）\n"
                "  → bluetoothctl では見える・connect できるのに bleak だと\n"
                "    タイムアウトする場合、BlueZ の experimental 機能が無効で\n"
                "    GATT 周りのやり取りが dbus 層で止まっているケースが多いです。\n"
                "    上の『BlueZ デバッグ情報』で --experimental が付いているか確認してください。"
            )
            with suppress(Exception):
                await client.disconnect()
            await asyncio.sleep(2)
        except Exception as e:
            last_error = e
            print(f"接続失敗: {type(e).__name__}: {e}")
            traceback.print_exc()
            with suppress(Exception):
                await client.disconnect()
            await asyncio.sleep(2)

    if last_error is not None:
        print("3回接続を試みましたが失敗しました。")
        return

    try:
        await client.start_notify(PYBRICKS_COMMAND_EVENT_CHAR_UUID, handle_rx)

        async def send_command(text: str):
            """ハブの stdin にコマンド文字列（改行区切り）を送信する"""
            await client.write_gatt_char(
                PYBRICKS_COMMAND_EVENT_CHAR_UUID,
                b"\x06" + text.encode() + b"\n",  # 0x06 = write stdin コマンド
                response=True,
            )

        print("ハブ側のボタンでプログラムを起動してください")
        await asyncio.sleep(3)  # ハブ側の起動待ち（環境に応じて調整）

        # --- 3. 動作確認: 一時停止 → 2秒待機 → 再開 ---
        print("PAUSE を送信")
        await send_command("PAUSE")
        await asyncio.sleep(2)

        print("RUN を送信")
        await send_command("RUN")

        # --- 実際の運用イメージ ---
        # 画像認識ループの中で、判定結果に応じて以下のように呼び出す:
        #
        #   if 障害物を検出した:
        #       await send_command("PAUSE")
        #   else:
        #       await send_command("RUN")

        print("動作確認が完了しました。Ctrl+C で終了します。")
        await asyncio.sleep(3600)  # 継続的に接続を維持する場合はここでループ待機
    finally:
        with suppress(Exception):
            await client.disconnect()


if __name__ == "__main__":
    with suppress(asyncio.CancelledError, KeyboardInterrupt):
        asyncio.run(main())
