"""Build a self-contained preview so file:// and downloaded reports work offline."""
from base64 import b64encode
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build():
    source = (ROOT / "index.template.html").read_text(encoding="utf-8")
    css = (ROOT / "report.css").read_text(encoding="utf-8")
    script = (ROOT / "report.js").read_text(encoding="utf-8")
    portrait = b64encode((ROOT / "assets/natsume-takashi.png").read_bytes()).decode("ascii")
    source = source.replace('<link rel="stylesheet" href="./report.css">', f"<style>\n{css}\n</style>")
    source = source.replace('  <script src="./report.js" defer></script>', "")
    source = source.replace('src="./assets/natsume-takashi.png"', f'src="data:image/png;base64,{portrait}"')
    source = source.replace("</body>", f"<script>\n{script}\n</script>\n</body>")
    (ROOT / "index.html").write_text(source, encoding="utf-8")
    print("Built self-contained index.html")


if __name__ == "__main__":
    build()
