# Python Code Guide

This guide explains the Python side of the website monitoring project: the main application, the controlled test website, and the automated tests.

The main project README covers Docker, GitLab CI/CD, Terraform, and AWS deployment. Here, the focus is on how the application handles website checks, database access, user input, and test results.

## Python Files

| File | Responsibility |
| --- | --- |
| `monitor/website_monitoring_app.py` | Monitoring application, database access, and dashboard routes |
| `test-site/test_website.py` | Predictable website responses for testing |
| `tests/test_monitoring_app.py` | Automated checks of application behavior |

The dashboard template is stored separately in:

```text
monitor/templates/Dashboard.html
```

Python handles the application logic and supplies the data. The template handles how that information appears in the browser.

## 1. Monitoring Application

### Main Responsibilities

The monitoring application connects several parts of the project:

- HTTP requests to monitored websites.
- Classification of check results.
- Database storage and retrieval.
- Website addition and removal.
- Recent monitoring history.
- Flask routes used by the dashboard.

The overall flow is:

1. A website is registered for monitoring.
2. The application sends an HTTP request to its URL.
3. The request produces a response or an error.
4. The application records the result.
5. The dashboard displays the latest stored information.
6. The history view displays previous checks.

### Imports and Their Roles

The application imports modules for different tasks rather than putting everything into Flask itself.

| Module | Purpose |
| --- | --- |
| `os` | Read environment configuration |
| `re` | Support text-pattern checks |
| `threading` | Support background execution |
| `time` | Timing and waiting |
| `datetime` | Timestamps and retention calculations |
| `urllib.parse.urlsplit` | Separate a URL into its components |
| `mysql.connector` | Communicate with MySQL |
| `requests` | Send HTTP requests |
| `flask` | Handle browser requests and render the dashboard |

An import tells us which tools are available to the file. It does not, by itself, show how every function uses them.

### Flask Application and Configuration

The Flask application object connects incoming requests to the application routes.

Two configuration settings visible in the application are:

- `TRUSTED_HOSTS`
- `MAX_CONTENT_LENGTH`

`TRUSTED_HOSTS` controls which hostnames Flask accepts when someone accesses the dashboard. The verified AWS deployment allowed localhost addresses and its active public IP.

This setting caused a real deployment issue: a localhost request succeeded, but Flask rejected the browser request using the EC2 public IP.

`MAX_CONTENT_LENGTH` is set to 8192 bytes. This limits the size of an incoming request body. It is not a limit on the size of a monitored website's response.

Reference: [Flask configuration](https://flask.palletsprojects.com/en/stable/config/).

## 2. Database Access

### Environment Configuration

The application reads database configuration from environment variables:

```text
MYSQL_DATABASE
MYSQL_USER
MYSQL_PASSWORD
```

This keeps the database password outside the published Python source.

The local application receives its runtime configuration through Docker Compose. The CI test job receives its database values through GitLab configuration and variables.

### Connection Function

The `database_connection()` function provides the application with a MySQL connection.

Keeping connection creation in one function gives database operations a shared starting point instead of repeating connection settings throughout the file.

Inside the container network, the application reaches MySQL through its container hostname. The username and password must match the database user's actual configuration.

A connection failure is different from a failed website check. If MySQL is unavailable, the application cannot reliably save or retrieve monitoring results even if it can still reach a website.

Reference: [MySQL connection arguments](https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html).

### Connections, Cursors, and Transactions

A database connection represents the session with MySQL. A cursor is the object used to execute SQL and retrieve query results.

For this application, database operations support tasks such as:

- Reading monitored websites.
- Saving website records.
- Saving check results.
- Retrieving recent history.
- Removing website records.
- Cleaning up old history.

There is an important difference between executing a statement and committing a change.

With Connector/Python's default transaction behavior, changes to transactional tables need a commit before they are permanently saved. A query appearing to run successfully does not necessarily mean its changes have been committed.

References:

- [MySQL cursor objects](https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlcursor.html)
- [MySQL commit behavior](https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlconnection-commit.html)

### SQL Error Encountered During Testing

An early test run failed with:

```text
1066 (42000): Not unique table/alias: 'websites'
```

The shared SQL setup referred to a table or alias in a way MySQL could not distinguish.

Because the error happened during shared setup, all 11 tests errored before their individual checks could complete. Correcting the duplicate alias allowed it to pass.

This was a useful reminder to separate application failures from failures in the code preparing the test environment.

## 3. Website Requests and Results

### Different Types of Failure

I wanted the dashboard to distinguish a website returning an error from a request that never receives a usable response.

| Situation | Meaning |
| --- | --- |
| HTTP 200 from the healthy endpoint | The endpoint returned a successful response |
| HTTP 500 from the error endpoint | The server responded, but reported an error |
| Timeout | The request exceeded its configured waiting limit |
| Connection error | The request could not establish or maintain the required connection |

A server returning HTTP 500 is still responding. A connection failure may provide no HTTP status at all.

This distinction affects what can be displayed and stored for a check.

Reference: [Requests error handling](https://requests.readthedocs.io/en/latest/user/quickstart/#errors-and-exceptions).

### Request Timeout

The configured request timeout is five seconds.

The controlled slow endpoint waits ten seconds before responding, allowing timeout handling to be checked reliably.

Requests does not define its timeout as a strict maximum duration for every part of a complete download. It controls connection and read waiting behavior. That matters when interpreting a timeout value.

Reference: [Requests timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts).

### Response Times

The dashboard displays available response times in milliseconds.

These values describe individual checks from the monitoring environment. They are not a general performance score for the website.

A successful response and a fast response are also different things. For example, an HTTP 500 response can arrive quickly while still being classified as an error.

## 4. URL Validation

Adding a website introduces user input into the application.

Before a URL is accepted, it needs more checking than whether the text contains a dot or begins with `http`.

The test suite includes rejected examples for:

- Text that is not a valid website URL.
- An unsupported scheme such as FTP.
- A URL containing a username and password.
- A port outside the valid range.

### Parsing the URL

The application imports `urlsplit` to separate a URL into components such as its scheme, host information, and path.

Parsing and validation are not the same operation. Python's URL parser can separate input without proving that the input is safe or suitable for this application.

The application still needs to decide which schemes, hosts, credentials, and ports it accepts.

Reference: [Python URL parsing and validation notes](https://docs.python.org/3/library/urllib.parse.html#url-parsing-security).

### Security Limit

Rejecting malformed URLs does not provide complete protection against server-side request forgery, or SSRF.

A URL can look valid while pointing to a private address or another destination the application should not contact.

The current validation tests show that certain unwanted inputs are rejected. They do not establish that arbitrary public use of the URL submission feature is safe.

## 5. Dashboard and User Actions

### Displaying Stored Results

The dashboard presents website records alongside their latest monitoring results.

The important fields include:

- Website name and URL.
- Latest result.
- Available HTTP code.
- Available response time.
- Last-check timestamp.

The Python application supplies the data used by `Dashboard.html`.

Website checks happen every 60 seconds, while the dashboard refreshes every 15 seconds. These are separate activities: refreshing the display does not imply that every website has just been checked again.

### Adding and Removing Websites

Website addition involves checking user input and storing an accepted website record.

Duplicate handling prevents repeated registration of the same website according to the application's rules.

Removal stops a website from remaining in the active monitored list. The test suite includes checks for both duplicate handling and website removal.

### Viewing History

The history view displays earlier results associated with a website.

It gives more context than the latest-result field. For example, several timestamped HTTP errors show repeated failures rather than a single failed request.

## 6. Timestamps and History Cleanup

The application displays timestamps in CET and retains recent history for 24 hours.

Retention handling needs to distinguish current results from records older than the allowed window.

The intended behavior is to remove expired history while keeping recent records. Removing all history would not satisfy that requirement.

The automated history-cleanup test checks this part of the application.

Timestamp handling is also important because the local machine, server, and browser may use different local time zones. Displaying UTC makes the recorded times easier to compare.

Reference: [Python datetime documentation](https://docs.python.org/3/library/datetime.html).

## 7. Controlled Test Website

The file `test-site/test_website.py` provides predictable responses for the monitoring application.

It is a separate application, with its own Dockerfile and requirements file.

### Healthy Endpoint

```text
/healthy
```

Returns HTTP 200.

This checks whether the monitoring application can record and display a successful result.

### Error Endpoint

```text
/error
```

Returns HTTP 500.

This checks whether an HTTP error is distinguished from a successful response.

### Slow Endpoint

```text
/slow
```

Delays its response for ten seconds.

Because this exceeds the configured request timeout, it checks the monitoring application's timeout behavior.

Keeping these responses under project control makes testing repeatable. An external website could change its response or become unavailable for reasons unrelated to the code.

## 8. Automated Tests

The file `tests/test_monitoring_app.py` checks application behavior.

The successful GitLab run collected 11 cases and passed all of them.

### Test Coverage

| Test | Behavior checked |
| --- | --- |
| `test_healthy_website` | Successful website response |
| `test_website_error` | HTTP error handling |
| `test_website_timeout` | Request timeout handling |
| `test_connection_error` | Connection failure handling |
| `test_history_cleanup` | Expired history cleanup |
| `test_remove_website` | Website removal |
| `test_invalid_url` | Four invalid URL inputs |
| `test_duplicate_website` | Duplicate website handling |

The invalid-URL test appears several times in the output because it runs against different inputs. Those cases contribute to the total of 11.

### Shared Test Setup

Tests often need the same starting conditions, such as application configuration, database access, or prepared records.

pytest fixtures provide a way to manage reusable setup and cleanup. They help keep repeated preparation separate from the assertions checking each behavior.

A problem in shared setup can affect many tests at once, as happened with the duplicate SQL alias.

Reference: [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html).

### Testing Flask Requests

Flask provides a test client for sending requests to an application without opening a real browser or running a separate public HTTP server.

This is useful for checking routes and responses in automated tests. Browser verification still has a separate role because it also exercises the deployed access path.

Reference: [Testing Flask applications](https://flask.palletsprojects.com/en/stable/testing/).

### Testing Several Inputs

pytest supports running one test with several inputs through parametrization.

This is useful for URL validation because malformed text, unsupported schemes, embedded credentials, and invalid ports are different cases of the same validation behavior.

Reference: [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html).

## 9. What the Tests Do Not Prove

A passing test suite verifies the cases included in that suite. It does not prove every part of the deployed environment is correct.

The 11 passing tests did not independently prove:

- The EC2 dashboard port was reachable from my browser.
- Flask accepted the EC2 public hostname.
- The application used HTTPS.
- Database backups were available.
- Every possible URL was safe to request.
- The application was ready for production use.

This is why I also checked the deployed containers, application logs, HTTP responses, dashboard, and history manually.

## References for the More Involved Parts

### Database Connections and Saved Changes

- [MySQL connection arguments](https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html)
- [MySQL cursor objects](https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlcursor.html)
- [MySQL transaction commits](https://dev.mysql.com/doc/connector-python/en/connector-python-api-mysqlconnection-commit.html)

### Request Failures and Timeouts

- [Requests errors and exceptions](https://requests.readthedocs.io/en/latest/user/quickstart/#errors-and-exceptions)
- [Requests timeout behavior](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts)

### URL Validation

- [Python URL parsing](https://docs.python.org/3/library/urllib.parse.html)
- [URL parsing security notes](https://docs.python.org/3/library/urllib.parse.html#url-parsing-security)

### Flask Host Validation and Testing

- [Flask trusted hosts](https://flask.palletsprojects.com/en/stable/config/#TRUSTED_HOSTS)
- [Flask request-size limits](https://flask.palletsprojects.com/en/stable/config/#MAX_CONTENT_LENGTH)
- [Flask testing guide](https://flask.palletsprojects.com/en/stable/testing/)

### Test Setup and Multiple Inputs

- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html)

### Time and Retention

- [Python datetime](https://docs.python.org/3/library/datetime.html)
