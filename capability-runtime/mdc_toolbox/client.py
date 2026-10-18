"""Lossless public response checking; never retries or launches recovery work."""
from copy import deepcopy


class ToolboxResponseError(RuntimeError):
    """Retain the complete original response even when its error is non-null.

    Callers must record job/request identities before deciding whether to make an
    explicit status/reconcile read. An exception is never authority to resubmit.
    """
    def __init__(self, response):
        self.response = deepcopy(response)
        self.job_id = response.get('job_id')
        self.request_id = response.get('job_request_id', response.get('request_id'))
        self.request_ids = tuple(response.get('request_ids', ()))
        self.session_ref = response.get('session_ref')
        error = response.get('error')
        self.code = error.get('code', 'toolbox_error') if isinstance(error, dict) else 'toolbox_error'
        super().__init__(self.code)


def check_response(response):
    """Return a response unchanged, or raise with all original evidence intact."""
    if not isinstance(response, dict):
        raise TypeError('Toolbox response must be an object')
    if response.get('error') is not None:
        raise ToolboxResponseError(response)
    return response
