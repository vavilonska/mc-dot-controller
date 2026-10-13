"""Pure evidence checks; missing legacy fields keep their original semantics."""
from .navigation_binding import discontinuity_release_confirmed, native_handoff_required, task_handoff_required


def native_release_unconfirmed(receipt):
    if not isinstance(receipt, dict):
        return False
    result = receipt.get('result')
    return (receipt.get('reason') == 'input_release_unconfirmed'
            or receipt.get('reason') == 'position_discontinuity_rebind_required'
            and not discontinuity_release_confirmed(receipt)
            or isinstance(result, dict) and 'input_release_confirmed' in result
            and result['input_release_confirmed'] is not True)


def task_release_unconfirmed(response):
    # A successful observation can contain an old failed action. Do not confuse
    # that historical receipt with a newly failed action task.
    if not isinstance(response, dict) or response.get('status') not in ('failed', 'cancelled', 'uncertain'):
        return False
    nested = response.get('result')
    if response.get('reason') == 'position_discontinuity_rebind_required':
        return not (response.get('status') == 'cancelled'
                    and discontinuity_release_confirmed(response.get('action')))
    return (response.get('reason') == 'input_release_unconfirmed'
            or native_release_unconfirmed(response.get('action'))
            or isinstance(nested, dict) and native_release_unconfirmed(nested.get('action')))
