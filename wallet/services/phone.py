import re

from django.db.models import Q

from wallet.models import User, UserStatus


def normalize_phone_number(raw):
    """Normalize a Guinea (or international) phone number to +E.164."""
    if raw is None:
        return ''
    value = str(raw).strip()
    if not value:
        return ''

    plus = value.startswith('+')
    digits = re.sub(r'\D', '', value)
    if digits.startswith('00'):
        digits = digits[2:]
        plus = True

    if digits.startswith('0') and len(digits) in (8, 9):
        digits = '224' + digits.lstrip('0')
    elif len(digits) == 8 and digits[0] in '67':
        digits = '224' + digits
    elif len(digits) == 9 and digits.startswith('6'):
        digits = '224' + digits
    elif plus and not digits.startswith('224') and len(digits) >= 8:
        pass
    elif not digits.startswith('224') and 8 <= len(digits) <= 9:
        digits = '224' + digits.lstrip('0')

    if len(digits) < 8:
        return ''
    return f'+{digits}'


def phone_lookup_values(raw):
    """Return likely stored forms of a number so older rows still match."""
    normalized = normalize_phone_number(raw)
    values = {str(raw).strip()} if raw else set()
    if normalized:
        values.add(normalized)
        digits = re.sub(r'\D', '', normalized)
        values.add(digits)
        values.add(digits.lstrip('224'))
        if digits.startswith('224') and len(digits) > 3:
            local = digits[3:]
            values.add(local)
            values.add(f'0{local}')
    return {item for item in values if item}


def resolve_user_by_identifier(query, *, exclude_user=None):
    """Find an active user by phone number, handle, or email."""
    query = (query or '').strip()
    if not query:
        return None

    phones = phone_lookup_values(query)
    filters = Q(handle__iexact=query) | Q(email__iexact=query)
    if phones:
        filters |= Q(phone_number__in=phones)

    users = User.objects.filter(filters, status=UserStatus.ACTIVE)
    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)
    return users.first()


def mask_phone_number(phone):
    digits = re.sub(r'\D', '', phone or '')
    if len(digits) < 4:
        return '****'
    return f'****{digits[-4:]}'
