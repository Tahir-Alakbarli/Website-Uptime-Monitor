from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import website_monitoring_app


@pytest.fixture
def connection_testing():
    connection = website_monitoring_app.database_connection()

    try:
        with connection.cursor() as cursor_testing:
            cursor_testing.execute("""
                CREATE TEMPORARY TABLE websites (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    url VARCHAR(2048) NOT NULL,
                    creation_time DATETIME(6) NOT NULL
                        DEFAULT CURRENT_TIMESTAMP(6),
                    is_active BOOLEAN NOT NULL DEFAULT TRUE
                )
            """)

            cursor_testing.execute("""
                CREATE TEMPORARY TABLE uptime_result (
                    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                    website_id BIGINT UNSIGNED NOT NULL,
                    website_result VARCHAR(32) NOT NULL,
                    response_code SMALLINT UNSIGNED,
                    response_time_ms DOUBLE,
                    check_time DATETIME(6) NOT NULL
                        DEFAULT CURRENT_TIMESTAMP(6),
                    error_message TEXT,
                    INDEX (website_id, check_time),
                    INDEX (check_time)
                )
            """)

            cursor_testing.execute(
                """
                INSERT INTO websites (id, name, url)
                VALUES (%s, %s, %s)
                """,
                (
                    1,
                    "Healthy Website",
                    "http://Test-Site-Container:8001/healthy",
                ),
            )

        connection.commit()

        connection_testing = MagicMock(wraps=connection)
        connection_testing.close.return_value = None

        with patch.object(
            website_monitoring_app,
            "database_connection",
            return_value=connection_testing,
        ):
            yield connection_testing

    finally:
        connection.close()


@pytest.fixture
def cursor_testing(connection_testing):
    with connection_testing.cursor(dictionary=True) as cursor_testing:
        yield cursor_testing


@pytest.fixture
def flask_client(connection_testing):
    with patch.dict(
        website_monitoring_app.app.config,
        {"TESTING": True},
    ):
        with website_monitoring_app.app.test_client() as flask_client:
            yield flask_client


@pytest.fixture
def website():
    return {
        "id": 1,
        "name": "Healthy Website",
        "url": "http://Test-Site-Container:8001/healthy",
    }


def test_healthy_website(website, cursor_testing):
    with patch.object(
        website_monitoring_app.requests,
        "get",
    ) as response:
        response.return_value.__enter__.return_value.status_code = 200

        website_monitoring_app.website_check(website)

    cursor_testing.execute("SELECT * FROM uptime_result")
    history_results = cursor_testing.fetchall()

    assert len(history_results) == 1
    assert history_results[0]["website_id"] == website["id"]
    assert history_results[0]["website_result"] == "Healthy"
    assert history_results[0]["response_code"] == 200
    assert history_results[0]["response_time_ms"] is not None
    assert history_results[0]["response_time_ms"] >= 0
    assert history_results[0]["check_time"] is not None
    assert history_results[0]["error_message"] is None


def test_website_error(website, cursor_testing):
    with patch.object(
        website_monitoring_app.requests,
        "get",
    ) as response:
        response.return_value.__enter__.return_value.status_code = 500

        website_monitoring_app.website_check(website)

    cursor_testing.execute("SELECT * FROM uptime_result")
    history_results = cursor_testing.fetchall()

    assert len(history_results) == 1
    assert history_results[0]["website_result"] == "HTTP Error"
    assert history_results[0]["response_code"] == 500
    assert history_results[0]["response_time_ms"] is not None
    assert history_results[0]["error_message"] == "HTTP 500"


def test_website_timeout(website, cursor_testing):
    with patch.object(
        website_monitoring_app.requests,
        "get",
        side_effect=website_monitoring_app.requests.exceptions.Timeout,
    ):
        website_monitoring_app.website_check(website)

    cursor_testing.execute("SELECT * FROM uptime_result")
    history_results = cursor_testing.fetchall()

    assert len(history_results) == 1
    assert history_results[0]["website_result"] == "Timeout"
    assert history_results[0]["response_code"] is None
    assert history_results[0]["response_time_ms"] is None
    assert history_results[0]["error_message"]


def test_connection_error(website, cursor_testing):
    with patch.object(
        website_monitoring_app.requests,
        "get",
        side_effect=(
            website_monitoring_app.requests.exceptions.ConnectionError(
                "Website cannot be reached"
            )
        ),
    ):
        website_monitoring_app.website_check(website)

    cursor_testing.execute("SELECT * FROM uptime_result")
    history_results = cursor_testing.fetchall()

    assert len(history_results) == 1
    assert history_results[0]["website_result"] == "Connection Error"
    assert history_results[0]["response_code"] is None
    assert history_results[0]["response_time_ms"] is None
    assert (
        history_results[0]["error_message"]
        == "Website cannot be reached"
    )


def test_history_cleanup(connection_testing, cursor_testing):
    check_time = datetime.now(timezone.utc)

    cursor_testing.executemany(
        """
        INSERT INTO uptime_result (
            website_id,
            website_result,
            response_code,
            response_time_ms,
            check_time
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        [
            (
                1,
                "Healthy",
                200,
                10,
                (
                    check_time - timedelta(hours=24, seconds=1)
                ).replace(tzinfo=None),
            ),
            (
                1,
                "Healthy",
                200,
                20,
                (
                    check_time - timedelta(hours=24)
                ).replace(tzinfo=None),
            ),
            (
                1,
                "Healthy",
                200,
                30,
                (
                    check_time - timedelta(hours=1)
                ).replace(tzinfo=None),
            ),
        ],
    )
    connection_testing.commit()

    with patch.object(
        website_monitoring_app,
        "datetime",
        wraps=datetime,
    ) as response:
        response.now.return_value = check_time

        website_monitoring_app.delete_results_old()

    cursor_testing.execute(
        """
        SELECT check_time
        FROM uptime_result
        ORDER BY check_time
        """
    )
    history_results = cursor_testing.fetchall()

    assert history_results == [
        {
            "check_time": (
                check_time - timedelta(hours=24)
            ).replace(tzinfo=None)
        },
        {
            "check_time": (
                check_time - timedelta(hours=1)
            ).replace(tzinfo=None)
        },
    ]


def test_remove_website(flask_client, cursor_testing, website):
    with patch.object(
        website_monitoring_app.requests,
        "get",
    ) as response:
        response.return_value.__enter__.return_value.status_code = 200

        website_monitoring_app.website_check(website)

    response = flask_client.post(
        "/websites/1/remove",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302

    cursor_testing.execute(
        "SELECT is_active FROM websites WHERE id = 1"
    )
    history_results = cursor_testing.fetchall()

    assert len(history_results) == 1
    assert history_results[0]["is_active"] == 0

    cursor_testing.execute(
        "SELECT website_result FROM uptime_result WHERE website_id = 1"
    )
    history_results = cursor_testing.fetchall()

    assert history_results == [{"website_result": "Healthy"}]

    website_monitoring_app.save_results(
        1,
        "HTTP Error",
        500,
        25,
        datetime.now(timezone.utc).replace(tzinfo=None),
        "HTTP 500",
    )

    cursor_testing.execute(
        "SELECT website_result FROM uptime_result WHERE website_id = 1"
    )
    history_results = cursor_testing.fetchall()

    assert history_results == [{"website_result": "Healthy"}]


@pytest.mark.parametrize(
    "url",
    [
        "not-a-url",
        "ftp://example.com",
        "https://user:password@example.com",
        "http://example.com:99999",
    ],
)
def test_invalid_url(flask_client, cursor_testing, url):
    response = flask_client.post(
        "/websites/add",
        data={
            "name": "Healthy Website",
            "url": url,
        },
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert "error_message=" in response.location

    cursor_testing.execute("SELECT id FROM websites ORDER BY id")
    history_results = cursor_testing.fetchall()

    assert history_results == [{"id": 1}]


def test_duplicate_website(flask_client, cursor_testing):
    response = flask_client.post(
        "/websites/add",
        data={
            "name": "Healthy Website",
            "url": "https://example.com",
        },
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert "error_message=" not in response.location

    cursor_testing.execute(
        """
        SELECT name, url
        FROM websites
        WHERE url = %s
        """,
        ("https://example.com",),
    )
    history_results = cursor_testing.fetchall()

    assert history_results == [
        {
            "name": "Healthy Website",
            "url": "https://example.com",
        }
    ]

    response = flask_client.post(
        "/websites/add",
        data={
            "name": "Website Error",
            "url": "https://example.com",
        },
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 302
    assert "error_message=" in response.location

    cursor_testing.execute(
        """
        SELECT name, url
        FROM websites
        WHERE url = %s
        """,
        ("https://example.com",),
    )
    history_results = cursor_testing.fetchall()

    assert history_results == [
        {
            "name": "Healthy Website",
            "url": "https://example.com",
        }
    ]