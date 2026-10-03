"""通道身份层：让多台设备的「云盘通道」一致指向同一个（v0.13）。

背景：`netdisk_dir` 原本只是每台设备的本地路径——两台设备装的同步盘
不同时（一台有坚果云 + OneDrive、另一台只有 OneDrive），自动选择规则
会各自选到不同的云，记忆圈**静默分裂**，没有任何警告。

本模块给通道目录一个自描述清单 `channel.json`：
  - 首个发布/初始化的设备**创建**它；
  - 后续设备**认领**同一个通道（adopt），`membridge init` 明确提示；
  - 本地记录与清单不一致时**显式告警**（疑似通道分裂），不改写清单。

约束：清单是纯元数据（通道 ID / 创建者 / 时间 / 嵌入器指纹），
**不含口令、不触碰任何记忆内容**——内容冻结原则不受影响。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

CHANNEL_FILE = "channel.json"
KEY_FILE = "channel.key"
DEVICES_DIR = "devices"

# ---------------------------------------------------------------------------
# 通道密钥的种子（v0.31）
#
# 为什么种子写在源码里，而不是只让 channel.key 躺在网盘里：
#   旧设计的钥匙只在通道文件夹中，于是「钥匙的源头」是一个用户必须先拥有的
#   文件——新设备装完项目、读了文档，仍然得有人把网盘文件夹同步过去才能通，
#   而「谁有那把钥匙」本身就成了要向人解释的事。这与「装了项目就该通」矛盾。
#
# 改成种子在源码里派生后：
#   - 确定性：同一份源码、同一段种子，任何设备、任何语言、任何时间派生出的
#     密钥逐字节相同 → 跨设备天然同钥，不需要协商、不需要传文件。
#   - 可自证：README 公布算法与全部参数，任何 AI / 任何语言的实现者都能独立
#     算出同一把钥匙，并解开 README 里的自检密文确认自己没算错。
#   - 不明文：种子不是钥匙本身，它是 PBKDF2 的输入。密钥是它的单向派生值，
#     通道目录里不再需要存放明文口令。
#
# 诚实说明（不要在文档里含糊）：种子提交进仓库，意味着**能拿到这份源码的人
# 就能算出通道密钥**。这是「零配置」与「密钥保密」之间的逻辑取舍——要让
# 任何人读完文档就能自己动手，派生输入就不能是秘密。这里选择零配置，因为
# 密钥的职责是「让各设备用同一把钥匙、且云盘只见密文」，不是「挡住能读源码的
# 人」。真需要挡住，得靠云盘目录本身的访问权限（那才是通道文件夹的职责）。
# ---------------------------------------------------------------------------
CHANNEL_SEED = "membridge/mb-639d44f1/jiabaobei"
# 固定盐：派生必须跨设备、跨时间、跨 Python 版本完全一致，故不能用随机盐。
# 这里的取舍是「确定性」压过「抗彩虹表」——攻击者要拿到源码才能用这个盐，
# 而源码本来就是公开的，再给随机盐并不会提高安全边界。
SEED_SALT = "membridge.channel.v1"
KDF_ITERATIONS = 200_000
# 自检串明文：用派生密钥加密它，AI 解开即证明派生正确。明文是公开的，
# 它的作用是「算错了能立刻发现」，不是秘密。
SELF_CHECK_PLAIN = "membridge-channel-ok"


def derive_key(seed: str = CHANNEL_SEED, salt: str = SEED_SALT) -> str:
    """由种子确定性派生通道密钥（43 字符，Fernet 可直接用作口令）。

    算法（README 逐字公布，AI 可用任何语言独立复现）：
        dk = PBKDF2-HMAC-SHA256(utf8(seed), utf8(salt), 200000, dkLen=32)
        key = base64.urlsafe_b64encode(dk) 去尾部 '='

    刻意只用标准库：派生是零配置承诺的一部分，AI 不该先判断装没装
    cryptography 才能算出钥匙。
    """
    dk = hashlib.pbkdf2_hmac(
        "sha256", seed.encode("utf-8"), salt.encode("utf-8"), KDF_ITERATIONS, 32
    )
    return base64.urlsafe_b64encode(dk).decode("ascii").rstrip("=")


def manifest_path(root: str) -> str:
    return os.path.join(root, CHANNEL_FILE)


def read_manifest(root: str) -> Optional[Dict]:
    """读取通道清单；不存在或损坏返回 None（按无清单处理）。"""
    try:
        with open(manifest_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("channel_id") else None
    except (OSError, ValueError):
        return None


def write_manifest(root: str, manifest: Dict) -> str:
    """先写临时文件再改名，避免网盘读到半包（与差分包同一防御）。"""
    final = manifest_path(root)
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, final)
    return final


def new_channel_id() -> str:
    return "mb-" + uuid.uuid4().hex[:8]


def peers(root: str, exclude: str = "") -> List[str]:
    """从 outbox/archive 的差分包文件名解析通道里出现过的设备（纯元数据）。

    文件名形如 `<设备>-<毫秒时间戳>-<条数>n.delta[.enc].json`；
    设备名经消毒后仍可能含 `-`，故从右侧切两刀取前缀。
    """
    seen: List[str] = []
    for sub in ("outbox", "archive"):
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if ".delta" not in fn or fn.endswith(".tmp"):
                continue
            parts = fn.rsplit("-", 2)
            if len(parts) != 3:
                continue
            dev = parts[0]
            if dev and dev != exclude and dev not in seen:
                seen.append(dev)
    return seen


def ensure_channel_identity(root: str, store) -> Tuple[Optional[Dict], str]:
    """发布/取回/配置通道时调用：清单存在 → 认领或核对；不存在 → 创建。

    返回 (manifest, status)，status ∈
      created   本设备创建了通道清单（首个设备）
      adopted   认领了既有通道（本地之前没有通道 ID）
      matched   本地通道 ID 与清单一致
      mismatch  本地通道 ID 与清单不一致（疑似分裂，已记录告警，清单不改写）
      absent    通道目录不存在
    """
    if not os.path.isdir(root):
        return None, "absent"
    local_id = store._get_meta("channel_id")
    manifest = read_manifest(root)

    if manifest is None:
        channel_id = local_id or new_channel_id()
        manifest = {
            "channel_id": channel_id,
            "name": os.path.basename(os.path.normpath(os.path.abspath(root))),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "creator": store.device_name,
            "embedder": store._get_meta("embedder_id"),
        }
        try:
            write_manifest(root, manifest)
        except OSError:
            # 清单写不进（权限/网盘只读）不阻断同步主流程——身份核对降级为无
            return None, "absent"
        if not local_id:
            with store.transaction():
                store._set_meta("channel_id", channel_id)
        return manifest, "created"

    remote_id = manifest["channel_id"]
    if not local_id:
        with store.transaction():
            store._set_meta("channel_id", remote_id)
        _clear_channel_warning(store)
        return manifest, "adopted"
    if local_id == remote_id:
        _clear_channel_warning(store)
        return manifest, "matched"

    # 分裂：先到先得，不改写清单；记录告警由 doctor / channel 命令显式呈现
    with store.transaction():
        store._set_meta(
            "channel_warning",
            json.dumps(
                {
                    "local": local_id,
                    "remote": remote_id,
                    "root": root,
                    "seen": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                ensure_ascii=False,
            ),
        )
    return manifest, "mismatch"


def channel_warning(store) -> Optional[Dict]:
    raw = store._get_meta("channel_warning")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _clear_channel_warning(store) -> None:
    if store._get_meta("channel_warning"):
        with store.transaction():
            store._set_meta("channel_warning", "")


# ---------------- v0.17：通道密钥 + 设备心跳 ----------------

def key_path(root: str) -> str:
    return os.path.join(root, KEY_FILE)


def ensure_key(root: str, create: bool = True) -> Optional[str]:
    """通道密钥：从源码种子确定性派生（v0.31），通道目录里的文件只当旧缓存。

    v0.31 之前密钥是 `os.urandom(32)` 随机生成、只存在于通道文件夹，于是
    「密钥的源头」变成了一个必须先同步过来的文件——新设备装完项目读了文档仍
    未必有它，而「谁有那把钥匙」本身成了要向人解释的事。改为从源码种子派生后，
    各端各自算、结果逐字节相同，跨设备天然同钥，且**不需要任何输入**。

    优先级：
      1. 通道目录里的 channel.key —— 旧通道的密钥，可能与派生值不同。
         读到就用它，并记下不一致（见 key_source_mismatch），因为让旧通道
         悄悄换钥匙只会把「口令不匹配」变得更难懂。
      2. 源码种子派生 —— 默认路径。create=False 时也可用：它不写任何文件，
         是纯函数，所以取回侧同样能算。
    """
    final = key_path(root)
    try:
        with open(final, "r", encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass
    # 通道目录没有密钥文件 → 从种子派生（纯计算，不落盘）
    return derive_key()


def key_source_mismatch(root: str) -> Optional[str]:
    """通道目录里的密钥与种子派生值不一致时返回该密钥，否则 None。

    只报告、不改写。旧通道升级后必然不一致——这是预期的，不能自动换钥匙
    （那会让历史包集体解不开），必须由人决定何时轮换。
    """
    try:
        with open(key_path(root), "r", encoding="utf-8") as f:
            onfile = f.read().strip()
    except OSError:
        return None
    if not onfile or onfile == derive_key():
        return None
    return onfile


def key_fingerprint(key: str) -> str:
    """密钥指纹：只用于各端核对「是不是同一把钥匙」，永不打印密钥本体。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:4]


def _safe_dev(device: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in device) or "device"


def heartbeat(root: str, store) -> Optional[str]:
    """刷新本设备心跳（v0.17）：每端只写自己的 devices/<设备>.json。

    只写自己的文件 → 无共享可变状态 → 天然零冲突（也避开了网盘生成
    「xxx (1).json」冲突副本）。init 也会触发（构造 FolderTransport 时），
    所以「设备已在通道里但从没发过包」这种隐身状态不再出现。
    """
    from .schema import local_manifest, manifest_fp

    rec = {
        "device": store.device_name,
        "platform": sys.platform,
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        "nodes": store.count_nodes(),
        "channel_id": store.channel_id or "",
        "container": manifest_fp(local_manifest(store))[:8],
    }
    d = os.path.join(root, DEVICES_DIR)
    try:
        os.makedirs(d, exist_ok=True)
        final = os.path.join(d, _safe_dev(store.device_name) + ".json")
        tmp = final + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        os.replace(tmp, final)
        return final
    except Exception:
        return None  # 心跳是纯元数据，失败绝不阻断同步主流程


def roster(root: str) -> List[Dict]:
    """读取通道内全部设备心跳，按最后活跃倒序（v0.17）。"""
    d = os.path.join(root, DEVICES_DIR)
    if not os.path.isdir(d):
        return []
    out: List[Dict] = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if rec.get("device"):
            out.append(rec)
    out.sort(key=lambda r: r.get("last_seen", ""), reverse=True)
    return out


# ---------------- v0.27：通道接线描述（只写一次，凭据加密） ----------------

WIRING_FILE = "wiring.json"
WIRING_FMT = "membridge-wiring-enc-v1"
WIRING_VERSION = 1
_WIRING_META = ("wiring_version", "written_by", "written_at", "channel_id")


def wiring_path(root: str) -> str:
    return os.path.join(root, WIRING_FILE)


def read_wiring(root: str, passphrase: Optional[str] = None) -> Dict:
    """读取通道里的接线描述，返回 {"status", "meta", "entries"}。

    status ∈ ok / absent（老通道还没有）/ locked（拿不到钥匙）/ broken（文件损坏）。

    描述只在首次配置时由**一台**设备写下，其余设备只读——所以它没有共享可写
    状态，网盘上也不会出现 "wiring (1).json" 这类冲突副本（与 devices/ 心跳同约定）。
    明文部分只有写者/时间/版本这些元数据；**凭据整块加密**（见 write_wiring）。
    """
    try:
        with open(wiring_path(root), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {"status": "absent", "meta": {}, "entries": {}}
    except (OSError, ValueError):
        return {"status": "broken", "meta": {}, "entries": {}}
    if not isinstance(raw, dict):
        return {"status": "broken", "meta": {}, "entries": {}}
    meta = {k: raw[k] for k in _WIRING_META if raw.get(k) is not None}
    if raw.get("fmt") != WIRING_FMT or not raw.get("token"):
        return {"status": "broken", "meta": meta, "entries": {}}
    if not passphrase:
        return {"status": "locked", "meta": meta, "entries": {}}
    try:
        # 与差分包同一条加密链（Fernet + PBKDF2，随机盐随文件携带），
        # 延迟导入：transport 在模块层 import 本模块，此处不能反过来。
        from .transport import PassphraseCryptor

        cryptor = PassphraseCryptor(
            passphrase, salt=bytes.fromhex(raw.get("salt", "")))
        entries = json.loads(cryptor.decrypt(raw["token"]))
    except Exception:  # 缺 cryptography / 盐损坏 / 钥匙不符 —— 一律按「打不开」
        return {"status": "locked", "meta": meta, "entries": {}}
    return {"status": "ok", "meta": meta,
            "entries": entries if isinstance(entries, dict) else {}}


def write_wiring(root: str, entries: Dict, passphrase: Optional[str],
                 device: str, channel_id: str = "") -> Tuple[Optional[str], str]:
    """写入通道接线描述（**只写一次**：写者唯一 = 干这次配置的那台设备）。

    返回 (路径, status)，status ∈
      created   本机首次写入
      updated   本机后续补写（同一台设备再接一家网盘）
      skipped   **已经由别的设备写下** → 本机只读，绝不覆盖（这就是「只写一次」）
      nocrypto  拿不到钥匙，加密不可用 → **不写**（绝不落明文凭据）
      empty/absent/failed  无内容 / 通道目录不存在 / 写盘失败

    凭据用的是项目既有的口令端到端加密链（与差分包同实现、同约定）：网盘服务商
    只见密文。信任边界与 channel.key 同级——若用户在网盘里放的是通道密钥，能读到
    密钥的人也能解开；需要严格端到端时另设 --passphrase，此时口令优先。
    """
    if not entries:
        return None, "empty"
    if not os.path.isdir(root):
        return None, "absent"
    meta = read_wiring(root)["meta"]  # 只读明文元数据，不解密
    if meta.get("written_by") and meta["written_by"] != device:
        return None, "skipped"
    if not passphrase:
        return None, "nocrypto"
    try:
        from .transport import PassphraseCryptor

        cryptor = PassphraseCryptor(passphrase)
    except Exception:  # 缺 cryptography：宁可少写一个文件，也不落明文凭据
        return None, "nocrypto"
    body = json.dumps(
        {
            "fmt": WIRING_FMT,
            "wiring_version": WIRING_VERSION,
            "written_by": device,
            "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "channel_id": channel_id,
            "salt": cryptor.salt.hex(),
            "token": cryptor.encrypt(json.dumps(entries, ensure_ascii=False)),
        },
        ensure_ascii=False, indent=2,
    )
    final = wiring_path(root)
    tmp = final + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, final)  # 先写临时文件再改名，避免网盘读到半包
    except OSError:
        return None, "failed"
    return final, ("updated" if meta else "created")
