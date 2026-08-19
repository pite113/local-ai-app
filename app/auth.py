"""访问认证：一次性动态密码(OTP) + 会话管理 + SMTP 邮件发送。

流程：管理员点"发送验证码" → 生成6位一次性码并发到指定邮箱 → 把码告诉访客
     → 访客输入码登录（一次性，10分钟有效，5次错误作废）→ 建立会话。
"""
import random
import secrets
import smtplib
import threading
import time
from email.mime.text import MIMEText

from .config import Settings
from .logger import LogStore


class Auth:
    def __init__(self, settings: Settings, logs: LogStore):
        self.s = settings
        self.logs = logs
        self._lock = threading.Lock()
        self._otp = None            # code -> {expiry, attempts}
        self._sessions = {}         # token -> expiry
        self._last_send = 0.0
        self._send_count = 0
        self._send_window_start = 0.0

    # ---------- OTP ----------
    def request_otp(self) -> dict:
        """生成一次性验证码并发送邮件。返回 {sent, debug_code?, error?}"""
        now = time.time()
        with self._lock:
            if now - self._last_send < self.s.otp_send_interval:
                wait = int(self.s.otp_send_interval - (now - self._last_send))
                return {"sent": False, "error": f"发送太频繁，请 {wait} 秒后再试"}
            # 每小时最多发送次数
            if now - self._send_window_start > 3600:
                self._send_window_start = now
                self._send_count = 0
            if self._send_count >= self.s.otp_max_per_hour:
                return {"sent": False, "error": "本小时发送次数已达上限，请稍后再试"}

            code = f"{random.randint(0, 999999):06d}"
            self._otp = {"code": code, "expiry": now + self.s.otp_ttl_seconds, "attempts": 0}
            self._last_send = now
            self._send_count += 1

        subject = "本地AI工作台 - 访问验证码"
        body = f"您的访问验证码是：{code}\n\n该验证码 10 分钟内有效，仅可使用一次。\n（如果这不是您本人的操作，请忽略本邮件。）"
        sent, err = self._send_email(subject, body)
        if sent:
            self.logs.add(type="auth", message="验证码已发送到邮箱", level="info")
            return {"sent": True}
        if self.s.smtp_host:
            self.logs.add(type="auth", level="error", error=f"邮件发送失败: {err}")
            return {"sent": False, "error": f"邮件发送失败: {err}"}
        # 未配置 SMTP：调试模式直接把码返回（仅限本机测试）
        self.logs.add(type="auth", message="SMTP未配置, 验证码以调试模式展示", level="warn")
        return {"sent": True, "debug_code": code, "warning": "SMTP 未配置，验证码显示在此（正式使用请配置邮箱）"}

    def verify_otp(self, code: str) -> tuple:
        """校验验证码。返回 (成功?, 错误信息)。一次性：无论对错都作废/计数。"""
        code = (code or "").strip()
        with self._lock:
            otp = self._otp
            if not otp:
                return False, "请先获取验证码"
            if code != otp["code"]:
                otp["attempts"] += 1
                if otp["attempts"] >= self.s.otp_max_attempts:
                    self._otp = None
                    return False, f"错误次数过多，验证码已作废，请重新获取"
                return False, f"验证码错误（还剩 {self.s.otp_max_attempts - otp['attempts']} 次机会）"
            if time.time() > otp["expiry"]:
                self._otp = None
                return False, "验证码已过期，请重新获取"
            self._otp = None  # 一次性：用后即焚
            return True, None

    # ---------- 会话 ----------
    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = time.time() + self.s.session_ttl_seconds
        return token

    def check_session(self, token: str) -> bool:
        if not token:
            return False
        with self._lock:
            exp = self._sessions.get(token)
            if exp and time.time() < exp:
                return True
            self._sessions.pop(token, None)
            return False

    def destroy_session(self, token: str):
        with self._lock:
            self._sessions.pop(token, None)

    # ---------- 邮件 ----------
    def _send_email(self, subject: str, body: str) -> tuple:
        s = self.s
        if not (s.smtp_host and s.smtp_user and s.smtp_pass and s.mail_to):
            return False, "SMTP 未配置"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = s.smtp_user
        msg["To"] = s.mail_to
        try:
            if s.smtp_port == 465:
                with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                    smtp.login(s.smtp_user, s.smtp_pass)
                    smtp.sendmail(s.smtp_user, [s.mail_to], msg.as_string())
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                    smtp.starttls()
                    smtp.login(s.smtp_user, s.smtp_pass)
                    smtp.sendmail(s.smtp_user, [s.mail_to], msg.as_string())
            return True, None
        except Exception as e:
            return False, str(e)
