"""Local HTTP error labels; original errors remain available as technical detail."""
import re


class DisplayError(ValueError):
    """Stable domain error at its source; original detail remains inspectable."""
    def __init__(self, code, detail, **params):
        super().__init__(detail)
        self.display_code = code
        self.display_params = params


def error_payload(error):
    detail = str(error)
    code = 'request'
    params = {}
    if isinstance(error, DisplayError):
        return dict(error=detail,error_code=error.display_code,error_params=error.display_params)
    missing_node = re.search(r'Unknown (?:global )?body ID:\s*(\d+)',detail,re.I)
    if missing_node:
        code = 'node_missing'
        params = {'body_id': missing_node.group(1)}
    elif re.search(r'Open (?:or prepare )?a (?:saved )?calculation scope first|Open or create.*scope',detail,re.I):
        code = 'scope_required'
    elif detail.startswith('Index unavailable'):
        code = 'index_unavailable'
    elif re.search(r'scope (?:changed|mismatch)|belongs to a different (?:index|scope)|identity.*mismatch',detail,re.I):
        code = 'scope_changed'
    elif re.search(r'budget|exceeds.*(?:limit|MiB)|memory limit',detail,re.I):
        code = 'memory_budget'
    # Unclassified backend errors retain their exact detail. Do not guess a
    # generic validation category from words such as "must" or "invalid".
    return dict(error=detail,error_code=code,error_params=params)
