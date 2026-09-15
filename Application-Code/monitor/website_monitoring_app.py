import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import mysql.connector
import requests
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    url_for,
)


app = Flask(__name__)
app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1", "18.197.51.109"]
app.config["MAX_CONTENT_LENGTH"] = 8192

check_time_pause = 60
request_timeout = 5
retention_time = 24


def database_connection():
    return mysql.connector.connect(
        host="MySQL-Container",
        port=3306,
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        connection_timeout=5,
        time_zone="+00:00",
    )


def database_preparation():
    connection = database_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS websites (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    creation_time DATETIME(6) NOT NULL
                        DEFAULT CURRENT_TIMESTAMP(6),
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uptime_result (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    website_id BIGINT UNSIGNED NOT NULL,
                    website_result VARCHAR(32) NOT NULL,
                    response_code SMALLINT UNSIGNED,
                    response_time_ms DOUBLE,
                    check_time DATETIME(6) NOT NULL
                        DEFAULT CURRENT_TIMESTAMP(6),
                    error_message TEXT,
                    FOREIGN KEY (website_id) REFERENCES websites(id),
                    INDEX (website_id, check_time),
                    INDEX (check_time)
                )
            """)

            website_list = [
                (
                    "Healthy Website",
                    "http://Test-Site-Container:8001/healthy",
                ),
                (
                    "Website Error",
                    "http://Test-Site-Container:8001/error",
                ),
                (
                    "Slow Website",
                    "http://Test-Site-Container:8001/slow",
                ),
            ]

            for name, url in website_list:
                cursor.execute(
                    """
                    INSERT INTO websites (name, url)
                    SELECT %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM websites
                        WHERE BINARY url = BINARY %s
                    )
                    """,
                    (name, url, url),
                )

        connection.commit()
    finally:
        connection.close()


def save_results(
    website_id,
    website_result,
    response_code,
    response_time_ms,
    check_time,
    error_message,
):
    connection = database_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO uptime_result (
                    website_id,
                    website_result,
                    response_code,
                    response_time_ms,
                    check_time,
                    error_message
                )
                SELECT %s, %s, %s, %s, %s, %s
                WHERE EXISTS (
                    SELECT 1
                    FROM websites
                    WHERE id = %s AND is_active = TRUE
                )
                """,
                (
                    website_id,
                    website_result,
                    response_code,
                    response_time_ms,
                    check_time,
                    error_message,
                    website_id,
                ),
            )

        connection.commit()
    finally:
        connection.close()


def website_check(website):
    check_time = datetime.now(timezone.utc).replace(tzinfo=None)
    start_time = time.monotonic()
    response_code = None
    response_time_ms = None
    error_message = None

    try:
        with requests.get(
            website["url"],
            timeout=request_timeout,
            stream=True,
        ) as response:
            response_code = response.status_code
            response_time_ms = round(
                (time.monotonic() - start_time) * 1000,
                2,
            )

            if 200 <= response_code < 300:
                website_result = "Healthy"
            else:
                website_result = "HTTP Error"
                error_message = f"HTTP {response_code}"

    except requests.exceptions.Timeout:
        website_result = "Timeout"
        error_message = (
            f"No response within the {request_timeout}-second timeout"
        )

    except requests.exceptions.RequestException as error:
        website_result = "Connection Error"
        error_message = str(error)

    save_results(
        website["id"],
        website_result,
        response_code,
        response_time_ms,
        check_time,
        error_message,
    )

    print(f"{website['name']}: {website_result}", flush=True)


def delete_results_old():
    off_time = (
        datetime.now(timezone.utc) - timedelta(hours=retention_time)
    ).replace(tzinfo=None)

    connection = database_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM uptime_result WHERE check_time < %s",
                (off_time,),
            )

        connection.commit()
    finally:
        connection.close()


def run_monitoring():
    while True:
        start_time = time.monotonic()

        try:
            delete_results_old()
            connection = database_connection()

            try:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute("""
                        SELECT id, name, url
                        FROM websites
                        WHERE is_active = TRUE
                        ORDER BY id
                    """)
                    website_list = cursor.fetchall()
            finally:
                connection.close()

            for website in website_list:
                website_check(website)

        except mysql.connector.Error:
            app.logger.exception(
                "Database operation failed; retrying next monitoring round."
            )

        time.sleep(
            max(0, check_time_pause - (time.monotonic() - start_time))
        )


@app.route("/")
def show_dasboard(
    website=None,
    history_results=None,
    removed_websites=None,
):
    off_time = (
        datetime.now(timezone.utc) - timedelta(hours=retention_time)
    ).replace(tzinfo=None)

    connection = database_connection()

    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT
                    websites.id,
                    websites.name,
                    websites.url,
                    uptime_result.website_result,
                    uptime_result.response_code,
                    uptime_result.response_time_ms,
                    uptime_result.check_time
                FROM websites
                LEFT JOIN uptime_result
                    ON uptime_result.id = (
                        SELECT id
                        FROM uptime_result
                        WHERE website_id = websites.id
                            AND check_time >= %s
                        ORDER BY check_time DESC, id DESC
                        LIMIT 1
                    )
                WHERE websites.is_active = TRUE
                ORDER BY websites.id
                """,
                (off_time,),
            )
            website_list = cursor.fetchall()
    finally:
        connection.close()

    total_websites = len(website_list)

    healthy_websites = sum(
        website["website_result"] == "Healthy"
        for website in website_list
    )

    failing_websites = sum(
        website["website_result"] not in (None, "Healthy")
        for website in website_list
    )

    return render_template(
        "Dashboard.html",
        website_list=website_list,
        website=website,
        history_results=history_results,
        removed_websites=removed_websites,
        total_websites=total_websites,
        healthy_websites=healthy_websites,
        failing_websites=failing_websites,
        check_time_pause=check_time_pause,
        retention_time=retention_time,
        error_message=request.args.get("error_message"),
    )


@app.route("/websites/add", methods=["POST"])
def add_website():
    if request.headers.get("Origin") != request.host_url.rstrip("/"):
        abort(403)

    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()

    try:
        website = urlsplit(url)

        if (
            not name
            or len(name) > 255
            or not url
            or len(url) > 2048
            or website.scheme not in ("http", "https")
            or not website.hostname
            or website.username is not None
            or website.password is not None
            or website.port == 0
            or re.search(r"[\s\\]", url)
        ):
            raise ValueError

        url = website._replace(fragment="").geturl()

    except ValueError:
        return redirect(
            url_for(
                "show_dasboard",
                error_message=(
                    "Enter a website name and a valid http:// or https:// "
                    "address without spaces or embedded credentials."
                ),
                name=name,
                url=url,
            )
        )

    connection = database_connection()

    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT id, is_active
                FROM websites
                WHERE BINARY url = BINARY %s
                LIMIT 1
                FOR UPDATE
                """,
                (url,),
            )
            website = cursor.fetchone()

            if website is not None and website["is_active"]:
                return redirect(
                    url_for(
                        "show_dasboard",
                        error_message="This URL is already being monitored.",
                        name=name,
                        url=url,
                    )
                )

            if website is not None:
                cursor.execute(
                    """
                    UPDATE websites
                    SET name = %s, is_active = TRUE
                    WHERE id = %s
                    """,
                    (name, website["id"]),
                )
            else:
                cursor.execute(
                    "INSERT INTO websites (name, url) VALUES (%s, %s)",
                    (name, url),
                )

        connection.commit()
    finally:
        connection.close()

    return redirect(url_for("show_dasboard"))


@app.route("/websites/<int:website_id>/remove", methods=["POST"])
def remove_website(website_id):
    if request.headers.get("Origin") != request.host_url.rstrip("/"):
        abort(403)

    connection = database_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE websites
                SET is_active = FALSE
                WHERE id = %s AND is_active = TRUE
                """,
                (website_id,),
            )

        connection.commit()
    finally:
        connection.close()

    return redirect(url_for("show_dasboard"))


@app.route("/history/<int:website_id>")
def show_history(website_id):
    off_time = (
        datetime.now(timezone.utc) - timedelta(hours=retention_time)
    ).replace(tzinfo=None)

    connection = database_connection()

    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT id, name, url, is_active FROM websites WHERE id = %s",
                (website_id,),
            )
            website = cursor.fetchone()

            if website is None:
                abort(404)

            cursor.execute(
                """
                SELECT
                    website_result,
                    response_code,
                    response_time_ms,
                    check_time,
                    error_message
                FROM uptime_result
                WHERE website_id = %s AND check_time >= %s
                ORDER BY check_time DESC, id DESC
                """,
                (website_id, off_time),
            )
            history_results = cursor.fetchall()
    finally:
        connection.close()

    return show_dasboard(
        website=website,
        history_results=history_results,
    )


@app.route("/history/removed")
def show_removed_history():
    off_time = (
        datetime.now(timezone.utc) - timedelta(hours=retention_time)
    ).replace(tzinfo=None)

    connection = database_connection()

    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """
                SELECT websites.id, websites.name, websites.url
                FROM websites
                WHERE websites.is_active = FALSE
                    AND EXISTS (
                        SELECT 1
                        FROM uptime_result
                        WHERE website_id = websites.id
                            AND check_time >= %s
                    )
                ORDER BY websites.id DESC
                """,
                (off_time,),
            )
            removed_websites = cursor.fetchall()
    finally:
        connection.close()

    return show_dasboard(removed_websites=removed_websites)


if __name__ == "__main__":
    database_preparation()

    monitoring_thread = threading.Thread(
        target=run_monitoring,
        daemon=True,
    )
    monitoring_thread.start()

    app.run(
        host="0.0.0.0",
        port=8000,
        debug=False,
        use_reloader=False,
    )