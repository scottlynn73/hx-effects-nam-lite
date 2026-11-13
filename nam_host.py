"""Where NAM sits, shared by build_all.py and build_nam_click.py: on the mono Regal Bass DI (Distortion > Mono, so a
cab IR can follow it) or on the 1024 IR block (IR > Single, the original placement)."""

NAM_HOSTS = {'regal': 'HD2_DistRegalBassDIMono', 'ir': None}   # --nam-host; None: the 1024 IR (be.TAKEOVER)
NAM_LIST_SLOTS = 21                                  # the longest list stock shows


def nam_off_ir(pa_params):
    """Model on a non-IR block: IR Select's 'dynamicList' display exists only on IR blocks, so a plain list of
    User IR slots 1..21, the same parameter and instance word."""
    p = pa_params[0]
    assert p['name'] == 'Index' and p['type'] == 2
    p['raw'][5], p['raw'][6], p['raw'][7] = 1, NAM_LIST_SLOTS, 1
    p['default_word'] = 1
    p['meta'] = [('displayType', 7, 'list'), ('displayName', 7, 'Model'), ('displayNameShort', 7, 'Model')] + \
        [(str(k), 7, str(k)) for k in range(1, NAM_LIST_SLOTS + 1)]
    return pa_params
