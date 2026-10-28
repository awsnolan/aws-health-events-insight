"""Infrastructure-level ingestion-robustness checks against the CFN templates.

The 'no DLQ on the member->central forwarding rule' gap lives in the templates,
not the Python, so it is asserted here. xfail(strict=True) until a DeadLetterConfig
is added.
"""
import pathlib

import pytest
import yaml

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


class _CfnLoader(yaml.SafeLoader):
    pass


def _cfn_multi(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_CfnLoader.add_multi_constructor("!", _cfn_multi)


def load_template(relpath):
    return yaml.load((SRC / relpath).read_text(), Loader=_CfnLoader)


def _rule_targets(template, logical_id):
    res = template["Resources"][logical_id]["Properties"].get("Targets", [])
    return res


@pytest.mark.xfail(strict=True, reason="backlog: no DLQ on the member->central health forwarding rule")
def test_member_forwarding_rule_has_dlq():
    t = load_template("HealthModule/HealthModuleCollectionSetup.yaml")
    targets = _rule_targets(t, "DefaultBusRuleHealth")
    assert targets, "DefaultBusRuleHealth has no targets"
    assert all("DeadLetterConfig" in tgt for tgt in targets), \
        "forwarding target should have a DeadLetterConfig for unrecoverable deliveries"


@pytest.mark.xfail(strict=True, reason="backlog: no DLQ on the central bus -> Firehose rule")
def test_central_bus_rule_has_dlq():
    t = load_template("DataCollectionModule/DataCollectionModule.yaml")
    targets = _rule_targets(t, "DataCollectionRuleOnCustomBus")
    assert targets, "DataCollectionRuleOnCustomBus has no targets"
    assert all("DeadLetterConfig" in tgt for tgt in targets)
