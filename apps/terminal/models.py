"""KFlow 桌面终端的设备绑定与访问令牌。

设计约束（见 docs/terminal.md）：

* 一块终端只绑定一个 KFlow 账号，数据只从该账号读出，不跨用户。
* 令牌只以 sha256 摘要落库，明文仅在配对完成后的第一次轮询下发一次。
* 终端只读：所有接口都不写积分、不消费权益、不改变社区内容。
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

STATUS_CHOICES = (
    (STATUS_PENDING, "待绑定"),
    (STATUS_ACTIVE, "已绑定"),
    (STATUS_REVOKED, "已吊销"),
)


class TerminalDevice(models.Model):
    """一块物理终端。``device_id`` 由固件生成（芯片 MAC 派生），全局唯一。"""

    id = models.AutoField(primary_key=True)
    device_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=64, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="terminal_devices",
    )

    token_hash = models.CharField(max_length=64, blank=True, default="")
    token_prefix = models.CharField(max_length=12, blank=True, default="")
    token_issued_at = models.DateTimeField(null=True, blank=True)
    # 令牌明文只在「绑定完成 → 固件首次轮询」这段窗口内保留，下发后立即清空。
    # 固件拿不到它就重新配对，避免长期留存可复用凭证。
    pending_token = models.CharField(max_length=64, blank=True, default="")
    # 令牌明文只允许下发一次：固件写入 NVS 后即可据此确认，避免日志泄漏可复用凭证。
    token_delivered_at = models.DateTimeField(null=True, blank=True)

    pairing_code = models.CharField(max_length=8, blank=True, default="", db_index=True)
    pairing_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)

    hardware = models.CharField(max_length=64, blank=True, default="")
    firmware = models.CharField(max_length=32, blank=True, default="")

    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_ip = models.CharField(max_length=64, blank=True, default="")
    sync_count = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    bound_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "terminal_devices"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "status"], name="idx_terminal_user_status")]

    def __str__(self) -> str:
        return f"{self.device_id} ({self.status})"


RESERVE_RESERVED = "reserved"
RESERVE_CANCELLED = "cancelled"
RESERVE_GRANTED = "granted"

RESERVE_STATUS_CHOICES = (
    (RESERVE_RESERVED, "已预约"),
    (RESERVE_CANCELLED, "已取消"),
    (RESERVE_GRANTED, "已发放"),
)

# 排队码前 10 名：年终报告时支付邮费即可获赠硬件小 K。
RESERVE_FREE_QUOTA = 10


class HardwareReservation(models.Model):
    """硬件小 K 预约排队记录。

    * 一个账号只占一个号：``user`` 唯一，取消后重新预约沿用原排队码，
      不允许反复取消/预约来刷前面的号。
    * ``queue_no`` 全局递增、永不复用给其他账号，发号发生在
      ``transaction.atomic`` 内，并发预约不会拿到同一个号。
    """

    id = models.AutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        db_column="user_id",
        on_delete=models.CASCADE,
        related_name="hardware_reservation",
    )
    queue_no = models.PositiveIntegerField(unique=True)
    code = models.CharField(max_length=16, unique=True)

    status = models.CharField(max_length=12, choices=RESERVE_STATUS_CHOICES, default=RESERVE_RESERVED)
    remark = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    granted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "terminal_hardware_reservations"
        ordering = ["queue_no"]

    def __str__(self) -> str:
        return f"#{self.queue_no} {self.code} ({self.status})"
