#!/usr/bin/env python3
"""
BOPS Playwright 自动登录 → 抓 token  （fork from gbase-customer-monitor/scripts/auth.py）

bops-ppt-monitor の CI で BOPS_TOKEN を毎回自動取得するため、姉妹 skill から複製。
ロジック更新時は両方を同期すること。

适用场景：GitHub Actions 上免人工每天/每周跑 monitor 时，自动获取 BOPS token。

使用方式：
    BOPS_LOGIN_URL=https://bops.gbase.ai/login \\
    BOPS_USERNAME=xxx \\
    BOPS_PASSWORD=xxx \\
    python3 auth.py

输出：
  - 在 GH Actions 上：把 token 写到 $GITHUB_OUTPUT，并 ::add-mask:: 到 log
  - 本地：把 token 打到 stdout（注意 shell history）

退出码：
  0 = 成功
  1 = 登录后 15s 内未抓到 token
  2 = 缺环境变量
"""

import asyncio
import os
import sys
from playwright.async_api import async_playwright


REQUIRED_ENV = ("BOPS_LOGIN_URL", "BOPS_USERNAME", "BOPS_PASSWORD")
LOGIN_WAIT_TIMEOUT_SEC = 30
DEBUG = os.environ.get("BOPS_AUTH_DEBUG", "").lower() in ("1", "true", "yes")


def _extract_token_from_body(body) -> str | None:
    """从登录响应 JSON 体里递归找 token（常见键名：token / accessToken / access_token / authorization）"""
    if not isinstance(body, dict):
        return None
    candidates = ("token", "accessToken", "access_token", "authorization",
                  "Authorization", "id_token", "auth_token")
    for key in candidates:
        val = body.get(key)
        if isinstance(val, str) and len(val) > 20:
            return val[7:].strip() if val.lower().startswith("bearer ") else val
    # 递归 data / result 嵌套
    for nest in ("data", "result", "payload"):
        nested = body.get(nest)
        if isinstance(nested, dict):
            found = _extract_token_from_body(nested)
            if found:
                return found
    return None


async def main() -> int:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        print(f"❌ 缺少环境变量: {', '.join(missing)}", file=sys.stderr)
        return 2

    login_url = os.environ["BOPS_LOGIN_URL"]
    username = os.environ["BOPS_USERNAME"]
    password = os.environ["BOPS_PASSWORD"]

    captured: dict[str, str] = {}

    seen_responses: list[tuple[int, str, list[str]]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not DEBUG)
        context = await browser.new_context()
        page = await context.new_page()

        # 拦截 response header（用户实测确认 token 在 API 响应 header 里）
        async def on_response(response) -> None:
            if "token" in captured:
                return
            headers = response.headers  # 已 lowercase
            if DEBUG:
                # 记录所有看到的 response（debug 用）
                interesting = [k for k in headers if any(
                    needle in k for needle in ("auth", "token"))]
                seen_responses.append((response.status, response.url, interesting))

            # 优先看 body 里的 token（很多 SPA 把 token 放在 JSON 响应体里）
            ct = headers.get("content-type", "")
            if "json" in ct and "/login" in response.url.lower():
                try:
                    body = await response.json()
                    token = _extract_token_from_body(body)
                    if token:
                        captured["token"] = token
                        captured["source"] = f"response.body from {response.url}"
                        return
                except Exception:
                    pass

            for key in ("authorization", "x-auth-token", "x-token", "token", "access-token"):
                val = headers.get(key, "").strip()
                if not val or len(val) < 20:
                    continue
                token = val[7:].strip() if val.lower().startswith("bearer ") else val
                captured["token"] = token
                captured["source"] = f"response[{key}] from {response.url}"
                return

        # 兜底：从后续请求里也找一遍（万一服务端把 token 通过 Set-Cookie 设置，
        # 浏览器后续请求会自动带 Authorization 头）
        def on_request(request) -> None:
            if "token" in captured:
                return
            auth = request.headers.get("authorization", "").strip()
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
                if len(token) > 20:
                    captured["token"] = token
                    captured["source"] = f"request.authorization to {request.url}"

        page.on("response", on_response)
        page.on("request", on_request)

        # 1. 打开登录页
        if DEBUG:
            print(f"→ 打开 {login_url}", file=sys.stderr)
        await page.goto(login_url, wait_until="domcontentloaded")

        # 2. 等表单渲染（SPA 可能需要时间）
        await page.wait_for_selector('input[autocomplete="username"]', timeout=10000)

        # 3. 填表单（用 autocomplete 属性最稳，跨语言不受 placeholder 影响）
        await page.fill('input[autocomplete="username"]', username)
        await page.fill('input[autocomplete="current-password"]', password)

        # 4. 提交
        await page.click('button[type="submit"]')
        if DEBUG:
            print("→ 已点击提交，等待 token 出现…", file=sys.stderr)

        # 5. 等待登录后续请求带回 token
        for _ in range(LOGIN_WAIT_TIMEOUT_SEC * 2):
            if "token" in captured:
                break
            await asyncio.sleep(0.5)

        # debug 时把见到的 response 打出来诊断
        if DEBUG and "token" not in captured:
            print("\n--- 见到的所有 response（status, url, auth-related-headers）---",
                  file=sys.stderr)
            for s, u, h in seen_responses[-30:]:
                print(f"  {s} {u}  headers={h}", file=sys.stderr)
            # 截图存到 /tmp
            screenshot_path = "/tmp/bops_auth_debug.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"\n截图已存: {screenshot_path}", file=sys.stderr)
            try:
                body = await page.content()
                with open("/tmp/bops_auth_debug.html", "w", encoding="utf-8") as f:
                    f.write(body)
                print("HTML 已存: /tmp/bops_auth_debug.html", file=sys.stderr)
            except Exception:
                pass

        await browser.close()

    if "token" not in captured:
        print(f"❌ 登录后 {LOGIN_WAIT_TIMEOUT_SEC}s 内未捕获到 token", file=sys.stderr)
        print("可能原因：登录失败（账号密码错）/ token 不在 header 而在 body /"
              " 页面没发任何带 token 的请求", file=sys.stderr)
        return 1

    token = captured["token"]
    source = captured.get("source", "?")

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        # GH Actions: 用 multiline marker 写 step output，mask token 防止 log 泄漏
        print(f"::add-mask::{token}")
        delim = "EOF_BOPS_TOKEN_42"
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"token<<{delim}\n{token}\n{delim}\n")
        print(f"✅ token 捕获成功（length={len(token)}, source={source[:60]}…）")
    elif os.environ.get("BOPS_AUTH_PRINT_TOKEN") == "1":
        # 显式要全文（管道喂 gh secret set 用）
        print(token)
    else:
        # 本地默认：仅打 length + 前 8 字符前缀，避免 shell history 泄漏
        print(f"✅ token 捕获成功 length={len(token)} prefix={token[:8]}…",
              file=sys.stderr)
        print(f"   source: {source[:80]}", file=sys.stderr)
        print(f"   想拿全文，加环境变量 BOPS_AUTH_PRINT_TOKEN=1 重跑", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
