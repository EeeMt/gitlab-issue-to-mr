import warnings


def pytest_configure(config):
    """Configure warnings filter before any tests run."""
    warnings.filterwarnings(
        "ignore",
        message="urllib3 v2 only supports OpenSSL",
        category=Warning
    )
