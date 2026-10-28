"""Exercise deployment output and HTTP behavior without the live database."""
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings


class StaticDeliveryTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = self.root / "static"
        source.mkdir()
        self.css = "/* deployment comment */\n" + ".sample { color: red; margin: 0px; }\n" * 100
        self.js = "// deployment comment\nwindow.staticExample = `hello ${1 + 2}`;\n"
        (source / "example.css").write_text(self.css, encoding="utf-8")
        (source / "example.js").write_text(self.js, encoding="utf-8")
        (source / "index.html").write_text(
            '<link rel="stylesheet" href="/example.css"><script src="/example.js" defer></script>', encoding="utf-8",
        )
        self.options = override_settings(
            BASE_DIR=self.root, STATIC_ROOT=self.root / "collected", STATICFILES_DIRS=[source],
            STATICFILES_FINDERS=["django.contrib.staticfiles.finders.FileSystemFinder"],
        )
        self.options.enable()
        self.addCleanup(self.options.disable)
        call_command("collectstatic", interactive=False, verbosity=0)

    def response_body(self, response):
        self.addCleanup(response.close)
        return b"".join(response.streaming_content) if response.streaming else response.content

    def test_build_minifies_hashes_and_precompresses_without_modifying_sources(self):
        name = staticfiles_storage.stored_name("example.css")
        target = self.root / "collected" / name
        compressed = target.with_name(target.name + ".gz")
        self.assertNotEqual(name, "example.css")
        self.assertLess(target.stat().st_size, len(self.css.encode()))
        self.assertEqual(gzip.decompress(compressed.read_bytes()), target.read_bytes())
        self.assertEqual((self.root / "static/example.css").read_text(), self.css)
        self.assertEqual((self.root / "static/example.js").read_text(), self.js)
        # Re-running collectstatic must produce the same content version.
        call_command("collectstatic", interactive=False, verbosity=0)
        self.assertEqual(staticfiles_storage.stored_name("example.css"), name)

    def test_hashed_assets_are_immutable_compressed_and_conditional(self):
        url = "/static/" + staticfiles_storage.stored_name("example.css")
        response = self.client.get(url, HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertIn("immutable", response["Cache-Control"])
        self.assertIn("Accept-Encoding", response["Vary"])
        self.assertNotIn(b"deployment comment", gzip.decompress(self.response_body(response)))
        cached = self.client.get(url, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(self.response_body(cached), b"")
        uncompressed = self.client.get(url, HTTP_ACCEPT_ENCODING="identity")
        self.response_body(uncompressed)
        self.assertNotIn("Content-Encoding", uncompressed)

    def test_pages_use_versioned_assets_and_seed_csrf_even_on_revalidation(self):
        response = self.client.get("/")
        body = self.response_body(response).decode()
        self.assertIn("/static/" + staticfiles_storage.stored_name("example.css"), body)
        self.assertIn("/static/" + staticfiles_storage.stored_name("example.js"), body)
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
        self.assertIn("csrftoken", self.client.cookies)
        self.client.cookies.clear()
        cached = self.client.get("/", HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(cached.status_code, 304)
        self.assertIn("csrftoken", self.client.cookies)

    def test_legacy_assets_revalidate_and_etags_override_dates(self):
        response = self.client.get("/example.js")
        self.assertEqual(self.response_body(response).decode().replace("\r\n", "\n"), self.js)
        cached = self.client.get("/example.js", HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(cached.status_code, 304)
        changed = self.client.get("/example.js", HTTP_IF_NONE_MATCH='"outdated"', HTTP_IF_MODIFIED_SINCE=response["Last-Modified"])
        self.assertEqual(changed.status_code, 200)
        self.response_body(changed)

    def test_runtime_injected_announcement_assets_revalidate(self):
        # header.js 动态插入的公告组件没有 ?v= 指纹，必须回源校验，
        # 否则改完插画/样式用户一年都看不到。
        for name in ("announcement.js", "announcement.css"):
            (self.root / "static" / name).write_text("/* probe */", encoding="utf-8")
            response = self.client.get(f"/{name}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Cache-Control"], "no-cache")

    def test_build_does_not_expose_material_or_uploads(self):
        response = self.client.get("/static/../data/homepage.db")
        self.assertEqual(response.status_code, 404)

    def test_hashed_names_missing_from_sources_fall_back_to_collected(self):
        # {% static %} 在 collectstatic 后给出哈希名，这类文件只存在于
        # STATIC_ROOT（.staticfiles），源码 static/ 目录里没有对应副本。
        collected = self.root / "collected" / "bundle"
        collected.mkdir(parents=True)
        (collected / "app.deadbeef1234.css").write_text(".hashed { color: blue; }", encoding="utf-8")
        response = self.client.get("/static/bundle/app.deadbeef1234.css")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.response_body(response).decode(), ".hashed { color: blue; }")
        self.assertIn("immutable", response["Cache-Control"])
        for attack in ("/static/bundle/../collected.json", "/static/bundle/app.deadbeef1234.css/../../settings.py"):
            with self.subTest(attack=attack):
                self.assertEqual(self.client.get(attack).status_code, 404)
