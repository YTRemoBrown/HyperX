# -*- coding: utf-8 -*-
"""
HyperX Android APK - Main Entry
Developed by: ريمو براون
© 2026 All Rights Reserved
"""
import os
import sys
import threading
import time
import socket
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import platform

if platform == "android":
    from jnius import autoclass
    from android.runnable import run_on_ui_thread

    WebView = autoclass("android.webkit.WebView")
    WebViewClient = autoclass("android.webkit.WebViewClient")
    WebSettings = autoclass("android.webkit.WebSettings")
    Activity = autoclass("org.kivy.android.PythonActivity")
    LinearLayout = autoclass("android.widget.LinearLayout")
    LayoutParams = autoclass("android.widget.LinearLayout$LayoutParams")
    AndroidColor = autoclass("android.graphics.Color")
else:
    WebView = None

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def find_free_port(start=5000, max_tries=50):
    for port in range(start, start + max_tries):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((FLASK_HOST, port))
            s.close()
            return port
        except OSError:
            continue
    return start


def start_flask():
    global FLASK_PORT
    FLASK_PORT = find_free_port()
    sys.path.insert(0, BASE_DIR)
    os.chdir(BASE_DIR)
    try:
        import app as hyperx_app
        hyperx_app.app.run(
            host=FLASK_HOST,
            port=FLASK_PORT,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except Exception as e:
        print(f"[Flask Error] {e}")
        import traceback
        traceback.print_exc()


if platform == "android":
    @run_on_ui_thread
    def create_webview(url):
        activity = Activity.mActivity
        webview = WebView(activity)
        settings = webview.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setAllowFileAccess(True)
        settings.setAllowContentAccess(True)
        settings.setLoadWithOverviewMode(True)
        settings.setUseWideViewPort(True)
        settings.setBuiltInZoomControls(False)
        settings.setDisplayZoomControls(False)
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW)
        webview.setWebViewClient(WebViewClient())
        webview.setBackgroundColor(AndroidColor.parseColor("#0a0e17"))
        layout = LinearLayout(activity)
        layout.setOrientation(LinearLayout.VERTICAL)
        params = LayoutParams(
            LayoutParams.MATCH_PARENT,
            LayoutParams.MATCH_PARENT,
        )
        layout.addView(webview, params)
        activity.setContentView(layout)
        webview.loadUrl(url)


class HyperXRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.padding = 30
        self.spacing = 20

        title = Label(
            text="[b][color=00e5ff]⚡ HyperX[/color][/b]\n"
                 "[size=14][color=7a8ba8]محلل APK متقدم[/color][/size]",
            markup=True,
            font_size="32sp",
            size_hint_y=0.3,
        )
        self.add_widget(title)

        status = Label(
            text="⏳ جاري تشغيل السيرفر...",
            markup=True,
            font_size="16sp",
            size_hint_y=0.2,
        )
        self.add_widget(status)
        self.status_label = status

        btn = Button(
            text="🌐 افتح في المتصفح",
            size_hint=(1, 0.15),
            background_color=(0, 0.9, 1, 1),
            color=(0, 0, 0, 1),
            font_size="20sp",
        )
        btn.bind(on_press=self.open_browser)
        self.add_widget(btn)
        self.open_btn = btn
        self.open_btn.disabled = True

        footer = Label(
            text="═══════════════════════\n"
                 "Developed by: ريمو براون\n"
                 "© 2026 All Rights Reserved\n"
                 "═══════════════════════",
            markup=True,
            font_size="12sp",
            color=(0.48, 0.55, 0.66, 1),
            size_hint_y=0.2,
        )
        self.add_widget(footer)

        Clock.schedule_interval(self.check_server, 0.5)

    def check_server(self, dt):
        try:
            s = socket.create_connection((FLASK_HOST, FLASK_PORT), timeout=1)
            s.close()
            self.status_label.text = (
                f"✅ السيرفر يعمل!\n"
                f"[size=12]http://{FLASK_HOST}:{FLASK_PORT}[/size]"
            )
            self.open_btn.disabled = False
            Clock.unschedule(self.check_server)
        except Exception:
            pass

    def open_browser(self, *args):
        import webbrowser
        webbrowser.open(f"http://{FLASK_HOST}:{FLASK_PORT}")


class HyperXApp(App):
    def build(self):
        self.title = "HyperX"
        Window.clearcolor = (0.04, 0.055, 0.09, 1)
        return HyperXRoot()

    def on_start(self):
        threading.Thread(target=start_flask, daemon=True).start()

        if platform == "android":
            def wait_and_open(dt):
                try:
                    s = socket.create_connection((FLASK_HOST, FLASK_PORT), timeout=1)
                    s.close()
                    create_webview(f"http://{FLASK_HOST}:{FLASK_PORT}")
                    Clock.unschedule(wait_and_open)
                except Exception:
                    pass
            Clock.schedule_interval(wait_and_open, 0.5)


if __name__ == "__main__":
    HyperXApp().run()
