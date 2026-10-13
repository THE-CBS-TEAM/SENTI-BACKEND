"""
Diagnostic error analysis utility for Sentimentri Scraper & Background Tasks.
Translates cryptic stack traces, HTTP errors, and scraper outputs into clear,
actionable diagnostic reports for administrators and developers.
"""
import re
from typing import Dict, Any, Optional


def classify_scraper_error(
    error_str: Optional[str],
    provider: Optional[str] = None,
    entity_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyzes an error message from FetchJob, TrackedPost, or Celery task
    and returns a structured diagnostic classification with human explanation
    and actionable remediation instructions.
    """
    if not error_str:
        return {
            'category': 'NONE',
            'badge': 'No Error',
            'severity': 'info',
            'is_actionable': False,
            'summary': 'Operation completed normally or no error was logged.',
            'remediation': None,
            'raw_error': ''
        }

    err = str(error_str).strip()
    provider_upper = (provider or '').upper()

    # 1. HTTP 402 - Payment Required / Credits Depleted
    if '402' in err or 'Payment Required' in err or 'insufficient credits' in err.lower() or 'balance' in err.lower() and 'depleted' in err.lower():
        prov_name = 'SocialData' if 'socialdata' in err.lower() or provider_upper == 'SOCIALDATA' else (provider_upper or 'Scraper Provider')
        billing_url = 'https://socialdata.tools/billing' if 'SOCIALDATA' in prov_name.upper() else 'https://console.apify.com/billing'
        return {
            'category': 'PAYMENT_REQUIRED',
            'badge': 'Credits Exhausted (402)',
            'severity': 'critical',
            'is_actionable': True,
            'summary': f"{prov_name} rejected the scrape request with HTTP 402 Payment Required because your account credit balance is depleted ($0.00).",
            'remediation': f"Add credits to your {prov_name} account at {billing_url} to immediately resume metric polling and profile analysis.",
            'raw_error': err
        }

    # 2. HTTP 401 / 403 - Invalid or Expired Token / Forbidden
    if any(code in err for code in ['401', '403', 'Unauthorized', 'Forbidden', 'Invalid API key', 'token expired']):
        prov_name = provider_upper or 'API Provider'
        return {
            'category': 'AUTH_EXPIRED',
            'badge': 'Authentication Failed (401/403)',
            'severity': 'critical',
            'is_actionable': True,
            'summary': f"Authentication failed with {prov_name}. The configured API key or bearer token is either invalid, revoked, or expired.",
            'remediation': f"Verify and update the API token ({prov_name}_API_KEY / APIFY_API_TOKEN) in your server environment (.env).",
            'raw_error': err
        }

    # 3. HTTP 404 - Not Found / Account Deleted / Private
    if '404' in err or 'Not Found' in err or 'User not found' in err or 'Tweet not found' in err:
        return {
            'category': 'TARGET_NOT_FOUND',
            'badge': 'Target Not Found (404)',
            'severity': 'warning',
            'is_actionable': True,
            'summary': "The requested social media post or creator profile could not be found. It may have been deleted, set to private, or the handle/URL changed.",
            'remediation': "Check if the URL or social handle is publicly accessible in a web browser. If deleted, archive or remove the tracked post.",
            'raw_error': err
        }

    # 4. HTTP 429 - Rate Limited
    if '429' in err or 'Too Many Requests' in err or 'rate limit' in err.lower():
        prov_name = provider_upper or 'External Scraper'
        return {
            'category': 'RATE_LIMITED',
            'badge': 'Rate Limited (429)',
            'severity': 'warning',
            'is_actionable': False,
            'summary': f"{prov_name} temporary rate limit threshold reached. Requests are being throttled.",
            'remediation': "Sentimentri's exponential backoff scheduler will automatically retry this job once the rate limit window resets. No immediate action required.",
            'raw_error': err
        }

    # 5. Database Schema / Constraint Violation
    if any(db_err in err for db_err in ['violates not-null constraint', 'IntegrityError', 'OperationalError', 'relation does not exist', 'unique constraint']):
        # Extract column/relation if possible
        match = re.search(r'column "([^"]+)" of relation "([^"]+)"', err)
        detail = f"on table '{match.group(2)}' (column '{match.group(1)}')" if match else ""
        return {
            'category': 'DB_CONSTRAINT_ERROR',
            'badge': 'Database Constraint Error',
            'severity': 'critical',
            'is_actionable': True,
            'summary': f"PostgreSQL database rejected the write operation {detail}. A required field was missing or a schema mismatch occurred.",
            'remediation': "Check backend migrations or database defaults. Developers should inspect Django model definitions and database constraints.",
            'raw_error': err
        }

    # 6. Network / Timeout / Connection Reset
    if any(net_err in err for net_err in ['ConnectionError', 'Timeout', 'timed out', 'Connection refused', 'MaxRetryError']):
        return {
            'category': 'NETWORK_TIMEOUT',
            'badge': 'Network Timeout',
            'severity': 'warning',
            'is_actionable': False,
            'summary': "The external scraper API connection timed out or failed to resolve DNS before responding.",
            'remediation': "Typically a transient network or third-party outage. The system will retry on the next polling tier interval.",
            'raw_error': err
        }

    # 7. Apify Actor Run Failure / Dataset Empty
    if 'Actor run failed' in err or 'apify' in err.lower() and ('failed' in err.lower() or 'crashed' in err.lower()):
        return {
            'category': 'SCRAPER_ACTOR_FAILED',
            'badge': 'Apify Actor Execution Failed',
            'severity': 'critical',
            'is_actionable': True,
            'summary': "The Apify scraper actor failed during execution or exceeded its container memory/timeout limit.",
            'remediation': "Inspect the Apify Console run logs for actor errors, proxy bans, or anti-bot challenge blocks.",
            'raw_error': err
        }

    # 8. Private Account or Geo-restricted Content
    if 'private' in err.lower() or 'restricted' in err.lower() or 'age-restricted' in err.lower():
        return {
            'category': 'CONTENT_RESTRICTED',
            'badge': 'Content Private/Restricted',
            'severity': 'warning',
            'is_actionable': True,
            'summary': "The target profile or post requires account login, is set to private, or has region/age restrictions.",
            'remediation': "Third-party scrapers cannot read private or restricted accounts without authenticated sessions.",
            'raw_error': err
        }

    # 9. Generic / Fallback
    return {
        'category': 'GENERAL_ERROR',
        'badge': 'Scraper Execution Error',
        'severity': 'warning',
        'is_actionable': False,
        'summary': err[:250] + ('...' if len(err) > 250 else ''),
        'remediation': "Review the raw error details below and check the Celery task log for the complete traceback.",
        'raw_error': err
    }


def format_error_summary(error_str: Optional[str], provider: Optional[str] = None, entity_type: Optional[str] = None) -> str:
    """Returns a concise, human-readable one-liner diagnostic summary for logging/storage."""
    if not error_str:
        return ""
    diag = classify_scraper_error(error_str, provider, entity_type)
    if diag.get('category') != 'GENERAL_ERROR':
        return f"[{diag['badge']}] {diag['summary']}"
    return str(error_str)
