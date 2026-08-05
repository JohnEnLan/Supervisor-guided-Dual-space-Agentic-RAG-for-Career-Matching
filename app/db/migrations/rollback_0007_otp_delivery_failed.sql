-- 回滚 0007：移除 OTP 发送失败标志列。

ALTER TABLE otp_challenges
    DROP COLUMN IF EXISTS delivery_failed;
