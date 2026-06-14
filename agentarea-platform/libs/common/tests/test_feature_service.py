from agentarea_common.features.service import DeploymentMode, FeatureService


def test_oss_mode_defaults():
    fs = FeatureService(mode=DeploymentMode.OSS)
    assert fs.system_entities_read_only_in_ui is False
    assert fs.show_system_entity_badge is False
    assert fs.enable_usage_metering is False


def test_enterprise_mode_defaults():
    fs = FeatureService(mode=DeploymentMode.ENTERPRISE)
    assert fs.system_entities_read_only_in_ui is True
    assert fs.show_system_entity_badge is True
    assert fs.enable_usage_metering is True


def test_default_mode_is_oss():
    fs = FeatureService()
    assert fs.mode == DeploymentMode.OSS
