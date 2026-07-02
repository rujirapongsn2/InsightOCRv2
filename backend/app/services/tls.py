import logging
import warnings
from functools import lru_cache
from typing import Any

from urllib3.exceptions import InsecureRequestWarning

logger = logging.getLogger(__name__)

# Keep urllib3 warnings visible, but prevent noisy repeats when a legacy/internal
# provider intentionally runs with certificate verification disabled.
warnings.filterwarnings("once", category=InsecureRequestWarning)


@lru_cache(maxsize=None)
def warn_ssl_verification_disabled(context: str) -> None:
    logger.warning(
        "TLS certificate verification is disabled for %s. "
        "Use a trusted CA/certificate and set verify_ssl=true in production.",
        context,
    )


def get_verify_ssl(setting: Any, context: str) -> bool:
    verify_ssl = bool(setting.verify_ssl) if getattr(setting, "verify_ssl", None) is not None else False
    if not verify_ssl:
        warn_ssl_verification_disabled(context)
    return verify_ssl
