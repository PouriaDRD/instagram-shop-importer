from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    url_for,
)

crawler_bp = Blueprint(
    "crawler",
    __name__,
)


@crawler_bp.get("/")
def index():
    return render_template("index.html")


@crawler_bp.post("/crawl")
def start_crawl():
    username = request.form.get("username", "").strip().lstrip("@")

    if not username:
        return redirect(url_for("crawler.index"))

    # در مرحله بعد CrawlService را اینجا وصل می‌کنیم.
    return f"Crawler input received: @{username}"
