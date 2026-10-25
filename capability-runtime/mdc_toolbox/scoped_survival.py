"""Closed registration for the new survival primitives, never a legacy fallback."""
TARGET_PROFILE = 'target-action-stationary-v1'
ITEM_PROFILE = 'item-on-block-observed-v1'
PORTAL_PROFILE = 'portal-entry-observed-v1'
PROFILE_ACTIONS = {
    TARGET_PROFILE: ['attack_entity', 'shoot_entity'],
    ITEM_PROFILE: ['interact_block'],
    PORTAL_PROFILE: ['follow_path'],
}
CAPABILITY_PROFILE = {
    'strike': TARGET_PROFILE, 'remove_crystal': TARGET_PROFILE,
    'ignite_portal_local': ITEM_PROFILE, 'insert_end_eye_local': ITEM_PROFILE,
    'enter_portal_local': PORTAL_PROFILE,
}

def available(capability, scoped):
    profile = CAPABILITY_PROFILE.get(capability)
    return (profile is not None and type(scoped) is dict
        and scoped.get('version') == 'scoped-native-preflight/1'
        and scoped.get('same_callback_capture_validate_admit') is True
        and scoped.get('private_singleplayer_only') is True
        and type(scoped.get('capability_guard_schema_version')) is int
        and scoped['capability_guard_schema_version'] == 1
        and type(scoped.get('profiles')) is dict
        and scoped['profiles'].get(profile) == PROFILE_ACTIONS[profile])

def select(capability, profiles):
    """Select one typed profile only for the explicitly requested public primitive."""
    profile = CAPABILITY_PROFILE.get(capability)
    if profile is not None:
        for action in PROFILE_ACTIONS[profile]:
            profiles[action] = profile
    return profiles
