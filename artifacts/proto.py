import os
import sys

try:
    from scapy.all import IP, UDP, PcapReader
except ImportError:
    print("Ошибка: не установлена библиотека scapy! Выполните: pip install scapy")
    sys.exit(1)

PCAP_FILE = "roblox_capture.pcapng"
OUTPUT_TXT = "roblox_handshake.txt"

UDMUX_PREFIX = b"\x01\x00\x00\x1f\x01\x11"
RAKNET_MAGIC = b"\x00\xff\xff\x00\xfe\xfe\xfe\xfe\xfd\xfd\xfd\xfd\x12\x34\x56\x78"


def extract_roblox_handshake():
    if not os.path.exists(PCAP_FILE):
        print(f"Ошибка: Файл '{PCAP_FILE}' не найден!")
        return

    print(f"Сканирование '{PCAP_FILE}' на наличие трафика Roblox...")

    output_lines = []
    output_lines.append(
        "======================================================================\n"
    )
    output_lines.append(
        "             ТОЧНЫЕ КАДРЫ РУКОПОЖАТИЯ ROBOLOX UDMUX / RAKNET          \n"
    )
    output_lines.append(
        "======================================================================\n\n"
    )

    total_pkts = 0
    matched_pkts = 0

    reader = PcapReader(PCAP_FILE)
    roblox_sockets = set()

    for pkt in reader:
        total_pkts += 1

        if total_pkts % 25000 == 0:
            print(f"Просканировано кадров: {total_pkts}...", end="\r")

        if not pkt.haslayer(UDP) or not pkt.haslayer(IP):
            continue

        ip_layer = pkt[IP]
        udp_layer = pkt[UDP]
        payload = bytes(udp_layer.payload)

        if len(payload) == 0:
            continue

        src_ep = (ip_layer.src, udp_layer.sport)
        dst_ep = (ip_layer.dst, udp_layer.dport)

        is_udmux = payload.startswith(UDMUX_PREFIX)
        has_magic = RAKNET_MAGIC in payload

        # Запоминаем сокеты при обнаружении UDMUX или RakNet Magic
        if is_udmux or has_magic:
            roblox_sockets.add(src_ep)
            roblox_sockets.add(dst_ep)

        # Выгружаем ТОЛЬКО пакеты Roblox
        if (
            is_udmux
            or has_magic
            or (src_ep in roblox_sockets or dst_ep in roblox_sockets)
        ):
            matched_pkts += 1

            src = f"{ip_layer.src}:{udp_layer.sport}"
            dst = f"{ip_layer.dst}:{udp_layer.dport}"

            block = []
            block.append(
                f"Frame #{total_pkts} | Time={float(pkt.time):.6f}s | {src} -> {dst} | Len={len(payload)}\n"
            )

            if is_udmux:
                ud32 = payload[:32]
                block.append("  [UDMUX HEADER (32B)]:\n")
                block.append(f"    Prefix (6B) : {ud32[:6].hex()}\n")
                block.append(f"    Token (16B)  : {ud32[6:22].hex()}\n")
                block.append(f"    IP Raw (5B) : {ud32[22:27].hex()}\n")
                block.append(
                    f"    Port (2B)   : {ud32[27:29].hex()} ({int.from_bytes(ud32[27:29], 'big')})\n"
                )
                block.append(f"    Pepper (3B) : {ud32[29:32].hex()}\n")

                rk = payload[32:]
                block.append(
                    f"  [RAKNET PAYLOAD] : ID=0x{rk[0]:02x} | Len={len(rk)}\n"
                    if len(rk) > 0
                    else "  [RAKNET PAYLOAD] : EMPTY\n"
                )
                block.append(f"  [FULL HEX]       : {payload.hex()}\n\n")
            else:
                block.append(
                    f"  [RAW UDP]        : ID=0x{payload[0]:02x} | Magic={'YES' if has_magic else 'NO'}\n"
                )
                block.append(f"  [FULL HEX]       : {payload.hex()}\n\n")

            output_lines.append("".join(block))

            if matched_pkts >= 80:  # Первые 80 кадра рукопожатия Roblox
                output_lines.append(
                    "=== НАЙДЕНЫ КЛЮЧЕВЫЕ КАДРЫ РУКОПОЖАТИЯ ROBOLOX ===\n"
                )
                break

    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.writelines(output_lines)

    print(
        f"\nГотово! Найдено кадров Roblox: {matched_pkts}. Результат в '{OUTPUT_TXT}'."
    )


if __name__ == "__main__":
    extract_roblox_handshake()