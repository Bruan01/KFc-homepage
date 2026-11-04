"""邮件 HTML 模板。

为什么不用 Django 模板文件、而是拼字符串：邮件 HTML 必须全部内联样式、table 布局，
一个变量的改动都藏在长长的 style 里，做成模板文件反而更难读。这里的函数只暴露业务参数。

三条兼容性红线（改的时候别破坏）：
1. 只用 table 布局，不用 flex / grid —— Outlook 用 Word 引擎渲染，不支持。
2. 样式全部内联，不用 <style> 块 —— Gmail 会剥掉 <head> 里的样式。
3. 图片必须是公网绝对地址 —— 邮件客户端不认相对路径，也不认 SVG。
"""
from __future__ import annotations

# 邮件主题色：中性黑灰。改这里就够，模板里不再有别的品牌色硬编码。
BRAND_DEEP = "#111111"
BRAND = "#27272A"
BRAND_SOFT = "#F4F4F5"
INK = "#27272A"
MUTED = "#52525B"
FAINT = "#71717A"
LINE = "#E4E4E7"
PAGE_BG = "#F4F4F5"

FONT = (
    "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
    "'Microsoft YaHei','Helvetica Neue',Arial,sans-serif"
)
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"


def _logo(base_url: str) -> str:
    return (
        f'<img src="{base_url}/kflow-mark-light.png" width="34" height="22" alt="KFlow" '
        'style="display:block;border:0;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;" />'
    )


def _layout(*, title: str, preheader: str, content: str, base_url: str, footer_note: str = "") -> str:
    year_note = footer_note or "这封邮件由 KFlow 系统自动发送，请勿直接回复。"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="light only" />
<meta name="supported-color-schemes" content="light only" />
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE_BG};-webkit-font-smoothing:antialiased;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{preheader}</div>
<table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation" style="background:{PAGE_BG};padding:28px 12px;">
  <tr>
    <td align="center">
      <table width="600" cellpadding="0" cellspacing="0" border="0" role="presentation"
             style="width:600px;max-width:600px;background:#FFFFFF;border:1px solid {LINE};border-radius:16px;overflow:hidden;">

        <tr>
          <td style="background:{BRAND_DEEP};padding:18px 28px;">
            <table cellpadding="0" cellspacing="0" border="0" role="presentation">
              <tr>
                <td style="vertical-align:middle;">{_logo(base_url)}</td>
                <td style="vertical-align:middle;padding-left:10px;color:#FFFFFF;font-family:{FONT};
                           font-size:16px;font-weight:600;letter-spacing:0.6px;">KFlow</td>
              </tr>
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:30px 28px 26px;font-family:{FONT};">
            {content}
          </td>
        </tr>

        <tr>
          <td style="padding:16px 28px 24px;border-top:1px solid {LINE};font-family:{FONT};">
            <p style="margin:0;font-size:12px;line-height:1.75;color:{FAINT};">
              {year_note}<br />
              如果这不是你本人的操作，忽略这封邮件即可，你的账号不会有任何变化。
            </p>
          </td>
        </tr>

      </table>
      <div style="max-width:600px;margin:14px auto 0;font-family:{FONT};font-size:11px;
                  line-height:1.6;color:#A1A1AA;text-align:center;">
        KFlow · 一个给 vibecoding 的社区
      </div>
    </td>
  </tr>
</table>
</body>
</html>"""


def _heading(text: str) -> str:
    return (
        f'<h1 style="margin:0 0 10px;font-size:20px;line-height:1.4;font-weight:600;'
        f'color:{BRAND_DEEP};">{text}</h1>'
    )


def _paragraph(html: str) -> str:
    return f'<p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:{INK};">{html}</p>'


def render_verification_code(*, code: str, purpose_label: str, ttl_minutes: int, base_url: str) -> str:
    content = (
        _heading("你的验证码")
        + _paragraph(f"你正在<strong style=\"color:{BRAND_DEEP};\">{purpose_label}</strong>，请使用下面的验证码完成操作。")
        + f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation" style="margin:22px 0 18px;">
          <tr>
            <td align="center" style="background:{BRAND_SOFT};border:1px solid #E4E4E7;border-radius:12px;padding:22px 10px;">
              <span style="font-family:{MONO};font-size:34px;line-height:1;font-weight:700;
                           color:{BRAND_DEEP};letter-spacing:9px;padding-left:9px;">{code}</span>
            </td>
          </tr>
        </table>
        """
        + _paragraph(
            f'<span style="color:{MUTED};">验证码 <strong>{ttl_minutes} 分钟</strong>内有效，只能使用一次。'
            "请勿转发给任何人——KFlow 的任何人都不会向你索要它。</span>"
        )
        + f"""
        <table cellpadding="0" cellspacing="0" border="0" role="presentation" style="margin-top:22px;width:100%;">
          <tr>
            <td style="border-left:3px solid {LINE};padding:2px 0 2px 12px;font-size:13px;line-height:1.8;color:{FAINT};">
              没收到？检查垃圾邮件文件夹，或在原页面重新发送。<br />
              请求过于频繁时，系统会自动限制，稍等一会再试即可。
            </td>
          </tr>
        </table>
        """
    )
    return _layout(
        title=f"KFlow 验证码：{code}",
        preheader=f"{purpose_label}的验证码是 {code}，{ttl_minutes} 分钟内有效。",
        content=content,
        base_url=base_url,
    )


def render_user_registered(*, username: str, email: str, created_at: str, request_ip: str, base_url: str) -> str:
    ip_row = (
        f'<tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">来源 IP</td>'
        f'<td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;'
        f'font-family:{MONO};color:{INK};">{request_ip}</td></tr>'
        if request_ip
        else ""
    )
    content = (
        _heading("有新用户完成注册")
        + _paragraph(f'<strong style="color:{BRAND_DEEP};">{username}</strong> 刚刚验证了邮箱并加入 KFlow。')
        + f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation" style="margin:18px 0 20px;">
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">用户名</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;
                  font-weight:600;color:{INK};">{username}</td></tr>
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">邮箱</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{INK};">{email}</td></tr>
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">注册时间</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{INK};">{created_at}</td></tr>
          {ip_row}
        </table>
        """
        + f"""
        <table cellpadding="0" cellspacing="0" border="0" role="presentation">
          <tr>
            <td style="background:{BRAND_DEEP};border-radius:8px;">
              <a href="{base_url}/admin/users" target="_blank"
                 style="display:inline-block;padding:11px 22px;font-family:{FONT};font-size:14px;
                        font-weight:600;color:#FFFFFF;text-decoration:none;">在后台查看用户</a>
            </td>
          </tr>
        </table>
        """
    )
    return _layout(
        title=f"KFlow 新用户注册：{username}",
        preheader=f"{username}（{email}）已完成注册。",
        content=content,
        base_url=base_url,
        footer_note="你收到这封邮件，是因为后台「系统邮箱设置」开启了新用户注册通知。",
    )


def render_test(*, from_email: str, actor: str, created_at: str, base_url: str) -> str:
    content = (
        _heading("邮件配置测试成功")
        + _paragraph("这封测试邮件已经从你的 KFlow 站点发出。看到它，说明 SMTP 配置、认证与投递链路都正常。")
        + f"""
        <table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation" style="margin:18px 0 4px;">
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">发件人</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{INK};">{from_email}</td></tr>
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">触发人</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{INK};">{actor}</td></tr>
          <tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{MUTED};">时间</td>
              <td align="right" style="padding:9px 0;border-bottom:1px solid {LINE};font-size:13px;color:{INK};">{created_at}</td></tr>
        </table>
        """
        + f"""
        <p style="margin:20px 0 0;font-size:12px;line-height:1.7;color:{FAINT};">
          如果收件方把它归进了垃圾邮件，建议在发信服务商里配置 SPF / DKIM，
          否则验证码邮件也可能被同样处理。
        </p>
        """
    )
    return _layout(
        title="KFlow 邮件配置测试",
        preheader="测试邮件发送成功，SMTP 配置可用。",
        content=content,
        base_url=base_url,
        footer_note="这是一封由后台手动触发的测试邮件。",
    )
