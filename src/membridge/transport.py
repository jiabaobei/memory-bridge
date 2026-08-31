"""传输通道层：DSS 差分包的跨设备搬运（论文 §3.4 同步通道 + §4.5 T4 云归档）。

设计原则：传输通道可插拔。v0 实现 FolderTransport（文件夹/网盘中转）——
任何"会在设备间自动同步的文件夹"都可以作为通道：百度网盘同步盘、坚果云、
OneDrive、iCloud、U 盘、局域网共享目录。零服务器、零配置，国内环境最务实。

工作方式（共享同一个同步文件夹）：
  发送端 publish → 把"尚未发布过"的差分包写入通道的 outbox/
  接收端 fetch   → 应用 outbox/ 中来自其他设备的差分包，并把包移入 archive/（T4 归档）

隐私约定（PAMS 的传输落位）：写入网盘的差分包默认必须端到端加密
（Fernet 口令加密，需 `pip install "membridge[netdisk]"`）——网盘服务商
只见密文；确要明文时必须显式 plaintext=True，防止无意泄漏。

后续通道：局域网直连、自托管实时中继（docs/roadmap.md Phase 2）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import channel
from .dss import Delta, EPSILON, apply_delta, delta_unsent, fingerprint
from .node import MemoryNode
from .privacy import preload_allowed
from .store import MemoryStore

logger = logging.getLogger(__name__)

OUTBOX = "outbox"
ARCHIVE = "archive"  # 论文 T4 云归档的工程落位
ENVELOPE_FMT = "membridge-delta-enc-v1"


class PassphraseCryptor:
    """口令端到端加密（Fernet + PBKDF2-HMAC-SHA256，盐随机且随包携带）。"""

    def __init__(self, passphrase: str, salt: Optional[bytes] = None) -> None:
        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        except ImportError as exc:
            raise ImportError(
                '需要加密依赖：pip install "membridge[netdisk]"'
            ) from exc
        self.salt = salt if salt is not None else secrets.token_bytes(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=self.salt, iterations=200_000
        )
        key = base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")


class FolderTransport:
    """文件夹/网盘中转通道：outbox 发包，fetch 收包，archive 归档（T4）。"""

    def __init__(self, root: str, store: MemoryStore) -> None:
        self.root = root
        self.store = store
        self.channel_status = ""  # v0.13 通道身份核对结果（created/adopted/matched/mismatch）
        os.makedirs(os.path.join(root, OUTBOX), exist_ok=True)
        os.makedirs(os.path.join(root, ARCHIVE), exist_ok=True)

    # ---------- 发送 ----------

    def publish(
        self,
        passphrase: Optional[str] = None,
        plaintext: bool = False,
        allowed: Optional[Callable[[MemoryNode], bool]] = None,
        eps: float = EPSILON,
        embedder_info: Optional[Dict] = None,
        delta: Optional[Delta] = None,
        force: bool = False,
    ) -> Optional[str]:
        """把本设备"尚未发布过"的差分包写入通道。无新内容时返回 None。

        默认强制端到端加密；plaintext=True 时需调用方显式确认放弃加密。
        embedder_info 为嵌入器自描述指纹，接收端据此做一致性握手。
        delta 可传入预构差分包（自动同步引擎按重要度筛选后使用）；
        未传入时按"尚未发布过"自动计算。

        force=True：忽略本地 published_fps 记录，重发全量。
        用于云盘侧差分包丢失/被清理后重建通道——否则本地仍认为"已发布"，
        记忆会被永久锁死、再也推不出去。
        """
        if cryptor_needed(passphrase, plaintext):
            raise ValueError(
                "出于隐私安全，写入网盘默认必须加密：请提供 passphrase，"
                "或显式确认 plaintext=True（明文，不推荐）"
            )
        if delta is None:
            delta = delta_unsent(
                self.store,
                set() if force else self._published_fps(),
                allowed=allowed if allowed is not None else (lambda n: preload_allowed(n)),
                eps=eps,
                embedder_info=embedder_info,
            )
        if not delta.nodes and not delta.edges:
            return None

        if embedder_info and not self.store._get_meta("embedder_id"):
            self.store._set_meta(
                "embedder_id", json.dumps(embedder_info, ensure_ascii=False)
            )

        payload = delta.to_json()
        if passphrase:
            cryptor = PassphraseCryptor(passphrase)
            body = json.dumps(
                {
                    "fmt": ENVELOPE_FMT,
                    "salt": cryptor.salt.hex(),
                    "token": cryptor.encrypt(payload),
                },
                ensure_ascii=False,
            )
            suffix = ".delta.enc.json"
        else:
            body = payload
            suffix = ".delta.json"

        name = "{}-{}-{}n{}".format(
            _safe_device(delta.from_device), int(time.time() * 1000),
            len(delta.nodes), suffix
        )
        outbox_dir = os.path.realpath(os.path.join(self.root, OUTBOX))
        final_path = os.path.join(outbox_dir, name)
        # 允许目录包含性校验：设备名可能含路径成分，落点必须在 outbox 之内
        if os.path.commonpath([outbox_dir, os.path.realpath(final_path)]) != outbox_dir:
            raise ValueError(f"非法通道文件名：{name}")
        tmp_path = final_path + ".tmp"
        Path(tmp_path).write_text(body, encoding="utf-8")
        os.replace(tmp_path, final_path)  # 先写临时文件再改名，避免网盘读到半包

        self._remember_published(n for n in delta.nodes)
        # 通道身份（v0.13）：首次发布即在通道里落「身份证」，后续设备认领
        _, self.channel_status = channel.ensure_channel_identity(self.root, self.store)
        return final_path

    # ---------- 接收 ----------

    def fetch(
        self, passphrase: Optional[str] = None
    ) -> Dict[str, List]:
        """应用通道中来自其他设备的差分包，outbox 的包成功后移入 archive（T4）。

        同时扫描 outbox 与 archive：三台及以上设备时，先取的设备会把包移入 archive，
        若只读 outbox，后续设备将永远取不到该包。指纹去重保证重复扫描不会重复入库。

        返回 {"applied": [(文件名, 来源设备, 结果)], "skipped": [(文件名, 原因)],
        "errors": [(文件名, 原因)]}。
        - skipped：**数据问题**（包损坏 / 口令错误 / 非差分包 / 重复包）——该包
          内容有问题，重试无意义，跳过不影响其他包。
        - errors：**环境问题**（磁盘满 / 权限 / I/O 故障）——包本身完好且保留
          在原位，下次 fetch 自动重试；同时记 warning 日志。

        单个包失败只跳过该包，不影响其他包。
        """
        applied: List = []
        skipped: List = []
        errors: List = []
        # 通道身份（v0.13）：认领既有通道清单；不一致记告警，由 doctor / channel 呈现
        _, self.channel_status = channel.ensure_channel_identity(self.root, self.store)
        my_name = self.store.device_name
        outbox = os.path.join(self.root, OUTBOX)
        store_fps = {fingerprint(n.content) for n in self.store.all_nodes()}

        # (目录名, 是否允许归档) —— outbox 的包取完移入 archive，archive 的原地保留
        scan_dirs = [
            (outbox, True),
            (os.path.join(self.root, ARCHIVE), False),
        ]

        # 先快照待处理清单：处理过程中 outbox 的包会被移入 archive，
        # 若边扫边处理，同一个包会在本次 fetch 内被处理两次（去重后无害但冗余）
        todo: List = []
        for directory, allow_archive in scan_dirs:
            if not os.path.isdir(directory):
                continue
            for fn in sorted(os.listdir(directory)):
                # 半可信同步目录：文件名必须为纯净 basename 且仅接受差分包后缀
                safe = os.path.basename(fn.replace("\\", "/"))
                if safe != fn or safe in (".", "..") or safe.endswith(".tmp"):
                    continue
                if not (safe.endswith(".json") or safe.endswith(".enc.json")):
                    continue
                todo.append((directory, fn, allow_archive))

        for directory, fn, allow_archive in todo:
            path = os.path.join(directory, fn)
            if not os.path.isfile(path):
                continue  # 已被上一次 fetch 归档
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read()
                if fn.endswith(".enc.json"):
                    env = json.loads(raw)
                    if env.get("fmt") != ENVELOPE_FMT:
                        raise ValueError("未知信封格式")
                    if not passphrase:
                        raise ValueError(
                            "已加密的差分包需要口令：请加 --passphrase，"
                            "或设置环境变量 MEMBRIDGE_PASSPHRASE"
                        )
                    cryptor = PassphraseCryptor(
                        passphrase, salt=bytes.fromhex(env["salt"])
                    )
                    try:
                        payload = cryptor.decrypt(env["token"])
                    except Exception:
                        # Fernet 抛 InvalidToken，对用户毫无信息量；换成可操作的提示
                        raise ValueError(
                            f"口令不匹配，无法解密 {fn}：发布端与接收端必须使用同一口令，"
                            "可用 membridge show-passphrase 查看本机口令"
                        ) from None
                else:
                    payload = raw
                delta = Delta.from_json(payload)
            except OSError as exc:
                # 环境问题（磁盘满/权限/I/O）：包保留原位，下次 fetch 重试
                logger.warning("差分包 %s 读取失败（环境错误，将重试）: %s", fn, exc)
                errors.append((fn, f"环境错误（包已保留，下次 fetch 自动重试）：{exc}"))
                continue
            except Exception as exc:  # 数据问题：包损坏 / 口令错误 / 非差分包
                skipped.append((fn, str(exc)))
                continue

            if delta.from_device == my_name:
                skipped.append((fn, "自己发布的包，等待其他设备取走"))
                continue

            # 已在库中的重复包（archive 重放场景）直接跳过，不重复应用
            if delta.nodes and all(
                fingerprint(d.get("content", "")) in store_fps for d in delta.nodes
            ):
                skipped.append((fn, "重复包：所有节点均已在库"))
                continue

            result = apply_delta(self.store, delta)
            applied.append((fn, delta.from_device, result))
            for d in delta.nodes:
                store_fps.add(fingerprint(d["content"]))
            # 只有 outbox 的包才需要归档；archive 里的原地保留，供后续设备补取
            if allow_archive:
                try:
                    os.replace(path, os.path.join(self.root, ARCHIVE, fn))
                except OSError:
                    pass  # 归档失败不影响数据正确性，下次 fetch 会幂等重放
        return {"applied": applied, "skipped": skipped, "errors": errors}

    # ---------- 已发布指纹的持久化 ----------

    def _published_fps(self) -> set:
        raw = self.store._get_meta("published_fps")
        return set(json.loads(raw)) if raw else set()

    def _remember_published(self, nodes) -> None:
        fps = self._published_fps()
        fps.update(fingerprint(n["content"]) if isinstance(n, dict) else fingerprint(n.content) for n in nodes)
        with self.store.transaction():
            self.store._set_meta("published_fps", json.dumps(sorted(fps)))


def _safe_device(device: str) -> str:
    """设备名出现在通道文件名里：消毒路径成分（设备名由用户自定义，属半可信输入）。"""
    return re.sub(r'[\\/:*?"<>|]+', "_", device).strip(".") or "unknown"


def cryptor_needed(passphrase: Optional[str], plaintext: bool) -> bool:
    """是否处于"既不给口令又不显式明文"的未决状态。"""
    return passphrase is None and not plaintext
