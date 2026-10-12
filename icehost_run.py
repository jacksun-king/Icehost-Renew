import os
import time
import json
import urllib.parse
import requests
# 引入 SeleniumBase 高级过盾包
from seleniumbase import SB

SERVER_URL = os.getenv("ICEHOST_SERVER_URL")
ICEHOST_COOKIES = os.getenv("ICEHOST_COOKIES")
# 代理配置（mihomo mixed-port，同时支持 http 和 socks5）
# 先测试代理是否可用，不可用则回退直连，避免 Chrome 连死代理导致页面加载失败
_raw_proxy = os.getenv("ALL_PROXY") or ""
PROXY = ""
if _raw_proxy:
    try:
        _test = requests.get("https://api.ipify.org", proxies={"http": _raw_proxy, "https": _raw_proxy}, timeout=10)
        if _test.status_code == 200:
            PROXY = _raw_proxy
            print(f"✅ 代理可用，出口 IP: {_test.text}")
        else:
            print(f"⚠️ 代理返回 {_test.status_code}，回退直连")
    except Exception as _e:
        print(f"⚠️ 代理 {_raw_proxy} 不可用（{_e}），回退直连")
else:
    print("ℹ️ 未配置 ALL_PROXY，直连模式")

def send_tg_notification(message, photo_path=None):
    """发送结果和截图至 Telegram"""
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("未配置 TG 机器人变量，跳过发送 TG 推送。")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload)
        print("TG 状态通知发送成功。")
    except Exception as e:
        print(f"发送 TG 消息异常: {e}")

    if photo_path and os.path.exists(photo_path):
        try:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": "IceHost 实时画面"}
                requests.post(url, data=data, files=files)
            print("TG 截图发送成功。")
        except Exception as e:
            print(f"发送 TG 截图异常: {e}")

def run():
    if not SERVER_URL:
        print("错误: 缺少 ICEHOST_SERVER_URL 环境变量")
        return

    # 1. 启动 SeleniumBase 并开启 UC 免密/防检测模式与 Xvfb 虚拟桌面 (xvfb=True)
    #    若配置了代理（住宅 IP），通过 --proxy-server 让浏览器走代理
    chromium_arg = f"--proxy-server={PROXY}" if PROXY else None
    with SB(uc=True, xvfb=True, chromium_arg=chromium_arg) as sb:
        print(f"正在访问 IceHost 面板: {SERVER_URL}")
        print(f"📌 代理: {PROXY or '直连'}")
        # 使用 UC 专属重连模式访问，能极大缓解首屏 Cloudflare 阻断
        sb.uc_open_with_reconnect(SERVER_URL, reconnect_time=8)
        sb.sleep(5)

        # 2. 注入 Cookies（已升级：智能兼容 JSON 或纯文本格式）
        if ICEHOST_COOKIES:
            try:
                cookies_to_add = []
                raw_cookies_str = ICEHOST_COOKIES.strip()

                # 尝试一：如果 Secret 填的是标准的 JSON 格式
                try:
                    raw_data = json.loads(raw_cookies_str)
                    if isinstance(raw_data, list):
                        cookies_to_add = raw_data
                    elif isinstance(raw_data, dict):
                        cookies_to_add = raw_data.get("cookies", [])
                    print("检测到 JSON 格式 Cookie，正在解析...")
                
                # 尝试二：如果解析失败，说明填的是纯文本
                except json.JSONDecodeError:
                    print("检测到纯文本 Cookie 格式，正在自动提取并生成标准字段...")
                    
                    # 提取真正的 Token 字符串值
                    token_value = raw_cookies_str
                    if "icehostpl_session=" in token_value:
                        token_value = token_value.split("icehostpl_session=")[1].split(";")[0]
                    elif "XSRF-TOKEN=" in token_value:
                        token_value = token_value.split("XSRF-TOKEN=")[1].split(";")[0]
                    
                    token_value = token_value.strip()

                    # 最稳妥策略：自动为 Selenium 生成两个核心的 Cookie 字典
                    cookies_to_add = [
                        {"name": "icehostpl_session", "value": token_value, "domain": "dash.icehost.pl"},
                        {"name": "XSRF-TOKEN", "value": token_value, "domain": "dash.icehost.pl"}
                    ]

                # 统一执行转换与注入
                for c in cookies_to_add:
                    raw_value = c["value"]
                    decoded_value = urllib.parse.unquote(raw_value)
                    
                    cookie_dict = {
                        "name": c["name"],
                        "value": decoded_value,
                        "domain": c.get("domain", "dash.icehost.pl"),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True)
                    }
                    if "sameSite" in c:
                        ss = str(c["sameSite"]).lower()
                        if ss in ["lax", "strict", "none"]:
                            cookie_dict["sameSite"] = ss.capitalize()
                    
                    sb.add_cookie(cookie_dict)
                
                print("Cookie 成功注入！")
                
                # 重新刷新加载，应用 Cookie
                sb.refresh()
                sb.sleep(5)
            except Exception as e:
                print(f"注入 Cookie 过程中发生异常，跳过: {e}")

        # 3. 核心过盾：自动寻找并执行系统级物理点击过 Cloudflare Turnstile 验证盾
        sb.save_screenshot("icehost_debug_screenshot.png")
        try:
            print("正在检测并调用系统级 PyAutoGUI 驱动，物理点击 Cloudflare 人机验证码...")
            # 在虚拟桌面上定位验证框并模拟发送系统硬件级点击事件
            sb.uc_gui_click_captcha()
            sb.sleep(10) # 给予 10 秒跳转缓冲
            sb.save_screenshot("icehost_debug_screenshot.png")
        except Exception as e:
            print(f"验证盾已被跳过或点击执行完毕: {e}")

        # 4. 判断登录状态
        current_url = sb.get_current_url()
        # 判断是否停留在登录页
        if "login" in current_url or sb.is_element_visible("input[type='email']"):
            msg = "❌ <b>IceHost 登录失效！</b>\n请在浏览器重新提取并更新 ICEHOST_COOKIES。"
            print(msg)
            send_tg_notification(msg, "icehost_debug_screenshot.png")
            return

        # 5. 判定波兰语与英语红框限制
        page_source = sb.get_page_source()
        # 🟢 修复：增加了英文的报错关键词，防止英文面板误判
        keywords = ["Nie możesz przedłużyć", "niedawno to zrobiłeś", "kolejne 6 godziny", "cannot extend", "recently", "next 6 hours"]
        is_limited = any(kw in page_source for kw in keywords)

        if is_limited:
            print("检测到红框限制提示：说明未到可续期时间。结束本次运行（不发送 Telegram 提醒）。")
            return

        # 6. 安全寻找并点击续期按钮
        # 🟢 修复：去掉 not(*) 限制（原条件排除有子元素的按钮如 <button><i>Add 6 hours</i></button>）
        #    改用 button/a/div/input 元素匹配，兼容带图标子元素的按钮
        renew_btn_selector = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6')] | //a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6')] | //div[@role='button' and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6')] | //input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add 6')]"
        
        try:
            print("正在等待续期按钮加载...")
            print(f"📌 当前 URL: {sb.get_current_url()}")
            print(f"📌 页面标题: {sb.get_title()}")

            # 🟢 修复：先在主文档找按钮，找不到就遍历 iframe 内部搜索
            btn_found = False
            
            # 尝试 1: 主文档直接搜索
            try:
                sb.wait_for_element_visible(renew_btn_selector, timeout=8)
                print("✅ 在主文档找到续期按钮")
                btn_found = True
            except:
                print("主文档未找到按钮，检查 iframe...")
            
            # 尝试 2: 遍历 iframe 搜索
            if not btn_found:
                try:
                    iframes = sb.find_elements("iframe")
                    print(f"📌 检测到 {len(iframes)} 个 iframe")
                    for i, ifr in enumerate(iframes):
                        try:
                            print(f"  → 切换到 iframe #{i}...")
                            sb.switch_to_frame(ifr)
                            sb.sleep(2)
                            # 打印 iframe 内的文本
                            try:
                                ifr_text = sb.get_text("body")
                                if ifr_text.strip():
                                    print(f"  📌 iframe#{i} 文本（前500字符）: {ifr_text[:500]}")
                                    for line in ifr_text.splitlines():
                                        ll = line.lower().strip()
                                        if any(k in ll for k in ["add", "6 hour", "validity", "dodaj", "godzin", "renew", "przedłu"]):
                                            print(f"  🔍 iframe匹配行: {line.strip()[:200]}")
                            except:
                                pass
                            # 在 iframe 内搜索按钮
                            try:
                                sb.wait_for_element_visible(renew_btn_selector, timeout=10)
                                print(f"  ✅ 在 iframe#{i} 内找到续期按钮！")
                                btn_found = True
                                break
                            except:
                                print(f"  iframe#{i} 内未找到按钮")
                                sb.switch_to_default_content()
                        except Exception as ie:
                            print(f"  iframe#{i} 切换异常: {ie}")
                            sb.switch_to_default_content()
                except Exception as fe:
                    print(f"iframe 遍历异常: {fe}")
            
            if not btn_found:
                raise Exception("在主文档和所有 iframe 内均未找到续期按钮")
            
            print("未检测到限制提示，找到续期按钮，正在点击...")
            sb.click(renew_btn_selector)
            
            # 点击后切回主文档
            try:
                sb.switch_to_default_content()
            except:
                pass
            
            # ⚡ 点击后，在不刷新页面的前提下，先等待 5 秒让可能弹出的红框提示充分渲染
            sb.sleep(5)
            sb.save_screenshot("icehost_debug_screenshot.png")
            
            # 立即读取当前最真实的页面源码（此时若有报错红条，必定还挂在屏幕上）
            current_source = sb.get_page_source()
            is_failed_due_to_limit = any(kw in current_source for kw in keywords)
            
            if is_failed_due_to_limit:
                print("点击后，页面立刻弹出了限制提示：说明未到可续期时间。结束本次运行。")
                return
            
            print("点击后未检测到报错红条，正在刷新页面确认续期结果...")
            sb.refresh()
            sb.sleep(5)
            sb.save_screenshot("icehost_debug_screenshot.png")
            
            updated_source = sb.get_page_source()
            is_now_limited = any(kw in updated_source for kw in keywords)
            
            if is_now_limited:
                msg = "⚡ <b>IceHost 服务器续期成功！</b>\n服务器已真正成功延长 6 小时有效期。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
            else:
                msg = "ℹ️ <b>IceHost 续期指令已发送</b>\n按钮已点击，请检查下方截图确认是否成功。"
                print(msg)
                send_tg_notification(msg, "icehost_debug_screenshot.png")
                
        except Exception as e:
            # 🟢 修复：加上了 TG 推送，找不到按钮时能在 TG 收到报错截图
            error_msg = "❌ <b>IceHost 续期异常！</b>\n未找到续期按钮，可能是网页加载失败、被限制或按钮文本有变，请查看截图。"
            print(f"未在页面中找到可用的续期按钮: {e}")
            # 打印当前 URL 和页面文本，方便诊断
            try:
                print(f"📌 异常时 URL: {sb.get_current_url()}")
                _body = sb.get_text("body")
                print(f"📌 页面可见文本（前1000字符）:\n{_body[:1000]}")
                # 搜索包含 add/6/validity/dodaj/renew 的行
                for line in _body.splitlines():
                    ll = line.lower().strip()
                    if any(k in ll for k in ["add", "6 hour", "validity", "dodaj", "godzin", "renew", "przedłu"]):
                        print(f"  🔍 匹配行: {line.strip()[:200]}")
            except:
                pass
            send_tg_notification(error_msg, "icehost_debug_screenshot.png")

if __name__ == "__main__":
    run()
