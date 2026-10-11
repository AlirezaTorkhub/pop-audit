import re


def normalize(text: str) -> str:
    return (text or "").strip().lower()


def classify_item(item: dict) -> str:
    name = normalize(item.get("name"))
    key = normalize(item.get("key_"))

    combined = f"{name} {key}"

    # =====================================================
    # EBand RX/TX Modulation
    # =====================================================

    if "actualrxacmtc" in combined:
        return "rx_modulation"

    if "actualtxacmtc" in combined:
        return "tx_modulation"

    # =====================================================
    # Huawei / generic modulation
    # =====================================================

    if "modulation_huawei" in combined:
        return "modulation"

    if "modulation huawei" in combined:
        return "modulation"

    # =====================================================
    # SNIR / SNR
    # =====================================================

    if "snir" in combined:
        return "snir"

    if re.search(r"\bsnr\b", combined):
        return "snr"

    # =====================================================
    # Packet Loss
    # =====================================================

    if "packetloss" in combined:
        return "packet_loss"

    if "packet loss" in combined:
        return "packet_loss"

    # =====================================================
    # Difference
    # =====================================================

    if "rx_tx_diff_slot2" in combined:
        return "difference"

    if "rx_tx_diff" in combined:
        return "difference"

    # =====================================================
    # RX / TX / Calloff
    # =====================================================

    if re.search(r"\brx_calloff\b", combined):
        return "rx_calloff"

    if re.search(r"\btx_calloff\b", combined):
        return "tx_calloff"

    if re.search(r"(^|[\s\[])rx\.", combined):
        return "rx_power"

    if re.search(r"(^|[\s\[])tx\.", combined):
        return "tx_power"

    # =====================================================
    # Capacity
    # =====================================================

    if "capacity" in combined:

        if "tx" in combined:
            return "tx_capacity"

        if "rx" in combined:
            return "rx_capacity"

        return "capacity"

    # =====================================================
    # Traffic
    # =====================================================

    if "traffic" in combined:

        if "incoming" in combined:
            return "rx_traffic"

        if "outgoing" in combined:
            return "tx_traffic"

    if "ifhcin" in combined:
        return "rx_traffic"

    if "ifhcout" in combined:
        return "tx_traffic"

    # =====================================================
    # Radio Error / Performance Counters
    # =====================================================

    if "bber" in combined:
        return "bber"

    if re.search(r"\bbbe\b", combined):
        return "bbe"

    if re.search(r"\besr\b", combined):
        return "esr"

    if re.search(r"\bes\b", combined):
        return "es"

    if re.search(r"\bsesr\b", combined):
        return "sesr"

    if re.search(r"\bses\b", combined):
        return "ses"

    if re.search(r"\buas\b", combined):
        return "uas"

    # =====================================================
    # Interface Status
    # =====================================================

    if "ifadminstatus" in combined:
        return "admin_status"

    if "ifoperstatus" in combined:
        return "oper_status"

    if "ifdescr" in combined:
        return "interface_description"

    if "ifalias" in combined:
        return "interface_alias"

    # =====================================================
    # Interface Errors
    # =====================================================

    if "ifinerrors" in combined:
        return "rx_errors"

    if "ifouterrors" in combined:
        return "tx_errors"

    if "ifindiscards" in combined:
        return "rx_discards"

    if "ifoutdiscards" in combined:
        return "tx_discards"

    # =====================================================
    # Other useful radio metrics
    # =====================================================

    if "respons" in combined:
        return "response_time"

    if "bandwith utilization incoming" in combined:
        return "rx_utilization"

    if "bandwith utilization outgoing" in combined:
        return "tx_utilization"

    # =====================================================
    # Unknown
    # =====================================================

    return "other"
